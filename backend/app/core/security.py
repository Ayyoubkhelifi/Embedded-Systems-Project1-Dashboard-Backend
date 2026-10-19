import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

from app.core.config import get_settings

_BCRYPT_ROUNDS = 12


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        # Malformed hash in DB — treat any error as failed verification.
        return False


def generate_gateway_api_key() -> str:
    """256-bit random secrets prefixed for easy identification in configs/logs."""
    return f"ess_gw_{secrets.token_urlsafe(32)}"


def gateway_key_fingerprint(api_key: str) -> str:
    """Fast, deterministic fingerprint used for constant-time lookup equality checks.

    bcrypt *should* be used for direct verification; this fingerprint lets
    indexing/selecting the right row without scanning every gateway row with
    bcrypt.checkpw. Not a security boundary on its own — verify_password on the
    selected row still decides access.
    """
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def constant_time_compare(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def create_access_token(
    subject: str,
    role: str,
    user_id: int | None = None,
    expires_in_minutes: int | None = None,
) -> tuple[str, datetime]:
    settings = get_settings()
    ttl = (
        expires_in_minutes
        if expires_in_minutes is not None
        else settings.access_token_ttl_minutes
    )
    now = datetime.now(UTC)
    exp = now + timedelta(minutes=ttl)
    claims: dict[str, Any] = {
        "sub": subject,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    if user_id is not None:
        claims["uid"] = user_id
    token = jwt.encode(claims, settings.secret_jwt_key, algorithm=settings.jwt_algorithm)
    return token, exp


def decode_access_token(token: str) -> dict[str, Any]:
    """Raises jwt.PyJWTError on any failure."""
    settings = get_settings()
    return jwt.decode(
        token,
        settings.secret_jwt_key,
        algorithms=[settings.jwt_algorithm],
        options={"require": ["sub", "exp", "role"]},
    )
