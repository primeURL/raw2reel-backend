"""Caption looks and ready-made templates for the app's pickers, with preview images drawn by the
real renderer (scripts/make_look_previews.py)."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import current_user
from app.db import get_db
from app.models import Style, StyleStatus, User
from app.schemas import StyleOut
from app.services import caption_looks as CL
from app.services import motion as MO
from app.services import templates as T

router = APIRouter(tags=["looks"])


def _static(request: Request, path: str) -> str:
    return str(request.base_url).rstrip("/") + "/static/" + path


@router.get("/caption-looks")
def caption_looks(request: Request, user: User = Depends(current_user)) -> dict:
    return {
        "groups": [{"id": g, "name": n} for g, n in CL.GROUPS.items()],
        "looks": [{"id": lk.id, "name": lk.name, "group": lk.group, "animation": lk.animation,
                   "preview_url": _static(request, f"looks/{lk.id}.jpg")} for lk in CL.LOOKS],
    }


@router.get("/templates")
def templates(request: Request, user: User = Depends(current_user)) -> list[dict]:
    return [{"id": t.id, "name": t.name, "emoji": t.emoji, "tagline": t.tagline, "summary": t.profile["summary"],
             "caption_look": t.profile["captions"]["look"], "music_mood": t.profile["sound"]["music_mood"],
             "cover_url": _static(request, f"templates/{t.id}.jpg")} for t in T.TEMPLATES]


@router.post("/templates/{template_id}/use", response_model=StyleOut)
def use_template(template_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> StyleOut:
    """The template as one of the creator's styles (made once, then reused)."""
    t = T.get(template_id)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found")
    for s in db.scalars(select(Style).where(Style.user_id == user.id)):
        if (s.meta or {}).get("template") == t.id:
            return StyleOut.model_validate(s).model_copy(update={"template": t.id})
    style = Style(user_id=user.id, name=t.name, status=StyleStatus.ready, profile=T.validated(t),
                  meta={"template": t.id, "reference_notes": [f"Started from the {t.name} template"]})
    db.add(style)
    db.commit()
    db.refresh(style)
    return StyleOut.model_validate(style).model_copy(update={"template": t.id})


@router.get("/effects/motion")
def motion_effects(request: Request, user: User = Depends(current_user)) -> list[dict]:
    """The motion-graphics effects for the editor's gallery, with a looping preview and sample inputs."""
    return [{"type": k, "name": name, "help": help_, "sample": sample,
             "position": MO.DEFAULT_POSITION.get(k, "top"),
             "preview_url": _static(request, f"motion/{k}.webp")} for k, (name, help_, sample) in MO.CATALOG.items()]
