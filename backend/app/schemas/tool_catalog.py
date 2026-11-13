"""The tool CATALOG: names, descriptions, parameter models, required
permission and risk level.

Neutral by construction -- it contains no implementations and imports
nothing that touches the database. This is what the agent package reads in
order to tell Claude which tools exist. Knowing a tool's name is not the
same as being able to run it.

The binding from catalog entry to executable function lives in
app/tools/registry.py, which only the governance engine may import.
"""
from dataclasses import dataclass

from pydantic import BaseModel

from app.models.enums import Permission, RiskLevel
from app.schemas.tool_params import CancelAppointmentParams, SearchServicesParams


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    params_model: type[BaseModel]
    required_permission: Permission
    risk_level: RiskLevel


TOOL_CATALOG: dict[str, ToolDefinition] = {
    "search_services": ToolDefinition(
        name="search_services",
        description=(
            "List the services NexaCare offers, with duration and price. "
            "Use this whenever the customer asks what the business does, "
            "what it costs, or how long something takes. Do not answer "
            "questions about services or pricing from your own knowledge."
        ),
        params_model=SearchServicesParams,
        required_permission=Permission.READ_BUSINESS_DATA,
        risk_level=RiskLevel.LOW,
    ),
    "cancel_appointment": ToolDefinition(
        name="cancel_appointment",
        description=(
            "Cancel an existing appointment. Only call this after the "
            "customer has explicitly confirmed they want to cancel and has "
            "given you the appointment ID."
        ),
        params_model=CancelAppointmentParams,
        required_permission=Permission.CANCEL_APPOINTMENT,
        risk_level=RiskLevel.HIGH,
    ),
}
