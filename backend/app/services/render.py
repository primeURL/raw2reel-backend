"""Edit plan -> MP4 with FFmpeg. No AI, deterministic: same plan + clips = same video.

Pipeline (all in a temp work dir):
  1. each shot -> segment.mp4   trim, speed, cover-crop to 1080x1920, optional zoom/push, its
                                own audio or silence (so every segment has the same streams)
  2. concat segments            stream copy
  3. finish                     hold last frame under an end card, overlay caption/title/card
                                PNGs with fades, fade out, final encode
"""

import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

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


class RenderError(RuntimeError):
    pass


@dataclass
class RenderResult:
    path: Path
    duration_s: float
    thumbnail: Path


def _run(cmd: list[str], timeout: int = 300) -> None:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise RenderError(f"ffmpeg took longer than {timeout}s and was stopped") from exc
    if p.returncode != 0:
        raise RenderError(f"ffmpeg failed: {p.stderr.strip()[-600:]}")


def _probe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, timeout=60,
    ).stdout.strip()
    return float(out or 0)


def _segment(shot, src: Path, dest: Path, w: int, h: int, has_audio: bool) -> float:
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
    _run(cmd)
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
           work: Path, quality: str = "final") -> RenderResult:
    """sources: clip alias -> (proxy path, has_audio)."""
    if quality not in QUALITY:
        raise RenderError(f"unknown quality {quality}")
    w, h, crf, preset = QUALITY[quality]
    work.mkdir(parents=True, exist_ok=True)
    style = style or {}
    cap_style = style.get("captions") or {}
    accent = (style.get("look") or {}).get("accent_color") or "#FF5A1F"

    # 1. segments ---------------------------------------------------------------
    segs = []
    for i, shot in enumerate(plan.shots):
        src, has_audio = sources[shot.clip]
        seg = work / f"seg{i:02d}.mp4"
        _segment(shot, src, seg, w, h, has_audio)
        segs.append(seg)

    # 2. join -------------------------------------------------------------------
    # The concat *filter* (re-encode), not the concat demuxer with stream copy: a segment with
    # real AAC audio shifts the copied timestamps (start 0.021 s), and the overlay step then
    # waits forever for frames that never line up.
    joined = work / "joined.mp4"
    ins = [x for s in segs for x in ("-i", str(s))]
    pads = "".join(f"[{i}:v][{i}:a]" for i in range(len(segs)))
    _run(["ffmpeg", "-v", "error", "-y", *ins, "-filter_complex", f"{pads}concat=n={len(segs)}:v=1:a=1[v][a]",
          "-map", "[v]", "-map", "[a]", "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast", "-crf", "16",
          "-c:a", "aac", "-b:a", "160k", "-ar", "48000", str(joined)], timeout=300)

    # 3. graphics as PNG layers ------------------------------------------------------
    layers: list[tuple[Path, float, float]] = []  # (png, start, end)
    for i, c in enumerate(plan.captions):
        png = graphics.caption_png(
            c.text, work / f"cap{i:02d}.png", position=c.position,
            size=cap_style.get("size", "small"), weight=cap_style.get("weight", "medium"),
            color=cap_style.get("text_color", "#FFFFFF"), accent=accent, highlight=c.highlight,
            case=cap_style.get("case", "sentence"),
        )
        layers.append((png, c.start_s, c.end_s))
    for i, o in enumerate(plan.overlays):
        if o.type == "stats_card":
            png = graphics.stats_card_png(o.title, [(it.label, it.value) for it in o.items], work / f"ovl{i:02d}.png", accent=accent)
        else:
            png = graphics.title_png(o.title or "", work / f"ovl{i:02d}.png")
        layers.append((png, o.start_s, o.end_s))
    # cards first so captions sit on top of them
    layers.sort(key=lambda l: 0 if l[0].name.startswith("ovl") else 1)

    # 4. finish: tail hold, overlays, end fade ---------------------------------------
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
    vfinal = f"[{last}]" + (f"fade=t=out:st={total - fade_out:.3f}:d={fade_out:.3f}," if fade_out else "") + "format=yuv420p[vout]"
    afinal = f"[0:a]apad=whole_dur={total:.3f}" + (f",afade=t=out:st={total - fade_out:.3f}:d={fade_out:.3f}" if fade_out else "") + "[aout]"
    chains += [vfinal, afinal]

    out = work / "reel.mp4"
    _run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", ";".join(chains),
          "-map", "[vout]", "-map", "[aout]", "-t", f"{total:.3f}", "-r", str(FPS),
          "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p",
          "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out)], timeout=max(300, int(total * 20)))

    duration = _probe_duration(out)
    if abs(duration - total) > 0.25:
        log.warning("rendered %.2fs, plan said %.2fs", duration, total)
    thumb = work / "thumb.jpg"
    _run(["ffmpeg", "-v", "error", "-y", "-ss", f"{min(1.0, duration / 2):.2f}", "-i", str(out),
          "-frames:v", "1", "-vf", "scale=360:-2", "-q:v", "4", str(thumb)])
    return RenderResult(path=out, duration_s=round(duration, 3), thumbnail=thumb)


def cleanup(work: Path) -> None:
    shutil.rmtree(work, ignore_errors=True)
