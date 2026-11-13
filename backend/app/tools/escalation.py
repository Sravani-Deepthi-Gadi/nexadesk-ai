"""escalate_to_human: hand the conversation to a person."""
from app.models import Escalation
from app.models.enums import ConversationState, EscalationStatus
from app.schemas.tool_params import EscalateToHumanParams
from app.tools.context import ToolContext


def escalate_to_human(ctx: ToolContext, params: EscalateToHumanParams) -> dict:
    convo = ctx.conversation

    escalation = Escalation(
        conversation_id=ctx.conversation_id,
        customer_id=ctx.current_customer_id(),
        created_by_agent_id=ctx.agent_id,
        reason=params.reason.strip(),
        summary=params.summary.strip(),
        status=EscalationStatus.OPEN,
    )
    ctx.db.add(escalation)

    if convo is not None:
        convo.state = ConversationState.ESCALATED

    ctx.db.flush()   # never commit: the engine owns the transaction

    return {
        "escalation_id": escalation.id,
        "status": escalation.status.value,
        "reason": escalation.reason,
        "note": (
            "A member of staff has been notified. Tell the customer someone "
            "will follow up, and do not promise a specific time."
        ),
    }
