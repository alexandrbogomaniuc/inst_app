from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from igw.app.db import get_db
from igw.app.models import Wallet
from igw.app.models_gameplay import GameplayTransaction

from ..helpers import md5_hex_refund, media_response, wallet_cents
from ..settings import get_bank_settings, resolve_bank_id
from ..xml.utils import envelope_fail, envelope_refund_ok
from ..wallet_utils import get_wallet_for_user

# NOTE: NO /betsoft here; your top-level router already has prefix="/betsoft"
router = APIRouter(tags=["betsoft/bsg"], include_in_schema=False)


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

    req_fields = {
        "USERID": str(userId) if userId is not None else "",
        "CASINOTRANSACTIONID": casinoTransactionId or "",
        "HASH": hash or "",
    }

    if protocol != "xml":
        return media_response(
            {"result": "failed", "code": 400, "reason": "xml only"},
            "json",
            status_code=400,
        )

    # Required params
    if userId is None or not casinoTransactionId or not hash:
        xml = envelope_fail(400, "missing userId or casinoTransactionId or hash", request_fields=req_fields)
        return Response(content=xml, media_type="application/xml")

    # Hash: MD5(userId + casinoTransactionId + passkey)
    expected = md5_hex_refund(user_id=int(userId), casino_tx_id=str(casinoTransactionId), pass_key=bank.BSG_PASS_KEY)
    if expected.lower() != (hash or "").lower():
        xml = envelope_fail(401, "invalid hash", request_fields=req_fields)
        return Response(content=xml, media_type="application/xml")

    # Original bet must exist and be Processed
    original = (
        db.query(GameplayTransaction)
        .filter(
            GameplayTransaction.userId == int(userId),
            GameplayTransaction.bank_id == resolved_bank_id,
            GameplayTransaction.transaction_type == "bet",
            GameplayTransaction.external_transaction_id == str(casinoTransactionId),
            GameplayTransaction.status == "Processed",
        )
        .first()
    )
    if not original:
        xml = envelope_fail(302, "ORIGINAL_TRANSACTION_NOT_FOUND", request_fields=req_fields)
        return Response(content=xml, media_type="application/xml")

    # Idempotency: refund already Processed?
    existing_refund = (
        db.query(GameplayTransaction)
        .filter(
            GameplayTransaction.userId == int(userId),
            GameplayTransaction.bank_id == resolved_bank_id,
            GameplayTransaction.transaction_type == "refund",
            GameplayTransaction.external_transaction_id == str(casinoTransactionId),
            GameplayTransaction.status == "Processed",
        )
        .first()
    )
    if existing_refund:
        xml = envelope_refund_ok(
            ext_system_transaction_id=str(existing_refund.transaction_id),  # <-- underscore fixed
            request_fields=req_fields,
        )
        return Response(content=xml, media_type="application/xml")

    # Create pending refund; amount equals the original bet amount
    wallet: Wallet = get_wallet_for_user(db, int(userId), bank.BSG_DEFAULT_CURRENCY or "USD")
    amount = Decimal(original.amount or Decimal("0.00"))

    refund_tx = GameplayTransaction(
        userId=int(userId),
        wallet_id=wallet.wallet_id,
        bank_id=resolved_bank_id,
        transaction_type="refund",
        amount=amount,
        status="Pending",
        description="BSG refund",
        external_transaction_id=str(casinoTransactionId),
        external_gamesession_id=original.external_gamesession_id,
        external_gameround_id=original.external_gameround_id,
        external_game_id=original.external_game_id,
        ISROUNDFINISHED=original.ISROUNDFINISHED,
    )
    db.add(refund_tx)
    db.flush()

    try:
        wallet.balance = (wallet.balance or Decimal("0.00")) + amount
        db.flush()
        refund_tx.status = "Processed"
        db.commit()
    except Exception as e:
        db.rollback()
        refund_tx.status = "Failed"
        db.add(refund_tx)
        db.commit()
        xml = envelope_fail(500, f"wallet update failed: {e}", request_fields=req_fields)
        return Response(content=xml, media_type="application/xml")

    xml = envelope_refund_ok(
        ext_system_transaction_id=str(refund_tx.transaction_id),  # <-- underscore fixed
        request_fields=req_fields,
    )
    return Response(content=xml, media_type="application/xml")
