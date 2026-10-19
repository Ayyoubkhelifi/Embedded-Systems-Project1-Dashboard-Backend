from fastapi import APIRouter, Depends
from sqlalchemy import text

from app.api.deps import DbSession

router = APIRouter(tags=["health"])

API_VERSION = "1.0.0"


@router.get("/health")
async def health(session: DbSession) -> dict:
    """Liveness + DB connectivity probe (also used by Docker/LoadBalancers)."""
    db_ok = True
    try:
        await session.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 — health must never throw
        db_ok = False
    return {
        "status": "ok" if db_ok else "degraded",
        "database": "connected" if db_ok else "unavailable",
        "version": API_VERSION,
    }
