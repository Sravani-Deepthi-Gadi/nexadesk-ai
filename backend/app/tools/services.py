"""Implementation of search_services. Touches the database.

TRANSACTION CONTRACT: tools never commit (see app/tools/appointments.py).
"""
from app.models import Service
from app.schemas.tool_params import SearchServicesParams
from app.tools.context import ToolContext


def search_services(ctx: ToolContext, params: SearchServicesParams) -> dict:
    stmt = ctx.db.query(Service).filter(Service.is_active.is_(True))
    if params.query:
        like = f"%{params.query.lower()}%"
        stmt = stmt.filter(
            Service.name.ilike(like) | Service.description.ilike(like)
        )
    rows = stmt.order_by(Service.id).all()
    return {
        "services": [
            {
                "id": s.id,
                "name": s.name,
                "description": s.description,
                "duration_minutes": s.duration_minutes,
                "price_cents": s.price_cents,
            }
            for s in rows
        ],
        "count": len(rows),
    }
