"""Edit plans with Claude: clips (contact sheets + measured facts) + style + script -> EditPlan."""

import base64
import difflib
import json
import logging
import re
from dataclasses import dataclass

from pydantic import BaseModel, Field

from app.services import lessons, library, reps
from app.services.plan_schema import BUILT_IN_SOUNDS, AIEditPlan, EditPlan
from app.services.style_ai import StyleAIError, _parse

log = logging.getLogger(__name__)

SYSTEM = """You are the editor inside Raw2Reel. You turn a creator's raw phone clips into one \
short vertical reel (1080x1920), following their style profile and their script.

You get, for each clip: an alias (C1, C2...), its length, a contact sheet (evenly spaced frames, \
each stamped with its time inside that clip), scene cuts, silences, and a transcript with timings.

Rules:
- Use EVERY clip at least once. The creator chose these clips; never drop one because it seems
  weaker - give it a short shot instead. Only leave a clip out if the script explicitly says so.
- The script is the story. When the creator gives one, split it into its steps (beats) in the \
order it tells them, then LOOK at every contact sheet to find which clip shows each step, and put \
the shots in the order of the story - not in upload order. Example: the script says "chop apple, \
banana and cashews, then oats in milk" and C4 shows chopping fruit while C1 shows oats -> C4's \
shots come first. Write the result in `story`: each beat with the clips that show it. A clip that \
fits no beat goes where it fits best (often as a short cutaway in the nearest beat).
- With no script, keep the given order (C1, C2, C3...) unless the frames clearly show a natural \
sequence (e.g. cooking steps); still fill `story` with what you made of it.
- Follow the creator's script when they give one. Their words win over the style, and so do \
their creator_choices (caption look, sounds, transitions, effects).
- creator_lessons are corrections this creator made to earlier edits. Follow every one whose \
applies_to is "all" or fits this reel (e.g. "workout" for exercise clips): they win over the style, \
and only this reel's script or creator_choices can override them.
- Pick the best moments using the contact sheet times: skip shaky starts, the camera being set \
up, the subject leaving frame, and dead air. shot in_s/out_s are seconds INSIDE that clip and must \
stay within its length.
- The same clip may be used more than once. A second "angle" from one clip = a different time \
range with zoom_from/zoom_to of 1.5-1.8 and focus_x/focus_y on the subject.
- Respect the style: shot lengths, total length, captions (words on screen, position, script), \
look, music, ending. Never put text over the subject's face: pick the caption position for that.
- Captions are on the final timeline. Give each one enough time to read: about 0.5 s + 0.3 s per \
word. They must not overlap. Follow the style's captions: mode and max_words_on_screen decide how \
many words show at once (word_by_word/phrase = short captions in quick succession), case decides \
capitals. Highlights: if the style has keyword_highlight, give most captions a highlight - the one \
word that carries the meaning (the ingredient, the number, the result); otherwise highlight at most \
one number in the whole reel.
- If someone speaks (has_speech), keep_audio=true on that shot and caption what they say, timed \
to the transcript; otherwise keep_audio=false and write short captions from the script.
- A stats card may only show numbers the creator provided in run_stats. Never invent numbers. \
It may start at the end of the last shot; the last frame is held underneath it.
- Write captions in the creator's language. For Hindi/Hinglish follow the style's script setting.
- Only one thing reads at a time: don't add a title overlay that repeats a caption, and keep \
captions in lower_middle while a stats card is on screen. A highlight is a whole word or a \
number with its unit (e.g. "2 km").
- Keep the total reel inside the style's target length unless the script asks otherwise; if every
  clip can't fit, shorten shots rather than dropping clips.

Talking clips (best take):
- People say a line, dislike it and say it again. likely_retakes lists transcript segments (by \
index) that are tries of the same line. Keep ONE take of each line: the fluent one that matches \
the script, later over earlier when equal (people warm up). Leave out restarts, false starts, \
"okay again", fillers and long pauses. Do this by splitting the clip into several shots (same \
clip, different in_s/out_s) in speaking order. Cut in the gaps between segments, never inside one. \
This is how a talking clip is "used"; it still counts as using every clip.
- If a long sentence run is clean, keep it as one shot rather than cutting it into pieces.

Effects (optional, a few, on key moments; follow the style's energy, none for a calm style):
- punch_in on the one word that carries the point; slow_push under a reflective line; spotlight \
for a reveal; grade for a mood change (e.g. bw for a flashback); freeze_frame with a 2-4 word \
label to point at something; flash on a hard beat or cut; countdown before a start; \
backdrop_word for the topic or the big result, early in the reel, behind a person facing the camera.
- sound_effects: off for a calm/cinematic or music-led style (or the style's sound.sound_effects \
is none), punchy for high energy or "frequent", else subtle.

Graphics (the motion-graphic effect types: chat, counter, checklist...):
- Add one only where it shows something the reel is about that the picture alone doesn't say. 0-3 \
per reel; none for a calm or aesthetic style unless the script asks. They don't count towards the \
one-effect-every-4-s limit, but never two graphics at once.
- Numbers come only from the script, run_stats, what is said, or repeated_movement. Never invent \
prices, stats, names, handles or counts. No name or handle known -> no name_card / follow.
- Pick by content: exercise with repeated_movement -> counter (title the exercise, e.g. "PUSH-UPS", \
numbers [0], or [reps already shown] for a later set) starting just before the first rep of the shot; \
cut exercise shots between rep_windows_s so every rep shows whole, down and up (the app moves a cut \
that lands inside a rep). The \
app counts each real rep as it finishes and runs it to the last one. Captions that count reps use \
those rep_done_at_s times. Recipe ingredients or steps -> checklist; a place -> location near the \
start; a product price -> price_tag; workout/run numbers in run_stats -> widgets or graph near the \
end; day N of a challenge -> progress; a timed hold (plank) -> timer with its seconds; a story or \
comedy hook -> chat or notification in the first 3 s; the creator introducing themselves -> \
name_card; the creator asking to follow -> follow on the last shot; a celebration -> emoji_burst.
- Place it away from the face and the action (position top/middle/bottom from the contact sheet) \
and not where the captions are at that time. behind=true only for a big counter or price_tag at \
middle while one person fills the frame; else false.
- Graphics come with their own sound; don't add one for them (the counter ticks by itself).

Transitions (transition_in on each shot):
- Follow the style's look.transitions: hard_cuts -> almost all cut; whip -> whip when the scene or \
step changes; mixed -> whip or zoom on step changes, flash on one hard beat; dissolves -> cut, with \
a zoom only on the biggest change. The first shot is always cut, and so is every cut inside one \
continuous talking take. Use at most one non-cut transition every ~3 s.

Sound design (sounds; [] when sound_effects is off):
- You are the sound designer. Place each sound on the moment it accents, in reel seconds: \
whoosh_fast on every whip/zoom transition (at the cut) and on a punch_in; whoosh_soft under a \
slow_push or a gentle change; slam when a backdrop_word lands (+0.25 s), on a flash or the result; \
boom for a spotlight or the one big reveal; shutter on a freeze_frame; tick on each count of a \
countdown or while ticking through list items (ingredients, steps); pop when a key highlighted \
word or a list item appears.
- Match the style's energy: subtle = only the transitions and effects; punchy/frequent = also pops \
on key captions. Never more than one sound every ~0.6 s. level soft while someone is talking, \
loud only for the single biggest moment.
- Every effect and every non-cut transition gets its sound; nothing else needs one.
- The brief's sound_library says which sounds are available; use only those. Extra ones when \
available: riser building into a reveal (at_s = the reveal), ding on a tip or idea, click on a tap \
or a list item, swipe on a quick slide, glitch on a digital jump, cash on a price or money moment.

Music (music_library in the brief lists the moods we have):
- Pick music.mood from that list to fit the story and the style's music_mood (food/vlog -> upbeat \
or chill, fitness -> energetic, a milestone or family story -> emotional, festival/wedding -> desi, \
a reveal or travel -> cinematic). enabled false only if the style's music is none, or the library is empty.
- volume: low_under_voice when someone talks most of the reel, medium for a mix, music_led when \
there is little or no speech. The app picks the track, starts it on the beat and dips it under speech.
- At most one effect every ~4 s, never two zooms/freezes at once. They follow the face, so use \
punch_in/spotlight/freeze_frame/backdrop_word on shots where a person is visible. Times are on the final reel."""


