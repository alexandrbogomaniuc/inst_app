from __future__ import annotations
import hashlib
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session
from jose import jwt, JWTError

from ...db import get_db
from ...models import Player, Wallet
from ...config import settings
from ...utils.account import ensure_wallets_for_user
from .settings import bsg_settings, get_bank_settings, list_available_banks

router = APIRouter(prefix="/betsoft", tags=["betsoft"])

def md5_hex(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()

def debug(msg: str) -> None:
    print(f"[BSG] {msg}")

def xml_response(request_tags: Dict[str, Any], response_tags: Dict[str, Any]) -> Response:
    def tags_to_xml(d: Dict[str, Any]) -> str:
        parts = []
        for k, v in d.items():
            if v is None:
                continue
            parts.append(f"<{k.upper()}>{str(v)}</{k.upper()}>")
        return "".join(parts)

    now = datetime.now(timezone.utc).strftime("%d %b %Y %H:%M:%S")
    body = (
        "<EXTSYSTEM>"
        f"<REQUEST>{tags_to_xml(request_tags)}</REQUEST>"
        f"<TIME>{now}</TIME>"
        f"<RESPONSE>{tags_to_xml(response_tags)}</RESPONSE>"
        "</EXTSYSTEM>"
    )
    return Response(content=body, media_type="application/xml")

def to_cents(dec: Decimal) -> int:
    return int((dec * 100).quantize(Decimal("1")))

def from_cents(cents: int) -> Decimal:
    return (Decimal(cents) / Decimal(100)).quantize(Decimal("0.01"))

def resolve_bank_id(bank_id_param: str | None) -> str:
    if bank_id_param:
        return bank_id_param
    if bsg_settings.BSG_DEFAULT_BANK_ID:
        return bsg_settings.BSG_DEFAULT_BANK_ID
    banks = list_available_banks()
    if not banks:
        raise HTTPException(status_code=500, detail="No BSG bank configured")
    return banks[0]

def wallet_for_player(db: Session, user_id: int, currency_code: str | None) -> Wallet:
    q = db.query(Wallet).filter(Wallet.userId == user_id)
    if currency_code:
        w = q.filter(Wallet.currency_code == currency_code).first()
        if w:
            return w
    w = q.order_by(Wallet.wallet_id.asc()).first()
    if not w:
        ensure_wallets_for_user(db, user_id)
        w = q.order_by(Wallet.wallet_id.asc()).first()
    return w

def verify_token_local(token: str) -> dict:
    try:
        return jwt.decode(token, settings.JWT_SIGNING_KEY, algorithms=["HS256"])
    except JWTError as ex:
        raise HTTPException(status_code=400, detail=f"Invalid token: {ex}")


@router.get("/authenticate")
async def authenticate(
    token: str,
    hash: str,
    bankId: str | None = None,
    clientType: str | None = None,
    db: Session = Depends(get_db),
):
    bank_id = resolve_bank_id(bankId)
    bank = get_bank_settings(bank_id)
    hash_str = f"{token}{bank.BSG_PASS_KEY}"
    debug(f"AUTH: bankId={bank_id} token={token!r} calc_md5({hash_str})")
    if md5_hex(hash_str) != hash.lower():
        return xml_response({"token": token, "hash": hash, "bankId": bank_id}, {"RESULT": "ERROR", "CODE": 500})

    claims = verify_token_local(token)
    user_id = int(claims.get("uid", 0))
    if not user_id:
        return xml_response({"token": token, "hash": hash, "bankId": bank_id}, {"RESULT": "ERROR", "CODE": 400})

    player = db.query(Player).filter(Player.userId == user_id).first()
    if not player:
        return xml_response({"token": token, "hash": hash, "bankId": bank_id}, {"RESULT": "ERROR", "CODE": 399})

    currency = bank.BSG_DEFAULT_CURRENCY or bsg_settings.BSG_DEFAULT_CURRENCY
    w = wallet_for_player(db, user_id, currency)
    balance_cents = to_cents(w.balance)

    return xml_response(
        {"token": token, "hash": hash, "bankId": bank_id},
        {
            "RESULT": "OK",
            "USERID": player.userId,
            "USERNAME": player.user_name or "",
            "EMAIL": player.email or "",
            "CURRENCY": w.currency_code,
            "BALANCE": balance_cents,
        },
    )


@router.get("/balance")
async def get_balance(
    userId: str,
    bankId: str | None = None,
    db: Session = Depends(get_db),
):
    bank_id = resolve_bank_id(bankId)
    player = db.query(Player).filter(Player.userId == int(userId)).first()
    if not player:
        return xml_response({"userId": userId, "bankId": bank_id}, {"RESULT": "ERROR", "CODE": 310})
    bank = get_bank_settings(bank_id)
    currency = bank.BSG_DEFAULT_CURRENCY or bsg_settings.BSG_DEFAULT_CURRENCY
    w = wallet_for_player(db, player.userId, currency)
    return xml_response({"userId": userId, "bankId": bank_id}, {"RESULT": "OK", "BALANCE": to_cents(w.balance)})


@router.get("/account")
async def get_account(
    userId: str,
    hash: str,
    bankId: str | None = None,
    db: Session = Depends(get_db),
):
    bank_id = resolve_bank_id(bankId)
    bank = get_bank_settings(bank_id)
    hash_str = f"{userId}{bank.BSG_PASS_KEY}"
    debug(f"ACCOUNT: bankId={bank_id} userId={userId} calc_md5({hash_str})")
    if md5_hex(hash_str) != hash.lower():
        return xml_response({"userId": userId, "hash": hash, "bankId": bank_id}, {"RESULT": "ERROR", "CODE": 500})

    player = db.query(Player).filter(Player.userId == int(userId)).first()
    if not player:
        return xml_response({"userId": userId, "hash": hash, "bankId": bank_id}, {"RESULT": "ERROR", "CODE": 310})

    currency = bank.BSG_DEFAULT_CURRENCY or bsg_settings.BSG_DEFAULT_CURRENCY
    w = wallet_for_player(db, player.userId, currency)

    return xml_response(
        {"userId": userId, "hash": hash, "bankId": bank_id},
        {
            "RESULT": "OK",
            "USERNAME": player.user_name or "",
            "FIRSTNAME": player.first_name or "",
            "LASTNAME": player.last_name or "",
            "EMAIL": player.email or "",
            "CURRENCY": w.currency_code,
        },
    )


@router.get("/betResult")
async def bet_result(
    userId: str,
    bet: str | None = None,
    win: str | None = None,
    roundId: str | None = None,
    gameId: str | None = None,
    gameSessionId: str | None = None,
    isRoundFinished: str | None = None,
    negativeBet: str | None = None,
    promoWinAmount: str | None = None,
    jpWin: str | None = None,
    jpContribution: str | None = None,
    token: str | None = None,
    clientType: str | None = None,
    bankId: str | None = None,
    hash: str = "",
    db: Session = Depends(get_db),
):
    bank_id = resolve_bank_id(bankId)
    bank = get_bank_settings(bank_id)

    parts = [userId]
    if bet is not None: parts.append(bet)
    if win is not None: parts.append(win)
    if isRoundFinished is not None: parts.append(isRoundFinished)
    if roundId is not None: parts.append(roundId)
    if gameId is not None: parts.append(gameId)
    hash_str = "".join(parts) + bank.BSG_PASS_KEY
    debug(f"BETRESULT: bankId={bank_id} userId={userId} bet={bet} win={win} roundId={roundId} gameId={gameId} isRoundFinished={isRoundFinished} calc_md5({hash_str})")
    if md5_hex(hash_str) != hash.lower():
        return xml_response({"USERID": userId, "HASH": hash, "bankId": bank_id}, {"RESULT": "ERROR", "CODE": 500})

    player = db.query(Player).filter(Player.userId == int(userId)).first()
    if not player:
        return xml_response({"USERID": userId, "HASH": hash, "bankId": bank_id}, {"RESULT": "ERROR", "CODE": 310})

    currency = bank.BSG_DEFAULT_CURRENCY or bsg_settings.BSG_DEFAULT_CURRENCY
    w = wallet_for_player(db, player.userId, currency)
    balance_cents = to_cents(w.balance)

    if bet:
        try:
            bet_amount_str, casino_tx_id = bet.split("|", 1)
            amt_cents = int(bet_amount_str)
        except Exception:
            return xml_response({"USERID": userId, "BET": bet, "bankId": bank_id}, {"RESULT": "ERROR", "CODE": 301})
        if amt_cents > balance_cents:
            return xml_response({"USERID": userId, "BET": bet, "bankId": bank_id}, {"RESULT": "ERROR", "CODE": 300})

        balance_cents -= amt_cents
        w.balance = from_cents(balance_cents)
        db.commit()

        ext_tx_id = f"{userId}_{roundId or 'r'}_{casino_tx_id}"
        return xml_response(
            {"USERID": userId, "BET": bet, "ROUNDID": roundId, "GAMEID": gameId, "GAMESESSIONID": gameSessionId, "ISROUNDFINISHED": isRoundFinished, "HASH": hash, "bankId": bank_id},
            {"RESULT": "OK", "EXTSYSTEMTRANSACTIONID": ext_tx_id, "BALANCE": balance_cents},
        )

    if win:
        try:
            win_amount_str, casino_tx_id = win.split("|", 1)
            amt_cents = int(win_amount_str)
        except Exception:
            return xml_response({"USERID": userId, "WIN": win, "bankId": bank_id}, {"RESULT": "ERROR", "CODE": 301})

        neg_cents = int(negativeBet) if negativeBet else 0
        promo_cents = int(promoWinAmount) if promoWinAmount else 0
        balance_cents += amt_cents + neg_cents + promo_cents
        w.balance = from_cents(balance_cents)
        db.commit()

        ext_tx_id = f"{userId}_{roundId or 'r'}_{casino_tx_id}"
        return xml_response(
            {"USERID": userId, "WIN": win, "ROUNDID": roundId, "GAMEID": gameId, "GAMESESSIONID": gameSessionId, "ISROUNDFINISHED": isRoundFinished, "HASH": hash, "bankId": bank_id},
            {"RESULT": "OK", "EXTSYSTEMTRANSACTIONID": ext_tx_id, "BALANCE": balance_cents},
        )

    return xml_response({"USERID": userId, "HASH": hash, "bankId": bank_id}, {"RESULT": "ERROR", "CODE": 301})


@router.get("/refundBet")
async def refund_bet(
    userId: str,
    casinoTransactionId: str,
    hash: str,
    bankId: str | None = None,
    gameId: str | None = None,
    amount: str | None = None,
    roundId: str | None = None,
    token: str | None = None,
    db: Session = Depends(get_db),
):
    bank_id = resolve_bank_id(bankId)
    bank = get_bank_settings(bank_id)
    hash_str = f"{userId}{casinoTransactionId}{bank.BSG_PASS_KEY}"
    debug(f"REFUND: bankId={bank_id} userId={userId} casinoTransactionId={casinoTransactionId} calc_md5({hash_str})")
    if md5_hex(hash_str) != hash.lower():
        return xml_response({"USERID": userId, "CASINOTRANSACTIONID": casinoTransactionId, "HASH": hash, "bankId": bank_id}, {"RESULT": "ERROR", "CODE": 500})

    player = db.query(Player).filter(Player.userId == int(userId)).first()
    if not player:
        return xml_response({"USERID": userId, "CASINOTRANSACTIONID": casinoTransactionId, "bankId": bank_id}, {"RESULT": "ERROR", "CODE": 310})

    if amount:
        currency = bank.BSG_DEFAULT_CURRENCY or bsg_settings.BSG_DEFAULT_CURRENCY
        w = wallet_for_player(db, player.userId, currency)
        balance_cents = to_cents(w.balance) + int(amount)
        w.balance = from_cents(balance_cents)
        db.commit()

    ext_tx_id = f"{userId}_{roundId or 'r'}_{casinoTransactionId}"
    return xml_response(
        {"USERID": userId, "CASINOTRANSACTIONID": casinoTransactionId, "HASH": hash, "bankId": bank_id},
        {"RESULT": "OK", "EXTSYSTEMTRANSACTIONID": ext_tx_id},
    )


@router.get("/bonusRelease")
async def bonus_release(
    userId: str,
    bonusId: str,
    amount: str,
    hash: str,
    bankId: str | None = None,
    token: str | None = None,
    db: Session = Depends(get_db),
):
    bank_id = resolve_bank_id(bankId)
    bank = get_bank_settings(bank_id)
    hash_str = f"{userId}{bonusId}{amount}{bank.BSG_PASS_KEY}"
    debug(f"BONUS_RELEASE: bankId={bank_id} uid={userId} bonusId={bonusId} amount={amount} calc_md5({hash_str})")
    if md5_hex(hash_str) != hash.lower():
        return xml_response({"USERID": userId, "BONUSID": bonusId, "AMOUNT": amount, "HASH": hash, "bankId": bank_id}, {"RESULT": "ERROR", "CODE": 500})

    player = db.query(Player).filter(Player.userId == int(userId)).first()
    if not player:
        return xml_response({"USERID": userId, "bankId": bank_id}, {"RESULT": "ERROR", "CODE": 310})

    currency = bank.BSG_DEFAULT_CURRENCY or bsg_settings.BSG_DEFAULT_CURRENCY
    w = wallet_for_player(db, player.userId, currency)
    balance_cents = to_cents(w.balance) + int(amount)
    w.balance = from_cents(balance_cents)
    db.commit()

    return xml_response({"USERID": userId, "BONUSID": bonusId, "AMOUNT": amount, "HASH": hash, "bankId": bank_id}, {"RESULT": "OK"})


@router.get("/bonusWin")
async def bonus_win(
    userId: str,
    bonusId: str,
    amount: str,
    transactionId: str,
    hash: str,
    bankId: str | None = None,
    status: str | None = None,
    gameId: str | None = None,
    roundId: str | None = None,
    isRoundFinished: str | None = None,
    gameSessionId: str | None = None,
    clientType: str | None = None,
    token: str | None = None,
    db: Session = Depends(get_db),
):
    bank_id = resolve_bank_id(bankId)
    bank = get_bank_settings(bank_id)
    hash_str = f"{userId}{bonusId}{amount}{bank.BSG_PASS_KEY}"
    debug(f"BONUS_WIN: bankId={bank_id} uid={userId} bonusId={bonusId} amount={amount} tx={transactionId} calc_md5({hash_str})")
    if md5_hex(hash_str) != hash.lower():
        return xml_response(
            {"USERID": userId, "BONUSID": bonusId, "AMOUNT": amount, "TRANSACTIONID": transactionId, "HASH": hash, "STATUS": status, "bankId": bank_id},
            {"RESULT": "ERROR", "CODE": 500},
        )

    player = db.query(Player).filter(Player.userId == int(userId)).first()
    if not player:
        return xml_response({"USERID": userId, "bankId": bank_id}, {"RESULT": "ERROR", "CODE": 631})

    currency = bank.BSG_DEFAULT_CURRENCY or bsg_settings.BSG_DEFAULT_CURRENCY
    w = wallet_for_player(db, player.userId, currency)
    balance_cents = to_cents(w.balance) + int(amount)
    w.balance = from_cents(balance_cents)
    db.commit()

    return xml_response(
        {"USERID": userId, "BONUSID": bonusId, "AMOUNT": amount, "TRANSACTIONID": transactionId, "HASH": hash, "STATUS": status, "bankId": bank_id},
        {"RESULT": "OK", "BALANCE": balance_cents},
    )
