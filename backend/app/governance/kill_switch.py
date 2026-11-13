"""Emergency stop.

The switch is a column on the agents row, read fresh on every invocation.
It is not cached in the process, so flipping it takes effect on the very
next tool call without a restart.
"""
from sqlalchemy.orm import Session

from app.models import Agent
from app.models.enums import AgentStatus


def is_agent_enabled(db: Session, agent_id: int) -> bool:
    agent = db.get(Agent, agent_id)
    if agent is None:
        return False
    db.refresh(agent)
    return agent.status is AgentStatus.ACTIVE


def set_agent_status(db: Session, agent_id: int, status: AgentStatus) -> Agent:
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise ValueError(f"No agent with id {agent_id}")
    agent.status = status
    db.commit()
    db.refresh(agent)
    return agent