@dataclass
class ClipInput:
    alias: str
    duration_s: float
    contact_sheet_jpeg: bytes
    has_speech: bool
    transcript_segments: list[dict]
    scene_cuts: list[float]
    silences: list[dict]
    reps: dict | None = None


def _norm(t: str) -> str:
    return re.sub(r"[^\w ]", "", t.lower()).strip()


def likely_retakes(segments: list[dict]) -> list[list[int]]:
    """Groups of transcript segments that look like tries of the same line (free, no AI).
    Similar wording, or one try that stops part-way and the next that starts the same way."""
    texts = [_norm(s.get("text", "")) for s in segments]
    groups, seen = [], set()
    for i, a in enumerate(texts):
        if i in seen or len(a.split()) < 2:
            continue
        group = [i]
        for j in range(i + 1, min(len(texts), i + 8)):  # retakes come close together
            b = texts[j]
            if j in seen or len(b.split()) < 2:
                continue
            short, long_ = sorted((a, b), key=len)
            prefix = len(short.split()) >= 3 and long_.startswith(" ".join(short.split()[:3]))
            if prefix or difflib.SequenceMatcher(None, a, b).ratio() >= 0.6:
                group.append(j)
        if len(group) > 1:
            seen.update(group)
            groups.append(group)
    return groups


