"""FastAPI application entrypoint.

Run it with:  uvicorn app.main:app --reload
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import chat
from app.api.admin import approvals as admin_approvals
from app.api.admin import audit as admin_audit
from app.api.admin import auth as admin_auth
from app.config import get_settings
from app.db.seed import seed, seed_admin
from app.db.session import SessionLocal, init_db

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    db = SessionLocal()
    try:
        seed(db, agent_name=settings.default_agent_name)
        seed_admin(db)
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


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
