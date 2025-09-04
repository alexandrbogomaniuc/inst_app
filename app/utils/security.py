from datetime import datetime, timedelta, timezone
from jose import jwt
from ..config import settings

ALGO = "HS256"

def create_token(sub: str, extra: dict | None = None, ttl_minutes: int = 60 * 24):
    payload = {
        "sub": sub,
        "iat": int(datetime.now(tz=timezone.utc).timestamp()),
        "exp": int((datetime.now(tz=timezone.utc) + timedelta(minutes=ttl_minutes)).timestamp()),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.jwt_signing_key, algorithm=ALGO)
