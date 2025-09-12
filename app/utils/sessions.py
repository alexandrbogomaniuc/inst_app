from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, Dict

from sqlalchemy.orm import Session

from igw.app.models import UserSession
from igw.app.utils.security import decode_token, create_token


# ---------- JWT helpers ----------

def exp_from_jwt(token: str) -> Optional[datetime]:
    """
    Extract exp (seconds) from JWT and return naive UTC datetime.
    Returns None if token invalid or exp missing.
    """
    try:
        payload: Dict = decode_token(token)
        exp = payload.get("exp")
        if isinstance(exp, int):
            # return naive UTC so it matches your DB naive column
            return datetime.fromtimestamp(exp, tz=timezone.utc).replace(tzinfo=None)
    except Exception:
        return None
    return None


def compute_expires_at_from_minutes(minutes: int) -> datetime:
    return datetime.utcnow() + timedelta(minutes=minutes)


def should_refresh(token: str, threshold_minutes: int = 5) -> bool:
    """
    True if token will expire within the threshold window.
    """
    exp = exp_from_jwt(token)
    if not exp:
        # malformed/missing exp -> treat as needs refresh
        return True
    return (exp - datetime.utcnow()) <= timedelta(minutes=threshold_minutes)


# ---------- Session row helpers ----------

def expire_if_past(db: Session, session_row: UserSession) -> bool:
    """
    If row is 'active' but its (expires_at or JWT exp) is in the past,
    mark it 'expired' and set logout_time=now. Returns True if updated.
    """
    if session_row.status != "active":
        return False

    now = datetime.utcnow()
    exp_dt = session_row.expires_at or exp_from_jwt(session_row.token)

    if exp_dt is not None and exp_dt <= now:
        session_row.status = "expired"
        session_row.logout_time = now
        db.add(session_row)
        return True
    return False


def cleanup_user_active_sessions(db: Session, user_id: int) -> Dict[str, int]:
    """
    Opportunistic GC for a single user. Safe to call anywhere you already have user_id.
    """
    rows = (
        db.query(UserSession)
        .filter(UserSession.userId == user_id, UserSession.status == "active")
        .all()
    )
    updated = 0
    for s in rows:
        if expire_if_past(db, s):
            updated += 1
    if updated:
        db.commit()
    return {"checked": len(rows), "expired": updated}


def cleanup_all_active_sessions(db: Session, limit: int = 1000) -> Dict[str, int]:
    """
    Bulk GC for admin/cron use. Expires rows whose expires_at or JWT exp is in the past.
    """
    now = datetime.utcnow()

    with_exp = (
        db.query(UserSession)
        .filter(
            UserSession.status == "active",
            UserSession.expires_at.isnot(None),
            UserSession.expires_at <= now,
        )
        .limit(limit)
        .all()
    )
    without_exp = (
        db.query(UserSession)
        .filter(
            UserSession.status == "active",
            UserSession.expires_at.is_(None),
        )
        .limit(limit)
        .all()
    )

    updated = 0
    for row in with_exp:
        if expire_if_past(db, row):
            updated += 1
    for row in without_exp:
        if expire_if_past(db, row):
            updated += 1

    if updated:
        db.commit()
    return {"expired": updated, "scanned": len(with_exp) + len(without_exp)}


def refresh_session_token_if_needed(
    db: Session,
    session_row: UserSession,
    ttl_minutes: int,
    extra_claims: Optional[Dict] = None,
    threshold_minutes: int = 5,
) -> Optional[str]:
    """
    If the session’s JWT is close to expiring, mint a fresh one with the same identity,
    update the row’s token/expires_at, and return the new token. Otherwise return None.
    """
    if session_row.status != "active":
        return None

    if not should_refresh(session_row.token, threshold_minutes=threshold_minutes):
        return None

    payload = decode_token(session_row.token) or {}
    claims = {
        "sub": payload.get("sub"),
        "uid": payload.get("uid"),
        "type": payload.get("type"),
        "provider": payload.get("provider"),
        "bankId": payload.get("bankId"),
        "gameId": payload.get("gameId"),
        "exp_m": ttl_minutes,
    }
    if extra_claims:
        claims.update(extra_claims)

    new_token = create_token(claims)
    session_row.token = new_token
    session_row.expires_at = exp_from_jwt(new_token)
    db.add(session_row)
    db.commit()
    return new_token


__all__ = [
    "exp_from_jwt",
    "compute_expires_at_from_minutes",
    "should_refresh",
    "expire_if_past",
    "cleanup_user_active_sessions",
    "cleanup_all_active_sessions",
    "refresh_session_token_if_needed",
]
