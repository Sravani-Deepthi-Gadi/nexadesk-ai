"""Execution context handed to every tool implementation.

WHY THIS EXISTS: customer data isolation.

If `get_customer_details` took a `customer_id` parameter, the agent could
ask for any customer in the database -- and a poisoned document could tell
it to. Instead, tools receive the conversation they are running inside, and
customer-scoped tools resolve the customer FROM that conversation.

The agent cannot express a request for someone else's data, so no prompt
can talk it into one. Isolation becomes structural rather than a rule the
model is asked to follow.
"""
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import Conversation


@dataclass
class ToolContext:
    db: Session
    agent_id: int
    conversation_id: int | None = None

    @property
    def conversation(self) -> Conversation | None:
        if self.conversation_id is None:
            return None
        return self.db.get(Conversation, self.conversation_id)

    def current_customer_id(self) -> int | None:
        """The only customer a tool in this conversation may read."""
        convo = self.conversation
        return convo.customer_id if convo is not None else None

    @property
    def rag(self):
        from app.rag.service import get_rag

        return get_rag()
