"""Provider-neutral LLM interface.

The orchestrator talks to this, never to the Anthropic SDK directly. That
is what makes the "configurable provider interface" requirement real rather
than decorative, and it is what lets the test suite run with no API key and
no network.

Content blocks are normalised to plain dicts in Anthropic's shape:

    {"type": "text", "text": "..."}
    {"type": "tool_use", "id": "...", "name": "...", "input": {...}}
"""
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class LLMResponse:
    stop_reason: str
    content: list[dict[str, Any]] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "".join(
            b.get("text", "") for b in self.content if b.get("type") == "text"
        ).strip()

    @property
    def tool_uses(self) -> list[dict[str, Any]]:
        return [b for b in self.content if b.get("type") == "tool_use"]


@runtime_checkable
class LLMProvider(Protocol):
    def create(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
    ) -> LLMResponse:
        ...
