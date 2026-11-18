"""Housekeeping loop (its own container, like the Tendor `scheduler`).

Every 5 minutes:
  - jobs stuck in a running state (worker restarted / crashed / Docker stopped) are marked
    failed with a "please retry" message, so the app never spins forever;
  - leftover temp folders in WORK_DIR older than 2 hours are deleted (disk on a VPS is finite).

Run: python -m app.scheduler_loop
"""

import logging
import shutil
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import update

from app.config import get_settings
from app.db import session_scope
from app.models import Clip, MediaStatus, Project, ProjectStatus, ReferenceVideo, Render, Style, StyleStatus

log = logging.getLogger("scheduler")

INTERVAL_S = 300
RETRY = "This was interrupted - please try again"

# (model, column, running values, new value, minutes before it counts as stuck)
STUCK = [
    (ReferenceVideo, ReferenceVideo.status, [MediaStatus.downloading, MediaStatus.processing], MediaStatus.failed, 20),
    (ReferenceVideo, ReferenceVideo.analysis_status, [MediaStatus.processing], MediaStatus.failed, 30),
    (Clip, Clip.status, [MediaStatus.processing], MediaStatus.failed, 20),
    (Clip, Clip.analysis_status, [MediaStatus.processing], MediaStatus.failed, 30),
    (Style, Style.status, [StyleStatus.analyzing], StyleStatus.failed, 15),
    (Project, Project.status, [ProjectStatus.analyzing], ProjectStatus.failed, 15),
    (Project, Project.status, [ProjectStatus.rendering], ProjectStatus.planned, 45),
    (Render, Render.status, [MediaStatus.processing, MediaStatus.pending], MediaStatus.failed, 45),
]


def sweep_stuck(now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    fixed = 0
    with session_scope() as db:
        for model, col, running, new, minutes in STUCK:
            values = {col.key: new}
            if hasattr(model, "error") and not (model is Project and new == ProjectStatus.planned):
                values["error"] = RETRY
            res = db.execute(
                update(model)
                .where(col.in_(running), model.updated_at < now - timedelta(minutes=minutes))
                .values(**values)
            )
            if res.rowcount:
                log.warning("marked %d stuck %s.%s as %s", res.rowcount, model.__tablename__, col.key, new.value)
                fixed += res.rowcount
    return fixed


def clean_work_dir(max_age_h: float = 2.0) -> int:
    root = Path(get_settings().work_dir)
    cutoff = time.time() - max_age_h * 3600
    removed = 0
    for kind in ("references", "clips", "analysis", "renders"):
        base = root / kind
        if not base.exists():
            continue
        for d in base.rglob("*"):
            if d.is_dir() and d.parent in (base, base / "clips", base / "references") and d.stat().st_mtime < cutoff:
                shutil.rmtree(d, ignore_errors=True)
                removed += 1
    return removed


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log.info("scheduler started (every %ss)", INTERVAL_S)
    while True:
        try:
            n = sweep_stuck()
            m = clean_work_dir()
            if n or m:
                log.info("sweep: %d stuck jobs reset, %d temp folders removed", n, m)
        except Exception:
            log.exception("sweep failed")
        time.sleep(INTERVAL_S)


if __name__ == "__main__":
    main()
