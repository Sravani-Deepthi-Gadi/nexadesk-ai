"""Builds the tool definitions that are sent to the model.

This module reads the neutral catalog. It has no access to any
implementation, so there is no code path from the agent package to a
database write that does not pass through the governance engine.
"""
from typing import Any

from app.schemas.tool_catalog import TOOL_CATALOG


def _input_schema(model) -> dict[str, Any]:
    schema = model.model_json_schema()
    schema.pop("title", None)
    for prop in schema.get("properties", {}).values():
        prop.pop("title", None)
    schema.setdefault("type", "object")
    return schema


def build_tool_schemas() -> list[dict[str, Any]]:
    return [
        {
            "name": defn.name,
            "description": defn.description,
            "input_schema": _input_schema(defn.params_model),
        }
        for defn in TOOL_CATALOG.values()
    ]
