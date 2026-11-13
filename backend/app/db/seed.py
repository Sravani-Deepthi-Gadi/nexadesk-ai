"""Seed NexaCare's demo data.

Idempotent: safe to run on every boot. This is what makes a free-tier
deploy with an ephemeral filesystem reproducible.
"""
from sqlalchemy.orm import Session

from app.models import Agent, AgentPermission, Service
from app.models.enums import AgentStatus, Permission

SERVICES = [
    ("Initial Consultation", "A 30-minute introductory consultation with an advisor.", 30, 0),
    ("Business Advisory Session", "A full advisory session covering strategy and planning.", 60, 12000),
    ("Compliance Review", "Review of your documentation against current requirements.", 45, 9000),
    ("Account Health Check", "A short review of your existing account and services.", 30, 4500),
]

# The concierge may read and book, but NOT cancel or modify customer data.
# Note what is absent: CANCEL_APPOINTMENT and MODIFY_CUSTOMER_DATA.
DEFAULT_AGENT_PERMISSIONS = [
    Permission.READ_BUSINESS_DATA,
    Permission.CHECK_AVAILABILITY,
    Permission.CREATE_APPOINTMENT,
]


def seed(db: Session, agent_name: str = "nexadesk-concierge") -> Agent:
    if db.query(Service).count() == 0:
        for name, desc, minutes, price in SERVICES:
            db.add(Service(
                name=name, description=desc,
                duration_minutes=minutes, price_cents=price, is_active=True,
            ))

    agent = db.query(Agent).filter(Agent.name == agent_name).one_or_none()
    if agent is None:
        agent = Agent(name=agent_name, status=AgentStatus.ACTIVE)
        db.add(agent)
        db.flush()
        for perm in DEFAULT_AGENT_PERMISSIONS:
            db.add(AgentPermission(agent_id=agent.id, permission=perm, granted=True))

    db.commit()
    db.refresh(agent)
    return agent


def seed_admin(db: Session) -> "AdminUser | None":
    """Create the bootstrap admin from env vars, if both are set.

    No credentials are hardcoded. With ADMIN_EMAIL/ADMIN_PASSWORD unset this
    is a no-op and you create an operator with scripts/create_admin.py.
    """
    from app.config import get_settings
    from app.models import AdminUser
    from app.models.enums import AdminRole
    from app.security.password import hash_password

    settings = get_settings()
    if not settings.admin_email or not settings.admin_password:
        return None

    existing = (
        db.query(AdminUser)
        .filter(AdminUser.email == settings.admin_email)
        .one_or_none()
    )
    if existing is not None:
        return existing

    admin = AdminUser(
        email=settings.admin_email,
        password_hash=hash_password(settings.admin_password),
        role=AdminRole.ADMIN,
        is_active=True,
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    return admin
