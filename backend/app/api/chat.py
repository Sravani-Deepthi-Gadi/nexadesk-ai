"""Customer-facing chat endpoint."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agent.llm.base import LLMProvider
from app.agent.memory import new_session_token
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
