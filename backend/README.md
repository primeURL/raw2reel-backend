# Raw2Reel backend

FastAPI + Celery + Postgres + Redis, all in Docker Compose. Videos live in Cloudflare R2,
users sign in with Google through Firebase.

## Run locally

```bash
cp .env.example .env          # fill in; AUTH_DEV_BYPASS=true for local testing
docker compose up -d --build  # postgres, redis, migrate, web, worker-default, worker-media
open http://localhost:8000/docs
```

With `AUTH_DEV_BYPASS=true` (ignored when `APP_ENV=prod`) you can call the API with
`Authorization: Bearer dev:<any-user-id>` instead of a Firebase token.

Host ports: API `8000`, Postgres `5433`, Redis `6380` (change with `POSTGRES_HOST_PORT` / `REDIS_HOST_PORT`).

## Services

| Service | What it does |
|---|---|
| `migrate` | `alembic upgrade head`, then exits; other app services wait for it |
| `web` | FastAPI on :8000 |
| `worker-default` | quick Celery jobs (`default` queue) |
| `worker-media` | heavy jobs: Instagram downloads, ffmpeg, whisper, rendering (`media` queue) |

## API so far (v1)

| Method | Path | |
|---|---|---|
| GET | `/health` | Postgres + Redis check |
| GET | `/v1/me` | current user (created on first call) |
| POST/GET | `/v1/styles`, `/v1/styles/{id}` | styles |
| POST | `/v1/references/instagram` | `{url, style_id?}` → downloads the reel in the background, stores it in R2 |
| POST | `/v1/references/upload-url` | pre-signed R2 PUT URL for a reference file |
| POST | `/v1/references/{id}/complete` | after the app's PUT finishes → checks the video |
| GET | `/v1/references`, `/v1/references/{id}` | list / detail (with a signed download URL when ready) |
| POST | `/v1/references/{id}/retry` | retry a failed Instagram import |
| DELETE | `/v1/references/{id}` | delete row + R2 object |
| POST/GET | `/v1/projects`, `/v1/projects/{id}` | create / list (summary: clip count, total length, cover) / detail with clips |
| PATCH | `/v1/projects/{id}` | title, style, script, language (`en` / `hi` / `hinglish`) |
| DELETE | `/v1/projects/{id}` | project, clips and every R2 file under it |
| POST | `/v1/projects/{id}/clips/upload-url` | pre-signed PUT for a raw clip (max 12 clips, 1 GB each) |
| POST | `/v1/projects/{id}/clips/{clip_id}/complete` | worker checks it (≤ 5 min), reads size/rotation/fps/audio, makes an upright thumbnail |
| GET | `/v1/projects/{id}/clips` | clips in order, with thumbnail + download URLs |
| PUT | `/v1/projects/{id}/clips/order` | `{clip_ids: [...]}`, every clip exactly once |
| DELETE | `/v1/projects/{id}/clips/{clip_id}` | clip + its R2 files, remaining clips renumbered |

| GET | `/v1/projects/{id}/clips/{clip_id}/analysis` | full analysis + proxy and contact-sheet URLs |
| POST | `/v1/projects/{id}/analyze` | re-run analysis for every clip (e.g. after changing language) |

| POST/GET/PATCH | `/v1/styles…` | `POST /{id}/analyze` (1 AI call) → `needs_answers` → `POST /{id}/answers` `{answers, notes}` (1 AI call) or `/skip-questions` → `ready` |
| POST | `/v1/projects/{id}/plan` | 1 AI call: clips + style + script + `stats` → edit plan |
| PUT | `/v1/projects/{id}/plan` | save the user's edited plan; checked and auto-fixed, **no AI call** |

| POST | `/v1/projects/{id}/render` | `{quality: preview|final}` → new version v1, v2… (never overwritten), **no AI** |
| GET / DELETE | `/v1/projects/{id}/renders[/{render_id}]` | versions with video + thumbnail URLs |

## Rendering (`app/services/render.py`, `app/services/graphics.py`)

