"""FastAPI application entrypoint.

Run it with:  uvicorn app.main:app --reload
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import chat
from app.api.admin import approvals as admin_approvals
from app.api.admin import audit as admin_audit
from app.api.admin import documents as admin_documents
from app.api.admin import auth as admin_auth
from app.config import get_settings
from app.db.seed import seed, seed_admin
from app.db.session import SessionLocal, init_db
from app.governance.recovery import run_recovery

settings = get_settings()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    db = SessionLocal()
    try:
        seed(db, agent_name=settings.default_agent_name)
        seed_admin(db)

        # Sweep for work interrupted by a previous crash. Stranded requests
        # go back to APPROVED; they are NOT auto-executed, so a restart
        # never silently re-runs a human-approved action.
        report = run_recovery(db)
        if not report.is_clean:
            logger.warning(
                "Startup recovery: %d recovered, %d abandoned, "
                "%d executed without an audit row (ids: %s)",
                len(report.recovered), len(report.abandoned),
                len(report.unaudited), report.unaudited,
            )
    finally:
        db.close()
    yield


app = FastAPI(title="NexaDesk AI", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router)
app.include_router(admin_auth.router)
app.include_router(admin_approvals.router)
app.include_router(admin_audit.router)
app.include_router(admin_documents.router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
