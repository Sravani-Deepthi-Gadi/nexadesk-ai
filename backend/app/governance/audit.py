"""Audit logging. Append-only, enforced at the ORM layer."""
import json
from datetime import datetime, timezone

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.models import AuditLog
from app.models.enums import ApprovalStatus, Outcome, PermissionResult, RiskLevel


class AuditImmutabilityError(Exception):
    """Raised on any attempt to modify or delete an audit record."""


@event.listens_for(Session, "before_flush")
def _block_audit_mutation(session: Session, flush_context, instances) -> None:
    for obj in session.dirty:
        if isinstance(obj, AuditLog) and session.is_modified(obj):
            raise AuditImmutabilityError("audit_logs rows are append-only.")
    for obj in session.deleted:
        if isinstance(obj, AuditLog):
            raise AuditImmutabilityError("audit_logs rows cannot be deleted.")


def write_audit(
    db: Session,
    *,
    agent_id: int | None,
    conversation_id: int | None,
    tool_name: str,
    params: dict | None,
    risk_level: RiskLevel | None,
    permission_result: PermissionResult | None,
    approval_status: ApprovalStatus,
    outcome: Outcome,
    error_message: str | None = None,
) -> AuditLog:
    entry = AuditLog(
        ts=datetime.now(timezone.utc),
        agent_id=agent_id,
        conversation_id=conversation_id,
        tool_name=tool_name,
        params_json=json.dumps(params or {}, default=str),
        risk_level=risk_level,
        permission_result=permission_result,
        approval_status=approval_status,
        outcome=outcome,
        error_message=error_message,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry
