"""Track every Claude call and enforce the per-user daily limit (protects the API credit)."""

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import session_scope
from app.models import AIUsage


def _since() -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=24)


def calls_last_24h(db: Session, user_id: uuid.UUID) -> int:
    return db.scalar(select(func.count()).select_from(AIUsage).where(AIUsage.user_id == user_id, AIUsage.created_at >= _since())) or 0


def require_quota(db: Session, user_id: uuid.UUID) -> None:
    """Call before queuing any AI job."""
    limit = get_settings().ai_daily_limit
    if calls_last_24h(db, user_id) >= limit:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, f"Daily AI limit reached ({limit} per day). Try again tomorrow.")


def record(user_id: uuid.UUID, kind: str, usage: dict) -> None:
    s = get_settings()
    cost = usage["input_tokens"] / 1e6 * s.ai_price_in_per_m + usage["output_tokens"] / 1e6 * s.ai_price_out_per_m
    with session_scope() as db:
        db.add(AIUsage(user_id=user_id, kind=kind, model=usage.get("model", ""), input_tokens=usage["input_tokens"],
                       output_tokens=usage["output_tokens"], estimated_usd=round(cost, 5)))


def summary(db: Session, user_id: uuid.UUID) -> dict:
    rows = db.execute(
        select(AIUsage.kind, func.count(), func.coalesce(func.sum(AIUsage.estimated_usd), 0.0))
        .where(AIUsage.user_id == user_id)
        .group_by(AIUsage.kind)
    ).all()
    return {
        "calls_last_24h": calls_last_24h(db, user_id),
        "daily_limit": get_settings().ai_daily_limit,
        "all_time": {k: {"calls": n, "estimated_usd": round(c, 4)} for k, n, c in rows},
        "all_time_usd": round(sum(c for _, _, c in rows), 4),
    }
