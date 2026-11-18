"""Download a public Instagram reel from its link, for use as a style reference.

Strategy (first one that works wins):
  1. yt-dlp  - maintained extractor; works best with a logged-in cookies file.
  2. instaloader - fetches the post by shortcode; also accepts the cookies session.
  3. Optional paid API (e.g. an Apify actor) if INSTAGRAM_FALLBACK_API_URL is set.

Only instagram.com reel/post links are accepted (no arbitrary URLs -> no SSRF).
Downloaded reels are private style references: never re-published by Raw2Reel.
"""

import logging
import re
import shutil
from dataclasses import dataclass, field
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)

_HOSTS = {"instagram.com", "www.instagram.com", "m.instagram.com", "instagr.am", "www.instagr.am"}
_PATH_RE = re.compile(r"^/(?:[A-Za-z0-9_.]+/)?(reel|reels|p|tv)/([A-Za-z0-9_-]{5,64})/?$")


class InvalidInstagramUrl(ValueError):
    pass


class DownloadFailed(RuntimeError):
    pass


@dataclass
class ParsedUrl:
    shortcode: str
    canonical_url: str


@dataclass
class DownloadResult:
    path: Path
    downloader: str
    meta: dict = field(default_factory=dict)


def parse_instagram_url(raw: str) -> ParsedUrl:
    raw = raw.strip()
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    u = urlparse(raw)
    if (u.hostname or "").lower() not in _HOSTS:
        raise InvalidInstagramUrl("Only instagram.com reel or post links are supported")
    m = _PATH_RE.match(u.path)
    if not m:
        raise InvalidInstagramUrl("That doesn't look like a reel link, e.g. https://www.instagram.com/reel/ABC123/")
    kind, code = m.groups()
    kind = "reel" if kind == "reels" else kind
    return ParsedUrl(shortcode=code, canonical_url=f"https://www.instagram.com/{kind}/{code}/")


def download(url: str, dest_dir: Path) -> DownloadResult:
    parsed = parse_instagram_url(url)
    dest_dir.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    for name, fn in (("yt-dlp", _with_ytdlp), ("instaloader", _with_instaloader), ("api", _with_api)):
        try:
            result = fn(parsed, dest_dir)
        except Exception as exc:  # each strategy fails in its own way; try the next
            log.warning("instagram %s failed for %s: %s", name, parsed.shortcode, exc)
            errors.append(f"{name}: {exc}")
            continue
        if result is not None:
            return result
    raise DownloadFailed(
        "Couldn't download this reel (it may be private, deleted, or Instagram blocked the request). "
        "Try again later or upload the video file instead. Details: " + " | ".join(errors)[:800]
    )


# 1. yt-dlp -------------------------------------------------------------------


def _with_ytdlp(p: ParsedUrl, dest: Path) -> DownloadResult:
    import yt_dlp

    s = get_settings()
    opts = {
        "outtmpl": str(dest / f"{p.shortcode}.%(ext)s"),
        "format": "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "max_filesize": s.instagram_max_filesize_mb * 1024 * 1024,
        # "<=?" lets reels without duration metadata through; real length is checked with ffprobe later
        "match_filter": yt_dlp.utils.match_filter_func(f"duration <=? {s.instagram_max_duration_seconds}"),
        "socket_timeout": 30,
        "retries": 2,
    }
    if s.instagram_cookies_file and Path(s.instagram_cookies_file).exists():
        opts["cookiefile"] = s.instagram_cookies_file
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(p.canonical_url, download=True)
    if info is None or (info.get("_type") != "playlist" and not info.get("requested_downloads")):
        raise DownloadFailed("reel is longer than the allowed duration or too large")
    if info.get("_type") == "playlist":  # carousel: take the first video entry
        info = next((e for e in info.get("entries") or [] if e and e.get("vcodec") != "none"), None)
        if info is None:
            raise DownloadFailed("post has no video")
    path = _find_video(dest, p.shortcode)
    return DownloadResult(
        path=path,
        downloader="yt-dlp",
        meta={
            "title": info.get("title"),
            "caption": info.get("description"),
            "uploader": info.get("uploader") or info.get("channel"),
            "duration": info.get("duration"),
        },
    )


