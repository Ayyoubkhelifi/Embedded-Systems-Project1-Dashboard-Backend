import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import alerts, auth, devices, health, settings as settings_api, telemetry, ws
from app.core.config import get_settings
from app.core.errors import install_error_handlers
from app.core.logging import get_logger, setup_logging
from app.core.rate_limit import install_middleware
from app.db.session import get_sessionmaker
from app.db.base import Base  # noqa: F401 — imported for metadata side effects
from app.services.offline import offline_monitor_loop
from app.services.realtime import manager

logger = get_logger("app")


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.log_level, json_output=not settings.is_testing)

    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        openapi_url="/openapi.json" if not settings.is_production else None,
        lifespan=lifespan,
    )

    # Error envelope first, then CORS, then logging/rate-limit layers.
    install_error_handlers(app)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Gateway-Key"],
        max_age=600,
    )

    install_middleware(
        app,
        general_per_minute=settings.rate_limit_general_per_minute,
        ingest_per_minute=settings.rate_limit_ingest_per_minute,
        body_bytes=settings.max_request_body_bytes,
    )

    app.include_router(health.router, prefix="/api/v1")
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(telemetry.router, prefix="/api/v1")
    app.include_router(devices.router, prefix="/api/v1")
    app.include_router(alerts.router, prefix="/api/v1")
    app.include_router(settings_api.router, prefix="/api/v1")
    app.include_router(ws.router, prefix="/api/v1")

    return app


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    stop_event = asyncio.Event()
    tasks: list[asyncio.Task] = []

    if not settings.is_testing:
        tasks.append(asyncio.create_task(manager.heartbeat_loop()))
        tasks.append(asyncio.create_task(offline_monitor_loop(stop_event)))
        logger.info("startup complete env=%s", settings.env)

    try:
        yield
    finally:
        stop_event.set()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        sessionmaker = get_sessionmaker()
        try:
            from app.db.session import reset_engine

            await reset_engine()
        except Exception:  # noqa: BLE001
            pass
        logger.info("shutdown complete")


app = create_app()
