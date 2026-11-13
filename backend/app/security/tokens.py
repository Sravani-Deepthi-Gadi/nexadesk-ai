"""JWT issuing and verification.

HS256 with a server-side secret. The token carries the admin's id, email
and role, but the role in the token is NOT trusted on its own: every
protected route re-loads the user row and checks `is_active` and the role
stored in the database. A token is a claim about who you are, not a
standing grant -- otherwise deactivating an admin would leave their
outstanding tokens working until expiry.
"""
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

ALGORITHM = "HS256"


class TokenError(Exception):
    """Raised when a token is absent, malformed, expired or wrongly signed."""


def _require_secret(secret: str) -> str:
    if not secret or secret in {"change-me", "changeme", ""}:
        raise RuntimeError(
            "JWT_SECRET is not configured. Set it in backend/.env to a long "
            "random value (e.g. python -c \"import secrets;"
            " print(secrets.token_urlsafe(48))\")."
        )
    return secret


def create_access_token(
    *, subject_id: int, email: str, role: str, secret: str, expires_minutes: int = 60
) -> str:
    secret = _require_secret(secret)
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(subject_id),
        "email": email,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=expires_minutes)).timestamp()),
    }
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def decode_access_token(token: str, *, secret: str) -> dict[str, Any]:
    secret = _require_secret(secret)
    try:
        # algorithms is pinned: without it a token could nominate "none".
        return jwt.decode(token, secret, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("Token has expired.") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("Token is invalid.") from exc
