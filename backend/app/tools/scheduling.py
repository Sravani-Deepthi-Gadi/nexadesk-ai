"""check_availability and book_appointment.

Availability is COMPUTED from business_hours minus existing appointments.
There is no slot table, so there is nothing to drift out of sync and no
nightly job to forget to run.
"""
from datetime import date as date_cls, datetime, time, timedelta, timezone

from app.models import Appointment, BusinessHours, Conversation, Customer, Service
from app.models.enums import AppointmentStatus
from app.schemas.tool_params import BookAppointmentParams, CheckAvailabilityParams
from app.tools.appointments import ToolExecutionError
from app.tools.context import ToolContext

MAX_SLOTS = 20
MAX_DAYS_AHEAD = 180


def _parse_iso(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ToolExecutionError(
            f"'{value}' is not a valid ISO 8601 timestamp."
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _active_service(ctx: ToolContext, service_id: int) -> Service:
    service = ctx.db.get(Service, service_id)
    if service is None or not service.is_active:
        raise ToolExecutionError(f"No active service with id {service_id}.")
    return service


def _busy_intervals(ctx: ToolContext, day: date_cls) -> list[tuple[datetime, datetime]]:
    start = datetime.combine(day, time.min, tzinfo=timezone.utc)
    rows = (
        ctx.db.query(Appointment)
        .filter(
            Appointment.status == AppointmentStatus.BOOKED,
            Appointment.starts_at >= start - timedelta(days=1),
            Appointment.starts_at <= start + timedelta(days=2),
        ).all()
    )
    out = []
    for row in rows:
        s, e = row.starts_at, row.ends_at
        if s.tzinfo is None:
            s = s.replace(tzinfo=timezone.utc)
        if e.tzinfo is None:
            e = e.replace(tzinfo=timezone.utc)
        out.append((s, e))
    return out


def _overlaps(start: datetime, end: datetime, busy: list[tuple[datetime, datetime]]) -> bool:
    return any(start < b_end and b_start < end for b_start, b_end in busy)


def check_availability(ctx: ToolContext, params: CheckAvailabilityParams) -> dict:
    service = _active_service(ctx, params.service_id)
    try:
        day = date_cls.fromisoformat(params.date)
    except ValueError as exc:
        raise ToolExecutionError(f"'{params.date}' is not a valid date.") from exc

    today = datetime.now(timezone.utc).date()
    if day < today:
        raise ToolExecutionError("That date is in the past.")
    if day > today + timedelta(days=MAX_DAYS_AHEAD):
        raise ToolExecutionError(
            f"Bookings are only open {MAX_DAYS_AHEAD} days ahead."
        )

    hours = (
        ctx.db.query(BusinessHours)
        .filter(BusinessHours.weekday == day.weekday())
        .one_or_none()
    )
    if hours is None or not hours.is_open:
        return {
            "date": params.date, "service_id": service.id,
            "service_name": service.name, "slots": [], "count": 0,
            "note": "The business is closed on that day.",
        }

    duration = timedelta(minutes=service.duration_minutes)
    busy = _busy_intervals(ctx, day)
    now = datetime.now(timezone.utc)

    slots: list[str] = []
    cursor = datetime.combine(day, time.min, tzinfo=timezone.utc) + timedelta(
        minutes=hours.open_minute
    )
    closing = datetime.combine(day, time.min, tzinfo=timezone.utc) + timedelta(
        minutes=hours.close_minute
    )

    while cursor + duration <= closing and len(slots) < MAX_SLOTS:
        end = cursor + duration
        if cursor > now and not _overlaps(cursor, end, busy):
            slots.append(cursor.isoformat())
        cursor += duration

    return {
        "date": params.date,
        "service_id": service.id,
        "service_name": service.name,
        "duration_minutes": service.duration_minutes,
        "slots": slots,
        "count": len(slots),
        "note": (
            "Pass one of these slot values to book_appointment exactly as "
            "given." if slots else "No free slots remain on that date."
        ),
    }


def book_appointment(ctx: ToolContext, params: BookAppointmentParams) -> dict:
    service = _active_service(ctx, params.service_id)
    starts_at = _parse_iso(params.starts_at)
    ends_at = starts_at + timedelta(minutes=service.duration_minutes)

    if starts_at <= datetime.now(timezone.utc):
        raise ToolExecutionError("That start time is in the past.")

    hours = (
        ctx.db.query(BusinessHours)
        .filter(BusinessHours.weekday == starts_at.weekday())
        .one_or_none()
    )
    if hours is None or not hours.is_open:
        raise ToolExecutionError("The business is closed on that day.")

    day_start = datetime.combine(starts_at.date(), time.min, tzinfo=timezone.utc)
    if (
        starts_at < day_start + timedelta(minutes=hours.open_minute)
        or ends_at > day_start + timedelta(minutes=hours.close_minute)
    ):
        raise ToolExecutionError("That time is outside business hours.")

    if _overlaps(starts_at, ends_at, _busy_intervals(ctx, starts_at.date())):
        raise ToolExecutionError(
            "That slot has just been taken. Check availability again."
        )

    email = params.customer_email.strip().lower()
    if "@" not in email or email.startswith("@") or email.endswith("@"):
        raise ToolExecutionError(f"'{params.customer_email}' is not a valid email.")

    customer = ctx.db.query(Customer).filter(Customer.email == email).one_or_none()
    if customer is None:
        customer = Customer(name=params.customer_name.strip(), email=email)
        ctx.db.add(customer)
        ctx.db.flush()

    appointment = Appointment(
        customer_id=customer.id,
        service_id=service.id,
        starts_at=starts_at,
        ends_at=ends_at,
        status=AppointmentStatus.BOOKED,
        created_by_agent_id=ctx.agent_id,
    )
    ctx.db.add(appointment)
    ctx.db.flush()

    # Bind the customer to this conversation. This is what later lets
    # get_customer_details resolve a customer without taking an id.
    convo = ctx.conversation
    if convo is not None and convo.customer_id is None:
        convo.customer_id = customer.id

    ctx.db.flush()   # never commit: the engine owns the transaction

    return {
        "appointment_id": appointment.id,
        "service": service.name,
        "starts_at": starts_at.isoformat(),
        "ends_at": ends_at.isoformat(),
        "customer_name": customer.name,
        "status": appointment.status.value,
    }
