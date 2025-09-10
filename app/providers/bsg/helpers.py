from __future__ import annotations

import hashlib
from decimal import Decimal
from typing import Dict, Optional, Any, Union
from urllib.parse import unquote_plus

from fastapi.responses import HTMLResponse, JSONResponse, Response
from sqlalchemy.orm import Session

from igw.app.models import Wallet


# ------------------------------- Core utils (kept) -------------------------------

def md5_hex(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def media_response(payload: Any, protocol: str, *, status_code: int = 200) -> Response:
    """
    Return either XML (string) or JSON based on bank protocol.
    """
    if protocol == "json":
        if isinstance(payload, str):
            return JSONResponse({"payload": payload}, status_code=status_code)
        return JSONResponse(payload, status_code=status_code)
    # xml
    if not isinstance(payload, str):
        payload = str(payload)
    return HTMLResponse(payload, status_code=status_code, media_type="application/xml")


def hash_ok_token(token: str, pass_key: str, their_hash: Optional[str]) -> bool:
    """
    Validate MD5(token + PASS_KEY).
    """
    if not their_hash:
        return False
    expected = md5_hex(token + pass_key)
    return expected.lower() == their_hash.lower()


def hash_ok_user(user_id: int, pass_key: str, their_hash: Optional[str]) -> bool:
    """
    Validate MD5(userId + PASS_KEY).
    """
    if not their_hash:
        return False
    expected = md5_hex(f"{user_id}{pass_key}")
    return expected.lower() == their_hash.lower()


def echo_fields(token: Optional[str], hash_: Optional[str]) -> Dict[str, str]:
    return {"TOKEN": token or "", "HASH": hash_ or ""}


def echo_user_fields(user_id: Optional[int], hash_: Optional[str]) -> Dict[str, str]:
    return {"USERID": str(user_id) if user_id is not None else "", "HASH": hash_ or ""}


def wallet_cents(db: Session, uid: int, currency_code: str) -> int:
    """
    Return integer minor units for player's wallet in `currency_code`.
    """
    w: Wallet | None = (
        db.query(Wallet)
        .filter(Wallet.userId == uid, Wallet.currency_code == currency_code)
        .first()
    )
    if not w or w.balance is None:
        return 0
    return int(Decimal(w.balance) * 100)


# ------------------------------- New helpers for BSG hashes -------------------------------

def _concat_parts(*parts: Optional[Union[str, int, bool]]) -> str:
    """
    Concatenate parts as strings in order.
    None -> "" (empty). Booleans -> 'true' / 'false'.
    """
    out: list[str] = []
    for p in parts:
        if p is None:
            out.append("")
        elif isinstance(p, bool):
            out.append("true" if p else "false")
        else:
            out.append(str(p))
    return "".join(out)


def decode_bet_param(bet_raw: str) -> str:
    """
    BSG sends 'bet' URL-encoded (e.g. '80%7C2629682818'). We must hash the
    *decoded* value ('80|2629682818').
    """
    return unquote_plus(bet_raw)


def md5_hex_refund(user_id: Union[int, str], casino_transaction_id: Union[int, str], pass_key: str) -> str:
    """
    refund: MD5(userId + casinoTransactionId + passkey)
    """
    return md5_hex(_concat_parts(user_id, casino_transaction_id, pass_key))


def md5_hex_bet(
    user_id: Union[int, str],
    bet_decoded: str,
    win: Optional[Union[int, str]],
    is_round_finished: Optional[Union[bool, str]],
    round_id: Union[int, str],
    game_id: Union[int, str],
    pass_key: str,
) -> str:
    """
    betResult: MD5(userId + bet + win + isRoundFinished + roundId + gameId + passkey)

    - `bet_decoded` MUST be the decoded string ('80|2629682818').
    - `win` is optional; pass None if absent.
    - `is_round_finished` may be bool or 'true'/'false' string; both are handled.
    """
    return md5_hex(_concat_parts(user_id, bet_decoded, win, is_round_finished, round_id, game_id, pass_key))


__all__ = [
    # existing
    "md5_hex",
    "media_response",
    "hash_ok_token",
    "hash_ok_user",
    "echo_fields",
    "echo_user_fields",
    "wallet_cents",
    # new
    "decode_bet_param",
    "md5_hex_refund",
    "md5_hex_bet",
]
