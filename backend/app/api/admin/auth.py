"""Admin login."""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin
from app.config import get_settings
from app.db.session import get_db
from app.models import AdminUser
from app.security.password import verify_password
from app.security.tokens import create_access_token

router = APIRouter(prefix="/api/admin/auth", tags=["admin:auth"])


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int
    role: str


class MeResponse(BaseModel):
    id: int
    email: str
    role: str


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    settings = get_settings()
    admin = db.query(AdminUser).filter(AdminUser.email == payload.email).one_or_none()

    # One message and one code for "no such user" and "wrong password", so
    # the endpoint cannot be used to enumerate which emails are registered.
    # verify_password still runs on a dummy hash when the user is missing,
    # to keep the response time comparable.
    dummy = "$2b$12$" + "x" * 53
    ok = verify_password(payload.password, admin.password_hash if admin else dummy)

    if admin is None or not ok or not admin.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
        )

    token = create_access_token(
        subject_id=admin.id,
        email=admin.email,
        role=admin.role.value,
        secret=settings.jwt_secret,
        expires_minutes=settings.jwt_expire_minutes,
    )
    return TokenResponse(
        access_token=token,
        expires_in_minutes=settings.jwt_expire_minutes,
        role=admin.role.value,
    )


@router.get("/me", response_model=MeResponse)
def me(admin: AdminUser = Depends(get_current_admin)) -> MeResponse:
    return MeResponse(id=admin.id, email=admin.email, role=admin.role.value)
