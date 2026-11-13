"""The agent loop.

Roughly eighty lines, written by hand rather than delegated to a framework,
because this loop is the thing the project is being judged on.

The step that matters is the one in the middle: a tool_use block coming
back from the model is treated as DATA -- a request -- and handed to the
governance engine. The orchestrator has no import path to any tool
implementation, so it could not execute one if it tried.
"""
import json
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.agent.llm.base import LLMProvider
from app.agent.memory import (
    append_message, get_or_create_conversation, load_api_messages,
)
from app.agent.prompts import SYSTEM_PROMPT
from app.agent.tool_schemas import build_tool_schemas
from app.governance.engine import GovernanceEngine
from app.models.enums import ConversationState, MessageRole, Outcome


@dataclass
class AgentTurn:
    reply: str
    session_token: str
    conversation_id: int
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


class AgentOrchestrator:
    def __init__(
        self,
        db: Session,
        llm: LLMProvider,
        agent_id: int,
        max_iterations: int = 5,
        max_tokens: int = 1024,
    ):
        self.db = db
        self.llm = llm
        self.agent_id = agent_id
        self.max_iterations = max_iterations
        self.max_tokens = max_tokens
        self.tools = build_tool_schemas()

    def handle_message(self, session_token: str, user_text: str) -> AgentTurn:
        convo = get_or_create_conversation(self.db, session_token)
        governance = GovernanceEngine(
            self.db, agent_id=self.agent_id, conversation_id=convo.id
        )

        append_message(
            self.db, convo, MessageRole.USER,
            [{"type": "text", "text": user_text}],
        )

        tool_calls: list[dict[str, Any]] = []

        for _ in range(self.max_iterations):
            messages = load_api_messages(self.db, convo.id)
            response = self.llm.create(
                system=SYSTEM_PROMPT,
                messages=messages,
                tools=self.tools,
                max_tokens=self.max_tokens,
            )

            append_message(self.db, convo, MessageRole.ASSISTANT, response.content)

            if response.stop_reason != "tool_use" or not response.tool_uses:
                return AgentTurn(
                    reply=response.text or "",
                    session_token=session_token,
                    conversation_id=convo.id,
                    tool_calls=tool_calls,
                )

            # --- Every proposed call goes through governance. ------------
            result_blocks: list[dict[str, Any]] = []
            for block in response.tool_uses:
                name = block.get("name", "")
                raw_input = block.get("input") or {}
                outcome = governance.execute(
                    name, raw_input, tool_use_id=block.get("id")
                )

                # A withheld action parks the conversation until a human
                # rules on it. The approval service releases it again.
                if outcome.outcome is Outcome.PENDING_APPROVAL:
                    convo.state = ConversationState.AWAITING_APPROVAL
                    self.db.commit()

                tool_calls.append({
                    "tool": name,
                    "outcome": outcome.outcome.value,
                    "risk_level": outcome.risk_level.value if outcome.risk_level else None,
                    "audit_log_id": outcome.audit_log_id,
                    "action_request_id": outcome.action_request_id,
                })

                result_blocks.append({
                    "type": "tool_result",
                    "tool_use_id": block.get("id"),
                    "content": json.dumps(outcome.to_tool_result(), default=str),
                    "is_error": outcome.outcome
                    in (Outcome.ERROR, Outcome.BLOCKED),
                })

            append_message(self.db, convo, MessageRole.TOOL, result_blocks)

        # Loop budget exhausted: stop rather than spin.
        return AgentTurn(
            reply=(
                "I'm having trouble completing that. Let me pass you to a "
                "member of staff."
            ),
            session_token=session_token,
            conversation_id=convo.id,
            tool_calls=tool_calls,
        )
