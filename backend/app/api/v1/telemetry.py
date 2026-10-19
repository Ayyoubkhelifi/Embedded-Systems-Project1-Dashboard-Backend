from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from app.api.deps import DbSession, require_gateway, ViewerUser
from app.core.config import get_settings
from app.core.errors import ApiError
from app.schemas.telemetry import IngestResult, TelemetryIn, TelemetryOut
from app.services.ingestion import fetch_history, fetch_latest, get_device_by_lora_id, ingest

router = APIRouter(prefix="/telemetry", tags=["telemetry"])


def _parse_range(
    start: datetime | None,
    end: datetime | None,
    default_window_minutes: int = 1440,
) -> tuple[datetime, datetime]:
    settings = get_settings()
    now = datetime.now(UTC)
    if end is None and start is None:
        start = now - timedelta(minutes=default_window_minutes)
    end = end or now
    start = start or (end - timedelta(minutes=default_window_minutes))
    # Naive query params are interpreted as UTC.
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    if end.tzinfo is None:
        end = end.replace(tzinfo=UTC)
    if start >= end:
        raise ApiError("INVALID_TIME_RANGE", "'start' must be before 'end'.", 422)
    max_window = timedelta(days=settings.max_history_range_days)
    if end - start > max_window:
        raise ApiError(
            "TIME_RANGE_TOO_LARGE",
            f"Time range exceeds the {settings.max_history_range_days}-day maximum.",
            422,
        )
    return start, end


def _validate_paging(limit: int, offset: int) -> tuple[int, int]:
    settings = get_settings()
    if limit < 1 or limit > settings.max_page_limit:
        raise ApiError(
            "INVALID_PAGINATION",
            f"'limit' must be between 1 and {settings.max_page_limit}.",
            422,
        )
    if offset < 0:
        raise ApiError("INVALID_PAGINATION", "'offset' must be >= 0.", 422)
    return limit, offset


@router.post("", response_model=IngestResult, status_code=201)
async def post_telemetry(
    payload: TelemetryIn,
    request: Request,
    session: DbSession,
    gateway=Depends(require_gateway),
) -> IngestResult:
    """Gateway ingestion — authenticated via X-Gateway-Key.

    Idempotent: re-sending the same (device_id, seq) returns HTTP 200 with
    `duplicate: true` and never creates a second row (unique index enforced).
    """
    result = await ingest(session, gateway, payload)
    if result.duplicate:
        return JSONResponse(status_code=200, content=result.model_dump())
    return result


@router.get("/latest", response_model=list[TelemetryOut])
async def latest_readings(
    _: ViewerUser,
    session: DbSession,
    device_id: int | None = Query(default=None, ge=1, le=4294967295),
    limit: int = Query(default=10, ge=1, le=200),
) -> list[TelemetryOut]:
    """Most recent N readings (optionally scoped to one device), newest first."""
    device_id_ref = None
    if device_id is not None:
        device_id_ref = (await get_device_by_lora_id(session, device_id)).id
    return await fetch_latest(session, device_id_ref, limit)


@router.get("/history", response_model=list[TelemetryOut])
async def history(
    _: ViewerUser,
    session: DbSession,
    device_id: int | None = Query(default=None, ge=1, le=4294967295),
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = Query(default=500, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
) -> list[TelemetryOut]:
    """Readings within [start, end), optionally per device, paged."""
    start, end = _parse_range(start, end)
    limit, offset = _validate_paging(limit, offset)
    device_id_ref = None
    if device_id is not None:
        device_id_ref = (await get_device_by_lora_id(session, device_id)).id
    return await fetch_history(session, device_id_ref, start, end, limit, offset, order)
