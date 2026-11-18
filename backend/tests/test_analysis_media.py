"""Analysis must survive phone-like edge cases (runs ffmpeg; no network)."""
import subprocess
from pathlib import Path

from app.services import analysis as A
from app.services.media import probe


def _ff(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def test_rotated_clip_without_audio(tmp_path: Path):
    land, clip = tmp_path / "land.mp4", tmp_path / "clip.mp4"
    _ff("-f", "lavfi", "-i", "smptebars=size=1920x1080:rate=30", "-t", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(land))
    _ff("-display_rotation:v:0", "90", "-i", str(land), "-c", "copy", str(clip))
    assert probe(clip).display_size == (1080, 1920)
    proxy = A.make_proxy(clip, tmp_path / "proxy.mp4")
    p = probe(proxy)
    assert (p.width, p.height, p.rotation) == (1080, 1920, 0)
    assert A.silences(proxy) == []
    assert A.loudness_lufs(proxy) is None
    t = A.transcribe(proxy)
    assert t["has_speech"] is False and t["skipped"] == "no audio track"
    A.contact_sheet(proxy, tmp_path / "sheet.jpg", 2.0)
    assert (tmp_path / "sheet.jpg").stat().st_size > 1000
