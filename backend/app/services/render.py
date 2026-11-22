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

from app.services import effects as fx
from app.services import faces as F
from app.services import graphics
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
    has_fx = bool(plan.effects)
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
    ins = [x for s in segs for x in ("-i", str(s))]
    pads = "".join(f"[{i}:v][{i}:a]" for i in range(len(segs)))
    _run(["ffmpeg", "-v", "error", "-y", *ins, "-filter_complex", f"{pads}concat=n={len(segs)}:v=1:a=1[v][a]",
          "-map", "[v]", "-map", "[a]", "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast", "-crf", "16",
          "-c:a", "aac", "-b:a", "160k", "-ar", "48000", str(joined)], timeout=300)

    # 3. faces + effects -----------------------------------------------------------
    report(0.45, "Finding faces")
    faces = F.track(joined, w, h, footage)
    if has_fx:
        report(0.48, "Adding effects")
        fxd = work / "effects.mp4"
        fx.apply(joined, fxd, plan.effects, faces, w, h, FPS, accent, footage,
                 lambda f: report(0.48 + fx_share * f, "Adding effects"))
        joined = fxd
    final_from = 0.48 + fx_share
    report(final_from, "Adding captions and cards")

    # 4. graphics as PNG layers ------------------------------------------------------
    def caption_layer(i, c, center_y=None):
        return graphics.caption_png(
            c.text, work / f"cap{i:02d}.png", position=c.position,
            size=cap_style.get("size", "small"), weight=cap_style.get("weight", "medium"),
            color=cap_style.get("text_color", "#FFFFFF"), accent=accent, highlight=c.highlight,
            case=cap_style.get("case", "sentence"), center_y=center_y,
        )

    notes: list[str] = []
    still_on_face = 0
    layers: list[tuple[Path, float, float]] = []  # (png, start, end)
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
        layers.append((png, c.start_s, c.end_s))
    for i, o in enumerate(plan.overlays):
        if o.type == "stats_card":
            png = graphics.stats_card_png(o.title, [(it.label, it.value) for it in o.items], work / f"ovl{i:02d}.png", accent=accent)
        else:
            png = graphics.title_png(o.title or "", work / f"ovl{i:02d}.png")
        layers.append((png, o.start_s, o.end_s))
    # cards first so captions sit on top of them
    layers.sort(key=lambda l: 0 if l[0].name.startswith("ovl") else 1)

    # 5. finish: tail hold, overlays, voice level, end fade --------------------------
    total = timeline["total_s"]
    tail = timeline.get("tail_hold_s") or 0.0
    inputs = ["-i", str(joined)]
    chains = [f"[0:v]tpad=stop_mode=clone:stop_duration={tail:.3f},scale={w}:{h}[base]"]
    last = "base"
    for k, (png, start, end) in enumerate(layers, start=1):
        d = max(end - start, 0.1)
        fade = min(FADE_S, d / 3)
        inputs += ["-loop", "1", "-t", f"{d:.3f}", "-i", str(png)]
        chains.append(
            f"[{k}:v]scale={w}:{h},format=rgba,fade=t=in:st=0:d={fade:.3f}:alpha=1,"
            f"fade=t=out:st={d - fade:.3f}:d={fade:.3f}:alpha=1,setpts=PTS-STARTPTS+{start:.3f}/TB[l{k}]"
        )
        chains.append(f"[{last}][l{k}]overlay=0:0:eof_action=pass:enable='between(t,{start:.3f},{end:.3f})'[o{k}]")
        last = f"o{k}"
    fade_out = plan.end_fade_s
    voiced = any(sh.keep_audio and sources[sh.clip][1] for sh in plan.shots)
    # two-pass loudnorm sets the voice level exactly; the limiter catches peaks (and AAC overshoot)
    level = f",{_loudnorm(joined)},aresample=48000,alimiter=limit=0.75:level=disabled" if voiced else ""
    vfinal = f"[{last}]" + (f"fade=t=out:st={total - fade_out:.3f}:d={fade_out:.3f}," if fade_out else "") + "format=yuv420p[vout]"
    afinal = (f"[0:a]apad=whole_dur={total:.3f}{level}"
              + (f",afade=t=out:st={total - fade_out:.3f}:d={fade_out:.3f}" if fade_out else "") + "[aout]")
    chains += [vfinal, afinal]

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
