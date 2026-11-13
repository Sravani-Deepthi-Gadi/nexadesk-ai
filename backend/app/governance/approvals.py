"""Approval service: the only path by which a withheld action can run.

Nothing in app/agent/ may import this module. That is enforced by
tests/test_import_boundary.py, and it is what makes "the LLM can never
approve its own high-risk actions" a structural fact rather than a promise
in a prompt.

Flow for an approval:

    1. verify the request is PENDING and the admin saw these exact params
    2. PENDING -> APPROVED            (atomic; duplicate approval loses)
    3. audit the decision             (APPROVAL_DECISION row)
    4. APPROVED -> EXECUTING          (atomic; duplicate execution loses)
    5. run it through the engine, which re-checks kill switch + permission
    6. EXECUTING -> EXECUTED | FAILED
    7. audit the execution            (EXECUTION row)
"""
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.governance.action_requests import (
    ActionRequestConflict, claim_for_execution, mark_approved, mark_executed,
    mark_failed, mark_rejected,
)
from app.governance.audit import write_audit
from app.governance.engine import GovernanceEngine, GovernanceResult
from app.models import ActionRequest, AdminUser
from app.models.enums import (
    ActionRequestStatus, ApprovalStatus, AuditEventType, ConversationState,
    Outcome,
)
from app.models.tables import Conversation


class ParamsHashMismatch(Exception):
    """The administrator approved a different version of this action."""


@dataclass
class ApprovalOutcome:
    request: ActionRequest
    execution: GovernanceResult | None = None


def _require_pending(request: ActionRequest) -> None:
    if request.status is not ActionRequestStatus.PENDING:
        raise ActionRequestConflict(
            f"Action request {request.id} is already "
            f"'{request.status.value}' and cannot be decided again."
        )


def _check_hash(request: ActionRequest, expected_params_hash: str | None) -> None:
    """Bind the decision to the parameters the administrator was shown.

    The client sends back the hash it displayed. If the stored row has
    changed in between, the hashes differ and the decision is refused
    rather than silently applied to different parameters.
    """
    if expected_params_hash is None:
        return
    if expected_params_hash != request.params_hash:
        raise ParamsHashMismatch(
            "The action's parameters have changed since they were shown to "
            "you. Review the request again."
        )


def _release_conversation(db: Session, conversation_id: int | None) -> None:
    if conversation_id is None:
        return
    convo = db.get(Conversation, conversation_id)
    if convo is not None and convo.state is ConversationState.AWAITING_APPROVAL:
        convo.state = ConversationState.ACTIVE
        db.commit()


def reject(
    db: Session,
    request: ActionRequest,
    *,
    admin: AdminUser,
    note: str | None = None,
    expected_params_hash: str | None = None,
) -> ApprovalOutcome:
    _require_pending(request)
    _check_hash(request, expected_params_hash)

    updated = mark_rejected(db, request.id, admin_user_id=admin.id, note=note)

    write_audit(
        db,
        agent_id=updated.agent_id,
        conversation_id=updated.conversation_id,
        tool_name=updated.tool_name,
        params=None,
        risk_level=updated.risk_level,
        permission_result=None,
        approval_status=ApprovalStatus.REJECTED,
        outcome=Outcome.REJECTED,
        error_message=note,
        event_type=AuditEventType.APPROVAL_DECISION,
        action_request_id=updated.id,
        admin_user_id=admin.id,
    )
    _release_conversation(db, updated.conversation_id)
    # No execution path exists from here. REJECTED is terminal.
    return ApprovalOutcome(request=updated, execution=None)


def approve_and_execute(
    db: Session,
    request: ActionRequest,
    *,
    admin: AdminUser,
    note: str | None = None,
    expected_params_hash: str | None = None,
) -> ApprovalOutcome:
    _require_pending(request)
    _check_hash(request, expected_params_hash)

    approved = mark_approved(db, request.id, admin_user_id=admin.id, note=note)

    write_audit(
        db,
        agent_id=approved.agent_id,
        conversation_id=approved.conversation_id,
        tool_name=approved.tool_name,
        params=None,
        risk_level=approved.risk_level,
        permission_result=None,
        approval_status=ApprovalStatus.APPROVED,
        outcome=Outcome.APPROVED,
        error_message=None,
        event_type=AuditEventType.APPROVAL_DECISION,
        action_request_id=approved.id,
        admin_user_id=admin.id,
    )

    execution = execute_approved(db, approved.id)
    _release_conversation(db, approved.conversation_id)
    db.expire_all()
    return ApprovalOutcome(request=db.get(ActionRequest, approved.id), execution=execution)


def execute_approved(db: Session, request_id: int) -> GovernanceResult:
    """Claim an APPROVED request and run it. Raises on a lost race.

    Separated from the approval decision so that a retry of a failed
    execution does not require a second human decision -- and so that the
    duplicate-execution guard can be tested on its own.
    """
    claimed = claim_for_execution(db, request_id)  # APPROVED -> EXECUTING

    engine = GovernanceEngine(
        db, agent_id=claimed.agent_id, conversation_id=claimed.conversation_id
    )
    result = engine.execute_approved(claimed)

    if result.outcome is Outcome.EXECUTED:
        mark_executed(db, claimed.id, result.data)
    else:
        mark_failed(db, claimed.id, result.message)

    return result
