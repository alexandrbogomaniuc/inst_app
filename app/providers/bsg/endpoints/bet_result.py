from __future__ import annotations

from decimal import Decimal, ROUND_DOWN
from typing import Optional, Tuple, List
from urllib.parse import unquote_plus

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from igw.app.db import get_db
from igw.app.models import Wallet
from igw.app.models_gameplay import GameplayTransaction
from ..settings import get_bank_settings, resolve_bank_id
from ..helpers import md5_hex, wallet_cents
from ..xml.utils import envelope_fail, envelope_bet_ok

router = APIRouter()

# ---------- helpers ----------

def _parse_amount_and_ext(value: Optional[str]) -> Tuple[Optional[int], Optional[str]]:
    """
    Parse strings like "80|2629682833" into (80, "2629682833").
    Returns (None, None) if value is None or empty.
    """
    if not value:
        return None, None
    raw = unquote_plus(value)
    if "|" in raw:
        left, right = raw.split("|", 1)
        left = left.strip()
        right = right.strip()
        if left == "":
            amt = 0
        else:
            try:
                amt = int(left)
            except ValueError:
                amt = None
        ext = right or None
        return amt, ext
    # fallback: amount only
    try:
        amt = int(raw.strip())
    except ValueError:
        amt = None
    return amt, None


def _hash_for_bet_result(
    user_id: int,
    bet_raw: Optional[str],
    win_raw: Optional[str],
    is_round_finished: Optional[str],
    round_id: Optional[str],
    game_id: Optional[str],
    pass_key: str,
) -> Tuple[str, str]:
    """
    MD5(userId + bet + win + isRoundFinished + roundId + gameId + passkey)
    - bet / win absent => empty string
    - isRoundFinished absent => omit entirely
    - if present, normalize to lower-case 'true'/'false'
    """
    bet_part = unquote_plus(bet_raw) if bet_raw else ""
    win_part = unquote_plus(win_raw) if win_raw else ""

    parts: List[str] = [str(user_id), bet_part, win_part]
    if is_round_finished is not None:
        parts.append(str(is_round_finished).lower())
    parts.extend([str(round_id or ""), str(game_id or ""), pass_key])
    concat = "".join(parts)
    return md5_hex(concat), concat


def _get_or_create_wallet(db: Session, user_id: int, currency_code: str) -> Wallet:
    w: Wallet | None = (
        db.query(Wallet)
        .filter(Wallet.userId == user_id, Wallet.currency_code == currency_code)
        .with_for_update(read=True)
        .first()
    )
    if w:
        return w
    w = Wallet(userId=user_id, currency_code=currency_code, balance=Decimal("0.00"))
    db.add(w)
    db.flush()
    return w


def _apply_amount_to_wallet(w: Wallet, cents: int, *, op: str) -> None:
    """
    op='debit' => subtract; op='credit' => add. cents are integer minor units.
    """
    delta = (Decimal(cents) / Decimal(100)).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    if op == "debit":
        w.balance = (Decimal(w.balance or 0) - delta).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    else:
        w.balance = (Decimal(w.balance or 0) + delta).quantize(Decimal("0.01"), rounding=ROUND_DOWN)


# ---------- endpoint ----------

