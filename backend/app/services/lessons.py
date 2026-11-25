"""Creator memory: lessons the editor learns from a creator's change requests.

When a creator asks for a change ("remove the pop sounds", "show every push-up fully"), the same
AI call that revises the edit also says whether the request shows a lasting preference. If it
does, we keep it as a lesson. Every later edit for that creator gets their lessons in the brief,
and the few that are simple switches (a banned sound, effect or transition, no music) the app
also enforces itself, so they hold whatever the AI writes.

A lesson applies to "all" reels, or to one kind (e.g. "workout"): the AI decides when a kind
fits the reel in front of it. Code-enforced rules only run for "all" lessons, since code can't
tell what a reel is about.
"""

import difflib
import re
import uuid
from typing import Literal, get_args

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Lesson
from app.services.plan_schema import EffectType, SoundName

MAX_LESSONS = 40  # per creator, newest first, in the brief
_SOUNDS = get_args(SoundName)
_EFFECTS = get_args(EffectType)

# what the app can enforce by itself; the AI picks one of these, or "none"
RULES = ("none", "plain_cuts", "no_music", "no_sound:whoosh", *(f"no_sound:{s}" for s in _SOUNDS), *(f"no_effect:{e}" for e in _EFFECTS))
Rule = Literal[RULES]  # type: ignore[valid-type]

RULE_HELP = ("the switch the app can flip to keep this lesson, if one fits exactly: no_sound:<sound> "
             "(no_sound:whoosh = every whoosh), "
             "no_effect:<effect type>, plain_cuts (no fancy transitions), no_music; else none")


def banned(sound: str, avoid: list[str] | set[str]) -> bool:
    """Is this sound off-limits? A family name ("whoosh") bans all of it (whoosh_fast, whoosh_soft)."""
    return any(sound == a or sound.startswith(a + "_") for a in avoid)


def norm(text: str) -> str:
    return re.sub(r"[^\w ]+", "", " ".join((text or "").lower().split()))


def active(db: Session, user_id: uuid.UUID) -> list[Lesson]:
    return list(db.scalars(select(Lesson).where(Lesson.user_id == user_id, Lesson.active.is_(True))
                           .order_by(Lesson.created_at.desc()).limit(MAX_LESSONS)))


def as_brief(lessons: list) -> list[dict] | str:
    """What the AI reads: each lesson and what kind of reel it's for."""
    rows = [{"lesson": ls.text, "applies_to": ls.applies_to} for ls in lessons]
    return rows or "(none yet)"


def as_dicts(lessons: list[Lesson]) -> list[dict]:
    """Plain copies, to use after the database session has closed."""
    return [{"text": ls.text, "applies_to": ls.applies_to, "rule": ls.rule} for ls in lessons]


def is_known(text: str, rule: str | None, existing: list) -> bool:
    """Already learnt: same switch, or nearly the same words."""
    n = norm(text)
    for ls in existing:
        r = ls["rule"] if isinstance(ls, dict) else ls.rule
        t = ls["text"] if isinstance(ls, dict) else ls.text
        if rule and rule != "none" and r == rule:
            return True
        if difflib.SequenceMatcher(None, n, norm(t)).ratio() >= 0.8:
            return True
    return False


def learn(db: Session, user_id: uuid.UUID, text: str, applies_to: str, rule: str | None,
          project_id: uuid.UUID | None = None, request: str | None = None) -> Lesson | None:
    """Keep a new lesson, unless it's empty or one the creator already has (on or off)."""
    text = " ".join((text or "").split())[:200]
    if len(text) < 4:
        return None
    rule = rule if rule in RULES and rule != "none" else None
    existing = list(db.scalars(select(Lesson).where(Lesson.user_id == user_id)))
    if is_known(text, rule, existing):
        return None
    applies = norm(applies_to)[:40] or "all"
    ls = Lesson(user_id=user_id, text=text, applies_to=applies, rule=rule, active=True,
                project_id=project_id, request=(request or "")[:2000] or None)
    db.add(ls)
    db.flush()
    return ls


def enforce(plan, lessons: list[dict]) -> list[str]:
    """Apply the switch lessons (for all reels) to a plan, whatever the AI wrote. Returns what changed."""
    done = []
    for ls in lessons:
        rule = ls.get("rule")
        if not rule or ls.get("applies_to", "all") != "all":
            continue
        if rule.startswith("no_sound:"):
            name = rule.split(":", 1)[1]
            if name not in plan.avoid_sounds:
                plan.avoid_sounds.append(name)
            before = len(plan.sounds)
            plan.sounds = [c for c in plan.sounds if not banned(c.sound, [name])]
            if len(plan.sounds) < before:
                done.append(f"No {name} sounds (you asked before)")
        elif rule.startswith("no_effect:"):
            kind = rule.split(":", 1)[1]
            if any(e.type == kind for e in plan.effects):
                plan.effects = [e for e in plan.effects if e.type != kind]
                done.append(f"No {kind.replace('_', ' ')} (you asked before)")
        elif rule == "plain_cuts":
            if any(s.transition_in != "cut" for s in plan.shots):
                for s in plan.shots:
                    s.transition_in = "cut"
                done.append("Plain cuts only (you asked before)")
        elif rule == "no_music" and plan.music.enabled:
            plan.music.enabled = False
            done.append("No music (you asked before)")
    return done

