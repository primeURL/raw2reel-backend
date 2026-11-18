"""Clip and reference analysis - the steps done by hand for the Day 1 reel, as code.

  proxy          upright 30 fps H.264 copy the renderer works from (rotation baked in)
  scene cuts     ffmpeg scene score  -> where shots change (pacing of references)
  silences       ffmpeg silencedetect -> dead air to cut
  contact sheet  timestamped frame grid -> what Claude "sees" when planning
  transcript     faster-whisper with word timings -> captions + speech-aware cuts
"""

import logging
import re
import subprocess
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path

from app.config import get_settings

log = logging.getLogger(__name__)


# proxy -----------------------------------------------------------------------


def make_proxy(src: Path, dest: Path, max_w: int = 1080, max_h: int = 1920, fps: int = 30) -> Path:
    """Upright, constant-frame-rate H.264/AAC copy. Phones record variable frame rate and
    store portrait as rotated landscape; the renderer should never deal with either."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    vf = (
        f"scale=w='min({max_w},iw)':h='min({max_h},ih)':force_original_aspect_ratio=decrease,"
        f"scale=trunc(iw/2)*2:trunc(ih/2)*2,fps={fps},format=yuv420p"
    )
    _run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(src), "-vf", vf,
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
         "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
         "-movflags", "+faststart", str(dest)],
        timeout=600,
    )
    return dest


# scene cuts ------------------------------------------------------------------


def scene_cuts(src: Path, threshold: float = 0.3) -> list[float]:
    """Times (s) where the picture changes sharply - i.e. edit points in a reference reel."""
    out = _run(
        ["ffmpeg", "-hide_banner", "-i", str(src), "-an",
         "-vf", f"scale=320:-2,select='gt(scene,{threshold})',showinfo", "-f", "null", "-"],
        timeout=300,
    ).stderr
    return [round(float(t), 3) for t in re.findall(r"pts_time:([0-9.]+)", out)]


# silences ----------------------------------------------------------------------


def has_audio_stream(src: Path) -> bool:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", str(src)],
        capture_output=True, text=True, timeout=60,
    ).stdout
    return bool(out.strip())


def silences(src: Path, noise_db: int = -35, min_s: float = 0.5) -> list[dict]:
    if not has_audio_stream(src):  # muted export / screen recording: the whole clip is "silent"
        return []
    out = _run(
        ["ffmpeg", "-hide_banner", "-i", str(src), "-vn",
         "-af", f"silencedetect=noise={noise_db}dB:d={min_s}", "-f", "null", "-"],
        timeout=300,
    ).stderr
    starts = [float(x) for x in re.findall(r"silence_start: ([0-9.]+)", out)]
    ends = [float(x) for x in re.findall(r"silence_end: ([0-9.]+)", out)]
    result = []
    for i, s in enumerate(starts):
        e = ends[i] if i < len(ends) else None
        result.append({"start": round(s, 3), "end": round(e, 3) if e is not None else None})
    return result


def loudness_lufs(src: Path) -> float | None:
    if not has_audio_stream(src):
        return None
    out = _run(["ffmpeg", "-hide_banner", "-i", str(src), "-vn", "-af", "ebur128", "-f", "null", "-"], timeout=300).stderr
    m = re.findall(r"I:\s+(-?[0-9.]+) LUFS", out)
    return float(m[-1]) if m else None


# contact sheet -----------------------------------------------------------------


def contact_sheet(src: Path, dest: Path, duration_s: float, frames: int = 12, cols: int = 6, tile_w: int = 240) -> dict:
    """A grid of evenly spaced frames, each stamped with its time. Returns the times used."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    frames = max(1, min(frames, int(duration_s * 4) or 1))
    rows = -(-frames // cols)
    step = duration_s / frames
    times = [round(step * (i + 0.5), 2) for i in range(frames)]
    vf = (
        f"fps={frames}/{duration_s:.3f},scale={tile_w}:-2,"
        "drawtext=text='%{pts\\:hms}':x=6:y=6:fontsize=18:fontcolor=yellow:box=1:boxcolor=black@0.5,"
        f"tile={cols}x{rows}"
    )
    _run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-vf", vf, "-frames:v", "1", "-q:v", "4", str(dest)], timeout=300)
    return {"frames": frames, "cols": cols, "rows": rows, "times": times}


# transcript ----------------------------------------------------------------------

_model = None
_model_lock = threading.Lock()  # one transcription at a time per worker process


@dataclass
class Word:
    text: str
    start: float
    end: float
    prob: float


@dataclass
class Segment:
    text: str
    start: float
    end: float
    words: list[Word] = field(default_factory=list)


def _whisper():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        s = get_settings()
        log.info("loading whisper model %s (%s)", s.whisper_model, s.whisper_compute_type)
        _model = WhisperModel(
            s.whisper_model,
            device="cpu",
            compute_type=s.whisper_compute_type,
            cpu_threads=s.whisper_cpu_threads,
            download_root=str(Path(s.models_dir) / "whisper"),
        )
    return _model


# project.language -> whisper language. Hinglish is left to auto-detect: forcing "hi" writes
# English words in Devanagari, forcing "en" mangles Hindi. Claude romanises captions later.
_LANG = {"en": "en", "hi": "hi", "hinglish": None, None: None}


def _audio_16k(src: Path):
    """Decode audio with ffmpeg to 16 kHz mono float32 - what Whisper expects.
    (Avoids faster-whisper's PyAV decoder, which breaks across PyAV versions.)"""
    import numpy as np

    p = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
        capture_output=True,
        timeout=300,
    )
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg audio decode failed: {p.stderr.decode(errors='ignore')[-300:]}")
    return np.frombuffer(p.stdout, dtype=np.float32)


