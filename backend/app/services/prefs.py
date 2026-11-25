"""The creator's own choices for one reel (caption look, sounds, transitions, effects).

Anything they leave unset follows their style. merged_style() folds the choices into the style
profile, so the AI, the validator and the renderer all read one source of truth. Caption looks
need no AI: the renderer reads them, so changing them only needs a new export.
"""

from copy import deepcopy

TRANSITIONS = {"cuts": "hard_cuts", "smooth": "dissolves", "energetic": "mixed"}
SOUNDS = {"off": "none", "subtle": "subtle", "punchy": "frequent"}
EFFECTS_NOTE = {
    "none": "Use no effects at all (effects = []).",
    "few": "Use only 1-2 effects, on the strongest moments.",
    "lots": "Use plenty of effects - one on most key moments, still never two zooms at once.",
}


def merged_style(profile: dict | None, prefs: dict | None) -> dict | None:
    if not prefs:
        return profile
    out = deepcopy(profile) if profile else {}
    caps = {k: v for k, v in (prefs.get("captions") or {}).items() if v is not None}
    if caps:
        c = out.setdefault("captions", {})
        for key, target in (("enabled", "enabled"), ("animation", "animation"), ("look", "look"), ("size", "size"),
                            ("position", "position"), ("case", "case"), ("highlight", "keyword_highlight")):
            if key in caps:
                c[target] = caps[key]
    if prefs.get("transitions"):
        out.setdefault("look", {})["transitions"] = TRANSITIONS[prefs["transitions"]]
    if prefs.get("sound_effects"):
        out.setdefault("sound", {})["sound_effects"] = SOUNDS[prefs["sound_effects"]]
    return out or None


def ai_note(prefs: dict | None) -> str | None:
    """What the AI must follow on top of the style, in words."""
    if not prefs:
        return None
    notes = []
    caps = prefs.get("captions") or {}
    if caps.get("enabled") is False:
        notes.append("No captions at all (captions = []).")
    if caps.get("highlight") is True:
        notes.append("Highlight the key word in most captions.")
    elif caps.get("highlight") is False:
        notes.append("No highlighted words (highlight = null everywhere).")
    if caps.get("position"):
        notes.append(f"Put captions in {caps['position']} unless that covers a face.")
    if prefs.get("sound_effects"):
        notes.append(f"sound_effects must be {prefs['sound_effects']}.")
    if prefs.get("transitions"):
        notes.append({"cuts": "Use plain cuts only.", "smooth": "Use gentle transitions: mostly cuts, a zoom on the big scene changes.",
                      "energetic": "Use energetic transitions: whip or zoom on most scene changes, a flash on the biggest beat."}[prefs["transitions"]])
    if prefs.get("effects"):
        notes.append(EFFECTS_NOTE[prefs["effects"]])
    mus = prefs.get("music") or {}
    if mus.get("enabled") is False:
        notes.append("No background music (music.enabled false).")
    elif mus.get("track"):
        notes.append("The creator picked the music track themselves: keep music.enabled true.")
    return " ".join(notes) or None


def enforce(plan, prefs: dict | None) -> None:
    """Make sure the plan obeys the hard choices, whatever the AI wrote."""
    if not prefs:
        return
    caps = prefs.get("captions") or {}
    if caps.get("enabled") is False:
        plan.captions = []
    if caps.get("highlight") is False:
        for c in plan.captions:
            c.highlight = None
    if caps.get("position"):
        for c in plan.captions:
            c.position = caps["position"]
    if prefs.get("sound_effects"):
        plan.sound_effects = prefs["sound_effects"]
        if plan.sound_effects == "off":
            plan.sounds = []
    if prefs.get("transitions") == "cuts":
        for s in plan.shots:
            s.transition_in = "cut"
    if prefs.get("effects") == "none":
        plan.effects = []
    mus = prefs.get("music") or {}
    if mus.get("enabled") is not None:
        plan.music.enabled = mus["enabled"]
    if mus.get("track"):
        plan.music.enabled, plan.music.track = True, mus["track"]
    if mus.get("volume"):
        plan.music.volume = mus["volume"]
