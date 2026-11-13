"""Conversation memory.

History is stored per conversation and keyed by an opaque session token, so
one customer's session can never read another's. Assistant turns are stored
as raw content blocks so a tool_use turn can be replayed to the API
verbatim on the next request -- without that, the model loses the thread of
its own tool calls.
"""
import json
import secrets
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models import Conversation, Message
from app.models.enums import MessageRole


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def get_or_create_conversation(db: Session, session_token: str) -> Conversation:
    convo = (
        db.query(Conversation)
        .filter(Conversation.session_token == session_token)
        .one_or_none()
    )
    if convo is None:
        convo = Conversation(session_token=session_token)
        db.add(convo)
        db.commit()
        db.refresh(convo)
    return convo


def _next_seq(db: Session, conversation_id: int) -> int:
    last = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.seq.desc())
        .first()
    )
    return (last.seq + 1) if last else 1


def append_message(
    db: Session,
    conversation: Conversation,
    role: MessageRole,
    blocks: list[dict[str, Any]],
) -> Message:
    text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
    msg = Message(
        conversation_id=conversation.id,
        seq=_next_seq(db, conversation.id),
        role=role,
        content=text,
        blocks_json=json.dumps(blocks, default=str),
    )
    conversation.last_active_at = datetime.now(timezone.utc)
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


def load_api_messages(
    db: Session, conversation_id: int, max_messages: int = 40
) -> list[dict[str, Any]]:
    """Rebuild the messages array for the API, newest `max_messages` kept.

    Trimming by message count is the simple version. A production system
    would trim by token budget; the shape of the fix is the same.
    """
    rows = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.seq)
        .all()
    )
    rows = rows[-max_messages:]
    out: list[dict[str, Any]] = []
    for row in rows:
        blocks = json.loads(row.blocks_json) if row.blocks_json else [
            {"type": "text", "text": row.content}
        ]
        # tool_result blocks are sent back under the "user" role.
        api_role = "assistant" if row.role is MessageRole.ASSISTANT else "user"
        out.append({"role": api_role, "content": blocks})
    return out
