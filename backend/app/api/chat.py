"""Customer-facing chat endpoint."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import json

from fastapi import HTTPException, Query

from app.agent.llm.base import LLMProvider
from app.agent.memory import new_session_token
from app.models import ActionRequest, Conversation
from app.agent.orchestrator import AgentOrchestrator
from app.api.deps import get_default_agent, get_llm
from app.config import get_settings
from app.db.session import get_db

router = APIRouter(prefix="/api", tags=["chat"])


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_token: str | None = None


class ToolCallInfo(BaseModel):
    tool: str
    outcome: str
    risk_level: str | None = None
    audit_log_id: int | None = None
    action_request_id: int | None = None


class ChatResponse(BaseModel):
    reply: str
    session_token: str
    conversation_id: int
    tool_calls: list[ToolCallInfo]


@router.post("/chat", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    db: Session = Depends(get_db),
    llm: LLMProvider = Depends(get_llm),
) -> ChatResponse:
    settings = get_settings()
    # A missing token starts a new session. The token is opaque and
    # unguessable, which is what isolates one customer's history from another's.
    session_token = payload.session_token or new_session_token()

    agent = get_default_agent(db)
    orchestrator = AgentOrchestrator(
        db=db,
        llm=llm,
        agent_id=agent.id,
        max_iterations=settings.max_tool_iterations,
        max_tokens=settings.llm_max_tokens,
    )
    turn = orchestrator.handle_message(session_token, payload.message)
    return ChatResponse(
        reply=turn.reply,
        session_token=turn.session_token,
        conversation_id=turn.conversation_id,
        tool_calls=[ToolCallInfo(**tc) for tc in turn.tool_calls],
    )


# --------------------------------------------------------------------------
# Conversation status: how a customer learns an approval was decided
# --------------------------------------------------------------------------
class ActionStatusOut(BaseModel):
    action_request_id: int
    tool_name: str
    status: str
    risk_level: str
    requested_at: str
    decided_at: str | None = None
    executed_at: str | None = None
    #: Customer-facing wording. Never the admin's internal decision note.
    message: str


class ConversationStatusOut(BaseModel):
    session_token: str
    conversation_id: int
    state: str
    pending_actions: list[ActionStatusOut]
    resolved_actions: list[ActionStatusOut]


_CUSTOMER_WORDING = {
    "pending": "Waiting for a member of staff to review this.",
    "approved": "Approved by staff and being carried out.",
    "executing": "Approved by staff and being carried out.",
    "executed": "Done -- this has been completed.",
    "rejected": "Staff reviewed this and did not approve it.",
    "failed": "This could not be completed. A member of staff will follow up.",
}


def _to_status(row: ActionRequest) -> ActionStatusOut:
    return ActionStatusOut(
        action_request_id=row.id,
        tool_name=row.tool_name,
        status=row.status.value,
        risk_level=row.risk_level.value,
        requested_at=row.requested_at.isoformat(),
        decided_at=row.decided_at.isoformat() if row.decided_at else None,
        executed_at=row.executed_at.isoformat() if row.executed_at else None,
        message=_CUSTOMER_WORDING.get(row.status.value, "In progress."),
    )


@router.get("/chat/status", response_model=ConversationStatusOut)
def conversation_status(
    session_token: str = Query(min_length=10, max_length=128),
    db: Session = Depends(get_db),
) -> ConversationStatusOut:
    """Let a customer poll for the outcome of a withheld action.

    Scoped by session token ALONE. There is no conversation_id parameter,
    so one customer cannot read another's approvals by guessing an id --
    the same isolation principle as get_customer_details.

    The decision note an administrator wrote is deliberately NOT returned;
    internal review comments are not customer-facing.
    """
    convo = (
        db.query(Conversation)
        .filter(Conversation.session_token == session_token)
        .one_or_none()
    )
    if convo is None:
        raise HTTPException(status_code=404, detail="Unknown session.")

    rows = (
        db.query(ActionRequest)
        .filter(ActionRequest.conversation_id == convo.id)
        .order_by(ActionRequest.requested_at.desc())
        .all()
    )
    pending = [r for r in rows if r.status.value in ("pending", "approved", "executing")]
    resolved = [r for r in rows if r.status.value in ("executed", "rejected", "failed")]

    return ConversationStatusOut(
        session_token=session_token,
        conversation_id=convo.id,
        state=convo.state.value,
        pending_actions=[_to_status(r) for r in pending],
        resolved_actions=[_to_status(r) for r in resolved],
    )
