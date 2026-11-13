"""Implementation of cancel_appointment. Touches the database.

This is a real state change, not a stub. The governance tests assert that
it is NOT reached when the agent lacks CANCEL_APPOINTMENT, by checking the
appointment row is still 'booked' afterwards.
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
    db.commit()

    return {
        "appointment_id": appt.id,
        "status": appt.status.value,
        "cancelled_at": appt.cancelled_at.isoformat(),
    }
