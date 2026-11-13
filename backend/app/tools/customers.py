"""get_customer_details.

Takes NO customer identifier. The customer is resolved from the
conversation the tool is running inside, so the agent has no way to
express a request for anyone else's record -- and therefore no prompt or
poisoned document can talk it into one.

Returns a deliberately narrow view: name, email and this customer's own
appointments. Not every column on the row.
"""
from app.models import Appointment, Customer, Service
from app.schemas.tool_params import GetCustomerDetailsParams
from app.tools.context import ToolContext


def get_customer_details(ctx: ToolContext, params: GetCustomerDetailsParams) -> dict:
    customer_id = ctx.current_customer_id()
    if customer_id is None:
        return {
            "identified": False,
            "note": (
                "No customer is linked to this conversation yet. Ask the "
                "customer for the details you need; do not guess."
            ),
        }

    customer = ctx.db.get(Customer, customer_id)
    if customer is None:
        return {"identified": False, "note": "The linked customer record is missing."}

    rows = (
        ctx.db.query(Appointment)
        .filter(Appointment.customer_id == customer.id)
        .order_by(Appointment.starts_at)
        .all()
    )
    appointments = []
    for row in rows:
        service = ctx.db.get(Service, row.service_id)
        appointments.append({
            "appointment_id": row.id,
            "service": service.name if service else "Unknown service",
            "starts_at": row.starts_at.isoformat(),
            "status": row.status.value,
        })

    return {
        "identified": True,
        "name": customer.name,
        "email": customer.email,
        "appointments": appointments,
        "appointment_count": len(appointments),
    }
