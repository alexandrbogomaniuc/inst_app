# igw/app/utils/security.py
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import jwt  # PyJWT
from igw.app.config import settings

_ALG = "HS256"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def create_token(
    claims: Dict[str, Any],
    *,
    expires_minutes: Optional[int] = None,
) -> str:
    """
    Build a JWT:
      - 'sub' MUST be a string (PyJWT requirement), so we set it from uid if present.
      - include your claims at the top level (uid, type, provider, bankId, gameId, etc.)
      - iat/exp added
      - if claims contains 'exp_m', it takes precedence over 'expires_minutes'
    """
    payload: Dict[str, Any] = dict(claims) if claims else {}
    uid = payload.get("uid")
    sub_str = str(uid) if uid is not None else payload.get("sub") or "user"
    payload["sub"] = sub_str

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
    except Exception as e:
        # Optional: log for debugging
        # print(f"[JWT] decode failed: {e}")
        return None


def extract_subject(payload: Dict[str, Any]) -> Optional[Any]:
    """
    Compatibility helper:
      - if 'sub' is string -> return it
      - if 'sub' was older dict (legacy tokens) -> return dict
    """
    if not payload:
        return None
    sub = payload.get("sub")
    return sub
