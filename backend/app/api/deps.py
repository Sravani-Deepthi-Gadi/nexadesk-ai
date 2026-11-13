"""Shared FastAPI dependencies."""
from functools import lru_cache

from sqlalchemy.orm import Session

from app.agent.llm.base import LLMProvider
from app.agent.llm.claude import ClaudeProvider
from app.config import get_settings
from app.db.seed import seed
from app.models import Agent


@lru_cache
def get_llm() -> LLMProvider:
    settings = get_settings()
    if settings.llm_provider == "claude":
        return ClaudeProvider(
            api_key=settings.anthropic_api_key, model=settings.llm_model
        )
    raise ValueError(f"Unknown LLM provider: {settings.llm_provider}")


def get_default_agent(db: Session) -> Agent:
    settings = get_settings()
    agent = (
        db.query(Agent).filter(Agent.name == settings.default_agent_name).one_or_none()
    )
    if agent is None:
        agent = seed(db, agent_name=settings.default_agent_name)
    return agent
