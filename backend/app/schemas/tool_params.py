"""Pydantic parameter models for every agent tool.

This module is deliberately *neutral*: pure data shapes, no database access,
no imports from app.tools. Both sides of the import boundary may depend on it.

  app/agent/     -> imports this (to build the JSON schemas Claude sees)
  app/governance -> imports this (to validate what Claude sent back)
  app/tools/     -> imports this (to type its implementations)

The agent never imports app.tools, so it has no way to call an
implementation directly. See tests/test_import_boundary.py.
"""
from pydantic import BaseModel, Field


class SearchServicesParams(BaseModel):
    query: str | None = Field(
        default=None,
        description="Optional keyword to filter services by name or description.",
    )


class CancelAppointmentParams(BaseModel):
    appointment_id: int = Field(description="ID of the appointment to cancel.")
    reason: str = Field(
        default="",
        description="Reason the customer gave for cancelling.",
    )