def _clip_blocks(c: ClipInput) -> list[dict]:
    segs = [{"i": n, "start": s["start"], "end": s["end"], "text": s["text"]} for n, s in enumerate(c.transcript_segments)][:80]
    facts = {
        "duration_s": round(c.duration_s, 2),
        "has_speech": c.has_speech,
        "transcript": segs or None,
        "likely_retakes": likely_retakes(segs) or None,
        "scene_cuts_s": c.scene_cuts[:20],
        "silences": [[s["start"], s["end"]] for s in c.silences][:20],
        "repeated_movement": ({"reps": c.reps["count"], "rep_done_at_s": c.reps["up_s"][:40],
                               "rep_windows_s": [list(w) for w in reps.windows(c.reps)][:40]} if c.reps else None),
    }
    return [
        {"type": "text", "text": f"Clip {c.alias}:\n{json.dumps(facts, ensure_ascii=False)}"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                     "data": base64.standard_b64encode(c.contact_sheet_jpeg).decode()}},
    ]


def _library_brief() -> dict:
    moods = library.moods_available()
    return {
        "music_library": {m: library.MOOD_HELP[m] for m in moods} or "(empty - set music.enabled false)",
        "sound_library": sorted(set(BUILT_IN_SOUNDS) | library.sfx_categories()),
    }


def _as_plan(ai_plan: AIEditPlan) -> EditPlan:
    """The AI's plan as a stored plan (adds the app-side fields, like the music track). Stats cards
    and titles come in as effects; they're stored as overlays."""
    data = ai_plan.model_dump()
    effects, overlays = [], []
    for e in data["effects"]:
        if e["type"] in ("stats_card", "title"):
            rows = [r.split("|", 1) for r in e["items"] if "|" in r] if e["type"] == "stats_card" else []
            overlays.append({"type": e["type"], "start_s": e["start_s"], "end_s": e["end_s"], "title": e["text"],
                             "items": [{"label": a.strip(), "value": b.strip()} for a, b in rows]})
        else:
            effects.append(e)
    data["effects"], data["overlays"] = effects, overlays
    return EditPlan.model_validate(data)


