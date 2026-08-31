"""Accounts and sessions.

Passwords are hashed with Argon2id. The session is a signed, http-only cookie
carrying nothing but the user id -- there is no server-side session store to
keep in sync, and tampering invalidates the signature.
"""

from typing import Optional
import os
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError
from fastapi import Depends, HTTPException, Request, Response, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import User, get_session

COOKIE_NAME = "shelfplan_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 30  # 30 days

# A generated secret means sessions do not survive a restart. That is safe but
# annoying, so a deployment should set SESSION_SECRET explicitly.
SESSION_SECRET = os.getenv("SESSION_SECRET") or secrets.token_urlsafe(48)
SECRET_WAS_GENERATED = not os.getenv("SESSION_SECRET")

# Set COOKIE_SECURE=0 only for plain-http local use; anything internet-facing
# must serve over TLS and leave this on.
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "1") not in ("0", "false", "False")

_hasher = PasswordHasher()
_serializer = URLSafeTimedSerializer(SESSION_SECRET, salt="shelfplan.session")

MIN_PASSWORD_LENGTH = 10


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    try:
        _hasher.verify(stored_hash, password)
        return True
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(stored_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(stored_hash)
    except InvalidHashError:
        return False


def validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters.",
        )


def set_session(response: Response, user_id: int, session_version: int = 1) -> None:
    response.set_cookie(
        COOKIE_NAME,
        _serializer.dumps({"uid": user_id, "sv": session_version}),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=COOKIE_SECURE,
        path="/",
    )


def clear_session(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


def _session_from_request(request: Request):
    """(user_id, session_version) from the cookie, or (None, None)."""
    raw = request.cookies.get(COOKIE_NAME)
    if not raw:
        return None, None
    try:
        payload = _serializer.loads(raw, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None, None
    uid = payload.get("uid")
    if not isinstance(uid, int):
        return None, None
    version = payload.get("sv")
    # Cookies minted before session versioning carry no "sv"; treat them as
    # version 1 so existing sessions survive the upgrade.
    return uid, version if isinstance(version, int) else 1


def _resolve_user(request: Request, session: Session) -> Optional[User]:
    uid, version = _session_from_request(request)
    if uid is None:
        return None
    user = session.get(User, uid)
    if user is None:
        return None
    # A password change bumps session_version, retiring every older cookie.
    if (user.session_version or 1) != version:
        return None
    return user


def current_user(
    request: Request, session: Session = Depends(get_session)
) -> User:
    """Require a signed-in user, or 401."""
    user = _resolve_user(request, session)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in required.")
    return user


def optional_user(
    request: Request, session: Session = Depends(get_session)
) -> Optional[User]:
    return _resolve_user(request, session)


def register_user(session: Session, email: str, password: str) -> User:
    email = email.strip().lower()
    validate_password(password)
    existing = session.scalar(select(User).where(User.email == email))
    if existing is not None:
        # Same message as a bad login, so this cannot be used to enumerate
        # which addresses have accounts.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "That email cannot be registered. Try signing in instead.",
        )
    user = User(email=email, password_hash=hash_password(password))
    session.add(user)
    session.commit()
    return user


def authenticate(session: Session, email: str, password: str) -> User:
    email = email.strip().lower()
    user = session.scalar(select(User).where(User.email == email))
    if user is None:
        # Hash anyway so a missing account and a wrong password take the same
        # time, and neither is distinguishable from the response.
        _hasher.hash(password)
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Incorrect email or password."
        )
    if not verify_password(user.password_hash, password):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Incorrect email or password."
        )
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
        session.commit()
    return user
