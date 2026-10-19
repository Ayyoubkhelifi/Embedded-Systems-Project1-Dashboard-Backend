"""Consistent API error envelope + global exception handlers.

Every error returned by the API has the shape:
    {"error": {"code": str, "message": str, "details": ...}}
Client code (dashboard) pattern-matches on `error.code`, never on prose.
"""
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException


class ApiError(Exception):
    """Raise inside services to produce a structured error response."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details

    def to_response(self) -> JSONResponse:
        return error_response(self.code, self.message, self.status_code, self.details)


def error_response(
    code: str,
    message: str,
    status_code: int,
    details: Any = None,
) -> JSONResponse:
    payload: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details is not None:
        payload["error"]["details"] = details
    return JSONResponse(status_code=status_code, content=jsonable_encoder(payload))


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def handle_api_error(_: Request, exc: ApiError) -> JSONResponse:
        return exc.to_response()

    @app.exception_handler(RequestValidationError)
    async def handle_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = []
        for err in exc.errors():
            details.append(
                {
                    "field": ".".join(str(x) for x in err["loc"][1:]) or "",
                    "type": err["type"],
                }
            )
        return error_response(
            "VALIDATION_ERROR",
            "Request payload failed validation.",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            details,
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        codes = {
            status.HTTP_401_UNAUTHORIZED: "UNAUTHORIZED",
            status.HTTP_403_FORBIDDEN: "FORBIDDEN",
            status.HTTP_404_NOT_FOUND: "NOT_FOUND",
            status.HTTP_409_CONFLICT: "CONFLICT",
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE: "PAYLOAD_TOO_LARGE",
            status.HTTP_429_TOO_MANY_REQUESTS: "RATE_LIMITED",
        }
        return error_response(
            codes.get(exc.status_code, "HTTP_ERROR"),
            str(exc.detail),
            exc.status_code,
        )

    @app.exception_handler(IntegrityError)
    async def handle_integrity(_: Request, exc: IntegrityError) -> JSONResponse:
        return error_response(
            "CONFLICT",
            "The resource conflicts with an existing record.",
            status.HTTP_409_CONFLICT,
        )

    @app.exception_handler(OperationalError)
    async def handle_db_down(_: Request, exc: OperationalError) -> JSONResponse:
        # Never leak DB internals; log handled by middleware/generic logging.
        return error_response(
            "DATABASE_ERROR",
            "A database error occurred. Please retry.",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        from app.core.config import get_settings
        from app.core.logging import get_logger

        logger = get_logger("app.errors")
        logger.exception(
            "Unhandled error",
            extra={
                "method": request.method,
                "path": request.url.path,
            },
        )
        if get_settings().is_testing:
            raise exc
        return error_response(
            "INTERNAL_ERROR",
            "An internal error occurred.",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
