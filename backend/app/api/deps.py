import secrets
from typing import Annotated

import jwt
from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import ApiError
from app.core.security import decode_access_token, gateway_key_fingerprint, verify_password
from app.db.session import get_db
from app.models import Gateway, User, UserRole

DbSession = Annotated[AsyncSession, Depends(get_db)]


def _extract_token(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return request.cookies.get(get_settings().session_cookie_name)


async def load_user_from_token(token: str | None, session: AsyncSession) -> User:
    """Decode a JWT and load the active user; raise ApiError with envelope code."""
    if not token:
        raise ApiError("UNAUTHORIZED", "Authentication required.", 401)
    try:
        claims = decode_access_token(token)
    except jwt.ExpiredSignatureError:
        raise ApiError("TOKEN_EXPIRED", "Session expired. Please log in again.", 401) from None
    except jwt.PyJWTError:
        raise ApiError("UNAUTHORIZED", "Invalid authentication token.", 401) from None

    uid = claims.get("uid")
    username = claims.get("sub")
    stmt = (
        select(User).where(User.id == uid) if uid is not None else select(User).where(User.username == username)
    )
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise ApiError("UNAUTHORIZED", "Account disabled or missing.", 401)
    # Guard against role revoked after token issue.
    if user.role != claims.get("role"):
        raise ApiError("UNAUTHORIZED", "Session role no longer matches; log in again.", 401)
    return user


async def get_current_user(request: Request, session: DbSession) -> User:
    return await load_user_from_token(_extract_token(request), session)


async def get_current_user_optional(request: Request, session: DbSession) -> User | None:
    try:
        return await get_current_user(request, session)
    except ApiError:
        return None


def require_roles(*roles: str):
    async def _dep(user: Annotated[User, Depends(get_current_user)]) -> User:
        if user.role not in roles:
            raise ApiError("FORBIDDEN", "Insufficient role for this operation.", 403)
        return user

    return _dep


AdminUser = Annotated[User, Depends(require_roles(UserRole.ADMIN))]
OperatorUser = Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.OPERATOR))]
ViewerUser = Annotated[User, Depends(get_current_user)]


async def get_gateway(request: Request, session: DbSession) -> Gateway | None:
    """None when no gateway credential is presented (callers decide)."""
    api_key = request.headers.get("x-gateway-key")
    if not api_key:
        return None
    fp = gateway_key_fingerprint(api_key)
    result = await session.execute(select(Gateway).where(Gateway.api_key_fingerprint == fp))
    gateway = result.scalar_one_or_none()
    if gateway is None or not gateway.is_active:
        return None
    if not verify_password(api_key, gateway.api_key_hash):
        return None
    return gateway


async def require_gateway(request: Request, session: DbSession) -> Gateway:
    gateway = await get_gateway(request, session)
    if gateway is None:
        raise ApiError(
            "INVALID_GATEWAY_KEY",
            "Valid X-Gateway-Key header required for telemetry ingestion.",
            401,
        )
    return gateway


async def authenticate_ws_token(token: str, session: AsyncSession) -> User:
    return await load_user_from_token(token, session)


def random_request_id() -> str:
    return secrets.token_hex(8)
