import time
from collections import defaultdict, deque
from typing import Any, Deque

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.errors import error_response


class RateLimitExceeded(Exception):
    pass


class RequestContext:
    """Per-request state filled by middleware (rate limit identity + timing)."""

    request_id: str
    identity_key: str
    start_time: float


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request.state.start_time = time.perf_counter()
        request.state.request_id = f"{time.time_ns():x}"
        response = await call_next(request)
        duration_ms = (time.perf_counter() - request.state.start_time) * 1000.0
        from app.core.logging import get_logger

        logger = get_logger("app.access")
        logger.info(
            "%s %s -> %d",
            request.method,
            request.url.path,
            response.status_code,
            extra={
                "request_id": getattr(request.state, "request_id", ""),
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round(duration_ms, 2),
            },
        )
        return response


body_limit: int | None = None


def configure_body_limit(limit_bytes: int) -> None:
    global body_limit
    body_limit = limit_bytes


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        limit = body_limit or 65536
        content_length = request.headers.get("content-length")
        if request.method in ("POST", "PUT", "PATCH") and content_length:
            try:
                if int(content_length) > limit:
                    return error_response(
                        "PAYLOAD_TOO_LARGE",
                        f"Request body exceeds {limit} bytes.",
                        413,
                    )
            except ValueError:
                pass
        return await call_next(request)


class SlidingWindowRateLimitMiddleware(BaseHTTPMiddleware):
    """In-memory sliding-window limiter keyed by (bucket, identity)."""

    def __init__(self, app: Any, default_per_minute: int, ingest_per_minute: int) -> None:
        super().__init__(app)
        self.default_per_minute = default_per_minute
        self.ingest_per_minute = ingest_per_minute
        self._hits: dict[str, Deque[float]] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method == "OPTIONS" or request.url.path.startswith("/api/v1/health"):
            return await call_next(request)

        path = request.url.path
        limit = self.default_per_minute
        if path == "/api/v1/telemetry" and request.method == "POST":
            limit = self.ingest_per_minute
        identity = _identity(request)
        key = f"{identity}|{path}"
        now = time.monotonic()
        window = self._hits[key]
        while window and now - window[0] > 60.0:
            window.popleft()
        if len(window) >= limit:
            retry_after = max(1, int(60 - (now - window[0])))
            response = error_response(
                "RATE_LIMITED",
                f"Rate limit of {limit}/min exceeded for {path}.",
                429,
            )
            response.headers["Retry-After"] = str(retry_after)
            return response
        window.append(now)
        return await call_next(request)


def _identity(request: Request) -> str:
    api_key = request.headers.get("x-gateway-key")
    if api_key:
        return f"gw:{api_key[:8]}"
    token_cookie = request.cookies.get("ess_session") or request.headers.get("authorization", "")
    if token_cookie:
        return f"user:{token_cookie[:16]}"
    client_host = request.client.host if request.client else "unknown"
    return f"ip:{client_host}"


def install_middleware(app: Any, general_per_minute: int, ingest_per_minute: int, body_bytes: int) -> None:
    configure_body_limit(body_bytes)
    app.add_middleware(BodySizeLimitMiddleware)
    app.add_middleware(
        SlidingWindowRateLimitMiddleware,
        default_per_minute=general_per_minute,
        ingest_per_minute=ingest_per_minute,
    )
    app.add_middleware(RequestLoggingMiddleware)
