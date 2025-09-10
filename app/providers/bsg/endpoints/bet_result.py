from __future__ import annotations

from decimal import Decimal
from typing import Optional
from urllib.parse import unquote_plus

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from igw.app.db import get_db
from igw.app.models import Wallet
from igw.app.utils.security import decode_token

from ..settings import bsg_settings, get_bank_settings, resolve_bank_id
from ..xml.utils import envelope_fail, envelope_bet_ok
from ..wallet_utils import get_wallet_for_user  # returns Wallet + creates if missing
from ..helpers import md5_hex_bet, decode_bet_param

router = APIRouter()


def _cents_from_wallet(w: Wallet) -> int:
    bal = Decimal(w.balance or 0)
    return int((bal * Decimal("100")).quantize(Decimal("1")))


@router.get("/betResult")
async def bet_result(
    request: Request,
    token: str = Query(...),
    userId: int = Query(...),
    bet: str = Query(...),
    gameId: str = Query(...),
    roundId: str = Query(...),
    hash: str = Query(...),
    bankId: int | None = Query(None),
    isRoundFinished: Optional[str] = Query(None),
    win: Optional[str] = Query(None),
    clientType: Optional[str] = Query(None),
    gameSessionId: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """
    Idempotent bet handler:
    - Validate hash per provider rule (with URL-decoded bet string).
    - If a matching processed/pending transaction exists -> don't change wallet, return OK.
    - Otherwise insert Pending row, debit wallet, set Processed, and return OK.
    """

    # Resolve bank + protocol
    bank_id = resolve_bank_id(bankId)
    bank = get_bank_settings(bank_id)
    if (bank.BSG_PROTOCOL or "xml").lower() != "xml":
        xml = envelope_fail(400, "Bank protocol mismatch: expected xml",
                            request_fields={"USERID": str(userId)})
        return Response(content=xml, media_type="application/xml")

    # Decode the JWT just to ensure it's ours (we don't use payload fields further here)
    try:
        decode_token(token)
    except Exception as e:
        xml = envelope_fail(401, f"INVALID_TOKEN {e}",
                            request_fields={"USERID": str(userId)})
        return Response(content=xml, media_type="application/xml")

    # *** IMPORTANT: bet must be URL-decoded before hashing ***
    bet_decoded = unquote_plus(bet)

    # Hash check (order: userId, bet, win, isRoundFinished, roundId, gameId)
    expected = md5_hex_bet(
        user_id=str(userId),
        bet=bet_decoded,
        win=win or "",
        is_round_finished=(isRoundFinished or ""),
        round_id=roundId,
        game_id=gameId,
        pass_key=bank.BSG_PASS_KEY,
    )
    if expected.lower() != (hash or "").lower():
        xml = envelope_fail(
            401, "invalid hash",
            request_fields={
                "USERID": str(userId),
                "BET": bet_decoded,
                "WIN": win or "",
                "ISROUNDFINISHED": isRoundFinished or "",
                "ROUNDID": roundId,
                "GAMEID": gameId,
                "HASH": hash or "",
            },
        )
        return Response(content=xml, media_type="application/xml")

    # Split bet into cents + external_transaction_id
    # Example: "80|2629682819" => 80 cents, "2629682819" external tx id
    try:
        bet_cents_str, external_tx_id = bet_decoded.split("|", 1)
        bet_cents = int(bet_cents_str)
    except Exception:
        xml = envelope_fail(400, "bad bet format",
                            request_fields={"USERID": str(userId), "BET": bet_decoded})
        return Response(content=xml, media_type="application/xml")

    # Check for idempotency BEFORE inserting
    existing = db.execute(
        text("""
            SELECT transaction_id, status
            FROM gameplay_transactions
            WHERE userId = :uid AND bank_id = :bank_id
              AND transaction_type = 'bet'
              AND external_transaction_id = :ext_id
            LIMIT 1
        """),
        {"uid": userId, "bank_id": bank_id, "ext_id": external_tx_id},
    ).first()

    # Get (or create) wallet for default currency
    currency = bank.BSG_DEFAULT_CURRENCY or "USD"
    wallet = get_wallet_for_user(db, userId, currency)  # SELECT ... FOR UPDATE inside

    if existing:
        # Already seen. Don't change wallet again — return OK with same internal trx id
        xml = envelope_bet_ok(
            request_fields={
                "USERID": str(userId),
                "BET": bet_decoded,
                "WIN": win or "",
                "ISROUNDFINISHED": isRoundFinished or "",
                "ROUNDID": roundId,
                "GAMEID": gameId,
                "HASH": hash or "",
                "GAMESESSIONID": gameSessionId or "",
                "NEGATIVEBET": "0",
                "CLIENTTYPE": clientType or "",
            },
            extsystem_transaction_id=str(existing.transaction_id),  # our internal id
            balance_cents=_cents_from_wallet(wallet),
        )
        return Response(content=xml, media_type="application/xml")

    # Insert Pending transaction
    ins = db.execute(
        text("""
            INSERT INTO gameplay_transactions (
                userId, wallet_id, bank_id, transaction_type, amount, status,
                description, external_transaction_id, external_gamesession_id,
                external_gameround_id, external_game_id, ISROUNDFINISHED
            ) VALUES (
                :uid, :wallet_id, :bank_id, 'bet', :amount, 'Pending',
                :descr, :ext_id, :gsid, :grid, :gid, :irf
            )
        """),
        {
            "uid": userId,
            "wallet_id": wallet.wallet_id,
            "bank_id": bank_id,
            "amount": Decimal(bet_cents) / Decimal("100"),
            "descr": None,
            "ext_id": external_tx_id,
            "gsid": gameSessionId or None,
            "grid": roundId,
            "gid": gameId,
            "irf": isRoundFinished if isRoundFinished in ("true", "false") else None,
        },
    )
    # Get the generated internal transaction id
    trx_id = db.execute(text("SELECT LAST_INSERT_ID()")).scalar()

    # Debit wallet (allow negative for now; add limit checks if required)
    wallet.balance = (Decimal(wallet.balance or 0) - (Decimal(bet_cents) / Decimal("100")))
    db.add(wallet)

    # Mark transaction as Processed
    db.execute(
        text("""
            UPDATE gameplay_transactions
            SET status = 'Processed'
            WHERE transaction_id = :tid
        """),
        {"tid": trx_id},
    )

    db.commit()

    # Return OK with our internal transaction id + new balance (cents)
    xml = envelope_bet_ok(
        request_fields={
            "USERID": str(userId),
            "BET": bet_decoded,
            "WIN": win or "",
            "ISROUNDFINISHED": isRoundFinished or "",
            "ROUNDID": roundId,
            "GAMEID": gameId,
            "HASH": hash or "",
            "GAMESESSIONID": gameSessionId or "",
            "NEGATIVEBET": "0",
            "CLIENTTYPE": clientType or "",
        },
        extsystem_transaction_id=str(trx_id),
        balance_cents=_cents_from_wallet(wallet),
    )
    return Response(content=xml, media_type="application/xml")
