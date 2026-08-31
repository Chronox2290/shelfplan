"""Guards that only matter once the app is reachable from the internet.

Two things change when a URL is public rather than on your desk: anyone can
try passwords against it, and anyone who finds it can create an account. Argon2
is deliberately expensive to compute, so unlimited login attempts burn your own
CPU as well as risking the password -- rate limiting is a availability control
here, not just an auth one.

State is in-process. With a single container that is exactly right; if you ever
run more than one, each holds its own counters and the effective limit
multiplies by the number of instances. Move this to Redis at that point.
"""

from collections import defaultdict, deque
from typing import Deque, Dict, Optional, Tuple
import os
import threading
import time

from fastapi import HTTPException, Request, status

# --------------------------------------------------------------------------
# Who may sign up
# --------------------------------------------------------------------------

# open   -- anyone with the link (fine while you are the only user)
# invite -- must present SIGNUP_INVITE_CODE
# closed -- nobody; existing accounts still work
SIGNUP_MODE = os.getenv("SIGNUP_MODE", "invite").strip().lower()
SIGNUP_INVITE_CODE = os.getenv("SIGNUP_INVITE_CODE", "").strip()

_ALLOWED_MODES = ("open", "invite", "closed")


def signup_config_error() -> Optional[str]:
    """A misconfiguration that would silently leave signup wide open or dead."""
    if SIGNUP_MODE not in _ALLOWED_MODES:
        return (f"SIGNUP_MODE={SIGNUP_MODE!r} is not one of {_ALLOWED_MODES}.")
    if SIGNUP_MODE == "invite" and not SIGNUP_INVITE_CODE:
        return ("SIGNUP_MODE=invite but SIGNUP_INVITE_CODE is empty, so nobody "
                "can register. Set a code, or use SIGNUP_MODE=open.")
    return None


def check_signup_allowed(invite: Optional[str]) -> None:
    """Raise unless this registration attempt is permitted."""
    if SIGNUP_MODE == "open":
        return
    if SIGNUP_MODE == "closed":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Registration is closed on this server.",
        )
    supplied = (invite or "").strip()
    # Constant-time-ish: compare full strings, never short-circuit on length.
    import hmac
    if not supplied or not hmac.compare_digest(supplied, SIGNUP_INVITE_CODE):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "That invite code is not valid.",
        )


# --------------------------------------------------------------------------
# Rate limiting
# --------------------------------------------------------------------------

class SlidingWindow:
    """Counts events per key over a rolling window."""

    def __init__(self, limit: int, window_s: float) -> None:
        self.limit = limit
        self.window_s = window_s
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> Tuple[bool, float]:
        """Return (allowed, seconds_until_retry)."""
        now = time.monotonic()
        cutoff = now - self.window_s
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] < cutoff:
                hits.popleft()
            if len(hits) >= self.limit:
                return False, max(0.0, hits[0] + self.window_s - now)
            hits.append(now)
            return True, 0.0

    def reset(self, key: str) -> None:
        """Forget a key -- called after a success, so a good login clears it."""
        with self._lock:
            self._hits.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._hits.clear()


def _int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, default)))
    except (TypeError, ValueError):
        return default


# Per-IP, so one abusive client cannot lock out everybody. The per-account
# limiter below is what stops a distributed guess against one known email.
login_by_ip = SlidingWindow(_int_env("RATE_LOGIN_PER_IP", 20), 15 * 60)
login_by_account = SlidingWindow(_int_env("RATE_LOGIN_PER_ACCOUNT", 8), 15 * 60)
register_by_ip = SlidingWindow(_int_env("RATE_REGISTER_PER_IP", 5), 60 * 60)
# Price lookups leave this server's IP at the supermarkets, so a busy user can
# get everyone blocked. Cheap ceiling to keep one account from doing that.
refresh_by_user = SlidingWindow(_int_env("RATE_REFRESH_PER_USER", 12), 60 * 60)
# Reset requests send mail and cost an Argon2 hash on redemption. Limited per
# address as well as per IP so one account cannot be mail-bombed from a botnet.
forgot_by_ip = SlidingWindow(_int_env("RATE_FORGOT_PER_IP", 5), 60 * 60)
forgot_by_account = SlidingWindow(_int_env("RATE_FORGOT_PER_ACCOUNT", 3), 60 * 60)
reset_by_ip = SlidingWindow(_int_env("RATE_RESET_PER_IP", 10), 60 * 60)
# Each import fetches somebody else's page from this server's address. A cap
# keeps one enthusiastic user from making the server look like a crawler.
import_by_user = SlidingWindow(_int_env("RATE_IMPORT_PER_USER", 40), 60 * 60)


def client_ip(request: Request) -> str:
    """The caller's address.

    Behind a proxy this is only correct when the server runs with
    --proxy-headers, which rewrites request.client from X-Forwarded-For. The
    header is NOT read directly here: trusting it unconditionally would let
    anyone spoof their way past the limiter by setting it themselves.
    """
    return request.client.host if request.client else "unknown"


def enforce(window: SlidingWindow, key: str, what: str) -> None:
    allowed, retry_in = window.check(key)
    if not allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Too many {what}. Try again in {int(retry_in) + 1} seconds.",
            headers={"Retry-After": str(int(retry_in) + 1)},
        )


def reset_all() -> None:
    """Test hook."""
    for window in (login_by_ip, login_by_account, register_by_ip,
                   refresh_by_user, forgot_by_ip, forgot_by_account,
                   reset_by_ip, import_by_user):
        window.clear()


# --------------------------------------------------------------------------
# Response headers
# --------------------------------------------------------------------------

def security_headers(https_only: bool) -> Dict[str, str]:
    """Headers applied to every response.

    The CSP allows Google Fonts because the page uses them, and nothing else
    external. 'unsafe-inline' covers the stylesheet embedded in index.html --
    tightening that needs the CSS moved to its own file first.
    """
    headers = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "same-origin",
        "Content-Security-Policy": (
            "default-src 'self'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            # Product photos come from the supermarkets' own CDNs. Without
            # these the catalogue renders as a wall of broken images, because
            # the default policy allows no external hosts at all.
            "img-src 'self' data: "
            "https://cdn0.woolworths.media https://cdn1.woolworths.media "
            "https://productimages.coles.com.au https://shop.coles.com.au; "
            "script-src 'self'; "
            "connect-src 'self'; "
            "form-action 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'"
        ),
    }
    if https_only:
        headers["Strict-Transport-Security"] = "max-age=15552000; includeSubDomains"
    return headers
