"""The sound library for the app's music picker: tracks with a 20-second preview each.

Only previews are handed out: the licence of library music (Pixabay) allows it inside edited
reels, not as files on their own.
"""

from fastapi import APIRouter, Depends

from app import storage
from app.auth import current_user
from app.models import User
from app.services import library as L

router = APIRouter(tags=["library"])


@router.get("/library/music")
def music(user: User = Depends(current_user)) -> dict:
    tracks = []
    for t in L.music_tracks():
        tracks.append({
            "id": t["id"], "title": t["title"], "moods": t.get("moods", []), "energy": t.get("energy"),
            "bpm": t.get("bpm"), "duration_s": t.get("duration_s"),
            "preview_url": storage.presign_get(t["preview_key"]) if t.get("preview_key") else None,
        })
    return {
        "moods": [{"id": m, "help": L.MOOD_HELP[m]} for m in L.moods_available()],
        "tracks": tracks,
    }
