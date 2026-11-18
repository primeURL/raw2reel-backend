"""Edit plans with Claude: clips (contact sheets + measured facts) + style + script -> EditPlan."""

import base64
import json
import logging
from dataclasses import dataclass

from app.services.plan_schema import EditPlan
from app.services.style_ai import StyleAIError, _parse

log = logging.getLogger(__name__)

SYSTEM = """You are the editor inside Raw2Reel. You turn a creator's raw phone clips into one \
short vertical reel (1080x1920), following their style profile and their script.

You get, for each clip: an alias (C1, C2...), its length, a contact sheet (evenly spaced frames, \
each stamped with its time inside that clip), scene cuts, silences, and a transcript with timings.

Rules:
- Follow the creator's script and clip order when they give one. Their words win over the style.
- Pick the best moments using the contact sheet times: skip shaky starts, the camera being set \
up, the subject leaving frame, and dead air. shot in_s/out_s are seconds INSIDE that clip and must \
stay within its length.
- The same clip may be used more than once. A second "angle" from one clip = a different time \
range with zoom_from/zoom_to of 1.5-1.8 and focus_x/focus_y on the subject.
- Respect the style: shot lengths, total length, captions (words on screen, position, script), \
look, music, ending. Never put text over the subject's face: pick the caption position for that.
- Captions are on the final timeline. Give each one enough time to read: about 0.5 s + 0.3 s per \
word. They must not overlap. Highlight at most one number in the whole reel.
- If someone speaks (has_speech), keep_audio=true on that shot and caption what they say, timed \
to the transcript; otherwise keep_audio=false and write short captions from the script.
- A stats card may only show numbers the creator provided in run_stats. Never invent numbers. \
It may start at the end of the last shot; the last frame is held underneath it.
- Write captions in the creator's language. For Hindi/Hinglish follow the style's script setting.
- Only one thing reads at a time: don't add a title overlay that repeats a caption, and keep \
captions in lower_middle while a stats card is on screen. A highlight is a whole word or a \
number with its unit (e.g. "2 km").
- Keep the total reel inside the style's target length unless the script asks otherwise."""


@dataclass
class ClipInput:
    alias: str
    duration_s: float
    contact_sheet_jpeg: bytes
    has_speech: bool
    transcript_segments: list[dict]
    scene_cuts: list[float]
    silences: list[dict]


def _clip_blocks(c: ClipInput) -> list[dict]:
    segs = [{"start": s["start"], "end": s["end"], "text": s["text"]} for s in c.transcript_segments][:40]
    facts = {
        "duration_s": round(c.duration_s, 2),
        "has_speech": c.has_speech,
        "transcript": segs or None,
        "scene_cuts_s": c.scene_cuts[:20],
        "silences": [[s["start"], s["end"]] for s in c.silences][:20],
    }
    return [
        {"type": "text", "text": f"Clip {c.alias}:\n{json.dumps(facts, ensure_ascii=False)}"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                     "data": base64.standard_b64encode(c.contact_sheet_jpeg).decode()}},
    ]


def write_plan(
    clips: list[ClipInput],
    style_profile: dict | None,
    title: str,
    script: str | None,
    language: str | None,
    run_stats: dict | None,
) -> tuple[EditPlan, dict]:
    brief = {
        "title": title,
        "script": script or "(none - decide the story from the clips and the style)",
        "language": language or "auto",
        "run_stats": run_stats or {},
        "style_profile": style_profile or "(no style chosen - make a clean, simple edit)",
    }
    content: list[dict] = [{"type": "text", "text": "Brief:\n" + json.dumps(brief, ensure_ascii=False, indent=1)}]
    for c in clips:
        content += _clip_blocks(c)
    content.append({"type": "text", "text": "Write the edit plan."})
    return _parse(SYSTEM, content, EditPlan, effort="medium")


__all__ = ["ClipInput", "write_plan", "StyleAIError"]
