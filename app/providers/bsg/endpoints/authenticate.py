from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from igw.app.db import get_db
from igw.app.models import UserSession, Player
from igw.app.utils.security import decode_token

from ..settings import get_bank_settings, resolve_bank_id
from ..xml.utils import envelope_ok, envelope_fail
from ..helpers import hash_ok_token, echo_fields, wallet_cents

router = APIRouter()


@router.get("/authenticate")
async def authenticate(
    request: Request,
    token: str = Query(...),
    hash: str = Query(...),
    bankId: int | None = Query(None),
    clientType: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """
    BSG calls this before launching the game. Responds with EXTSYSTEM XML:
    RESULT/USERID/USERNAME/CURRENCY/BALANCE (balance in cents).
    """
    bank_id = resolve_bank_id(bankId)
    bank = get_bank_settings(bank_id)
    protocol = (bank.BSG_PROTOCOL or "xml").lower()

    # Enforce xml (your current bank)
    if protocol != "xml":
        xml = envelope_fail(400, "Bank protocol mismatch: expected xml",
                            request_fields=echo_fields(token, hash))
        return Response(content=xml, media_type="application/xml")

    # 1) Hash check MD5(token + PASS_KEY)
    if not hash_ok_token(token, bank.BSG_PASS_KEY, hash):
        xml = envelope_fail(401, "INVALID_HASH", request_fields=echo_fields(token, hash))
        return Response(content=xml, media_type="application/xml")

    # 2) Decode token and extract uid
    try:
        payload = decode_token(token)
    except Exception as e:
        xml = envelope_fail(401, f"INVALID_TOKEN {e}", request_fields=echo_fields(token, hash))
        return Response(content=xml, media_type="application/xml")

    uid: Optional[int] = None
    if isinstance(payload.get("sub"), str) and payload["sub"].isdigit():
        uid = int(payload["sub"])
    if uid is None and isinstance(payload.get("uid"), int):
        uid = payload["uid"]

    if uid is None:
        xml = envelope_fail(401, "INVALID_TOKEN no user in token", request_fields=echo_fields(token, hash))
        return Response(content=xml, media_type="application/xml")

    # 3) Verify game session exists
    sess = (
        db.query(UserSession)
        .filter(
            UserSession.userId == uid,
            UserSession.token == token,
            UserSession.session_type == "game",
            UserSession.provider == "bsg",
            UserSession.status == "active",
        )
        .first()
    )
    if not sess:
        xml = envelope_fail(401, "SESSION_NOT_FOUND", request_fields=echo_fields(token, hash))
        return Response(content=xml, media_type="application/xml")

    # 4) Build response with user info + balance in cents
    player: Player | None = db.query(Player).filter(Player.userId == uid).first()
    username = player.user_name if (player and player.user_name) else f"user_{uid}"
    currency = bank.BSG_DEFAULT_CURRENCY or "USD"
    balance_cents = wallet_cents(db, uid, currency)

    xml = envelope_ok(
        user_id=uid,
        username=username,
        currency=currency,
        balance_cents=balance_cents,
        request_fields=echo_fields(token, hash),
    )
    return Response(content=xml, media_type="application/xml")
