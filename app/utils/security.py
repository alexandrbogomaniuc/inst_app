# igw/app/utils/security.py
from __future__ import annotations

import bcrypt
import jwt
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from ..config import settings


# -------------------------
# Password hashing helpers
# -------------------------
def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    rounds = int(settings.password_bcrypt_rounds or 12)
    salt = bcrypt.gensalt(rounds)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), password_hash.encode("utf-8"))
    except Exception:
        return False


# -------------------------
# Token helpers (JWT)
# -------------------------
_ALG = "HS256"


def create_token(subject: str | int, expires_in: int = 24 * 60 * 60, extra: Dict[str, Any] | None = None) -> str:
    """
    Create a signed JWT for session/auth purposes.

    subject: user id (or any identifier)
    expires_in: seconds until expiry (default 24h)
    extra: optional additional claims to embed in the token
    """
    now = datetime.now(timezone.utc)
    payload: Dict[str, Any] = {
        "sub": str(subject),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in)).timestamp()),
    }
    if extra:
        payload.update(extra)

    token = jwt.encode(payload, settings.jwt_signing_key, algorithm=_ALG)
    # PyJWT may return bytes in old versions
    return token.decode("utf-8") if isinstance(token, bytes) else token


def decode_token(token: str) -> Dict[str, Any]:
    """
    Decode & validate a JWT created by create_token.
    Raises jwt.ExpiredSignatureError / jwt.InvalidTokenError on failure.
    """
    data = jwt.decode(token, settings.jwt_signing_key, algorithms=[_ALG])
    # ensure required claim exists
    if "sub" not in data:
        raise jwt.InvalidTokenError("missing 'sub' claim")
    return data
