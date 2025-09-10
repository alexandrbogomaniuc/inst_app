from __future__ import annotations

from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy import select, and_
from sqlalchemy.orm import Session

from igw.app.db import get_db
from igw.app.models import Wallet
from igw.app.models_gameplay import GameplayTransaction

from ..settings import get_bank_settings, resolve_bank_id
from ..xml.utils import envelope_ok, envelope_fail
from ..helpers import md5_hex

router = APIRouter()


@router.get("/refundBet")
async def refund_bet(
    request: Request,
    bankId: int | None = Query(None),
    userId: int = Query(...),
    casinoTransactionId: str = Query(...),
    hash: str = Query(...),
    token: Optional[str] = Query(None),  # not part of hash
    db: Session = Depends(get_db),
):
    """
    Refund hash formula:
      MD5(userId + casinoTransactionId + passkey)

    Response format (XML):
    <EXTSYSTEM>
      <REQUEST>
        <USERID>...</USERID>
        <CASINOTRANSACTIONID>...</CASINOTRANSACTIONID>
        <HASH>...</HASH>
      </REQUEST>
      <TIME>...</TIME>
      <RESPONSE>
        <RESULT>OK</RESULT>
        <EXTSYSTEMTRANSACTIONID>...</EXTSYSTEMTRANSACTIONID>
      </RESPONSE>
    </EXTSYSTEM>
    """
    resolved_bank_id = resolve_bank_id(bankId)
    bank = get_bank_settings(resolved_bank_id)

    # Build REQUEST echo (order per provider example)
    req_fields = {
        "USERID": str(userId) if userId is not None else "",
        "CASINOTRANSACTIONID": str(casinoTransactionId) if casinoTransactionId is not None else "",
        "HASH": hash or "",
    }

    # Validate hash
    expected = md5_hex(f"{userId}{casinoTransactionId}{bank.BSG_PASS_KEY}")
    print(f"[BSG/refundBet] concat='{userId}{casinoTransactionId}{bank.BSG_PASS_KEY}' "
          f"expected_md5='{expected}' provided='{hash}'")
    if expected.lower() != hash.lower():
        xml = envelope_fail(401, "invalid hash", request_fields=req_fields)
        return Response(content=xml, media_type="application/xml")

    # Find original BET transaction for this casinoTransactionId (idempotency anchor)
    orig_bet_row = db.execute(
        select(GameplayTransaction)
        .where(
            and_(
                GameplayTransaction.userId == userId,
                GameplayTransaction.external_transaction_id == str(casinoTransactionId),
                GameplayTransaction.transaction_type == "bet",
                # bank_id might be newly added; guard if column missing
                *( [GameplayTransaction.bank_id == resolved_bank_id]
                   if hasattr(GameplayTransaction, "bank_id") else [] )
            )
        )
        .limit(1)
    ).scalar_one_or_none()

    if not orig_bet_row:
        # Per your requirement: send FAILED with <CODE>302</CODE> if original tx not found
        xml = envelope_fail(302, "ORIGINAL_TRANSACTION_NOT_FOUND", request_fields=req_fields)
        return Response(content=xml, media_type="application/xml")

    # If refund already processed for this bet, return OK with same internal tx id (idempotency)
    existing_refund = db.execute(
        select(GameplayTransaction.transaction_id, GameplayTransaction.status)
        .where(
            and_(
                GameplayTransaction.userId == userId,
                GameplayTransaction.external_transaction_id == str(casinoTransactionId),
                GameplayTransaction.transaction_type == "refund",
                *( [GameplayTransaction.bank_id == resolved_bank_id]
                   if hasattr(GameplayTransaction, "bank_id") else [] )
            )
        )
        .order_by(GameplayTransaction.transaction_id.desc())
    ).first()

    if existing_refund and (existing_refund[1] or "").lower() == "processed":
        response_inner = (
            f"<RESULT>OK</RESULT>"
            f"<EXTSYSTEMTRANSACTIONID>{existing_refund[0]}</EXTSYSTEMTRANSACTIONID>"
        )
        xml = envelope_ok(response_inner_xml=response_inner, request_fields=req_fields)
        return Response(content=xml, media_type="application/xml")

    # We must credit back the original bet amount to the user's wallet (in currency units).
    amount = Decimal(orig_bet_row.amount or 0).quantize(Decimal("0.01"))
    currency = bank.BSG_DEFAULT_CURRENCY or "USD"

    wallet: Wallet | None = (
        db.query(Wallet)
        .filter(Wallet.userId == userId, Wallet.currency_code == currency)
        .with_for_update()
        .first()
    )
    if not wallet:
        xml = envelope_fail(404, "USER_WALLET_NOT_FOUND", request_fields=req_fields)
        return Response(content=xml, media_type="application/xml")

    # Insert refund tx with Pending
    refund_tx = GameplayTransaction(
        userId=userId,
        wallet_id=int(getattr(wallet, wallet.__mapper__.primary_key[0].key)),
        transaction_type="refund",
        amount=amount,  # credit
        description=f"Refund of casinoTx={casinoTransactionId}",
        external_transaction_id=str(casinoTransactionId),
        external_gamesession_id=None,
        external_gameround_id=orig_bet_row.external_gameround_id,
        external_game_id=orig_bet_row.external_game_id,
        ISROUNDFINISHED=None,
        # status/bank_id fields may not exist on older schema; set if present
        **({"status": "Pending"} if hasattr(GameplayTransaction, "status") else {}),
        **({"bank_id": resolved_bank_id} if hasattr(GameplayTransaction, "bank_id") else {}),
    )
    db.add(refund_tx)
    db.flush()  # get refund_tx.transaction_id

    try:
        # Credit wallet
        wallet.balance = (Decimal(wallet.balance or 0) + amount).quantize(Decimal("0.01"))

        # Mark processed
        if hasattr(refund_tx, "status"):
            refund_tx.status = "Processed"

        db.commit()

    except Exception as e:
        db.rollback()
        # Mark failed (best-effort) and persist
        try:
            if hasattr(refund_tx, "status"):
                refund_tx.status = "Failed"
            db.add(refund_tx)
            db.commit()
        except Exception:
            db.rollback()

        xml = envelope_fail(500, f"REFUND_FAILED {e}", request_fields=req_fields)
        return Response(content=xml, media_type="application/xml")

    # Success
    response_inner = (
        f"<RESULT>OK</RESULT>"
        f"<EXTSYSTEMTRANSACTIONID>{refund_tx.transaction_id}</EXTSYSTEMTRANSACTIONID>"
    )
    xml = envelope_ok(response_inner_xml=response_inner, request_fields=req_fields)
    return Response(content=xml, media_type="application/xml")
