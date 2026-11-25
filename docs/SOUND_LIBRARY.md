# Sound library: what to download and how to add it

The app's background music and extra sound effects live in R2 under `library/`. You download
files by hand (Pixabay blocks automated downloads), drop them into folders, and run one command.

## 1. Folder layout

Make a folder `~/Desktop/raw2reel-sounds` like this. The folder name is the tag, so spell it exactly:

```
raw2reel-sounds/
  music/
    upbeat/        energetic/     chill/       lofi/        emotional/
    cinematic/     inspiring/     funny/       desi/        dramatic/
    desi+upbeat/   (use + to give a track two moods)
  sfx/
    whoosh_fast/   whoosh_soft/   boom/   slam/   shutter/   tick/   pop/
    riser/         ding/          click/  swipe/  glitch/    cash/
```

## 2. What to download (first batch)

**Music: about 50 tracks** (pixabay.com/music)

| Mood folder | How many | Search Pixabay for |
|---|---|---|
| upbeat | 8 | upbeat, happy, vlog, food |
| energetic | 6 | workout, sport, phonk, hype |
| chill | 6 | chill, travel, morning, acoustic |
| lofi | 5 | lofi, study beats |
| emotional | 4 | emotional piano, heartfelt |
| cinematic | 4 | cinematic, epic, trailer |
| inspiring | 5 | inspiring, motivational, corporate uplifting |
| funny | 3 | funny, quirky, comedy |
| desi | 6 | indian, bollywood, shehnai, dhol, wedding |
| dramatic | 3 | suspense, tension, thriller |

Pick tracks **at least 60 seconds long** with a clear beat. Skip anything with vocals/lyrics
except desi (vocals compete with the creator's voice).

**Sound effects: 3-5 of each** (pixabay.com/sound-effects). Short (under 3 s), punchy, no long tails.

| Folder | Search for |
|---|---|
| whoosh_fast | whoosh, swoosh fast, transition whoosh |
| whoosh_soft | soft whoosh, air swoosh |
| boom | cinematic boom, bass drop, impact |
| slam | hit, punch impact, slam |
| shutter | camera shutter |
| tick | clock tick |
| pop | pop, bubble pop, ui pop |
| riser | riser, build up, tension rise |
| ding | ding, notification, bell |
| click | click, mouse click, ui click |
| swipe | swipe, page turn |
| glitch | glitch, digital glitch |
| cash | cash register, coin, ka-ching |

## 3. Licence rules (Pixabay Content License)

- OK: using the files inside our users' edited reels, commercially, no credit needed.
- Not OK: letting people download the files as they are. The app only streams 20-second previews.
- **Copyright claims:** some Pixabay tracks are registered with Content ID and can get a claim on
  Instagram/YouTube. Before adding a track, check its Pixabay page for a Content ID notice and skip
  it if there is one. If a track gets claimed later, take it out:
  `python scripts/import_sounds.py --block <track id>`.
- Keep the original file names. Pixabay names end with the item number, which the library
  records as the source of each file.

## 4. Add them to the library

With the backend running (`docker compose up -d` in `backend/`):

```bash
cd backend
docker compose run --rm -v ~/Desktop/raw2reel-sounds:/sounds:ro worker-media python scripts/import_sounds.py /sounds --dry-run
docker compose run --rm -v ~/Desktop/raw2reel-sounds:/sounds:ro worker-media python scripts/import_sounds.py /sounds
```

The dry run checks every file and prints its tempo, mood and energy without uploading. The real run
levels each file, finds the beats, makes the preview, uploads to R2 and updates
`library/manifest.json` (old versions are kept in `library/history/`). Files already added are
skipped, so run it again whenever you add more.

Other commands: `--list` (what's in the library), `--block ID` / `--unblock ID`.

## How the app uses it

- The AI picks a mood for each reel; the app picks a track for that mood and energy (the same
  track on every remake, different tracks across reels). The creator can pick their own in
  "Captions & sounds" or in Fine-tune > Sounds, with a ▶ preview.
- The track starts where its beats line up with the most cuts, fades in, and dips about 8-10 dB
  whenever someone is talking.
- Library sound effects join the built-in pack: repeats rotate through all takes, and the AI can
  use the new sounds (riser, ding, click, swipe, glitch, cash) once the library has them.
