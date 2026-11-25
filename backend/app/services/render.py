"""Edit plan -> MP4 with FFmpeg. No AI, deterministic: same plan + clips = same video.

Pipeline (all in a temp work dir):
  1. each shot -> segment.mp4   trim, speed, cover-crop to 1080x1920, optional zoom/push, its
                                own audio or silence (so every segment has the same streams)
  2. concat segments            stream copy
  3. faces + effects            find the face on the joined reel; draw face-aware effects
  4. finish                     hold last frame under an end card, overlay caption/title/card
                                PNGs with fades (captions moved off the face), even out the
                                voice level, fade out, final encode
  5. checks                     loudness, peaks, black frames, captions vs face, length
"""

import json
import logging
import re
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from app.services import caption_looks
from app.services import effects as fx
from app.services import faces as F
from app.services import graphics
from app.services import motion as MO
from app.services import music as M
from app.services import sfx as S
from app.services.plan_schema import EditPlan

log = logging.getLogger(__name__)

FPS = 30
QUALITY = {
    # name: (width, height, crf, preset)
    "preview": (540, 960, 28, "veryfast"),
    "final": (1080, 1920, 20, "medium"),
}
FADE_S = 0.3  # caption / overlay fade in & out
VOICE_LUFS = -16.0  # reels with someone talking are levelled to this (phone speakers, Reels/TikTok norm)
POSITION_NAMES = {"upper_third": "top", "middle": "middle", "lower_middle": "lower part"}


class RenderError(RuntimeError):
    pass


@dataclass
class RenderResult:
    path: Path
    duration_s: float
    thumbnail: Path
    notes: list[str] = field(default_factory=list)  # what the renderer changed on its own
    checks: list[dict] = field(default_factory=list)  # [{name, ok, detail}]


def _even(v: float) -> int:
    return max(2, int(round(v / 2)) * 2)


def _crop_layer(png: Path, work: Path, scale: float) -> tuple[Path, int, int, int, int]:
    """Cut a full-frame graphics layer down to what's drawn on it. Returns the cropped file and its
    place and size on the output frame (x, y, w, h), all scaled by `scale` (preview = 0.5)."""
    im = Image.open(png)
    box = im.getchannel("A").getbbox() if im.mode == "RGBA" else None
    if not box:
        return png, 0, 0, _even(im.width * scale), _even(im.height * scale)
    pad = 6
    x0, y0 = max(0, box[0] - pad), max(0, box[1] - pad)
    x1, y1 = min(im.width, box[2] + pad), min(im.height, box[3] + pad)
    out = work / f"{png.stem}_crop.png"
    im.crop((x0, y0, x1, y1)).save(out)
    return out, int(x0 * scale), int(y0 * scale), _even((x1 - x0) * scale), _even((y1 - y0) * scale)


def _run(cmd: list[str], timeout: int = 300) -> None:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise RenderError(f"ffmpeg took longer than {timeout}s and was stopped") from exc
    if p.returncode != 0:
        raise RenderError(f"ffmpeg failed: {p.stderr.strip()[-600:]}")


Progress = Callable[[float, str], None]  # (0..1 of the whole render, what is happening)


def _run_progress(cmd: list[str], expected_s: float, on: Callable[[float], None], timeout: int = 300) -> None:
    """Like _run, but reads ffmpeg's -progress output and reports 0..1 of expected_s."""
    cmd = cmd[:-1] + ["-progress", "pipe:1", "-nostats", cmd[-1]]
    start = time.monotonic()
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        for line in p.stdout:  # key=value lines, a block every ~0.5 s
            if line.startswith("out_time_us=") and expected_s > 0:
                try:
                    on(min(1.0, int(line.split("=", 1)[1]) / 1e6 / expected_s))
                except ValueError:
                    pass  # "N/A" before the first frame
            if time.monotonic() - start > timeout:
                p.kill()
                raise RenderError(f"ffmpeg took longer than {timeout}s and was stopped")
        p.wait(timeout=30)
    finally:
        if p.poll() is None:
            p.kill()
    if p.returncode != 0:
        raise RenderError(f"ffmpeg failed: {p.stderr.read().strip()[-600:]}")


def _probe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, timeout=60,
    ).stdout.strip()
    return float(out or 0)


