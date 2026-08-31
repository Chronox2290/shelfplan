"""Sending mail, with a fallback that suits a box on your own shelf.

Most self-hosted installs have no SMTP relay, and a password reset that can
only work with one is a reset that does not work. So when SMTP is unconfigured
the message is written to the server log instead: whoever runs the box can read
the link out of `docker compose logs` and hand it over. That is deliberate --
it keeps the feature usable on a NAS -- but it does mean anyone who can read
the logs can take over an account, which is why it is announced loudly at
startup rather than being a quiet default.
"""

from typing import Optional
import os
import smtplib
import ssl
import sys
from email.message import EmailMessage

SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "587") or 587)
SMTP_USER = os.getenv("SMTP_USER", "").strip()
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", "").strip() or (SMTP_USER or "shelfplan@localhost")
SMTP_STARTTLS = os.getenv("SMTP_STARTTLS", "1") not in ("0", "false", "False")
SMTP_SSL = os.getenv("SMTP_SSL", "0") not in ("0", "false", "False")

APP_NAME = os.getenv("APP_NAME", "Shelf Plan")


def configured() -> bool:
    return bool(SMTP_HOST)


def describe() -> str:
    if configured():
        return f"SMTP via {SMTP_HOST}:{SMTP_PORT} as {SMTP_FROM}"
    return "no SMTP configured -- reset links are written to the server log"


def send(to: str, subject: str, body: str) -> bool:
    """Deliver a message. Returns True if it actually went out by SMTP.

    Never raises: a failed send must not tell the caller whether the address
    exists, and must not turn a password-reset request into a 500.
    """
    if not configured():
        _log(to, subject, body, reason="SMTP not configured")
        return False

    message = EmailMessage()
    message["From"] = SMTP_FROM
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    try:
        if SMTP_SSL:
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT,
                                  context=ssl.create_default_context(),
                                  timeout=20) as server:
                if SMTP_USER:
                    server.login(SMTP_USER, SMTP_PASSWORD)
                server.send_message(message)
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
                if SMTP_STARTTLS:
                    server.starttls(context=ssl.create_default_context())
                if SMTP_USER:
                    server.login(SMTP_USER, SMTP_PASSWORD)
                server.send_message(message)
        return True
    except Exception as exc:  # noqa: BLE001 -- see docstring
        _log(to, subject, body, reason=f"SMTP send failed: {exc}")
        return False


def _log(to: str, subject: str, body: str, reason: str) -> None:
    print(
        f"\n=== {APP_NAME}: undelivered mail ({reason}) ===\n"
        f"To: {to}\nSubject: {subject}\n\n{body}\n"
        f"=== end ===\n",
        file=sys.stderr,
        flush=True,
    )


def reset_email(reset_url: str, minutes: int) -> tuple:
    """Subject and body for a password reset."""
    subject = f"Reset your {APP_NAME} password"
    body = (
        f"Someone asked to reset the {APP_NAME} password for this address.\n\n"
        f"Open this link to choose a new one:\n\n    {reset_url}\n\n"
        f"The link works once and expires in {minutes} minutes.\n\n"
        f"If this was not you, ignore this message -- your password has not "
        f"changed, and the link cannot be used without this email.\n"
    )
    return subject, body
