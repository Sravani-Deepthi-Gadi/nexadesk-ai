"""Agent controls: emergency stop and permission management.

These are themselves high-privilege operations, so each one writes an
audit row naming the administrator who did it. An agent-governance product
whose own controls were unaudited would be a strange thing to ship:
"who disabled the agent" and "who granted CANCEL_APPOINTMENT" have to be
answerable from the trail.
"""
from app.api.serialization import iso_utc
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin, require_admin
from app.config import get_settings
from app.db.session import get_db
from app.governance.audit import write_audit
from app.governance.kill_switch import set_agent_status
from app.models import AdminUser, Agent, AgentPermission
from app.models.enums import (
    AgentStatus, ApprovalStatus, AuditEventType, Outcome, Permission,
)

router = APIRouter(prefix="/api/admin/agent", tags=["admin:agent"])


class PermissionOut(BaseModel):
    permission: str
    granted: bool
    description: str


class AgentOut(BaseModel):
    id: int
    name: str
    status: str
    created_at: str
    permissions: list[PermissionOut]


class StatusRequest(BaseModel):
    status: AgentStatus
    reason: str | None = None


class PermissionRequest(BaseModel):
    permission: Permission
    granted: bool


PERMISSION_DESCRIPTIONS = {
    Permission.READ_BUSINESS_DATA: "Read services and uploaded documents",
    Permission.READ_CUSTOMER_DATA: "Read the customer in the current conversation",
    Permission.CHECK_AVAILABILITY: "Check free appointment slots",
    Permission.CREATE_APPOINTMENT: "Create appointments",
    Permission.CANCEL_APPOINTMENT: "Cancel appointments (requires approval)",
    Permission.MODIFY_CUSTOMER_DATA: "Modify customer records",
    Permission.ESCALATE_TO_HUMAN: "Open a ticket for staff",
}


def _current_agent(db: Session) -> Agent:
    settings = get_settings()
    agent = (
        db.query(Agent).filter(Agent.name == settings.default_agent_name).one_or_none()
    )
    if agent is None:
        agent = db.query(Agent).first()
    if agent is None:
        raise HTTPException(status_code=404, detail="No agent is configured.")
    return agent


def _to_out(db: Session, agent: Agent) -> AgentOut:
    granted = {
        row.permission: row.granted
        for row in db.query(AgentPermission).filter(
            AgentPermission.agent_id == agent.id
        ).all()
    }
    return AgentOut(
        id=agent.id, name=agent.name, status=agent.status.value,
        created_at=iso_utc(agent.created_at),
        permissions=[
            PermissionOut(
                permission=perm.value,
                granted=bool(granted.get(perm, False)),
                description=PERMISSION_DESCRIPTIONS[perm],
            )
            for perm in Permission
        ],
    )


def _audit_control(
    db: Session, agent: Agent, admin: AdminUser, action: str, detail: str
) -> None:
    write_audit(
        db,
        agent_id=agent.id, conversation_id=None,
        tool_name=action, params=None, risk_level=None,
        permission_result=None, approval_status=ApprovalStatus.NOT_REQUIRED,
        outcome=Outcome.EXECUTED, error_message=detail,
        event_type=AuditEventType.APPROVAL_DECISION,
        admin_user_id=admin.id,
    )


@router.get("", response_model=AgentOut)
def get_agent(
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> AgentOut:
    return _to_out(db, _current_agent(db))


@router.post("/status", response_model=AgentOut)
def change_status(
    payload: StatusRequest,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_admin),
) -> AgentOut:
    """Emergency stop, and re-enable. ADMIN only."""
    agent = _current_agent(db)
    set_agent_status(db, agent.id, payload.status)

    verb = "disabled" if payload.status is AgentStatus.DISABLED else "enabled"
    _audit_control(
        db, agent, admin, "agent_status_change",
        f"Agent {verb} by {admin.email}."
        + (f" Reason: {payload.reason}" if payload.reason else ""),
    )
    db.refresh(agent)
    return _to_out(db, agent)


@router.put("/permissions", response_model=AgentOut)
def change_permission(
    payload: PermissionRequest,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_admin),
) -> AgentOut:
    """Grant or revoke one permission. ADMIN only."""
    agent = _current_agent(db)
    row = (
        db.query(AgentPermission)
        .filter(
            AgentPermission.agent_id == agent.id,
            AgentPermission.permission == payload.permission,
        ).one_or_none()
    )
    if row is None:
        row = AgentPermission(
            agent_id=agent.id, permission=payload.permission, granted=payload.granted
        )
        db.add(row)
    else:
        row.granted = payload.granted
    db.commit()

    _audit_control(
        db, agent, admin, "agent_permission_change",
        f"{'Granted' if payload.granted else 'Revoked'} "
        f"{payload.permission.value} by {admin.email}.",
    )
    return _to_out(db, agent)
