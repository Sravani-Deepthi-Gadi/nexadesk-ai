"""Shared FastAPI dependencies."""
from functools import lru_cache

from fastapi import HTTPException, status

from sqlalchemy.orm import Session

from app.agent.llm.base import LLMProvider
from app.agent.llm.claude import ClaudeProvider
from app.config import get_settings
from app.db.seed import seed
from app.models import Agent


@lru_cache
def _build_llm() -> LLMProvider:
    settings = get_settings()
    if settings.llm_provider == "claude":
        return ClaudeProvider(
            api_key=settings.anthropic_api_key, model=settings.llm_model
        )
    raise ValueError(f"Unknown LLM provider: {settings.llm_provider}")


def get_llm() -> LLMProvider:
    """Resolve the LLM provider, or fail as a configuration problem.

    A missing API key is an operator mistake, not a server fault. Letting
    the ValueError escape produces a 500 and a stack trace in the log for
    something a one-line .env change fixes, and tells the customer nothing.
    """
    try:
        return _build_llm()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "The assistant is not configured yet. "
                "An administrator needs to set ANTHROPIC_API_KEY."
            ),
        ) from exc


def get_default_agent(db: Session) -> Agent:
    settings = get_settings()
    agent = (
        db.query(Agent).filter(Agent.name == settings.default_agent_name).one_or_none()
    )
    if agent is None:
        agent = seed(db, agent_name=settings.default_agent_name)
    return agent


# --------------------------------------------------------------------------
# Admin authentication and authorisation (Milestone 2)
# --------------------------------------------------------------------------
from fastapi import Depends, HTTPException, status  # noqa: E402
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer  # noqa: E402

from app.db.session import get_db  # noqa: E402
from app.models import AdminUser  # noqa: E402
from app.models.enums import AdminRole  # noqa: E402
from app.security.tokens import TokenError, decode_access_token  # noqa: E402

#: auto_error=False so a missing header produces our 401 shape, not FastAPI's 403.
_bearer = HTTPBearer(auto_error=False)

_UNAUTHORISED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated.",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> AdminUser:
    """Resolve the bearer token to a live admin row.

    The role inside the token is NOT trusted. The user is re-loaded from the
    database on every request and `is_active` is re-checked, so revoking an
    account takes effect immediately rather than at token expiry.
    """
    if credentials is None or not credentials.credentials:
        raise _UNAUTHORISED

    settings = get_settings()
    try:
        payload = decode_access_token(credentials.credentials, secret=settings.jwt_secret)
    except TokenError:
        raise _UNAUTHORISED from None

    subject = payload.get("sub")
    if subject is None:
        raise _UNAUTHORISED
    try:
        admin_id = int(subject)
    except (TypeError, ValueError):
        raise _UNAUTHORISED from None

    admin = db.get(AdminUser, admin_id)
    if admin is None or not admin.is_active:
        raise _UNAUTHORISED
    return admin


def require_admin(admin: AdminUser = Depends(get_current_admin)) -> AdminUser:
    """Role gate for decisions. VIEWER may read; only ADMIN may approve or reject."""
    if admin.role is not AdminRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This action requires the admin role.",
        )
    return admin
