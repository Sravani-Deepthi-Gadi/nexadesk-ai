"""The action-request state machine.

Deliberately contains no execution logic and imports nothing from the
engine, so that app/governance/engine.py can depend on it without a cycle.

Two ideas carry the security of this module:

1. **Canonical parameters and a hash.** Parameters are serialised with
   sorted keys and no incidental whitespace, then hashed together with the
   tool name. Two dicts that differ only in key order produce the same
   hash; two that differ in any value do not. An administrator approves a
   hash, and the executor re-derives it before running.

2. **Every transition is an atomic conditional UPDATE.** Never
   read-then-write. ``UPDATE ... WHERE id = ? AND status = ?`` either
   affects exactly one row or the transition was already made by someone
   else. That single ``rowcount`` check is what makes duplicate approval
   and duplicate execution impossible under concurrency.
"""
import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models import ActionRequest
from app.models.enums import ActionRequestStatus, RiskLevel


class ActionRequestConflict(Exception):
    """The request was not in the status this transition required.

    Raised on duplicate approval, duplicate execution, deciding on an
    already-rejected request, and similar races. Callers map this to 409.
    """


class ParamsTamperedError(Exception):
    """Stored parameters no longer match the hash recorded with them."""


def canonical_params(params: dict[str, Any]) -> str:
    return json.dumps(params, sort_keys=True, separators=(",", ":"), default=str)


def compute_params_hash(tool_name: str, params: dict[str, Any]) -> str:
    payload = f"{tool_name}:{canonical_params(params)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def verify_params_hash(request: ActionRequest) -> dict[str, Any]:
    """Re-derive the hash from what is stored and compare. Returns the params.

    Catches a params_json edited in the database after a human approved it.
    It does not catch an attacker who rewrites both columns -- see the
    README's limitations section, which says so plainly.
    """
    params = json.loads(request.params_json)
    expected = compute_params_hash(request.tool_name, params)
    if expected != request.params_hash:
        raise ParamsTamperedError(
            f"Parameters for action request {request.id} do not match their hash."
        )
    return params


def create_action_request(
    db: Session,
    *,
    agent_id: int,
    conversation_id: int | None,
    tool_name: str,
    params: dict[str, Any],
    risk_level: RiskLevel,
    tool_use_id: str | None = None,
) -> ActionRequest:
    request = ActionRequest(
        agent_id=agent_id,
        conversation_id=conversation_id,
        tool_use_id=tool_use_id,
        tool_name=tool_name,
        params_json=canonical_params(params),
        params_hash=compute_params_hash(tool_name, params),
        risk_level=risk_level,
        status=ActionRequestStatus.PENDING,
    )
    db.add(request)
    db.commit()
    db.refresh(request)
    return request


def _transition(
    db: Session,
    request_id: int,
    *,
    expected_from: ActionRequestStatus,
    to: ActionRequestStatus,
    **values: Any,
) -> ActionRequest:
    """Atomically move a request from one status to another.

    Raises ActionRequestConflict if the row was not in `expected_from`,
    which is exactly the duplicate-decision and duplicate-execution case.
    """
    stmt = (
        update(ActionRequest)
        .where(
            ActionRequest.id == request_id,
            ActionRequest.status == expected_from,
        )
        .values(status=to, **values)
        .execution_options(synchronize_session=False)
    )
    result = db.execute(stmt)
    db.commit()

    if result.rowcount != 1:
        db.expire_all()
        current = db.get(ActionRequest, request_id)
        if current is None:
            raise ActionRequestConflict(f"No action request with id {request_id}.")
        raise ActionRequestConflict(
            f"Action request {request_id} is '{current.status.value}', "
            f"not '{expected_from.value}'."
        )

    db.expire_all()
    return db.get(ActionRequest, request_id)


def mark_approved(
    db: Session, request_id: int, *, admin_user_id: int, note: str | None = None
) -> ActionRequest:
    return _transition(
        db, request_id,
        expected_from=ActionRequestStatus.PENDING,
        to=ActionRequestStatus.APPROVED,
        decided_at=datetime.now(timezone.utc),
        decided_by_admin_id=admin_user_id,
        decision_note=note,
    )


def mark_rejected(
    db: Session, request_id: int, *, admin_user_id: int, note: str | None = None
) -> ActionRequest:
    return _transition(
        db, request_id,
        expected_from=ActionRequestStatus.PENDING,
        to=ActionRequestStatus.REJECTED,
        decided_at=datetime.now(timezone.utc),
        decided_by_admin_id=admin_user_id,
        decision_note=note,
    )


def claim_for_execution(db: Session, request_id: int) -> ActionRequest:
    """APPROVED -> EXECUTING. Only one caller can ever win this."""
    return _transition(
        db, request_id,
        expected_from=ActionRequestStatus.APPROVED,
        to=ActionRequestStatus.EXECUTING,
    )


def mark_executed(db: Session, request_id: int, result: dict[str, Any]) -> ActionRequest:
    return _transition(
        db, request_id,
        expected_from=ActionRequestStatus.EXECUTING,
        to=ActionRequestStatus.EXECUTED,
        executed_at=datetime.now(timezone.utc),
        result_json=json.dumps(result, default=str),
    )


def mark_failed(db: Session, request_id: int, error: str) -> ActionRequest:
    return _transition(
        db, request_id,
        expected_from=ActionRequestStatus.EXECUTING,
        to=ActionRequestStatus.FAILED,
        executed_at=datetime.now(timezone.utc),
        error_message=error,
    )


def list_requests(
    db: Session,
    *,
    status: ActionRequestStatus | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[ActionRequest]:
    query = db.query(ActionRequest)
    if status is not None:
        query = query.filter(ActionRequest.status == status)
    return (
        query.order_by(ActionRequest.requested_at.desc())
        .offset(offset).limit(limit).all()
    )
