from __future__ import annotations

import hashlib
from decimal import Decimal
from typing import Optional
from urllib.parse import unquote_plus

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from igw.app.db import get_db
from igw.app.models import Wallet
from igw.app.models_gameplay import GameplayTransaction  # NEW: small dedicated model
from igw.app.utils.security import decode_token
from ..settings import get_bank_settings, resolve_bank_id
from ..helpers import media_response, wallet_cents
from ..xml.utils import envelope_fail, envelope_bet_ok

router = APIRouter()


def _normalize_bool_to_bsg(val: Optional[str]) -> str:
    if val is None:
        return ""
    s = str(val).strip().lower()
    if s in ("true", "false", ""):
        return s
    if s in ("1", "y", "yes", "t"):
        return "true"
    if s in ("0", "n", "no", "f"):
        return "false"
    return s


def _md5_bet(
    *,
    user_id: int | str | None,
    bet_raw: str | None,            # may be url-encoded like '80%7C2629'
    win: str | None,
    is_round_finished: str | None,  # expect 'true'/'false' or empty
    round_id: str | None,
    game_id: str | None,
    pass_key: str,
) -> str:
    user_s = "" if user_id is None else str(user_id)
    # IMPORTANT: decode bet BEFORE hashing per BSG spec
    bet_s = "" if bet_raw is None else unquote_plus(str(bet_raw))
    win_s = "" if win is None else str(win)
    isrf_s = _normalize_bool_to_bsg(is_round_finished)
    round_s = "" if round_id is None else str(round_id)
    game_s = "" if game_id is None else str(game_id)
    concat = f"{user_s}{bet_s}{win_s}{isrf_s}{round_s}{game_s}{pass_key}"
    digest = hashlib.md5(concat.encode("utf-8")).hexdigest()
    print(f"[BSG/betResult] concat='{concat}' expected_md5='{digest}'")
    return digest


