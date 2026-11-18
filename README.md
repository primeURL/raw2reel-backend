# Raw2Reel

Mobile app that edits short vertical reels automatically: learn a creator's style from
reference reels (uploads or Instagram links), then turn their raw clips into a finished reel.

| Part | Stack | Status |
|---|---|---|
| [`backend/`](backend/README.md) | FastAPI, Celery, Postgres, Redis, Cloudflare R2, FFmpeg, faster-whisper, Claude | Week 1 done: import, analysis, style, edit plan, render |
| `app/` | React Native (Expo), Firebase Google sign-in | Week 2 |

Quick start: `cd backend && cp .env.example .env && docker compose up -d --build`, then
`python3 scripts/e2e.py --skip-instagram` to check the whole pipeline.
