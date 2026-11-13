"""Enumerations shared across the domain.

These are the vocabulary of the governance layer. Keeping them in one
module means permission names and risk levels cannot drift between the
registry, the engine and the audit log.
"""
import enum


class Permission(str, enum.Enum):
    READ_BUSINESS_DATA = "READ_BUSINESS_DATA"
    READ_CUSTOMER_DATA = "READ_CUSTOMER_DATA"
    CHECK_AVAILABILITY = "CHECK_AVAILABILITY"
    CREATE_APPOINTMENT = "CREATE_APPOINTMENT"
    CANCEL_APPOINTMENT = "CANCEL_APPOINTMENT"
    MODIFY_CUSTOMER_DATA = "MODIFY_CUSTOMER_DATA"


class RiskLevel(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class AgentStatus(str, enum.Enum):
    ACTIVE = "active"
    DISABLED = "disabled"


class AppointmentStatus(str, enum.Enum):
    BOOKED = "booked"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


class ConversationState(str, enum.Enum):
    ACTIVE = "active"
    AWAITING_APPROVAL = "awaiting_approval"
    ESCALATED = "escalated"
    CLOSED = "closed"


class MessageRole(str, enum.Enum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class PermissionResult(str, enum.Enum):
    PASS = "pass"
    FAIL = "fail"


class ApprovalStatus(str, enum.Enum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class Outcome(str, enum.Enum):
    """Terminal result of one governed tool invocation."""
    EXECUTED = "executed"
    BLOCKED = "blocked"
    PENDING_APPROVAL = "pending_approval"
    ERROR = "error"
