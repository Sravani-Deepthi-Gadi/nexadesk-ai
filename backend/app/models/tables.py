"""SQLAlchemy ORM models.

Design notes that matter for the interview:

* ``action_requests`` (workflow state, mutable) is deliberately separate
  from ``audit_logs`` (append-only evidence). Merging them would give the
  audit trail an UPDATE path, which defeats its purpose.
* Every column type used here is PostgreSQL-compatible, so the move off
  SQLite is a connection-string change plus a migration, not a rewrite.
* Timestamps are timezone-aware UTC.
"""
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, DateTime, Enum as SAEnum, ForeignKey, Integer, String, Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.enums import (
    AgentStatus, ApprovalStatus, AppointmentStatus, ConversationState,
    MessageRole, Outcome, Permission, PermissionResult, RiskLevel,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------
# Business domain
# --------------------------------------------------------------------------
class Service(Base):
    __tablename__ = "services"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Appointment(Base):
    __tablename__ = "appointments"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[AppointmentStatus] = mapped_column(
        SAEnum(AppointmentStatus), default=AppointmentStatus.BOOKED, nullable=False
    )
    created_by_agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    customer: Mapped["Customer"] = relationship()
    service: Mapped["Service"] = relationship()


# --------------------------------------------------------------------------
# Agent identity and permissions
# --------------------------------------------------------------------------
class Agent(Base):
    """An AI agent identity. ``status`` IS the emergency stop."""
    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    status: Mapped[AgentStatus] = mapped_column(
        SAEnum(AgentStatus), default=AgentStatus.ACTIVE, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    permissions: Mapped[list["AgentPermission"]] = relationship(
        back_populates="agent", cascade="all, delete-orphan"
    )


class AgentPermission(Base):
    """Permissions live in the DATABASE, never in the prompt.

    Anything in a prompt is negotiable; anything in a WHERE clause is not.
    """
    __tablename__ = "agent_permissions"
    __table_args__ = (UniqueConstraint("agent_id", "permission"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), nullable=False)
    permission: Mapped[Permission] = mapped_column(SAEnum(Permission), nullable=False)
    granted: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    agent: Mapped["Agent"] = relationship(back_populates="permissions")


# --------------------------------------------------------------------------
# Conversation memory
# --------------------------------------------------------------------------
class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"))
    state: Mapped[ConversationState] = mapped_column(
        SAEnum(ConversationState), default=ConversationState.ACTIVE, nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_active_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan",
        order_by="Message.seq",
    )


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (UniqueConstraint("conversation_id", "seq"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[MessageRole] = mapped_column(SAEnum(MessageRole), nullable=False)
    content: Mapped[str] = mapped_column(Text, default="")
    # Raw Anthropic content blocks, JSON-encoded, so a tool-use turn can be
    # replayed to the API verbatim on the next request.
    blocks_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")


# --------------------------------------------------------------------------
# Governance evidence
# --------------------------------------------------------------------------
class AuditLog(Base):
    """Append-only record of every governed tool invocation.

    Written on EVERY path, including rejections. Updates and deletes are
    blocked at the ORM layer (see app/governance/audit.py).
    """
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id"))
    conversation_id: Mapped[int | None] = mapped_column(ForeignKey("conversations.id"))
    tool_name: Mapped[str] = mapped_column(String(80), nullable=False)
    params_json: Mapped[str] = mapped_column(Text, default="{}")
    risk_level: Mapped[RiskLevel | None] = mapped_column(SAEnum(RiskLevel))
    permission_result: Mapped[PermissionResult | None] = mapped_column(SAEnum(PermissionResult))
    approval_status: Mapped[ApprovalStatus] = mapped_column(
        SAEnum(ApprovalStatus), default=ApprovalStatus.NOT_REQUIRED, nullable=False
    )
    outcome: Mapped[Outcome] = mapped_column(SAEnum(Outcome), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
