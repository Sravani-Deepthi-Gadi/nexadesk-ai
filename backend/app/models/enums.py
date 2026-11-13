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
    """Result recorded on one audit row."""
    EXECUTED = "executed"
    BLOCKED = "blocked"
    PENDING_APPROVAL = "pending_approval"
    ERROR = "error"
    # Decision outcomes, recorded on APPROVAL_DECISION rows.
    APPROVED = "approved"
    REJECTED = "rejected"


class AuditEventType(str, enum.Enum):
    """What kind of event an audit row records.

    A HIGH-risk action produces three rows over its lifetime:
    TOOL_INVOCATION (agent proposed it), APPROVAL_DECISION (a human ruled
    on it), EXECUTION (what actually happened). Keeping them distinct means
    the trail reads as a story rather than a pile of ambiguous rows.
    """
    TOOL_INVOCATION = "tool_invocation"
    APPROVAL_DECISION = "approval_decision"
    EXECUTION = "execution"


class ActionRequestStatus(str, enum.Enum):
    """Lifecycle of a withheld action.

    PENDING -> APPROVED -> EXECUTING -> EXECUTED | FAILED
    PENDING -> REJECTED  (terminal: can never execute)

    EXECUTING exists solely so that the APPROVED -> EXECUTING transition can
    be an atomic conditional UPDATE. Without that intermediate state, two
    concurrent execute calls could both read APPROVED and both run.
    """
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTING = "executing"
    EXECUTED = "executed"
    FAILED = "failed"


class AdminRole(str, enum.Enum):
    ADMIN = "admin"      # may approve and reject
    VIEWER = "viewer"    # read-only
