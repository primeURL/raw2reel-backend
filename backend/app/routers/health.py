import redis
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    checks = {}
    try:
        db.execute(text("select 1"))
        checks["postgres"] = "ok"
    except Exception as exc:
        checks["postgres"] = f"error: {exc.__class__.__name__}"
    try:
        redis.Redis.from_url(get_settings().redis_url, socket_timeout=2).ping()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"error: {exc.__class__.__name__}"
    ok = all(v == "ok" for v in checks.values())
    return {"status": "ok" if ok else "degraded", **checks}
