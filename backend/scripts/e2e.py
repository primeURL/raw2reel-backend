#!/usr/bin/env python3
"""End-to-end check of the whole Raw2Reel pipeline against a running backend.

    python3 scripts/e2e.py                 # free: no AI calls (hand-written plan)
    python3 scripts/e2e.py --ai            # also style analysis + AI plan (3 Claude calls, ~$0.12)
    python3 scripts/e2e.py --api http://my-vps:8000 --keep

Needs: the stack running with AUTH_DEV_BYPASS=true, ffmpeg/ffprobe on this machine.
Creates a fresh dev user, generates its own test clips, and deletes everything at the end
(unless --keep). Exits 1 on the first failure.
"""

import argparse
import json
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

IG_REEL = "https://www.instagram.com/reel/DLDXI0fylTC/"  # public reel, ~85 s


class E2E:
    def __init__(self, api: str, user: str):
        self.api, self.h = api.rstrip("/"), {"Authorization": f"Bearer dev:{user}", "Content-Type": "application/json"}
        self.t0 = time.time()

    def call(self, method, path, body=None, expect=(200, 201, 202, 204)):
        req = urllib.request.Request(self.api + path, method=method, headers=self.h,
                                     data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                code, data = r.status, (json.load(r) if r.status != 204 else None)
        except urllib.error.HTTPError as e:
            code, data = e.code, json.load(e)
        if code not in expect:
            self.fail(f"{method} {path} -> {code} {data}")
        return data

    def wait(self, what, fn, done, timeout=600, every=3):
        t = time.time()
        while time.time() - t < timeout:
            v = fn()
            if done(v):
                return v
            time.sleep(every)
        self.fail(f"timed out waiting for {what}")

    def ok(self, msg):
        print(f"  ✓ [{time.time() - self.t0:6.1f}s] {msg}")

    def fail(self, msg):
        print(f"  ✗ {msg}")
        raise SystemExit(1)

    cleanup: list = []

    def run_cleanup(self):
        for method, path in reversed(self.cleanup):
            try:
                self.call(method, path, expect=(200, 204, 404))
            except SystemExit:
                pass

    def upload(self, url, path: Path, ctype="video/mp4"):
        req = urllib.request.Request(url, method="PUT", data=path.read_bytes(), headers={"Content-Type": ctype})
        with urllib.request.urlopen(req, timeout=300) as r:
            if r.status != 200:
                self.fail(f"R2 upload {r.status}")


def make_clips(d: Path) -> list[Path]:
    """Three phone-like test clips: plain vertical, sideways-stored (rotation flag), and one with sound."""
    def ff(*args):
        subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)

    a, b, c = d / "a.mp4", d / "b.mp4", d / "c.mp4"
    ff("-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=30", "-f", "lavfi", "-i", "anoisesrc=a=0.01",
       "-t", "4", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(a))
    # stored landscape + a 90 degree display-rotation flag, like a phone's portrait video
    land = d / "land.mp4"
    ff("-f", "lavfi", "-i", "smptebars=size=1920x1080:rate=30", "-t", "3", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(land))
    ff("-display_rotation:v:0", "90", "-i", str(land), "-c", "copy", str(b))
    ff("-f", "lavfi", "-i", "mandelbrot=size=1080x1920:rate=30", "-f", "lavfi", "-i", "sine=frequency=330",
       "-t", "5", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(c))
    return [a, b, c]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--ai", action="store_true", help="include the 3 Claude calls")
    ap.add_argument("--keep", action="store_true", help="don't delete the test data")
    ap.add_argument("--skip-instagram", action="store_true", help="skip the slow Instagram import (~4 min)")
    args = ap.parse_args()
    t = E2E(args.api + "/v1", f"e2e-{int(time.time())}")
    try:
        run(t, args)
    finally:
        t.run_cleanup()  # also on failure: don't leave test files in R2


