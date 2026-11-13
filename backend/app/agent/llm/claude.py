"""Anthropic Claude provider."""
from typing import Any

from app.agent.llm.base import LLMResponse


class ClaudeProvider:
    def __init__(self, api_key: str, model: str):
        if not api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY is not set. Put it in backend/.env. "
                "Note that a Claude.ai subscription is not API access -- you "
                "need prepaid credits at console.anthropic.com."
            )
        # Imported lazily so the package is only required when actually used.
        from anthropic import Anthropic

        self._client = Anthropic(api_key=api_key)
        self._model = model

    def create(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
    ) -> LLMResponse:
        resp = self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
            tools=tools,
        )
        content = [block.model_dump() for block in resp.content]
        return LLMResponse(stop_reason=resp.stop_reason or "end_turn", content=content)
