"""Dashboard metrics and conversation transcripts."""
import json
from datetime import datetime, timedelta, timezone

from app.api.serialization import iso_utc
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin
from app.config import get_settings
from app.db.session import get_db
from app.models import (
    ActionRequest, AdminUser, Agent, AuditLog, Conversation, Document,
    Escalation, Message,
)
from app.models.enums import (
    ActionRequestStatus, AuditEventType, DocumentStatus, EscalationStatus,
    Outcome, RiskLevel,
)

router = APIRouter(prefix="/api/admin", tags=["admin:metrics"])


class RiskSlice(BaseModel):
    risk_level: str
    count: int


class ActivityItem(BaseModel):
    id: int
    ts: str
    event_type: str
    tool_name: str
    outcome: str
    risk_level: str | None
    admin_user_id: int | None
    action_request_id: int | None


class OverviewOut(BaseModel):
    total_conversations: int
    total_tool_calls: int
    successful_actions: int
    blocked_actions: int
    pending_approvals: int
    open_escalations: int
    indexed_documents: int
    agent_status: str
    agent_name: str
    risk_distribution: list[RiskSlice]
    recent_activity: list[ActivityItem]
    tool_calls_last_7_days: list[dict]


@router.get("/metrics/overview", response_model=OverviewOut)
def overview(
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> OverviewOut:
    settings = get_settings()
    agent = (
        db.query(Agent).filter(Agent.name == settings.default_agent_name).one_or_none()
        or db.query(Agent).first()
    )

    invocations = db.query(AuditLog).filter(
        AuditLog.event_type == AuditEventType.TOOL_INVOCATION
    )

    risk_counts = (
        db.query(AuditLog.risk_level, func.count(AuditLog.id))
        .filter(
            AuditLog.event_type == AuditEventType.TOOL_INVOCATION,
            AuditLog.risk_level.isnot(None),
        )
        .group_by(AuditLog.risk_level).all()
    )
    by_risk = {r.value: 0 for r in RiskLevel}
    for level, count in risk_counts:
        if level is not None:
            by_risk[level.value] = count

    # Seven-day series, zero-filled so the chart has no gaps.
    today = datetime.now(timezone.utc).date()
    series = []
    for offset in range(6, -1, -1):
        day = today - timedelta(days=offset)
        start = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
        count = (
            db.query(func.count(AuditLog.id))
            .filter(
                AuditLog.event_type == AuditEventType.TOOL_INVOCATION,
                AuditLog.ts >= start,
                AuditLog.ts < start + timedelta(days=1),
            ).scalar() or 0
        )
        series.append({"date": day.isoformat(), "calls": count})

    recent = (
        db.query(AuditLog).order_by(AuditLog.id.desc()).limit(10).all()
    )

    return OverviewOut(
        total_conversations=db.query(func.count(Conversation.id)).scalar() or 0,
        total_tool_calls=invocations.count(),
        successful_actions=db.query(AuditLog).filter(
            AuditLog.outcome == Outcome.EXECUTED
        ).count(),
        blocked_actions=db.query(AuditLog).filter(
            AuditLog.outcome == Outcome.BLOCKED
        ).count(),
        pending_approvals=db.query(ActionRequest).filter(
            ActionRequest.status == ActionRequestStatus.PENDING
        ).count(),
        open_escalations=db.query(Escalation).filter(
            Escalation.status == EscalationStatus.OPEN
        ).count(),
        indexed_documents=db.query(Document).filter(
            Document.status == DocumentStatus.INDEXED
        ).count(),
        agent_status=agent.status.value if agent else "unknown",
        agent_name=agent.name if agent else "none",
        risk_distribution=[
            RiskSlice(risk_level=k, count=v) for k, v in by_risk.items()
        ],
        recent_activity=[
            ActivityItem(
                id=r.id, ts=iso_utc(r.ts), event_type=r.event_type.value,
                tool_name=r.tool_name, outcome=r.outcome.value,
                risk_level=r.risk_level.value if r.risk_level else None,
                admin_user_id=r.admin_user_id,
                action_request_id=r.action_request_id,
            )
            for r in recent
        ],
        tool_calls_last_7_days=series,
    )


# --------------------------------------------------------------------------
# Conversations
# --------------------------------------------------------------------------
class ConversationSummary(BaseModel):
    id: int
    state: str
    customer_id: int | None
    started_at: str
    last_active_at: str
    message_count: int
    pending_actions: int


class MessageOut(BaseModel):
    seq: int
    role: str
    content: str
    tool_calls: list[str]
    created_at: str


class ConversationDetail(ConversationSummary):
    messages: list[MessageOut]


def _summarise(db: Session, convo: Conversation) -> ConversationSummary:
    return ConversationSummary(
        id=convo.id, state=convo.state.value, customer_id=convo.customer_id,
        started_at=iso_utc(convo.started_at),
        last_active_at=iso_utc(convo.last_active_at),
        message_count=db.query(func.count(Message.id)).filter(
            Message.conversation_id == convo.id
        ).scalar() or 0,
        pending_actions=db.query(func.count(ActionRequest.id)).filter(
            ActionRequest.conversation_id == convo.id,
            ActionRequest.status == ActionRequestStatus.PENDING,
        ).scalar() or 0,
    )


@router.get("/conversations", response_model=list[ConversationSummary])
def list_conversations(
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> list[ConversationSummary]:
    rows = (
        db.query(Conversation)
        .order_by(Conversation.last_active_at.desc())
        .limit(limit).all()
    )
    return [_summarise(db, c) for c in rows]


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
def get_conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> ConversationDetail:
    """Full transcript.

    The session_token is deliberately NOT returned: it is a bearer
    credential for that conversation, and an admin reading a transcript has
    no need to be able to impersonate the customer.
    """
    convo = db.get(Conversation, conversation_id)
    if convo is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")

    messages = []
    for row in sorted(convo.messages, key=lambda m: m.seq):
        tool_names: list[str] = []
        if row.blocks_json:
            try:
                for block in json.loads(row.blocks_json):
                    if block.get("type") == "tool_use":
                        tool_names.append(block.get("name", "?"))
                    elif block.get("type") == "tool_result":
                        tool_names.append("result")
            except (ValueError, TypeError):
                pass
        messages.append(MessageOut(
            seq=row.seq, role=row.role.value, content=row.content,
            tool_calls=tool_names, created_at=iso_utc(row.created_at),
        ))

    base = _summarise(db, convo)
    return ConversationDetail(**base.model_dump(), messages=messages)


# --------------------------------------------------------------------------
# Escalations
# --------------------------------------------------------------------------
class EscalationOut(BaseModel):
    id: int
    conversation_id: int | None
    customer_id: int | None
    reason: str
    summary: str
    status: str
    created_at: str


@router.get("/escalations", response_model=list[EscalationOut])
def list_escalations(
    escalation_status: EscalationStatus | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> list[EscalationOut]:
    query = db.query(Escalation)
    if escalation_status is not None:
        query = query.filter(Escalation.status == escalation_status)
    return [
        EscalationOut(
            id=r.id, conversation_id=r.conversation_id, customer_id=r.customer_id,
            reason=r.reason, summary=r.summary, status=r.status.value,
            created_at=iso_utc(r.created_at),
        )
        for r in query.order_by(Escalation.created_at.desc()).limit(100).all()
    ]