def run(t: "E2E", args) -> None:
    print(f"Raw2Reel end-to-end ({'with AI' if args.ai else 'free, no AI'}) against {args.api}")

    health = json.load(urllib.request.urlopen(args.api + "/health", timeout=10))
    if health.get("status") != "ok":
        t.fail(f"health: {health}")
    t.ok(f"health {health}")
    me = t.call("GET", "/me")
    t.ok(f"new user {me['id'][:8]}")

    # style + Instagram reference --------------------------------------------------
    style = t.call("POST", "/styles", {"name": "E2E style"})
    t.cleanup = []
    if not args.keep:
        t.cleanup.append(("DELETE", f"/styles/{style['id']}"))
    t.call("POST", "/references/instagram", {"url": "https://evil.example/reel/abc/"}, expect=(422,))
    if args.skip_instagram and args.ai:
        t.fail("--ai needs the Instagram reference for the style")
    ref = None if args.skip_instagram else t.call("POST", "/references/instagram", {"url": IG_REEL + "?igsh=e2e", "style_id": style["id"]})
    if ref and not args.keep:
        t.cleanup.append(("DELETE", f"/references/{ref['id']}"))
    ref = ref and t.wait("Instagram import", lambda: t.call("GET", f"/references/{ref['id']}"),
                 lambda r: r["status"] == "failed" or r["analysis_status"] in ("ready", "failed"), timeout=900)
    if ref and (ref["status"] != "ready" or ref["analysis_status"] != "ready"):
        t.fail(f"Instagram reference: {ref['status']}/{ref['analysis_status']} {ref['error']}")
    if ref:
        t.ok(f"Instagram reel imported + analysed: {ref['duration_s']:.1f}s, pacing {ref['pacing']['shot_count']} shots")

    # project + clips ------------------------------------------------------------------
    with tempfile.TemporaryDirectory() as tmp:
        clips = make_clips(Path(tmp))
        project = t.call("POST", "/projects", {"title": "E2E reel", "language": "en",
                                               "stats": {"Distance": "2.06 km", "Time": "15:10"},
                                               "style_id": style["id"] if args.ai else None})
        pid = project["id"]
        if not args.keep:
            t.cleanup.append(("DELETE", f"/projects/{pid}"))
        for f in clips:
            up = t.call("POST", f"/projects/{pid}/clips/upload-url",
                        {"filename": f.name, "content_type": "video/mp4", "size_bytes": f.stat().st_size})
            t.upload(up["upload_url"], f)
            t.call("POST", f"/projects/{pid}/clips/{up['clip_id']}/complete")
    t.ok("3 clips uploaded to R2")
    p = t.wait("clip analysis", lambda: t.call("GET", f"/projects/{pid}"),
               lambda p: p["analysis_ready"] or any(c["analysis_status"] == "failed" or c["status"] == "failed" for c in p["clips"]))
    if not p["analysis_ready"]:
        t.fail(f"clips: {[(c['status'], c['analysis_status'], c['error']) for c in p['clips']]}")
    rotated = p["clips"][1]
    if (rotated["width"], rotated["height"]) != (1080, 1920):
        t.fail(f"rotated clip reads as {rotated['width']}x{rotated['height']}")
    t.ok(f"clips analysed: {[round(c['duration_s'], 1) for c in p['clips']]}s, sideways clip upright, cover {'ok' if p['cover_url'] else 'missing'}")

    # plan ------------------------------------------------------------------------------
    if args.ai:
        s = t.call("POST", f"/styles/{style['id']}/analyze")
        s = t.wait("style analysis", lambda: t.call("GET", f"/styles/{style['id']}"), lambda s: s["status"] != "analyzing")
        if s["status"] != "needs_answers":
            t.fail(f"style: {s['status']} {s['error']}")
        t.call("POST", f"/styles/{style['id']}/answers", {"answers": [{"question_id": s["questions"][0]["id"], "answer": s["questions"][0]["options"][0]}]})
        s = t.wait("style answers", lambda: t.call("GET", f"/styles/{style['id']}"), lambda s: s["status"] != "analyzing")
        t.ok(f"style {s['status']}: {s['profile']['name']}")
        t.call("POST", f"/projects/{pid}/plan")
        p = t.wait("AI plan", lambda: t.call("GET", f"/projects/{pid}"), lambda p: p["status"] != "analyzing")
        if p["status"] != "planned":
            t.fail(f"plan: {p['status']} {p['error']}")
    else:
        shot = lambda c, a, b, **kw: {"clip": c, "in_s": a, "out_s": b, "speed": 1.0, "zoom_from": 1.0, "zoom_to": 1.0,
                                      "focus_x": 0.5, "focus_y": 0.5, "keep_audio": False, "purpose": "e2e", **kw}
        plan = {
            "title": "E2E", "summary": "hand-written test plan",
            "shots": [shot("C1", 0.2, 3.2), shot("C2", 0, 2.5, zoom_from=1.0, zoom_to=1.3),
                      shot("C3", 0.5, 4.5, speed=0.8, keep_audio=True, zoom_from=1.6, zoom_to=1.8)],
            "captions": [{"text": "Day 1.", "start_s": 0.3, "end_s": 2.0, "position": "lower_middle", "highlight": None},
                         {"text": "Target: 2 km. Let's see.", "start_s": 3.2, "end_s": 5.4, "position": "lower_middle", "highlight": "2"},
                         {"text": "सबसे पहले warm-up ✓", "start_s": 6.0, "end_s": 9.0, "position": "lower_middle", "highlight": None}],
            "overlays": [{"type": "stats_card", "start_s": 10.5, "end_s": 13.5, "title": "E2E · RUN",
                          "items": [{"label": "Distance", "value": "2.06 km"}, {"label": "Time", "value": "15:10"}]}],
            "music": {"enabled": False, "mood": "", "volume": "medium"}, "end_fade_s": 0.5,
        }
        p = t.call("PUT", f"/projects/{pid}/plan", plan)
    tl = p["plan_timeline"]
    t.ok(f"plan {p['status']}: {tl['total_s']}s ({len(p['plan']['shots'])} shots), warnings: {p['plan_warnings'] or 'none'}")

    # render ----------------------------------------------------------------------------
    r = t.call("POST", f"/projects/{pid}/render", {"quality": "preview"})
    t.call("POST", f"/projects/{pid}/render", {"quality": "preview"}, expect=(409,))  # busy guard
    r = t.wait("render", lambda: [x for x in t.call("GET", f"/projects/{pid}/renders") if x["id"] == r["id"]][0],
               lambda r: r["status"] in ("ready", "failed"))
    if r["status"] != "ready":
        t.fail(f"render: {r['error']}")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "reel.mp4"
        urllib.request.urlretrieve(r["video_url"], out)
        probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(out)],
                                          capture_output=True, text=True).stdout)
    dur = float(probe["format"]["duration"])
    v = next(s for s in probe["streams"] if s["codec_type"] == "video")
    if abs(dur - tl["total_s"]) > 0.15 or (v["width"], v["height"]) != (540, 960):
        t.fail(f"rendered {v['width']}x{v['height']} {dur:.2f}s, plan {tl['total_s']}s")
    t.ok(f"render v{r['version']} ready in {r['seconds_taken']}s: {v['width']}x{v['height']}, {dur:.2f}s (plan {tl['total_s']}s), audio {'yes' if any(s['codec_type'] == 'audio' for s in probe['streams']) else 'no'}")

    usage = t.call("GET", "/me/ai-usage")
    t.ok(f"AI usage for this user: {usage['calls_last_24h']} calls, ${usage['all_time_usd']}")

    # cleanup ---------------------------------------------------------------------------
    if not args.keep:
        t.run_cleanup()
        t.cleanup = []
        t.call("GET", f"/projects/{pid}", expect=(404,))
        t.ok("cleaned up (project, renders, clips, reference, style)")
    print(f"PASS in {time.time() - t.t0:.0f}s")


if __name__ == "__main__":
    main()
