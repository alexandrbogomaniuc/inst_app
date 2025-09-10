from __future__ import annotations

import hashlib
from decimal import Decimal
from urllib.parse import unquote_plus

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from igw.app.db import get_db
from igw.app.models import Wallet
from igw.app.models_gameplay import GameplayTransaction
from ..settings import get_bank_settings, resolve_bank_id
from ..helpers import media_response
from ..xml.utils import envelope_fail, envelope_refund_ok  # assumes you have this

router = APIRouter()


@router.get("/refundBet")
async def refund_bet(
    request: Request,
    bankId: int | None = Query(None),
    userId: int | None = Query(None),
    casinoTransactionId: str | None = Query(None),
    hash: str | None = Query(None),
    token: str | None = Query(None),
    db: Session = Depends(get_db),
):
    resolved_bank_id = resolve_bank_id(bankId)
    bank = get_bank_settings(resolved_bank_id)
    protocol = (bank.BSG_PROTOCOL or "xml").lower()

    if protocol != "xml":
        return media_response({"result": "failed", "code": 415, "reason": "xml-only bank"}, "json")

    req_fields = {
        "USERID": str(userId) if userId is not None else "",
        "CASINOTRANSACTIONID": casinoTransactionId or "",
        "HASH": hash or "",
    }

    if userId is None or not casinoTransactionId or not hash:
        xml = envelope_fail(400, "missing required params", request_fields=req_fields)
        return Response(content=xml, media_type="application/xml")

    # Hash = MD5(userId + casinoTransactionId + passkey)
    concat = f"{userId}{casinoTransactionId}{bank.BSG_PASS_KEY}"
    expected = hashlib.md5(concat.encode("utf-8")).hexdigest()
    print(f"[BSG/refundBet] concat='{concat}' expected_md5='{expected}' provided='{hash}'")
    if expected.lower() != hash.lower():
        xml = envelope_fail(401, "invalid hash", request_fields=req_fields)
        return Response(content=xml, media_type="application/xml")

    # Find original tx (bet/win)
    original = (
        db.query(GameplayTransaction)
        .filter(
            GameplayTransaction.userId == userId,
            GameplayTransaction.bank_id == resolved_bank_id,
            GameplayTransaction.external_transaction_id == casinoTransactionId,
            GameplayTransaction.transaction_type.in_(["bet", "win"]),
            GameplayTransaction.status == "Processed",
        )
        .first()
    )
    if not original:
        xml = envelope_fail(302, "ORIGINAL_TRANSACTION_NOT_FOUND", request_fields=req_fields)
        return Response(content=xml, media_type="application/xml")

    # Idempotency for refund
    already = (
        db.query(GameplayTransaction)
        .filter(
            GameplayTransaction.userId == userId,
            GameplayTransaction.bank_id == resolved_bank_id,
            GameplayTransaction.transaction_type == "refund",
            GameplayTransaction.external_transaction_id == casinoTransactionId,
            GameplayTransaction.status == "Processed",
        )
        .first()
    )
    if already:
        xml = envelope_refund_ok(ext_system_transaction_id=str(already.transaction_id), request_fields=req_fields)
        return Response(content=xml, media_type="application/xml")

    # Credit back the original amount
    wallet = db.query(Wallet).filter(Wallet.wallet_id == original.wallet_id).first()
    if not wallet:
        xml = envelope_fail(500, "wallet not found", request_fields=req_fields)
        return Response(content=xml, media_type="application/xml")

    refund_tx = GameplayTransaction(
        userId=userId,
        wallet_id=original.wallet_id,
        bank_id=resolved_bank_id,
        transaction_type="refund",
        amount=original.amount,  # add back what was deducted
        status="Pending",
        description=f"Refund of {casinoTransactionId}",
        external_transaction_id=casinoTransactionId,
        external_gamesession_id=original.external_gamesession_id,
        external_gameround_id=original.external_gameround_id,
        external_game_id=original.external_game_id,
        ISROUNDFINISHED=None,
    )
    db.add(refund_tx)
    db.flush()

    try:
        wallet.balance = (wallet.balance or Decimal("0.00")) + (original.amount or Decimal("0.00"))
        db.flush()
        refund_tx.status = "Processed"
        db.commit()
    except Exception as e:
        db.rollback()
        refund_tx.status = "Failed"
        db.add(refund_tx)
        db.commit()
        xml = envelope_fail(500, f"refund failed: {e}", request_fields=req_fields)
        return Response(content=xml, media_type="application/xml")

    xml = envelope_refund_ok(ext_system_transaction_id=str(refund_tx.transaction_id), request_fields=req_fields)
    return Response(content=xml, media_type="application/xml")
