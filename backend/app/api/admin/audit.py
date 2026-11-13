"""Read-only audit log access for the dashboard."""
import json

from app.api.serialization import iso_utc
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin
from app.db.session import get_db
from app.models import AdminUser, AuditLog
from app.models.enums import AuditEventType, Outcome

router = APIRouter(prefix="/api/admin/audit", tags=["admin:audit"])


class AuditLogOut(BaseModel):
    id: int
    ts: str
    event_type: str
    agent_id: int | None
    admin_user_id: int | None
    conversation_id: int | None
    action_request_id: int | None
    tool_name: str
    params: dict
    risk_level: str | None
    permission_result: str | None
    approval_status: str
    outcome: str
    error_message: str | None


@router.get("", response_model=list[AuditLogOut])
def list_audit_logs(
    event_type: AuditEventType | None = Query(default=None),
    outcome: Outcome | None = Query(default=None),
    action_request_id: int | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> list[AuditLogOut]:
    query = db.query(AuditLog)
    if event_type is not None:
        query = query.filter(AuditLog.event_type == event_type)
    if outcome is not None:
        query = query.filter(AuditLog.outcome == outcome)
    if action_request_id is not None:
        query = query.filter(AuditLog.action_request_id == action_request_id)

    rows = query.order_by(AuditLog.id.desc()).offset(offset).limit(limit).all()
    return [
        AuditLogOut(
            id=r.id,
            ts=iso_utc(r.ts),
            event_type=r.event_type.value,
            agent_id=r.agent_id,
            admin_user_id=r.admin_user_id,
            conversation_id=r.conversation_id,
            action_request_id=r.action_request_id,
            tool_name=r.tool_name,
            params=json.loads(r.params_json or "{}"),
            risk_level=r.risk_level.value if r.risk_level else None,
            permission_result=(
                r.permission_result.value if r.permission_result else None
            ),
            approval_status=r.approval_status.value,
            outcome=r.outcome.value,
            error_message=r.error_message,
        )
        for r in rows
    ]