@router.get("/betResult")
async def bet_result(
    request: Request,
    bankId: int | None = Query(None),
    userId: int | None = Query(None),
    bet: str | None = Query(None),            # "80|2629..." (URL-encoded in query)
    win: str | None = Query(None),            # may be omitted -> '' for hash
    isRoundFinished: str | None = Query(None),
    roundId: str | None = Query(None),
    gameId: str | None = Query(None),
    gameSessionId: str | None = Query(None),
    clientType: str | None = Query(None),
    hash: str | None = Query(None),
    token: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """
    BSG bet result:

    Hash must be:
      MD5(userId + bet + win + isRoundFinished + roundId + gameId + passkey)
      where 'bet' is URL-decoded *before* hashing (e.g. '80%7C123' -> '80|123').
      'win' may be absent -> treated as '' for hashing.

    On new bet: create 'Pending' tx, deduct wallet, set 'Processed', return:
      <RESULT>OK</RESULT>
      <EXTSYSTEMTRANSACTIONID>{external_tx_id}</EXTSYSTEMTRANSACTIONID>
      <BALANCE>{balance_in_cents}</BALANCE>

    Idempotency: if an identical external tx (type 'bet'/'win') is already Processed,
    do NOT change balance again; return OK with current balance.
    """
    resolved_bank_id = resolve_bank_id(bankId)
    bank = get_bank_settings(resolved_bank_id)
    protocol = (bank.BSG_PROTOCOL or "xml").lower()

    if protocol != "xml":
        return media_response({"result": "failed", "code": 415, "reason": "xml-only bank"}, "json")

    # REQUEST echo (what BSG wants to see back)
    bet_decoded = unquote_plus(bet) if bet is not None else ""
    req_fields = {
        "USERID": str(userId) if userId is not None else "",
        "BET": bet_decoded,
        "WIN": "" if win is None else str(win),
        "ISROUNDFINISHED": isRoundFinished or "",
        "ROUNDID": roundId or "",
        "GAMEID": gameId or "",
        "HASH": hash or "",
        "GAMESESSIONID": gameSessionId or "",
        "CLIENTTYPE": clientType or "",
    }

    # Basic required params
    if userId is None or bet is None or roundId is None or gameId is None or not hash:
        xml = envelope_fail(400, "missing required params", request_fields=req_fields)
        return Response(content=xml, media_type="application/xml")

    # Verify hash
    expected = _md5_bet(
        user_id=userId,
        bet_raw=bet,  # keep encoded; helper will unquote internally
        win=win,
        is_round_finished=isRoundFinished,
        round_id=roundId,
        game_id=gameId,
        pass_key=bank.BSG_PASS_KEY,
    )
    if expected.lower() != (hash or "").lower():
        xml = envelope_fail(401, "invalid hash", request_fields=req_fields)
        return Response(content=xml, media_type="application/xml")

    # Extract "cents|ext_tx_id" from decoded bet
    try:
        bet_cents_str, ext_tx_id = bet_decoded.split("|", 1)
    except ValueError:
        xml = envelope_fail(400, "malformed bet", request_fields=req_fields)
        return Response(content=xml, media_type="application/xml")

    try:
        bet_cents = int(bet_cents_str)
    except ValueError:
        xml = envelope_fail(400, "invalid bet amount", request_fields=req_fields)
        return Response(content=xml, media_type="application/xml")

    # Idempotency: already processed?
    existing = (
        db.query(GameplayTransaction)
        .filter(
            GameplayTransaction.userId == userId,
            GameplayTransaction.bank_id == resolved_bank_id,
            GameplayTransaction.transaction_type.in_(["bet", "win"]),
            GameplayTransaction.external_transaction_id == ext_tx_id,
        )
        .first()
    )
    if existing and existing.status == "Processed":
        currency = bank.BSG_DEFAULT_CURRENCY or "USD"
        bal_cents = wallet_cents(db, userId, currency)
        xml = envelope_bet_ok(
            ext_system_transaction_id=ext_tx_id,
            balance_cents=bal_cents,
            request_fields=req_fields,
        )
        return Response(content=xml, media_type="application/xml")

    # Load/create wallet
    currency = bank.BSG_DEFAULT_CURRENCY or "USD"
    wallet: Wallet | None = (
        db.query(Wallet)
        .filter(Wallet.userId == userId, Wallet.currency_code == currency)
        .first()
    )
    if not wallet:
        wallet = Wallet(userId=userId, currency_code=currency, balance=Decimal("0.00"))
        db.add(wallet)
        db.flush()

    # Create pending tx
    tx = GameplayTransaction(
        userId=userId,
        wallet_id=wallet.wallet_id,
        bank_id=resolved_bank_id,
        transaction_type="bet",
        amount=Decimal(bet_cents) / Decimal(100),
        status="Pending",
        description=None,
        external_transaction_id=ext_tx_id,
        external_gamesession_id=gameSessionId or None,
        external_gameround_id=roundId or None,
        external_game_id=str(gameId) if gameId is not None else None,
        ISROUNDFINISHED=isRoundFinished or None,
    )
    db.add(tx)
    db.flush()

    # Deduct and finalize
    try:
        wallet.balance = (wallet.balance or Decimal("0.00")) - (Decimal(bet_cents) / Decimal(100))
        db.flush()
        tx.status = "Processed"
        db.commit()
    except Exception as e:
        db.rollback()
        tx.status = "Failed"
        db.add(tx)
        db.commit()
        xml = envelope_fail(500, f"wallet update failed: {e}", request_fields=req_fields)
        return Response(content=xml, media_type="application/xml")

    # OK with new balance (cents) + external tx id
    bal_cents = wallet_cents(db, userId, currency)
    xml = envelope_bet_ok(
        ext_system_transaction_id=ext_tx_id,
        balance_cents=bal_cents,
        request_fields=req_fields,
    )
    return Response(content=xml, media_type="application/xml")
