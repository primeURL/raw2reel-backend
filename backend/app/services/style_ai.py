"""Style analysis with Claude.

Input per reference: its contact sheet (image) + measured facts (duration, pacing, loudness,
transcript, Instagram caption). Output: a validated StyleProfile + 3 questions (StyleAnalysis).
A second call folds the user's answers back into the profile.
"""

import base64
import json
import logging
from dataclasses import dataclass
from functools import lru_cache

import anthropic

from app.config import get_settings
from app.services.style_schema import StyleAnalysis, StyleProfile

log = logging.getLogger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"

SYSTEM = """You are the editing brain of Raw2Reel, an app that edits short vertical reels \
(Instagram Reels / YouTube Shorts) automatically for creators.

A creator has shared reels whose editing they love. Your job is to turn them into a style \
profile that an automatic editor will follow for the creator's OWN footage.

How to work:
- Each reference comes with a contact sheet (evenly spaced frames, each stamped with its time) \
and measured facts: duration, shot lengths from scene detection, loudness, and a transcript. \
Trust the measurements for pacing; use the frames for captions, framing, colour, graphics.
- A transcript can be song lyrics from the background music rather than the creator speaking: \
if it reads like lyrics, treat that reel as music-led with no voice.
- Find what the references share. Where they disagree, choose the most likely intent and ask \
about it in a question.
- Be INSPIRED, never copy: take principles (pacing, caption feel, energy, hook), not their exact \
fonts, logos, brand marks, music, graphics or wording. Describe fonts by feel only. Do not name \
third-party apps or brands as part of the style.
- Prefer concrete, followable values (seconds, sizes, positions) over adjectives.
- Captions must never sit in the bottom 15% of the frame.
- Write the summary in plain words a creator understands.
- Ask exactly 3 questions, only about real ambiguities that change the edit. Give 2-4 short \
tappable options each."""

UPDATE_SYSTEM = """You maintain a creator's editing style profile for Raw2Reel. Apply the \
creator's answers to the profile: change every field the answers affect, keep everything else, \
and keep the summary in plain words. The answers are the creator's preference and win over \
what the references suggested. Still never copy third-party fonts, logos, music or text."""


class StyleAIError(RuntimeError):
    """Shown to the user as the style's error."""


@dataclass
class ReferenceInput:
    index: int
    duration_s: float
    contact_sheet_jpeg: bytes
    pacing: dict | None
    loudness_lufs: float | None
    transcript: str
    spoken_language: str | None
    ig_caption: str | None


@lru_cache
def _client() -> anthropic.Anthropic:
    s = get_settings()
    if not s.anthropic_api_key:
        raise StyleAIError("The AI service is not configured yet (ANTHROPIC_API_KEY is missing)")
    return anthropic.Anthropic(api_key=s.anthropic_api_key, max_retries=3, timeout=600)


def _reference_blocks(ref: ReferenceInput) -> list[dict]:
    facts = {
        "duration_s": round(ref.duration_s, 1),
        "pacing": ref.pacing,
        "loudness_lufs": ref.loudness_lufs,
        "spoken_language": ref.spoken_language,
        "transcript": (ref.transcript or "")[:1500] or "(no speech - music/ambience only)",
        "instagram_caption": (ref.ig_caption or "")[:300] or None,
    }
    return [
        {"type": "text", "text": f"Reference {ref.index}:\n{json.dumps(facts, ensure_ascii=False, indent=1)}"},
        {
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.standard_b64encode(ref.contact_sheet_jpeg).decode()},
        },
    ]


def _parse(system: str, content: list[dict], output_format, effort: str):
    s = get_settings()
    try:
        resp = _client().beta.messages.parse(
            model=s.anthropic_model,
            max_tokens=8000,  # a full profile + questions is ~2-3k tokens; cap runaway spend
            system=system,
            messages=[{"role": "user", "content": content}],
            output_format=output_format,
            output_config={"effort": effort},
            betas=[FALLBACK_BETA],
            fallbacks="default",  # on a policy decline, the API retries on a fallback model in the same call
        )
    except anthropic.RateLimitError as exc:
        raise StyleAIError("The AI service is busy right now, please try again in a minute") from exc
    except anthropic.APIStatusError as exc:
        log.error("claude error %s: %s", exc.status_code, exc.message)
        raise StyleAIError(f"The AI service returned an error ({exc.status_code})") from exc
    except anthropic.APIConnectionError as exc:
        raise StyleAIError("Couldn't reach the AI service, please try again") from exc

    if resp.stop_reason == "refusal":
        raise StyleAIError("The AI couldn't analyse these references. Try different reels.")
    if resp.stop_reason == "max_tokens" or resp.parsed_output is None:
        raise StyleAIError("The AI response was incomplete, please try again")
    usage = {
        "model": resp.model,
        "effort": effort,
        "input_tokens": resp.usage.input_tokens,
        "output_tokens": resp.usage.output_tokens,
    }
    log.info("claude call: %s", usage)
    return resp.parsed_output, usage


def analyze_references(refs: list[ReferenceInput], style_name: str | None = None) -> tuple[StyleAnalysis, dict]:
    content: list[dict] = [
        {"type": "text", "text": f"The creator shared {len(refs)} reference reel(s)."
         + (f" They call this style \"{style_name}\"." if style_name and style_name != "My style" else "")},
    ]
    for ref in refs:
        content += _reference_blocks(ref)
    content.append({"type": "text", "text": "Write the style profile, one note per reference, and the 3 questions."})
    # Sonnet 5.5 at medium effort: enough judgement for reading 3-6 reels, far cheaper than high.
    return _parse(SYSTEM, content, StyleAnalysis, effort="medium")


def apply_answers(profile: dict, questions: list[dict], answers: list[dict]) -> tuple[StyleProfile, dict]:
    qa = []
    by_id = {a["question_id"]: a["answer"] for a in answers}
    for q in questions:
        if q["id"] in by_id:
            qa.append({"question": q["question"], "answer": by_id[q["id"]]})
    if "_notes" in by_id:
        qa.append({"question": "Anything else to change?", "answer": by_id["_notes"]})
    content = [
        {"type": "text", "text": "Current profile:\n" + json.dumps(profile, ensure_ascii=False, indent=1)},
        {"type": "text", "text": "Creator's answers:\n" + json.dumps(qa, ensure_ascii=False, indent=1)},
        {"type": "text", "text": "Return the updated profile."},
    ]
    # Folding 3 answers into a profile is simple editing: low effort.
    return _parse(UPDATE_SYSTEM, content, StyleProfile, effort="low")
