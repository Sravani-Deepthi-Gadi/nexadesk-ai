"""Create an admin operator interactively.

    python -m scripts.create_admin
"""
import getpass
import sys

from app.db.session import SessionLocal, init_db
from app.models import AdminUser
from app.models.enums import AdminRole
from app.security.password import hash_password


def main() -> int:
    init_db()
    email = input("Email: ").strip()
    if not email:
        print("Email is required.")
        return 1

    password = getpass.getpass("Password: ")
    if len(password) < 12:
        print("Use at least 12 characters.")
        return 1
    if password != getpass.getpass("Confirm: "):
        print("Passwords do not match.")
        return 1

    role_input = input("Role [admin/viewer] (admin): ").strip().lower() or "admin"
    try:
        role = AdminRole(role_input)
    except ValueError:
        print(f"Unknown role: {role_input}")
        return 1

    db = SessionLocal()
    try:
        if db.query(AdminUser).filter(AdminUser.email == email).one_or_none():
            print(f"{email} already exists.")
            return 1
        db.add(AdminUser(
            email=email, password_hash=hash_password(password),
            role=role, is_active=True,
        ))
        db.commit()
        print(f"Created {role.value}: {email}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
