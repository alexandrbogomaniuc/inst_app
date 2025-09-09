# igw/app/utils/security.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import bcrypt
import jwt

from igw.app.config import settings

_ALG = "HS256"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# -------------------------
# Password hashing helpers
# -------------------------
def hash_password(plain: str) -> str:
    """
    Hash a plaintext password using bcrypt.
    Respects settings.PASSWORD_BCRYPT_ROUNDS (default 12).
    """
    if plain is None:
        raise ValueError("plain password is required")
    rounds = int(getattr(settings, "PASSWORD_BCRYPT_ROUNDS", 12) or 12)
    salt = bcrypt.gensalt(rounds)
    return bcrypt.hashpw(plain.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """
    Verify a plaintext password against a bcrypt hash.
    """
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# -------------------------
# JWT helpers
# -------------------------
def create_token(
    claims: Dict[str, Any],
    *,
    expires_minutes: Optional[int] = None,
) -> str:
    """
    Build a JWT:
      - 'sub' MUST be a string for PyJWT; we set it from uid if present.
      - Your custom claims (uid, type, provider, bankId, gameId, etc.) stay top-level.
      - iat/exp are added. 'exp_m' inside claims overrides expires_minutes.
    """
    payload: Dict[str, Any] = dict(claims) if claims else {}

    # Ensure sub is a string
    uid = payload.get("uid")
    sub = payload.get("sub")
    if uid is not None:
        payload["sub"] = str(uid)
    elif sub is not None:
        payload["sub"] = str(sub)
    else:
        payload["sub"] = "user"

    now = _utcnow()
    exp_m = payload.pop("exp_m", None) or expires_minutes or 60
    payload["iat"] = int(now.timestamp())
    payload["exp"] = int((now + timedelta(minutes=int(exp_m))).timestamp())

    token = jwt.encode(payload, settings.JWT_SIGNING_KEY, algorithm=_ALG)
    return token


def decode_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Verify & decode. Returns payload dict or None if invalid/expired.
    """
    try:
        payload = jwt.decode(token, settings.JWT_SIGNING_KEY, algorithms=[_ALG])
        return payload
    except Exception:
        return None


def extract_subject(payload: Dict[str, Any]) -> Optional[str]:
    """
    Return the subject (sub) as a string if present.
    """
    if not payload:
        return None
    sub = payload.get("sub")
    return None if sub is None else str(sub)


__all__ = [
    "hash_password",
    "verify_password",
    "create_token",
    "decode_token",
    "extract_subject",
]
