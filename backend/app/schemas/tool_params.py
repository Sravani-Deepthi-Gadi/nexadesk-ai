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


# --- Milestone 3A -------------------------------------------------------
class SearchKnowledgeBaseParams(BaseModel):
    query: str = Field(
        min_length=2, max_length=500,
        description="What to look up in the business's uploaded documents.",
    )


class CheckAvailabilityParams(BaseModel):
    service_id: int = Field(description="ID of the service, from search_services.")
    date: str = Field(
        description="The date to check, as YYYY-MM-DD.",
        pattern=r"^\d{4}-\d{2}-\d{2}$",
    )


class BookAppointmentParams(BaseModel):
    service_id: int = Field(description="ID of the service to book.")
    starts_at: str = Field(
        description=(
            "Start time as an ISO 8601 timestamp, exactly as returned by "
            "check_availability."
        ),
        max_length=40,
    )
    customer_name: str = Field(min_length=1, max_length=120)
    customer_email: str = Field(min_length=3, max_length=255)


class GetCustomerDetailsParams(BaseModel):
    """Deliberately empty.

    The customer is resolved from the conversation, never from a parameter.
    If this model had a customer_id field, the agent could ask for anyone's
    record -- and a poisoned document could tell it to. See
    app/tools/context.py.
    """


class EscalateToHumanParams(BaseModel):
    reason: str = Field(
        min_length=3, max_length=255,
        description="Short reason this needs a person, e.g. 'billing dispute'.",
    )
    summary: str = Field(
        default="", max_length=2000,
        description="What the customer asked and what you were unable to resolve.",
    )
