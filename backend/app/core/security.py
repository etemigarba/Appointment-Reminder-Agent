"""Password hashing (PBKDF2-HMAC-SHA256, stdlib) and JWT helpers (PyJWT)."""

from __future__ import annotations

import hashlib
import hmac
import os
from datetime import UTC, datetime, timedelta

import jwt

PBKDF2_ITERATIONS = 260_000
TOKEN_ALGORITHM = "HS256"
TOKEN_EXPIRY_HOURS = 24


def get_jwt_secret() -> str:
    secret = os.environ.get("APP_JWT_SECRET", "")
    if not secret:
        # Documented insecure dev default (>=32 bytes); production must set APP_JWT_SECRET.
        secret = "dev-insecret-key-change-me-in-production!"
    return secret


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, iterations, salt_hex, digest_hex = stored.split("$")
        if scheme != "pbkdf2":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations)
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def create_access_token(tenant_id: str) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": tenant_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=TOKEN_EXPIRY_HOURS)).timestamp()),
    }
    return jwt.encode(payload, get_jwt_secret(), algorithm=TOKEN_ALGORITHM)


def decode_access_token(token: str) -> str | None:
    """Return the tenant_id for a valid token, else None."""
    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=[TOKEN_ALGORITHM])
    except jwt.PyJWTError:
        return None
    sub = payload.get("sub")
    return str(sub) if sub else None
