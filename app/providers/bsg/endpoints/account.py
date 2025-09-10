from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from igw.app.db import get_db
from igw.app.models import Player

from ..settings import get_bank_settings, resolve_bank_id
from ..xml.utils import envelope_ok, envelope_fail
from ..helpers import hash_ok_user, echo_user_fields, wallet_cents

router = APIRouter()


@router.get("/account")
async def account_info(
    request: Request,
    bankId: int | None = Query(None),
    userId: int | None = Query(None),
    hash: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """
    BSG 'Get Account info' — XML EXTSYSTEM with RESULT/USERID/USERNAME/CURRENCY/BALANCE.
    """
    resolved_bank_id = resolve_bank_id(bankId)
    bank = get_bank_settings(resolved_bank_id)
    protocol = (bank.BSG_PROTOCOL or "xml").lower()

    req_fields = echo_user_fields(userId, hash)

    if userId is None or not hash:
        xml = envelope_fail(400, "missing userId or hash", request_fields=req_fields)
        return Response(content=xml, media_type="application/xml")

    if not hash_ok_user(userId, bank.BSG_PASS_KEY, hash):
        xml = envelope_fail(401, "INVALID_HASH", request_fields=req_fields)
        return Response(content=xml, media_type="application/xml")

    player: Player | None = db.query(Player).filter(Player.userId == userId).first()
    if not player:
        xml = envelope_fail(404, "USER_NOT_FOUND", request_fields=req_fields)
        return Response(content=xml, media_type="application/xml")

    currency = bank.BSG_DEFAULT_CURRENCY or "USD"
    balance_cents = wallet_cents(db, userId, currency)

    xml = envelope_ok(
        user_id=userId,
        username=player.user_name or f"user_{userId}",
        currency=currency,
        balance_cents=balance_cents,
        request_fields=req_fields,
    )
    return Response(content=xml, media_type="application/xml")
