from fastapi import APIRouter, Response
from sqlalchemy import select

from app.api.deps import AdminUser, DbSession, ViewerUser
from app.core.config import get_settings
from app.core.errors import ApiError
from app.core.security import create_access_token, hash_password, verify_password
from app.models import User
from app.schemas.auth import LoginIn, TokenOut, UserCreate, UserList, UserOut, UserUpdate

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_session_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        max_age=settings.access_token_ttl_minutes * 60,
        path="/",
    )


@router.post("/login", response_model=TokenOut)
async def login(payload: LoginIn, response: Response, session: DbSession) -> TokenOut:
    result = await session.execute(select(User).where(User.username == payload.username))
    user = result.scalar_one_or_none()
    # Constant-ish response regardless of which factor failed (no user enumeration).
    if user is None or not verify_password(payload.password, user.password_hash):
        raise ApiError("BAD_CREDENTIALS", "Invalid username or password.", 401)
    if not user.is_active:
        raise ApiError("ACCOUNT_DISABLED", "This account has been deactivated.", 403)

    token, expires_at = create_access_token(subject=user.username, role=user.role, user_id=user.id)
    _set_session_cookie(response, token)
    return TokenOut(
        access_token=token,
        token_type="bearer",
        expires_at=expires_at,
        user=UserOut.model_validate(user),
    )


@router.post("/logout")
async def logout(response: Response) -> dict:
    settings = get_settings()
    response.delete_cookie(settings.session_cookie_name, path="/")
    return {"ok": True}


@router.get("/me", response_model=UserOut)
async def me(user: ViewerUser) -> UserOut:
    return UserOut.model_validate(user)


# ---- Admin: user management -------------------------------------------------


@router.get("/users", response_model=UserList)
async def list_users(_: AdminUser, session: DbSession) -> UserList:
    result = await session.execute(select(User).order_by(User.created_at))
    users = result.scalars().all()
    return UserList(items=[UserOut.model_validate(u) for u in users], total=len(users))


@router.post("/users", response_model=UserOut, status_code=201)
async def create_user(payload: UserCreate, _: AdminUser, session: DbSession) -> UserOut:
    existing = await session.execute(select(User).where(User.username == payload.username))
    if existing.scalar_one_or_none() is not None:
        raise ApiError("USERNAME_TAKEN", "A user with that username already exists.", 409)
    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        role=payload.role,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return UserOut.model_validate(user)


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(user_id: int, payload: UserUpdate, admin: AdminUser, session: DbSession) -> UserOut:
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise ApiError("NOT_FOUND", "User not found.", 404)

    # Guard: an admin must not be able to demote/disable themselves into a lock-out.
    if user.id == admin.id and (payload.is_active is False or (payload.role and payload.role != "admin")):
        raise ApiError("SELF_LOCKOUT_FORBIDDEN", "You cannot demote or disable your own admin account.", 409)

    data = payload.model_dump(exclude_none=True)
    if "password" in data:
        user.password_hash = hash_password(data.pop("password"))
    if "role" in data:
        user.role = data.pop("role")
    if "is_active" in data:
        user.is_active = data.pop("is_active")
    await session.commit()
    await session.refresh(user)
    return UserOut.model_validate(user)


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(user_id: int, admin: AdminUser, session: DbSession) -> Response:
    if user_id == admin.id:
        raise ApiError("SELF_DELETE_FORBIDDEN", "You cannot delete your own admin account.", 409)
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise ApiError("NOT_FOUND", "User not found.", 404)
    user.is_active = False  # soft delete: alerts reference acknowledged_by
    await session.commit()
    return Response(status_code=204)
