"""ffprobe helpers shared by every pipeline step."""

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ProbeResult:
    duration_s: float
    width: int
    height: int
    rotation: int  # degrees from the display matrix (phones store portrait as rotated landscape)
    has_audio: bool
    fps: float | None = None

    @property
    def display_size(self) -> tuple[int, int]:
        """Width/height as the video is actually shown."""
        if abs(self.rotation) in (90, 270):
            return self.height, self.width
        return self.width, self.height


def probe(path: Path) -> ProbeResult:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    ).stdout
    data = json.loads(out)
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    if video is None:
        raise ValueError("file has no video stream")
    rotation = 0
    for sd in video.get("side_data_list", []) or []:
        if "rotation" in sd:
            rotation = int(sd["rotation"])
    duration = float(data.get("format", {}).get("duration") or video.get("duration") or 0)
    return ProbeResult(
        duration_s=duration,
        width=int(video["width"]),
        height=int(video["height"]),
        rotation=rotation,
        has_audio=any(s.get("codec_type") == "audio" for s in data.get("streams", [])),
        fps=_fps(video.get("avg_frame_rate") or video.get("r_frame_rate")),
    )


def _fps(rate: str | None) -> float | None:
    try:
        num, den = (rate or "").split("/")
        return round(int(num) / int(den), 3) if int(den) else None
    except ValueError:
        return None


def thumbnail(src: Path, dest: Path, at_s: float, width: int = 360) -> Path:
    """One upright JPEG frame (ffmpeg applies the phone's rotation flag automatically)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-ss", f"{max(at_s, 0):.3f}", "-i", str(src),
         "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "4", str(dest)],
        check=True,
        timeout=60,
    )
    return dest