Plan → MP4 with FFmpeg: per-shot trim/speed/cover-crop/zoom (zoompan at 2× for smooth
pushes), own audio only where `keep_audio`, concat, last-frame hold under an end card,
caption/title/stats PNG layers (Pillow, Inter + Noto Devanagari/symbol fallback, balanced
line breaks, one accent highlight) with fades, end fade, H.264/AAC faststart. The plan is
re-validated (free) right before rendering. Measured on the M1: 26.5 s Day 1 reel, preview
540×960 in 41 s, final 1080×1920 in ~2 min (21 MB).

## AI usage (Claude Sonnet 5.5, `ANTHROPIC_MODEL`)

| Call | Effort | Measured |
|---|---|---|
| Style from 5 references | medium | 16.5k in / 1.8k out ≈ $0.05 |
| Apply 3 answers + notes | low | 4.9k in / 1.0k out ≈ $0.02 |
| Edit plan, 4 clips | medium | 11.2k in / 3.2k out ≈ $0.05 |

Every call logs its token usage (`claude call:` in the worker log) and has an 8k output cap.
AI is only called by an explicit user action; validation and hand edits are free
(`app/services/plan_validate.py`).

## Analysis (runs automatically)

After a clip or reference is ready, `worker-media` runs `app/tasks/analysis.py`:

| Step | Clips | References | Notes |
|---|---|---|---|
| Proxy | ✅ | – | upright, 30 fps CFR, H.264 ≤1080×1920; the renderer works from this |
| Contact sheet | 12 frames | 16 frames | timestamped grid; what Claude looks at |
| Scene cuts | ✅ | ✅ → `pacing` | shot lengths, cuts per 10 s |
| Silences, loudness | ✅ | loudness | dead air to cut |
| Transcript | ✅ | ✅ | faster-whisper `large-v3-turbo`, word timings. A Silero VAD check runs first and skips Whisper when nobody speaks (~25 s → <1 s). Low-confidence hallucinations ("You", "Thank you") are dropped. Hinglish is auto-detected and comes out in Roman script. |

Whisper weights (~1.6 GB) download into the `models` volume on first use. Measured on an
M1 (Docker, 8 cores): 4 Day-1 clips (32 s total) in 49 s; a 38 s Hinglish reference transcribed correctly.

## Instagram import

`app/services/instagram.py` tries, in order:

1. **yt-dlp** (unpinned in `requirements.txt`, because Instagram changes often; rebuild the image to update it)
2. **instaloader**, by shortcode
3. an optional hosted API (`INSTAGRAM_FALLBACK_API_URL`), e.g. an Apify actor

Public reels downloaded without login when tested (2026-11-18). If Instagram starts blocking the
VPS IP, put a `cookies.txt` from a **dedicated** Instagram account in `secrets/` and set
`INSTAGRAM_COOKIES_FILE=/app/secrets/cookies.txt`. Only `instagram.com` reel/post links are
accepted. Reels are limited to 3 minutes / 200 MB and are used privately as style references.

## Migrations

```bash
docker compose run --rm --no-deps -v "$PWD":/app -u 0 migrate alembic revision --autogenerate -m "message"
docker compose up -d migrate
```

## Spend protection

- Every Claude call is logged in `ai_usage` (kind, tokens, estimated USD). `GET /v1/me/ai-usage`
  shows calls in the last 24 h, the limit and spend so far.
- `AI_DAILY_LIMIT` (default 20) AI calls per user per 24 h; over it the API returns 429 before
  anything is queued.

## Housekeeping (`scheduler` service, `app/scheduler_loop.py`)

Every 5 min: jobs stuck in a running state (worker restart, Docker stopped) are marked failed
with "This was interrupted - please try again" (a stuck render puts the project back to
`planned`), and temp folders in `work/` older than 2 h are deleted.

## Tests

```bash
docker compose exec -u 0 web sh -c "pip install -q pytest && python -m pytest -q tests"
python3 scripts/e2e.py          # whole flow as a new dev user, free (no AI); cleans up after itself
python3 scripts/e2e.py --ai     # same + style analysis and AI plan (3 Claude calls)
```