def write_plan(
    clips: list[ClipInput],
    style_profile: dict | None,
    title: str,
    script: str | None,
    language: str | None,
    run_stats: dict | None,
    choices: str | None = None,
    creator_lessons: list[dict] | str | None = None,
) -> tuple[EditPlan, dict]:
    brief = {
        "title": title,
        "script": script or "(none - decide the story from the clips and the style)",
        "language": language or "auto",
        "run_stats": run_stats or {},
        "style_profile": style_profile or "(no style chosen - make a clean, simple edit)",
        "creator_choices": choices or "(none - follow the style)",
        "creator_lessons": creator_lessons or "(none yet)",
        **_library_brief(),
    }
    content: list[dict] = [{"type": "text", "text": "Brief:\n" + json.dumps(brief, ensure_ascii=False, indent=1)}]
    for c in clips:
        content += _clip_blocks(c)
    content.append({"type": "text", "text": "Write the edit plan."})
    plan, usage = _parse(SYSTEM, content, AIEditPlan, effort="medium")
    return _as_plan(plan), usage


REVISE = """

Revising: the creator watched the edit below and asks for a change in their own words. Make that \
change and keep everything they didn't mention as it is (same shots, captions, effects and sounds), \
re-timing captions, effects and sounds that sit after anything you lengthen, shorten or move. If \
they ask for "another version" or "something different", make a fresh take that still tells the \
same story. Follow the same rules as above. In `changes`, list what you changed, each in a few \
plain words the creator will read (e.g. "Oats scene now comes first", "Added a pop on each \
ingredient").

Learning: if the request shows a lasting preference of this creator - something they would want \
in their next reels too (a sound they dislike, how to show exercise reps, caption taste, pacing) - \
write it in `lesson` as one short rule in plain words, e.g. "No pop sounds", "Show every rep fully, \
down and up". Leave it "" when the request is only about this reel's content (which scene comes \
first, a typo, this clip's timing), or when creator_lessons already has it."""


class AIRevision(BaseModel):
    changes: list[str] = Field(description="what you changed, each in a few plain words for the creator")
    lesson: str = Field(description="a lasting preference learnt from this request, as a short rule; '' if none")
    lesson_applies_to: str = Field(description="'all', or the kind of reel the lesson is about in 1-2 words, e.g. 'workout', 'recipe'")
    lesson_rule: lessons.Rule = Field(description=lessons.RULE_HELP)
    plan: AIEditPlan


def revise_plan(
    clips: list[ClipInput],
    style_profile: dict | None,
    title: str,
    script: str | None,
    language: str | None,
    run_stats: dict | None,
    current: dict,
    request: str,
    choices: str | None = None,
    creator_lessons: list[dict] | str | None = None,
) -> tuple[EditPlan, list[str], dict, dict | None]:
    brief = {
        "title": title,
        "script": script or "(none)",
        "language": language or "auto",
        "run_stats": run_stats or {},
        "style_profile": style_profile or "(no style chosen - make a clean, simple edit)",
        "creator_choices": choices or "(none - follow the style)",
        "creator_lessons": creator_lessons or "(none yet)",
        **_library_brief(),
    }
    content: list[dict] = [{"type": "text", "text": "Brief:\n" + json.dumps(brief, ensure_ascii=False, indent=1)}]
    for c in clips:
        content += _clip_blocks(c)
    content.append({"type": "text", "text": "Current edit (its overlays go in your plan as stats_card / title "
                    "effects):\n" + json.dumps(current, ensure_ascii=False)})
    content.append({"type": "text", "text": f"The creator asks: {request.strip()}\n\nWrite the revised edit plan."})
    out, usage = _parse(SYSTEM + REVISE, content, AIRevision, effort="medium")
    lesson = ({"text": out.lesson.strip(), "applies_to": lessons.norm(out.lesson_applies_to) or "all", "rule": out.lesson_rule}
              if out.lesson.strip() else None)
    return _as_plan(out.plan), [c for c in out.changes if c.strip()][:8], usage, lesson


__all__ = ["ClipInput", "write_plan", "revise_plan", "StyleAIError"]
