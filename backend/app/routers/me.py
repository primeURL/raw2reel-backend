import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import current_user
from app.db import get_db
from app.models import Lesson, User
from app.schemas import LessonIn, LessonOut, LessonPatch, UserOut
from app.services import ai_usage
from app.services import lessons as LS

router = APIRouter(tags=["me"])


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)) -> User:
    return user


@router.get("/me/ai-usage")
def my_ai_usage(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """How many AI calls were used in the last 24 h, the limit, and estimated spend so far."""
    return ai_usage.summary(db, user.id)


# creator memory -------------------------------------------------------------------


@router.get("/me/lessons", response_model=list[LessonOut])
def my_lessons(user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[Lesson]:
    """Everything the editor has learnt from this creator, newest first (switched-off ones too)."""
    return list(db.scalars(select(Lesson).where(Lesson.user_id == user.id).order_by(Lesson.created_at.desc())))


@router.post("/me/lessons", response_model=LessonOut, status_code=status.HTTP_201_CREATED)
def add_lesson(body: LessonIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> Lesson:
    """A lesson the creator types in themselves ("Always end with my handle")."""
    ls = LS.learn(db, user.id, body.text, body.applies_to, None)
    if ls is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "I already know that one")
    db.commit()
    return ls


def _own(lesson_id: uuid.UUID, user: User, db: Session) -> Lesson:
    ls = db.get(Lesson, lesson_id)
    if ls is None or ls.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lesson not found")
    return ls


@router.patch("/me/lessons/{lesson_id}", response_model=LessonOut)
def edit_lesson(lesson_id: uuid.UUID, body: LessonPatch, user: User = Depends(current_user),
                db: Session = Depends(get_db)) -> Lesson:
    ls = _own(lesson_id, user, db)
    if body.text is not None:
        ls.text = " ".join(body.text.split())
    if body.applies_to is not None:
        ls.applies_to = LS.norm(body.applies_to) or "all"
    if body.active is not None:
        ls.active = body.active
    db.commit()
    return ls


@router.delete("/me/lessons/{lesson_id}", status_code=status.HTTP_204_NO_CONTENT)
def forget_lesson(lesson_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> None:
    """Forget it (the app's Undo on "I'll remember...")."""
    db.delete(_own(lesson_id, user, db))
    db.commit()
