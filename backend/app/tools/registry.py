"""Binds each catalog entry to the function that actually performs it.

IMPORTANT: importing this module gives you the ability to execute tools,
because it imports the real implementations. Only app/governance/engine.py
is allowed to import it -- enforced by tests/test_import_boundary.py.
"""
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.schemas.tool_catalog import TOOL_CATALOG, ToolDefinition
from app.tools.appointments import cancel_appointment
from app.tools.customers import get_customer_details
from app.tools.escalation import escalate_to_human
from app.tools.knowledge import search_knowledge_base
from app.tools.scheduling import book_appointment, check_availability
from app.tools.services import search_services

#: name -> implementation. Every catalog entry must appear here.
_IMPLEMENTATIONS: dict[str, Callable[..., dict[str, Any]]] = {
    "search_services": search_services,
    "search_knowledge_base": search_knowledge_base,
    "check_availability": check_availability,
    "book_appointment": book_appointment,
    "get_customer_details": get_customer_details,
    "escalate_to_human": escalate_to_human,
    "cancel_appointment": cancel_appointment,
}


@dataclass(frozen=True)
class ToolSpec:
    definition: ToolDefinition
    impl: Callable[..., dict[str, Any]]

    @property
    def name(self) -> str:
        return self.definition.name

    @property
    def params_model(self):
        return self.definition.params_model

    @property
    def required_permission(self):
        return self.definition.required_permission

    @property
    def risk_level(self):
        return self.definition.risk_level


def _build() -> dict[str, ToolSpec]:
    missing = set(TOOL_CATALOG) - set(_IMPLEMENTATIONS)
    if missing:
        raise RuntimeError(f"Catalog entries with no implementation: {sorted(missing)}")
    orphans = set(_IMPLEMENTATIONS) - set(TOOL_CATALOG)
    if orphans:
        raise RuntimeError(f"Implementations with no catalog entry: {sorted(orphans)}")
    return {
        name: ToolSpec(definition=defn, impl=_IMPLEMENTATIONS[name])
        for name, defn in TOOL_CATALOG.items()
    }


TOOL_REGISTRY: dict[str, ToolSpec] = _build()


def get_tool(name: str) -> ToolSpec | None:
    return TOOL_REGISTRY.get(name)
