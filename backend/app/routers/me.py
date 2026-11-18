from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import current_user
from app.db import get_db
from app.models import User
from app.schemas import UserOut
from app.services import ai_usage

router = APIRouter(tags=["me"])


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)) -> User:
    return user


@router.get("/me/ai-usage")
def my_ai_usage(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """How many AI calls were used in the last 24 h, the limit, and estimated spend so far."""
    return ai_usage.summary(db, user.id)
