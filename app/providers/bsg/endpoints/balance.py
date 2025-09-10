from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from igw.app.db import get_db

from ..settings import get_bank_settings, resolve_bank_id
from ..xml.utils import envelope_ok, envelope_fail
from ..helpers import hash_ok_user, wallet_cents

router = APIRouter()


@router.get("/balance")
async def balance(
    request: Request,
    bankId: int | None = Query(None),
    userId: int | None = Query(None),
    hash: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """
    BSG 'Get Balance' (XML flavor)
    Request: bankId, userId, hash (MD5(userId + PASS_KEY))
    Response EXTSYSTEM with RESULT/BALANCE (minor units).
    """
    resolved_bank_id = resolve_bank_id(bankId)
    bank = get_bank_settings(resolved_bank_id)

    # Build REQUEST echo with USERID ONLY (per provider example).
    request_fields = {"USERID": str(userId) if userId is not None else ""}

    if userId is None or not hash:
        xml = envelope_fail(400, "missing userId or hash", request_fields=request_fields)
        return Response(content=xml, media_type="application/xml")

    if not hash_ok_user(userId, bank.BSG_PASS_KEY, hash):
        xml = envelope_fail(401, "INVALID_HASH", request_fields=request_fields)
        return Response(content=xml, media_type="application/xml")

    currency = bank.BSG_DEFAULT_CURRENCY or "USD"
    balance_cents = wallet_cents(db, userId, currency)

    xml = envelope_ok(balance_cents=balance_cents, request_fields=request_fields)
    return Response(content=xml, media_type="application/xml")
