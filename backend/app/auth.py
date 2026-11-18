"""Firebase (Google sign-in) auth.

The app signs in with Google through Firebase and sends the Firebase ID token as
`Authorization: Bearer <token>`. We verify it with firebase-admin and upsert the user.
"""

import logging
from dataclasses import dataclass
from functools import lru_cache

import firebase_admin
from fastapi import Depends, Header, HTTPException, status
from firebase_admin import auth as fb_auth
from firebase_admin import credentials
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import User

log = logging.getLogger(__name__)


@dataclass
class TokenClaims:
    uid: str
    email: str | None = None
    name: str | None = None
    picture: str | None = None


@lru_cache
def _firebase_app() -> firebase_admin.App:
    s = get_settings()
    options = {"projectId": s.firebase_project_id} if s.firebase_project_id else None
    if s.firebase_credentials_file:
        cred = credentials.Certificate(s.firebase_credentials_file)
        return firebase_admin.initialize_app(cred, options)
    # Falls back to GOOGLE_APPLICATION_CREDENTIALS / metadata server.
    return firebase_admin.initialize_app(options=options)


def _verify(token: str) -> TokenClaims:
    s = get_settings()
    if s.dev_bypass_enabled and token.startswith("dev:"):
        uid = token.removeprefix("dev:") or "dev-user"
        return TokenClaims(uid=uid, email=f"{uid}@dev.local", name=uid)
    try:
        decoded = fb_auth.verify_id_token(token, app=_firebase_app(), check_revoked=False)
    except Exception as exc:  # invalid, expired, wrong project...
        log.info("token rejected: %s", exc)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token") from exc
    return TokenClaims(
        uid=decoded["uid"],
        email=decoded.get("email"),
        name=decoded.get("name"),
        picture=decoded.get("picture"),
    )


def current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    claims = _verify(authorization.split(" ", 1)[1].strip())

    user = db.scalar(select(User).where(User.firebase_uid == claims.uid))
    if user is None:
        user = User(firebase_uid=claims.uid, email=claims.email, name=claims.name, photo_url=claims.picture)
        db.add(user)
    else:
        user.email = claims.email or user.email
        user.name = claims.name or user.name
        user.photo_url = claims.picture or user.photo_url
    db.commit()
    db.refresh(user)
    return user
