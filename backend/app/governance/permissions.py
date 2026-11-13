"""Permission checks. Reads from the database, never from the prompt."""
from sqlalchemy.orm import Session

from app.models import AgentPermission
from app.models.enums import Permission


def agent_has_permission(db: Session, agent_id: int, permission: Permission) -> bool:
    row = (
        db.query(AgentPermission)
        .filter(
            AgentPermission.agent_id == agent_id,
            AgentPermission.permission == permission,
        )
        .one_or_none()
    )
    return bool(row and row.granted)


def list_permissions(db: Session, agent_id: int) -> list[Permission]:
    rows = (
        db.query(AgentPermission)
        .filter(AgentPermission.agent_id == agent_id, AgentPermission.granted.is_(True))
        .all()
    )
    return [r.permission for r in rows]
