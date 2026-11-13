"""Password hashing.

bcrypt with a per-password salt and a work factor. Deliberately slow: that
is the feature. bcrypt silently truncates inputs beyond 72 bytes, so long
passwords are rejected rather than quietly weakened.
"""
import bcrypt

MAX_PASSWORD_BYTES = 72


class PasswordTooLongError(ValueError):
    pass


def hash_password(plain: str) -> str:
    raw = plain.encode("utf-8")
    if len(raw) > MAX_PASSWORD_BYTES:
        raise PasswordTooLongError(
            f"Password exceeds {MAX_PASSWORD_BYTES} bytes, which bcrypt would truncate."
        )
    return bcrypt.hashpw(raw, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    raw = plain.encode("utf-8")
    if len(raw) > MAX_PASSWORD_BYTES:
        return False
    try:
        return bcrypt.checkpw(raw, hashed.encode("utf-8"))
    except (ValueError, TypeError):
        # Malformed hash in the database -- fail closed, never fail open.
        return False
