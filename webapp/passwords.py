"""Password reset: issuing, redeeming and invalidating one-time tokens.

Three properties matter here and each one costs something specific:

* The token is stored only as a SHA-256 hash. Anyone reading the database --
  a backup, a stolen volume, a nosy admin -- gets hashes they cannot present.
* Requesting a reset never reveals whether the address has an account. The
  response and the timing are the same either way.
* Redeeming a token bumps the user's session version, which signs out every
  existing session. Otherwise someone who reset a stolen account's password
  would leave the thief's cookie working.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
import hashlib
import os
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import PasswordReset, User, utcnow

TOKEN_TTL_MINUTES = max(5, int(os.getenv("RESET_TTL_MINUTES", "60") or 60))
_TOKEN_BYTES = 32


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _aware(moment: datetime) -> datetime:
    """SQLite hands back naive datetimes; compare in UTC either way."""
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def issue(session: Session, email: str, ip: str = "") -> Optional[Tuple[User, str]]:
    """Create a reset token for `email`, or None if no such account.

    The caller must respond identically either way -- returning None is for
    deciding whether to send mail, never for shaping the API response.
    """
    address = email.strip().lower()
    user = session.scalar(select(User).where(User.email == address))
    if user is None:
        return None

    # One live token per account: issuing a new one retires the old.
    for stale in session.scalars(
        select(PasswordReset).where(
            PasswordReset.user_id == user.id, PasswordReset.used_at.is_(None)
        )
    ):
        stale.used_at = utcnow()

    token = secrets.token_urlsafe(_TOKEN_BYTES)
    session.add(PasswordReset(
        user_id=user.id,
        token_hash=_hash(token),
        expires_at=utcnow() + timedelta(minutes=TOKEN_TTL_MINUTES),
        requested_ip=ip[:45],
    ))
    session.commit()
    return user, token


def redeem(session: Session, token: str, new_password: str,
           hash_password) -> User:
    """Consume a token and set the new password.

    Raises ValueError with a deliberately vague message on any failure: a
    caller cannot tell an unknown token from an expired or spent one.
    """
    supplied = (token or "").strip()
    if not supplied:
        raise ValueError("That reset link is not valid or has expired.")

    record = session.scalar(
        select(PasswordReset).where(PasswordReset.token_hash == _hash(supplied))
    )
    if record is None or record.used_at is not None:
        raise ValueError("That reset link is not valid or has expired.")
    if _aware(record.expires_at) <= datetime.now(timezone.utc):
        raise ValueError("That reset link is not valid or has expired.")

    user = session.get(User, record.user_id)
    if user is None:
        raise ValueError("That reset link is not valid or has expired.")

    user.password_hash = hash_password(new_password)
    # Signs out every existing session for this account, including whoever
    # prompted the reset.
    user.session_version = (user.session_version or 1) + 1
    record.used_at = utcnow()
    session.commit()
    return user


def change_password(session: Session, user: User, new_password: str,
                    hash_password) -> None:
    """Set a new password for a signed-in user and drop other sessions."""
    user.password_hash = hash_password(new_password)
    user.session_version = (user.session_version or 1) + 1
    session.commit()


def purge_expired(session: Session) -> int:
    """Delete spent and expired tokens. Returns how many went."""
    now = datetime.now(timezone.utc)
    gone = 0
    for record in session.scalars(select(PasswordReset)):
        if record.used_at is not None or _aware(record.expires_at) <= now:
            session.delete(record)
            gone += 1
    if gone:
        session.commit()
    return gone
