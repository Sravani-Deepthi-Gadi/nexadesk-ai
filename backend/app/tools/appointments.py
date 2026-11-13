"""Implementation of cancel_appointment. Touches the database.

This is a real state change, not a stub. The governance tests assert that
it is NOT reached when the agent lacks CANCEL_APPOINTMENT, by checking the
appointment row is still 'booked' afterwards.

TRANSACTION CONTRACT: tool implementations must NEVER commit. They flush so
their changes are visible within the caller's transaction, and the
governance engine commits the business change together with the action
request's status transition. That single commit is what makes crash
recovery decidable -- see docs/RECOVERY.md.

tests/test_import_boundary.py fails the build if a tool calls commit().
"""
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import Appointment
from app.models.enums import AppointmentStatus
from app.schemas.tool_params import CancelAppointmentParams


class ToolExecutionError(Exception):
    """Raised when a tool cannot complete for a legitimate domain reason."""


def cancel_appointment(db: Session, params: CancelAppointmentParams) -> dict:
    appt = db.get(Appointment, params.appointment_id)
    if appt is None:
        raise ToolExecutionError(f"No appointment with id {params.appointment_id}.")
    if appt.status is AppointmentStatus.CANCELLED:
        raise ToolExecutionError("That appointment is already cancelled.")

    appt.status = AppointmentStatus.CANCELLED
    appt.cancelled_at = datetime.now(timezone.utc)
    # flush, not commit: the engine owns the transaction boundary.
    db.flush()

    return {
        "appointment_id": appt.id,
        "status": appt.status.value,
        "cancelled_at": appt.cancelled_at.isoformat(),
    }
