"""Promote a Phoenix user to admin by email.

Usage:
    python scripts/promote_admin.py --email harishprogram@gmail.com
    python scripts/promote_admin.py --email user@example.com --demote

Flips users.is_admin and users.role in one transaction. The user must log out
and log back in for their JWT to reflect the new flag (JWT is stamped at
login via auth.py::_create_access_token).
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import select

from shared.db.engine import get_engine
from shared.db.models.user import User
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def _run(email: str, *, demote: bool) -> int:
    engine = get_engine()
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with Session() as sess:
        res = await sess.execute(select(User).where(User.email == email))
        user = res.scalar_one_or_none()
        if not user:
            print(f"ERROR: no user with email {email!r}")
            return 1

        print(f"Before: {user.email}  is_admin={user.is_admin}  role={user.role}")
        if demote:
            user.is_admin = False
            if (user.role or "").lower() == "admin":
                user.role = "trader"
        else:
            user.is_admin = True
            user.role = "admin"
        await sess.commit()
        print(f"After:  {user.email}  is_admin={user.is_admin}  role={user.role}")
        print("\nReminder: the user must log out + log back in to refresh their JWT.")
    await engine.dispose()
    return 0


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--email", required=True)
    p.add_argument("--demote", action="store_true",
                   help="Revoke admin instead of granting it")
    args = p.parse_args()
    sys.exit(asyncio.run(_run(args.email, demote=args.demote)))


if __name__ == "__main__":
    main()