def _segment(shot, src: Path, dest: Path, w: int, h: int, has_audio: bool, on: Callable[[float], None] = lambda _: None) -> float:
    dur_src = shot.out_s - shot.in_s
    dur = dur_src / shot.speed
    frames = max(1, round(dur * FPS))
    vf = [f"setpts=(PTS-STARTPTS)/{shot.speed}", f"fps={FPS}",
          f"scale={w}:{h}:force_original_aspect_ratio=increase", f"crop={w}:{h}"]
    if shot.zoom_from > 1.001 or shot.zoom_to > 1.001:
        # zoompan is jittery at 1x; render it at 2x then scale down for a smooth push
        z0, z1 = shot.zoom_from, shot.zoom_to
        z = f"{z0}+({z1}-{z0})*on/{max(frames - 1, 1)}"
        fx, fy = shot.focus_x, shot.focus_y
        vf += [
            f"scale={w * 2}:{h * 2}",
            f"zoompan=z='{z}':x='max(0,min(iw-iw/zoom,iw*{fx}-iw/zoom/2))':"
            f"y='max(0,min(ih-ih/zoom,ih*{fy}-ih/zoom/2))':d=1:s={w * 2}x{h * 2}:fps={FPS}",
            f"scale={w}:{h}",
        ]
    vf.append("format=yuv420p")

    cmd = ["ffmpeg", "-v", "error", "-y", "-ss", f"{shot.in_s:.3f}", "-t", f"{dur_src:.3f}", "-i", str(src)]
    if shot.keep_audio and has_audio:
        af = _atempo(shot.speed)
        cmd += ["-filter_complex", f"[0:v]{','.join(vf)}[v];[0:a]{af}aresample=48000,apad[a]",
                "-map", "[v]", "-map", "[a]"]
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                "-filter_complex", f"[0:v]{','.join(vf)}[v]", "-map", "[v]", "-map", "1:a"]
    cmd += ["-t", f"{dur:.3f}", "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast", "-crf", "16",
            "-c:a", "aac", "-b:a", "160k", "-ac", "2", "-ar", "48000", str(dest)]
    _run_progress(cmd, dur, on)
    return dur


def _atempo(speed: float) -> str:
    """atempo only accepts 0.5-2.0 per filter; chain for slower speeds."""
    parts, s = [], speed
    while s < 0.5:
        parts.append("atempo=0.5")
        s /= 0.5
    parts.append(f"atempo={s:.4f}")
    return ",".join(parts) + ","