@router.get("/betResult")
async def bet_result(
    request: Request,
    bankId: int = Query(...),
    userId: int = Query(...),
    gameId: str = Query(...),
    roundId: str = Query(...),
    hash: str = Query(...),
    token: Optional[str] = Query(None),         # echoed only
    bet: Optional[str] = Query(None),
    win: Optional[str] = Query(None),
    isRoundFinished: Optional[str] = Query(None),
    gameSessionId: Optional[str] = Query(None),
    clientType: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """
    Accepts bet-only, win-only, or both.
    Updates wallet: bet -> debit, win -> credit.
    Idempotent by (userId, bank_id, transaction_type, external_transaction_id).
    Responds with EXTSYSTEM XML including EXTSYSTEMTRANSACTIONID and BALANCE.
    """
    resolved_bank_id = resolve_bank_id(bankId)
    bank = get_bank_settings(resolved_bank_id)

    # Echo the request in the expected order
    req_fields = [
        ("USERID", userId),
        ("BET", unquote_plus(bet) if bet else ""),
        ("WIN", unquote_plus(win) if win else ""),
        ("ISROUNDFINISHED", str(isRoundFinished).lower() if isRoundFinished is not None else ""),
        ("ROUNDID", roundId),
        ("GAMEID", gameId),
        ("HASH", hash),
        ("GAMESESSIONID", gameSessionId or ""),
        ("CLIENTTYPE", clientType or ""),
    ]

    # At least one of bet/win must be present
    if not bet and not win:
        xml = envelope_fail(400, "missing parameters: bet and/or win", request_fields=req_fields)
        return Response(content=xml, media_type="application/xml")

    # Validate hash
    expected_md5, _concat = _hash_for_bet_result(
        user_id=userId,
        bet_raw=bet or "",
        win_raw=win or "",
        is_round_finished=isRoundFinished,
        round_id=roundId,
        game_id=gameId,
        pass_key=bank.BSG_PASS_KEY,
    )
    if expected_md5.lower() != hash.lower():
        xml = envelope_fail(401, "invalid hash", request_fields=req_fields)
        return Response(content=xml, media_type="application/xml")

    # Parse bet and win (amount in cents + external id)
    bet_cents, bet_ext = _parse_amount_and_ext(bet)
    win_cents, win_ext = _parse_amount_and_ext(win)

    # Open / create wallet (bank default currency)
    currency = bank.BSG_DEFAULT_CURRENCY or "USD"
    w = _get_or_create_wallet(db, userId, currency)

    # Process bet (debit) if present and not already processed
    if bet_ext is not None and bet_cents is not None:
        try:
            tx = GameplayTransaction(
                userId=userId,
                wallet_id=w.wallet_id,
                bank_id=resolved_bank_id,
                transaction_type="bet",
                amount=Decimal(bet_cents) / Decimal(100),
                status="Pending",
                description=None,
                external_transaction_id=str(bet_ext),
                external_gamesession_id=str(gameSessionId or ""),
                external_gameround_id=str(roundId or ""),
                external_game_id=str(gameId or ""),
                ISROUNDFINISHED=str(isRoundFinished).lower() if isRoundFinished is not None else None,
            )
            db.add(tx)
            _apply_amount_to_wallet(w, bet_cents, op="debit")
            tx.status = "Processed"
            db.flush()
        except IntegrityError:
            db.rollback()
            # Already processed bet => no double-debit
        except Exception:
            db.rollback()
            xml = envelope_fail(500, "internal error applying bet", request_fields=req_fields)
            return Response(content=xml, media_type="application/xml")

    # Process win (credit) if present and not already processed
    if win_ext is not None and win_cents is not None:
        try:
            tx = GameplayTransaction(
                userId=userId,
                wallet_id=w.wallet_id,
                bank_id=resolved_bank_id,
                transaction_type="win",
                amount=Decimal(win_cents) / Decimal(100),
                status="Pending",
                description=None,
                external_transaction_id=str(win_ext),
                external_gamesession_id=str(gameSessionId or ""),
                external_gameround_id=str(roundId or ""),
                external_game_id=str(gameId or ""),
                ISROUNDFINISHED=str(isRoundFinished).lower() if isRoundFinished is not None else None,
            )
            db.add(tx)
            if win_cents and win_cents > 0:
                _apply_amount_to_wallet(w, win_cents, op="credit")
            tx.status = "Processed"
            db.flush()
        except IntegrityError:
            db.rollback()
            # Already processed win => no double-credit
        except Exception:
            db.rollback()
            xml = envelope_fail(500, "internal error applying win", request_fields=req_fields)
            return Response(content=xml, media_type="application/xml")

    # Commit
    try:
        db.commit()
    except Exception:
        db.rollback()
        xml = envelope_fail(500, "internal error committing", request_fields=req_fields)
        return Response(content=xml, media_type="application/xml")

    # Balance in cents for response
    balance_after_cents = wallet_cents(db, userId, currency)

    # Choose external id to echo back: prefer WIN if present, else BET
    ext_id = win_ext or bet_ext or ""

    xml = envelope_bet_ok(
        ext_system_transaction_id=str(ext_id),
        balance_cents=balance_after_cents,
        request_fields=req_fields,
    )
    return Response(content=xml, media_type="application/xml")
