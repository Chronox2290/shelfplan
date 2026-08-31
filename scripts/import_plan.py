"""Load a plan's state JSON into an account.

Takes either a plan HTML file (reads its <script id="state"> block) or a raw
JSON file, and attaches it to a user -- creating the account if needed.

    uv run python scripts/import_plan.py shelf-plan.html --email you@example.com
"""

import argparse
import getpass
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from webapp import auth  # noqa: E402
from webapp.db import Plan, SessionLocal, User, init_db  # noqa: E402

STATE_RE = re.compile(r'<script[^>]*id="state"[^>]*>(.*?)</script>', re.S)


def read_state(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".html", ".htm"):
        match = STATE_RE.search(text)
        if not match:
            raise SystemExit('no <script id="state"> block in that file')
        text = match.group(1).replace("<\\/", "</")
    return json.loads(text)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", help="Plan .html or .json file")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", default="Shelf Plan", help="Plan name")
    parser.add_argument("--replace", action="store_true",
                        help="Overwrite an existing plan of the same name")
    args = parser.parse_args()

    data = read_state(Path(args.plan))
    init_db()

    with SessionLocal() as session:
        email = args.email.strip().lower()
        user = session.scalar(select(User).where(User.email == email))
        if user is None:
            print(f"No account for {email}. Creating one.")
            password = getpass.getpass("Choose a password (min 10 chars): ")
            if len(password) < auth.MIN_PASSWORD_LENGTH:
                raise SystemExit("Password too short.")
            if password != getpass.getpass("Confirm: "):
                raise SystemExit("Passwords did not match.")
            user = User(email=email, password_hash=auth.hash_password(password))
            session.add(user)
            session.commit()

        plan = session.scalar(
            select(Plan).where(Plan.user_id == user.id, Plan.name == args.name)
        )
        if plan and not args.replace:
            raise SystemExit(
                f'"{args.name}" already exists for {email}. Pass --replace to overwrite.'
            )
        if plan:
            plan.data = data
        else:
            plan = Plan(user_id=user.id, name=args.name, data=data)
            session.add(plan)
        session.commit()

        print(f'Imported "{args.name}" for {email}: '
              f'{len(data.get("shop") or {})} shopping items, '
              f'{len(data.get("prices") or {})} priced foods, '
              f'{len(data.get("recipes") or [])} recipes.')


if __name__ == "__main__":
    main()