def render(plan: EditPlan, timeline: dict, sources: dict[str, tuple[Path, bool]], style: dict | None,
           work: Path, quality: str = "final", progress: Progress | None = None) -> RenderResult:
    """sources: clip alias -> (proxy path, has_audio).

    progress(fraction, stage) is called as work advances: shots 5-45%, joining 45-55%,
    captions + final encode 55-95%. The caller reports downloading (0-5%) and uploading (95-100%)."""
    report = progress or (lambda f, s: None)
    if quality not in QUALITY:
        raise RenderError(f"unknown quality {quality}")
    w, h, crf, preset = QUALITY[quality]
    work.mkdir(parents=True, exist_ok=True)
    style = style or {}
    cap_style = style.get("captions") or {}
    accent = (style.get("look") or {}).get("accent_color") or "#FF5A1F"

    # 1. segments ---------------------------------------------------------------
    cuts = S.transition_times(plan)
    has_fx = bool(plan.effects or cuts)
    fx_share = 0.17 if has_fx else 0.0
    segs = []
    footage = max(sum((s.out_s - s.in_s) / s.speed for s in plan.shots), 0.001)
    done = 0.0
    for i, shot in enumerate(plan.shots):
        src, has_audio = sources[shot.clip]
        seg = work / f"seg{i:02d}.mp4"
        length = (shot.out_s - shot.in_s) / shot.speed
        stage = f"Cutting shot {i + 1} of {len(plan.shots)}"
        report(0.05 + 0.35 * done / footage, stage)
        _segment(shot, src, seg, w, h, has_audio, lambda f, d=done, n=length, st=stage: report(0.05 + 0.35 * (d + f * n) / footage, st))
        done += length
        segs.append(seg)

    # 2. join -------------------------------------------------------------------
    # The concat *filter* (re-encode), not the concat demuxer with stream copy: a segment with
    # real AAC audio shifts the copied timestamps (start 0.021 s), and the overlay step then
    # waits forever for frames that never line up.
    joined = work / "joined.mp4"
    report(0.40, "Joining shots")
    # every segment's decoder is open at once: keep each to 2 threads (each thread holds whole
    # 1080p frames) so a 12-clip reel doesn't need gigabytes
    ins = [x for s in segs for x in ("-threads", "2", "-i", str(s))]
    pads = "".join(f"[{i}:v][{i}:a]" for i in range(len(segs)))
    _run(["ffmpeg", "-v", "error", "-y", *ins, "-filter_complex", f"{pads}concat=n={len(segs)}:v=1:a=1[v][a]",
          "-map", "[v]", "-map", "[a]", "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast", "-crf", "16",
          "-c:a", "aac", "-b:a", "160k", "-ar", "48000", str(joined)], timeout=300)

    # 3. faces + effects -----------------------------------------------------------
    report(0.45, "Finding faces")
    notes: list[str] = []
    faces = F.track(joined, w, h, footage)
    if has_fx:
        motion_frames = {}
        if any(e.type in MO.MOTION_TYPES for e in plan.effects):
            report(0.47, "Drawing graphics")
            MO.keep_off_face(plan.effects, faces, h, notes)
            motion_frames = MO.render_all(plan.effects, w, h, FPS, accent, work, lambda f: report(0.47 + 0.01 * f, "Drawing graphics"))
        report(0.48, "Adding effects")
        fxd = work / "effects.mp4"
        fx.apply(joined, fxd, plan.effects, faces, w, h, FPS, accent, footage,
                 lambda f: report(0.48 + fx_share * f, "Adding effects"), transitions=cuts, motion_frames=motion_frames)
        joined = fxd
    final_from = 0.48 + fx_share
    report(final_from, "Adding captions and cards")

    # 4. graphics as PNG layers ------------------------------------------------------
    look = caption_looks.get(cap_style.get("look"))

    def caption_layer(i, c, center_y=None, words=None, name=None, active=None):
        return graphics.caption_png(
            c.text, work / (name or f"cap{i:02d}.png"), position=c.position,
            size=cap_style.get("size", "small"), weight=cap_style.get("weight", "medium"),
            color=cap_style.get("text_color", "#FFFFFF"), accent=accent, highlight=c.highlight,
            case=cap_style.get("case", "sentence"), center_y=center_y, visible_words=words,
            look=look, active_word=active,
        )

    still_on_face = 0
    layers: list[tuple[Path, float, float, str]] = []  # (png, start, end, animation)
    anim_name = (look.animation if look and look.animation else None) or cap_style.get("animation", "fade")
    cap_anim = {"pop": "pop", "typewriter": "typewriter", "slide_up": "slide_up", "none": "none",
                "karaoke": "karaoke"}.get(anim_name, "fade")
    card_times = [(o.start_s, o.end_s) for o in plan.overlays if o.type == "stats_card"]
    for i, c in enumerate(plan.captions):
        png = caption_layer(i, c)
        under_card = any(c.start_s < e and c.end_s > s_ for s_, e in card_times)  # must stay below the card
        boxes = faces.boxes(c.start_s, min(c.end_s, footage)) if faces.found else []
        if boxes and not under_card:
            hits = _face_hits(png, boxes, w / graphics.W)
            if hits > 0.25:
                planned = c.position
                scores = {planned: hits}
                for pos in ("lower_middle", "upper_third", "middle"):
                    if pos == planned:
                        continue
                    c.position = pos
                    scores[pos] = _face_hits(caption_layer(i, c), boxes, w / graphics.W)
                    if scores[pos] == 0:
                        break
                c.position = min(scores, key=lambda p: (scores[p], p != planned))
                png = caption_layer(i, c)  # the file holds the last trial; draw the chosen one again
                where = POSITION_NAMES[c.position]
                if scores[c.position] > 0.25:  # close-up: no fixed spot is free, hug the chin or the hair
                    for y, label in _free_heights(png, boxes, w / graphics.W):
                        trial = caption_layer(i, c, y)
                        if _face_hits(trial, boxes, w / graphics.W) <= 0.25:
                            png, where, scores[c.position] = trial, label, 0.0
                            break
                    else:
                        png = caption_layer(i, c)
                place = where if where.startswith("just") else "the " + where
                if scores[c.position] > 0.25:
                    still_on_face += 1
                    if c.position != planned:
                        notes.append(f"Caption \u201c{c.text}\u201d moved to {place} to cover less of your face")
                elif c.position != planned or where.startswith("just"):
                    notes.append(f"Caption \u201c{c.text}\u201d moved to {place} so it doesn't cover your face")
        n_words = len(c.text.split())
        if cap_anim == "typewriter" and n_words > 1:
            # word by word: one layer per step, each drawn with the same layout (lines never jump)
            center = graphics.layer_center_y(png)
            step = min(0.16, (c.end_s - c.start_s) * 0.6 / n_words)
            for k in range(1, n_words + 1):
                s0 = c.start_s + (k - 1) * step
                s1 = c.start_s + k * step if k < n_words else c.end_s
                layers.append((caption_layer(i, c, center, k, f"cap{i:02d}_w{k:02d}.png"), s0, s1,
                               "type_first" if k == 1 else "type_last" if k == n_words else "type_step"))
            continue
        if cap_anim == "karaoke" and n_words > 1:
            # the whole line stays; the highlight steps through the words as they're said
            center = graphics.layer_center_y(png)
            weights = [max(2, len(wd)) for wd in c.text.split()]  # longer words take longer to say
            t0, span = c.start_s, c.end_s - c.start_s
            for k in range(n_words):
                s0 = t0 + span * sum(weights[:k]) / sum(weights)
                s1 = t0 + span * sum(weights[:k + 1]) / sum(weights) if k < n_words - 1 else c.end_s
                layers.append((caption_layer(i, c, center, None, f"cap{i:02d}_k{k:02d}.png", k), s0, s1,
                               "type_first" if k == 0 else "type_last" if k == n_words - 1 else "type_step"))
            continue
        layers.append((png, c.start_s, c.end_s, "fade" if cap_anim == "karaoke" else cap_anim))
    for i, o in enumerate(plan.overlays):
        if o.type == "stats_card":
            png = graphics.stats_card_png(o.title, [(it.label, it.value) for it in o.items], work / f"ovl{i:02d}.png", accent=accent)
        else:
            png = graphics.title_png(o.title or "", work / f"ovl{i:02d}.png")
        layers.append((png, o.start_s, o.end_s, "fade"))
    # cards first so captions sit on top of them
    layers.sort(key=lambda l: 0 if l[0].name.startswith("ovl") else 1)

    # 5. finish: tail hold, overlays, voice level, end fade --------------------------
    total = timeline["total_s"]
    tail = timeline.get("tail_hold_s") or 0.0
    inputs = ["-i", str(joined)]
    chains = [f"[0:v]tpad=stop_mode=clone:stop_duration={tail:.3f},scale={w}:{h}[base]"]
    last = "base"
    for k, (png, start, end, anim) in enumerate(layers, start=1):
        d = max(end - start, 0.05)
        # typewriter steps swap hard (no fade between words); only the whole caption fades out
        fade_in = 0.0 if anim in ("none", "type_step", "type_last") else min(FADE_S if anim == "fade" else 0.12, d / 3)
        fade_out = 0.0 if anim in ("type_first", "type_step") else min(FADE_S if anim != "none" else 0.0, d / 3)
        # only the drawn part of the layer, placed where it was drawn: far less to blend per frame
        png, x, y, lw, lh = _crop_layer(png, work, w / graphics.W)
        # -itsoffset puts the layer's own timestamps at its start time, so ffmpeg only reads it when
        # the reel gets there. (Shifting it later in the filter instead made ffmpeg read every layer
        # at once and queue full-size RGBA frames until their turn: ~3 GB for 8 captions -> killed.)
        inputs += ["-loop", "1", "-framerate", str(FPS), "-t", f"{d:.3f}", "-itsoffset", f"{start:.3f}", "-i", str(png)]
        chain = f"[{k}:v]scale={lw}:{lh},format=rgba"
        ox, oy = str(x), str(y)
        if anim == "pop":  # grows in with a small overshoot; padded so the layer keeps one size
            lt = f"(t-{start:.3f})"
            grow = f"if(lt({lt},0.12),0.8+0.26*{lt}/0.12,if(lt({lt},0.2),1.06-0.06*({lt}-0.12)/0.08,1))"
            pw, ph = _even(lw * 1.08), _even(lh * 1.08)
            chain += (f",scale=w='trunc({lw}*{grow}/2)*2':h=-2:eval=frame,"
                      f"pad=w={pw}:h={ph}:x='(ow-iw)/2':y='(oh-ih)/2':color=black@0:eval=frame")
            ox, oy = str(x - (pw - lw) // 2), str(y - (ph - lh) // 2)
        elif anim == "slide_up":  # rises into place
            oy = f"'{y}+{round(36 * w / graphics.W)}*max(0,1-(t-{start:.3f})/0.22)'"
        if fade_in:
            chain += f",fade=t=in:st={start:.3f}:d={fade_in:.3f}:alpha=1"
        if fade_out:
            chain += f",fade=t=out:st={start + d - fade_out:.3f}:d={fade_out:.3f}:alpha=1"
        chain += f"[l{k}]"
        chains.append(chain)
        chains.append(f"[{last}][l{k}]overlay=x={ox}:y={oy}:eof_action=pass:enable='between(t,{start:.3f},{end:.3f})'[o{k}]")
        last = f"o{k}"
    fade_out = plan.end_fade_s
    voiced = any(sh.keep_audio and sources[sh.clip][1] for sh in plan.shots)
    # two-pass loudnorm sets the voice level exactly; the limiter catches peaks (and AAC overshoot)
    level = f",{_loudnorm(joined)},aresample=48000,alimiter=limit=0.75:level=disabled" if voiced else ""
    vfinal = f"[{last}]" + (f"fade=t=out:st={total - fade_out:.3f}:d={fade_out:.3f}," if fade_out else "") + "format=yuv420p[vout]"
    # sound effects go in after the voice is levelled, so they sit at a fixed distance under it
    sfx_cues = S.cues(plan, total)
    sfx_in, sfx_chains, sfx_labels = S.mix_graph(sfx_cues, plan.sound_effects, 1 + len(layers))  # after the video and the picture layers
    inputs += sfx_in
    # music goes in after the effects, dipped under the levelled voice
    music = M.mix_graph(plan, total, voiced, 1 + len(layers) + len(sfx_in) // 2, "vkey" if voiced else None)
    if music:
        inputs += music.inputs
    afade = f",afade=t=out:st={total - fade_out:.3f}:d={fade_out:.3f}" if fade_out else ""
    extra = [*sfx_labels, *([music.label] if music else [])]
    if extra:
        voice = level[1:] if level else "anull"
        if music and voiced:
            chains.append(f"[0:a]apad=whole_dur={total:.3f},{voice},asplit=2[voice][vkey]")
        else:
            chains.append(f"[0:a]apad=whole_dur={total:.3f},{voice}[voice]")
        chains += [*sfx_chains, *(music.chains if music else [])]
        chains.append("".join(f"[{x}]" for x in ["voice", *extra])
                      + f"amix=inputs={len(extra) + 1}:normalize=0:duration=first,"
                      + f"alimiter=limit=0.75:level=disabled{afade}[aout]")
    else:
        chains.append(f"[0:a]apad=whole_dur={total:.3f}{level}{afade}[aout]")
    chains.append(vfinal)

    out = work / "reel.mp4"
    _run_progress(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", ";".join(chains),
          "-map", "[vout]", "-map", "[aout]", "-t", f"{total:.3f}", "-r", str(FPS),
          "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p",
          "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-movflags", "+faststart", str(out)],
         total, lambda f: report(final_from + (0.92 - final_from) * f, "Adding captions and cards"),
         timeout=max(300, int(total * 20)))

    duration = _probe_duration(out)
    if abs(duration - total) > 0.25:
        log.warning("rendered %.2fs, plan said %.2fs", duration, total)
    thumb = work / "thumb.jpg"
    _run(["ffmpeg", "-v", "error", "-y", "-ss", f"{min(1.0, duration / 2):.2f}", "-i", str(out),
          "-frames:v", "1", "-vf", "scale=360:-2", "-q:v", "4", str(thumb)])

    # 6. checks ----------------------------------------------------------------------
    report(0.92, "Checking the reel")
    checks = quality_checks(out, total, duration, voiced, fade_out, still_on_face, faces.found > 0)
    return RenderResult(path=out, duration_s=round(duration, 3), thumbnail=thumb, notes=notes, checks=checks)


def _loudnorm(src: Path) -> str:
    """loudnorm filter for src's audio: measure first (audio only, about a second), then apply
    linearly. One-pass loudnorm undershoots on short or mostly silent reels (-20 for a -16 target)."""
    base = f"loudnorm=I={VOICE_LUFS}:TP=-2:LRA=11"
    try:
        p = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(src), "-vn", "-af", f"{base}:print_format=json",
                            "-f", "null", "-"], capture_output=True, text=True, timeout=120)
        m = json.loads(p.stderr[p.stderr.rindex("{"): p.stderr.rindex("}") + 1])
        if m["input_i"] in ("-inf", "inf") or float(m["input_i"]) < -60:
            return base  # (near) silence: nothing to measure
        return (f"{base}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}"
                f":measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
    except (ValueError, KeyError, subprocess.TimeoutExpired):
        log.warning("loudness measurement failed, using one-pass", exc_info=True)
        return base


def _free_heights(png: Path, boxes, scale: float) -> list[tuple[int, str]]:
    """Caption centre heights (1080x1920 space) just under the lowest chin / above the highest
    hair line in this stretch, if they fit inside the app's safe area."""
    with Image.open(png) as im:
        box = im.getchannel("A").point(lambda a: 255 if a > 140 else 0).getbbox()
    if not box:
        return []
    half = (box[3] - box[1]) / 2
    outs = [tuple(v / scale for v in F.keep_out(f)) for f in boxes]
    below = max(o[3] for o in outs) + 24 + half
    above = min(o[1] for o in outs) - 24 - half
    out = []
    if below + half <= graphics.SAFE_BOTTOM:
        out.append((int(below), "just under your chin"))
    if above - half >= graphics.SAFE_TOP:
        out.append((int(above), "just above your head"))
    return out


def _face_hits(png: Path, boxes: list[tuple[float, float, float]], scale: float) -> float:
    """Share of face samples (0-1) where the caption's pixels cover the head area."""
    with Image.open(png) as im:
        box = im.getchannel("A").point(lambda a: 255 if a > 140 else 0).getbbox()  # the text, not its soft shadow
    if not box:
        return 0.0
    x0, y0, x1, y1 = box
    ch = y1 - y0
    n = 0
    for face in boxes:
        fx0, fy0, fx1, fy1 = (v / scale for v in F.keep_out(face))
        ox = min(x1, fx1) - max(x0, fx0)
        oy = min(y1, fy1) - max(y0, fy0)
        if ox > 0 and oy > 0.2 * ch:
            n += 1
    return n / len(boxes)


def quality_checks(out: Path, planned_s: float, duration_s: float, voiced: bool, fade_out: float,
                   captions_on_face: int, face_seen: bool) -> list[dict]:
    """Cheap measurements of the finished reel, shown to the creator next to the video."""
    checks = []
    checks.append({"name": "Length", "ok": abs(duration_s - planned_s) <= 0.25,
                   "detail": f"{duration_s:.1f}s (planned {planned_s:.1f}s)"})
    try:
        p = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(out), "-vn", "-af", "ebur128=peak=true",
                            "-f", "null", "-"], capture_output=True, text=True, timeout=120)
        tail = p.stderr[p.stderr.rfind("Summary:"):]
        i_m = re.search(r"I:\s+(-?[\d.]+|-inf) LUFS", tail)
        tp_m = re.search(r"Peak:\s+(-?[\d.]+|-inf) dBFS", tail)
        lufs = float(i_m.group(1)) if i_m and i_m.group(1) != "-inf" else None
        peak = float(tp_m.group(1)) if tp_m and tp_m.group(1) != "-inf" else None
        if voiced:
            ok = lufs is not None and -19 <= lufs <= -12
            checks.append({"name": "Voice level", "ok": ok,
                           "detail": f"{lufs:.1f} LUFS" if lufs is not None else "no sound found"})
        if peak is not None:
            checks.append({"name": "No clipping", "ok": peak <= -0.5, "detail": f"peak {peak:.1f} dB"})
    except (subprocess.TimeoutExpired, ValueError):
        log.warning("loudness check failed", exc_info=True)
    try:
        p = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(out), "-an",
                            "-vf", "scale=240:-2,blackdetect=d=0.4:pix_th=0.06", "-f", "null", "-"],
                           capture_output=True, text=True, timeout=180)
        blacks = [(float(a), float(b)) for a, b in re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", p.stderr)]
        blacks = [(a, b) for a, b in blacks if a < duration_s - fade_out - 0.3]  # the planned end fade is fine
        checks.append({"name": "No black frames", "ok": not blacks,
                       "detail": ", ".join(f"{a:.1f}-{b:.1f}s" for a, b in blacks[:3]) or "none"})
    except subprocess.TimeoutExpired:
        log.warning("black frame check timed out")
    if face_seen:
        checks.append({"name": "Captions clear of face", "ok": captions_on_face == 0,
                       "detail": "all clear" if captions_on_face == 0 else
                       f"{captions_on_face} caption(s) still touch your face for part of the time - move or shorten them in the editor"})
    return checks


def cleanup(work: Path) -> None:
    shutil.rmtree(work, ignore_errors=True)
