"""Create or promote a dedicated platform super-admin account.

Run from the backend directory (or inside the backend container):

    python create_superadmin.py --email ops@example.com --password "S3cret!" --name "Ops Admin"

Behavior:
    * If no user with that email exists, a new internal super-admin is created.
    * If a user already exists, it is promoted to super-admin (and, when
      --password is supplied, its password is reset). This makes the command a
      safe way to bootstrap access when the default admin is unavailable.

Super-admin accounts require TOTP two-factor authentication; enrollment is
forced on the account's first login (see docs/MFA_SETUP.md).
"""
import argparse
import sys

from sqlalchemy.orm import Session

from app.config import settings
from app.database import sync_engine
from app.models import User  # noqa: F401 - registers all models
from app.auth.password import hash_password


def create_superadmin(email: str, password: str | None, display_name: str) -> None:
    with Session(sync_engine) as session:
        existing = session.query(User).filter_by(email=email).first()
        if existing:
            existing.is_super_admin = True
            existing.is_active = True
            if password:
                existing.password_hash = hash_password(password)
                existing.auth_provider = "internal"
            session.commit()
            print(f"Promoted existing user to super-admin: {email}")
            return

        if not password:
            sys.exit("Error: --password is required when creating a new account.")

        # Platform super-admins are intentionally not tied to an organization;
        # they bypass org-scoped checks (see app/auth/dependencies.py). Leaving
        # organization_id null keeps the account org-agnostic.
        user = User(
            email=email,
            display_name=display_name,
            password_hash=hash_password(password),
            auth_provider="internal",
            role="admin",
            is_active=True,
            is_super_admin=True,
        )
        session.add(user)
        session.commit()
        print(f"Created super-admin user: {email}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create or promote a dedicated platform super-admin account.",
    )
    parser.add_argument("--email", required=True, help="Account email address.")
    parser.add_argument(
        "--password",
        help="Account password. Required when creating a new account; "
             "resets the password when promoting an existing one.",
    )
    parser.add_argument(
        "--name",
        default="Super Admin",
        help="Display name for a newly created account (default: 'Super Admin').",
    )
    args = parser.parse_args()

    print(f"Database: {settings.DATABASE_URL_SYNC.split('@')[-1]}")  # hide credentials
    create_superadmin(args.email, args.password, args.name)


if __name__ == "__main__":
    main()
