"""Check the mail settings actually work, before trusting them to a reset.

    uv run python scripts/test_email.py you@example.com

Reads the same environment the app does, so a pass here means password resets
will be delivered rather than dropped into the container log.
"""

import argparse
import os
import smtplib
import ssl
import sys
from pathlib import Path


def load_env(path: Path) -> None:
    """Minimal .env reader, so this works without the app's dependencies."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("to", help="Address to send the test message to")
    parser.add_argument("--env", default=".env", help="Env file to read")
    args = parser.parse_args()

    load_env(Path(args.env))

    host = os.getenv("SMTP_HOST", "").strip()
    port = int(os.getenv("SMTP_PORT", "587") or 587)
    user = os.getenv("SMTP_USER", "").strip()
    password = os.getenv("SMTP_PASSWORD", "")
    sender = os.getenv("SMTP_FROM", "").strip() or user
    use_ssl = os.getenv("SMTP_SSL", "0") not in ("0", "false", "False")
    starttls = os.getenv("SMTP_STARTTLS", "1") not in ("0", "false", "False")

    print("Settings the app will use:")
    print(f"  SMTP_HOST      {host or '(not set)'}")
    print(f"  SMTP_PORT      {port}")
    print(f"  SMTP_USER      {user or '(not set)'}")
    print(f"  SMTP_PASSWORD  {'set, ' + str(len(password)) + ' characters' if password else '(not set)'}")
    print(f"  SMTP_FROM      {sender or '(not set)'}")
    print(f"  encryption     {'SSL' if use_ssl else ('STARTTLS' if starttls else 'none')}")
    print()

    if not host:
        print("SMTP_HOST is empty, so reset links go to the server log instead.")
        print("Fill in the SMTP_ lines in .env and run this again.")
        return 1
    if not password:
        print("SMTP_PASSWORD is empty. Most providers need an app password here,")
        print("not your normal account password.")
        return 1

    from email.message import EmailMessage
    message = EmailMessage()
    message["From"] = sender
    message["To"] = args.to
    message["Subject"] = "Shelf Plan test message"
    message.set_content(
        "If you are reading this, Shelf Plan can send mail.\n\n"
        "Password reset links will now be emailed rather than written to the "
        "server log.\n"
    )

    try:
        if use_ssl:
            with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(),
                                  timeout=25) as server:
                server.login(user, password)
                server.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=25) as server:
                if starttls:
                    server.starttls(context=ssl.create_default_context())
                server.login(user, password)
                server.send_message(message)
    except smtplib.SMTPAuthenticationError:
        print("FAILED: the server rejected that username or password.")
        print("Gmail, Outlook and Yahoo all require an *app password* with")
        print("two-factor authentication switched on -- your normal password")
        print("will always be refused here.")
        return 1
    except Exception as exc:  # noqa: BLE001 -- report whatever went wrong
        print(f"FAILED: {type(exc).__name__}: {exc}")
        print()
        print("Common causes: wrong port (587 for STARTTLS, 465 for SSL),")
        print("a firewall blocking outbound mail, or the wrong host name.")
        return 1

    print(f"SENT. Check {args.to} -- including the spam folder.")
    print("Password resets will now be emailed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
