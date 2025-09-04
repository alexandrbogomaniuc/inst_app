from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import jwt

# Prefer passlib+bcrypt for password hashing
try:
    from passlib.context import CryptContext

    _pwd_context: Optional[CryptContext] = CryptContext(
        schemes=["bcrypt"], deprecated="auto"
    )
except Exception:  # pragma: no cover
    _pwd_context = None

from ..config import settings

JWT_ALGO = "HS256"


def hash_password(plain: str) -> str:
    """
    Hash a plaintext password for local/email-password accounts.
    If passlib/bcrypt is unavailable, fall back to a flagged SHA256 (less secure).
    """
    if not isinstance(plain, str):
        raise TypeError("plain password must be a string")

    if _pwd_context:
        return _pwd_context.hash(plain)

    # Fallback (only if passlib/bcrypt not available)
    import hashlib
    return "sha256$" + hashlib.sha256(plain.encode("utf-8")).hexdigest()


def verify_password(plain: str, hashed: str) -> bool:
    """
    Verify a plaintext password against a stored hash.
    Supports passlib bcrypt and the SHA256 fallback above.
    """
    if not isinstance(hashed, str):
        return False

    # OAuth-only accounts may store a sentinel like "oauth:<id>"
    if hashed.startswith("oauth:"):
        return False

    if _pwd_context and (hashed.startswith("$2a$") or hashed.startswith("$2b$") or hashed.startswith("$2y$")):
        try:
            return _pwd_context.verify(plain, hashed)
        except Exception:
            return False

    if hashed.startswith("sha256$"):
        import hashlib
        digest = "sha256$" + hashlib.sha256(plain.encode("utf-8")).hexdigest()
        return digest == hashed

    # Unknown format
    return False


def create_token(sub: str, extra: dict | None = None, ttl_minutes: int = 60 * 24) -> str:
    """
    Create a signed JWT for sessions.
    `sub` should be the internal player ID as a string.
    """
    now = datetime.now(tz=timezone.utc)
    payload = {
        "sub": sub,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=ttl_minutes)).timestamp()),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.jwt_signing_key, algorithm=JWT_ALGO)