# 2. instaloader --------------------------------------------------------------


def _with_instaloader(p: ParsedUrl, dest: Path) -> DownloadResult:
    import instaloader

    s = get_settings()
    L = instaloader.Instaloader(
        download_pictures=False,
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=False,
        save_metadata=False,
        compress_json=False,
        quiet=True,
        max_connection_attempts=2,
    )
    if s.instagram_cookies_file and Path(s.instagram_cookies_file).exists():
        jar = MozillaCookieJar(s.instagram_cookies_file)
        jar.load(ignore_discard=True, ignore_expires=True)
        L.context._session.cookies.update(jar)  # reuse the same logged-in session as yt-dlp

    post = instaloader.Post.from_shortcode(L.context, p.shortcode)
    video_url = post.video_url if post.is_video else None
    if not video_url and post.typename == "GraphSidecar":
        video_url = next((n.video_url for n in post.get_sidecar_nodes() if n.is_video), None)
    if not video_url:
        raise DownloadFailed("post has no video")
    if post.video_duration and post.video_duration > s.instagram_max_duration_seconds:
        raise DownloadFailed("reel is longer than the allowed duration")

    path = dest / f"{p.shortcode}.mp4"
    _stream_to_file(video_url, path, s.instagram_max_filesize_mb)
    return DownloadResult(
        path=path,
        downloader="instaloader",
        meta={"caption": post.caption, "uploader": post.owner_username, "duration": post.video_duration},
    )


# 3. Optional paid API ---------------------------------------------------------


def _with_api(p: ParsedUrl, dest: Path) -> DownloadResult | None:
    """Generic hook for a hosted downloader. Expects JSON with a direct `video_url`.

    Wire the exact request/response shape once a provider is chosen.
    """
    s = get_settings()
    if not s.instagram_fallback_api_url:
        return None
    r = httpx.post(
        s.instagram_fallback_api_url,
        json={"url": p.canonical_url},
        headers={"Authorization": f"Bearer {s.instagram_fallback_api_token}"},
        timeout=90,
    )
    r.raise_for_status()
    data = r.json()
    video_url = data.get("video_url") if isinstance(data, dict) else None
    if not video_url:
        raise DownloadFailed("fallback API returned no video_url")
    path = dest / f"{p.shortcode}.mp4"
    _stream_to_file(video_url, path, s.instagram_max_filesize_mb, any_https_host=True)
    return DownloadResult(path=path, downloader="api", meta={"provider_response_keys": sorted(data)[:20]})


# helpers ---------------------------------------------------------------------


def _find_video(dest: Path, stem: str) -> Path:
    files = sorted(dest.glob(f"{stem}.*"), key=lambda f: f.stat().st_size, reverse=True)
    files = [f for f in files if f.suffix.lower() in {".mp4", ".mov", ".webm", ".mkv"}]
    if not files:
        raise DownloadFailed("downloader finished but no video file was written")
    if files[0].suffix.lower() != ".mp4":
        target = files[0].with_suffix(".mp4")
        shutil.move(files[0], target)
        return target
    return files[0]


def _stream_to_file(url: str, path: Path, max_mb: int, any_https_host: bool = False) -> None:
    u = urlparse(url)
    host = (u.hostname or "").lower()
    if u.scheme != "https":
        raise DownloadFailed("video URL is not https")
    if not any_https_host and not (host.endswith(".cdninstagram.com") or host.endswith(".fbcdn.net")):
        raise DownloadFailed(f"unexpected video host {host}")
    limit = max_mb * 1024 * 1024
    written = 0
    with httpx.stream("GET", url, timeout=60, follow_redirects=True) as r:
        r.raise_for_status()
        with path.open("wb") as f:
            for chunk in r.iter_bytes(1 << 16):
                written += len(chunk)
                if written > limit:
                    raise DownloadFailed("video is larger than the allowed size")
                f.write(chunk)