def transcribe(src: Path, language: str | None = None) -> dict:
    empty = {"language": None, "language_probability": 0.0, "text": "", "has_speech": False, "segments": [], "dropped_segments": []}
    if not has_audio_stream(src):
        return {**empty, "skipped": "no audio track"}
    audio = _audio_16k(src)
    if audio.size < 16000 * 0.3:  # no audio track or under 0.3 s
        return empty
    # Silero VAD takes well under a second; Whisper takes ~25 s even on silence (language
    # detection always encodes a 30 s window). Most B-roll has no speech, so check first.
    if not _has_voice(audio):
        return {**empty, "skipped": "no voice detected"}
    with _model_lock:
        model = _whisper()
        segments, info = model.transcribe(
            audio,
            language=_LANG.get(language),
            word_timestamps=True,
            vad_filter=True,  # skip music-only / silent parts instead of hallucinating
            vad_parameters={"min_silence_duration_ms": 400},
            beam_size=5,
            condition_on_previous_text=False,
        )
        segs, dropped = [], []
        for seg in segments:
            words = [Word(w.word.strip(), round(w.start, 3), round(w.end, 3), round(w.probability, 3)) for w in seg.words or []]
            s = Segment(seg.text.strip(), round(seg.start, 3), round(seg.end, 3), words)
            (segs if _is_real_speech(seg, words) else dropped).append(s)
    text = " ".join(s.text for s in segs).strip()
    return {
        "dropped_segments": [s.text for s in dropped],  # likely hallucinations on wind/music
        "language": info.language if text else None,
        "language_probability": round(info.language_probability, 3),
        "text": text,
        "has_speech": bool(text),
        "segments": [asdict(s) for s in segs],
    }


def _has_voice(audio) -> bool:
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    chunks = get_speech_timestamps(audio, VadOptions(min_silence_duration_ms=400, min_speech_duration_ms=250))
    voiced_s = sum(c["end"] - c["start"] for c in chunks) / 16000
    return voiced_s >= 0.4


# Whisper invents short phrases ("You", "Thank you.") on wind, traffic or music.
_HALLUCINATIONS = {"you", "thank you", "thanks for watching", "bye", "okay", "so"}


def _is_real_speech(seg, words: list[Word]) -> bool:
    if not words:
        return False
    mean_p = sum(w.prob for w in words) / len(words)
    if seg.no_speech_prob > 0.6 and seg.avg_logprob < -0.8:
        return False
    if mean_p < 0.45:
        return False
    clean = seg.text.strip().lower().strip(".!?, ")
    if clean in _HALLUCINATIONS and (mean_p < 0.8 or seg.no_speech_prob > 0.3):
        return False
    return True


# helpers ---------------------------------------------------------------------


def _run(cmd: list[str], timeout: int) -> subprocess.CompletedProcess:
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed: {p.stderr.strip()[-400:]}")
    return p
