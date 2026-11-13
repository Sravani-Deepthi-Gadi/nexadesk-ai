"""Admin approval queue: list, inspect, approve, reject.

Listing is open to any authenticated admin user (ADMIN or VIEWER).
Deciding requires the ADMIN role.
"""
import json

from app.api.serialization import iso_utc
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin, require_admin
from app.db.session import get_db
from app.governance import approvals as approval_service
from app.governance.action_requests import ActionRequestConflict, list_requests
from app.models import ActionRequest, AdminUser
from app.models.enums import ActionRequestStatus

router = APIRouter(prefix="/api/admin/approvals", tags=["admin:approvals"])


class ActionRequestOut(BaseModel):
    id: int
    agent_id: int
    conversation_id: int | None
    tool_name: str
    params: dict
    #: Echo this back on approve/reject to bind the decision to these params.
    params_hash: str
    risk_level: str
    status: str
    requested_at: str
    decided_at: str | None = None
    decided_by_admin_id: int | None = None
    decision_note: str | None = None
    executed_at: str | None = None
    result: dict | None = None
    error_message: str | None = None

    @classmethod
    def from_row(cls, row: ActionRequest) -> "ActionRequestOut":
        return cls(
            id=row.id,
            agent_id=row.agent_id,
            conversation_id=row.conversation_id,
            tool_name=row.tool_name,
            params=json.loads(row.params_json),
            params_hash=row.params_hash,
            risk_level=row.risk_level.value,
            status=row.status.value,
            requested_at=iso_utc(row.requested_at),
            decided_at=iso_utc(row.decided_at),
            decided_by_admin_id=row.decided_by_admin_id,
            decision_note=row.decision_note,
            executed_at=iso_utc(row.executed_at),
            result=json.loads(row.result_json) if row.result_json else None,
            error_message=row.error_message,
        )


class DecisionRequest(BaseModel):
    #: The hash shown alongside the parameters you reviewed. Required, so a
    #: decision cannot be applied to parameters that changed in between.
    params_hash: str = Field(min_length=64, max_length=64)
    note: str | None = Field(default=None, max_length=1000)


class DecisionResponse(BaseModel):
    request: ActionRequestOut
    execution_outcome: str | None = None
    execution_message: str | None = None


def _get_request_or_404(db: Session, request_id: int) -> ActionRequest:
    row = db.get(ActionRequest, request_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Action request not found.")
    return row


@router.get("", response_model=list[ActionRequestOut])
def list_action_requests(
    request_status: ActionRequestStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> list[ActionRequestOut]:
    rows = list_requests(db, status=request_status, limit=limit, offset=offset)
    return [ActionRequestOut.from_row(r) for r in rows]


@router.get("/pending", response_model=list[ActionRequestOut])
def list_pending(
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> list[ActionRequestOut]:
    rows = list_requests(db, status=ActionRequestStatus.PENDING, limit=limit)
    return [ActionRequestOut.from_row(r) for r in rows]


@router.get("/{request_id}", response_model=ActionRequestOut)
def get_action_request(
    request_id: int,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> ActionRequestOut:
    return ActionRequestOut.from_row(_get_request_or_404(db, request_id))


@router.post("/{request_id}/approve", response_model=DecisionResponse)
def approve(
    request_id: int,
    payload: DecisionRequest,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_admin),
) -> DecisionResponse:
    row = _get_request_or_404(db, request_id)
    try:
        outcome = approval_service.approve_and_execute(
            db, row, admin=admin, note=payload.note,
            expected_params_hash=payload.params_hash,
        )
    except approval_service.ParamsHashMismatch as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from None
    except ActionRequestConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from None

    return DecisionResponse(
        request=ActionRequestOut.from_row(outcome.request),
        execution_outcome=outcome.execution.outcome.value if outcome.execution else None,
        execution_message=outcome.execution.message if outcome.execution else None,
    )


@router.post("/{request_id}/reject", response_model=DecisionResponse)
def reject(
    request_id: int,
    payload: DecisionRequest,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_admin),
) -> DecisionResponse:
    row = _get_request_or_404(db, request_id)
    try:
        outcome = approval_service.reject(
            db, row, admin=admin, note=payload.note,
            expected_params_hash=payload.params_hash,
        )
    except approval_service.ParamsHashMismatch as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from None
    except ActionRequestConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from None

    return DecisionResponse(request=ActionRequestOut.from_row(outcome.request))
