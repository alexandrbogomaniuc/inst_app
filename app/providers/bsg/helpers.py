from __future__ import annotations

import hashlib
from decimal import Decimal
from typing import Dict, Optional, Any
from urllib.parse import unquote_plus

from fastapi.responses import HTMLResponse, JSONResponse, Response
from sqlalchemy.orm import Session

from igw.app.models import Wallet


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


# -------------------- BSG-specific helpers --------------------

def _normalize_bool_to_bsg(val: Any) -> str:
    """
    BSG expects 'true' / 'false' strings for isRoundFinished.
    If missing/None -> '' (empty string).
    """
    if val is None:
        return ""
    if isinstance(val, str):
        s = val.strip().lower()
        if s in ("true", "false", ""):
            return s
        # allow "0"/"1"/"yes"/"no" etc. -> coerce to true/false
        if s in ("1", "y", "yes", "t"):
            return "true"
        if s in ("0", "n", "no", "f"):
            return "false"
        return s
    return "true" if bool(val) else "false"


def md5_hex_bet(*args, **kwargs) -> str:
    """
    Compute betresult hash:

      MD5(userId + bet + win + isRoundFinished + roundId + gameId + passkey)

    Accepts either positional:
        (user_id, bet, win, is_round_finished, round_id, game_id, pass_key)
    or keyword (snake_case and camelCase):
        user_id/userId, bet/bet_str, win,
        is_round_finished/isRoundFinished, round_id/roundId,
        game_id/gameId, pass_key

    Notes:
      - 'bet' is URL-decoded before hashing (e.g., '80%7C123' -> '80|123')
      - If win missing -> '' (empty string)
      - isRoundFinished normalized to 'true'/'false' (or '' if missing)
    """
    if args and not kwargs:
        user_id, bet, win, is_round_finished, round_id, game_id, pass_key = args
    else:
        user_id = kwargs.get("user_id", kwargs.get("userId"))
        bet = kwargs.get("bet", kwargs.get("bet_str"))
        win = kwargs.get("win", "")
        is_round_finished = kwargs.get("is_round_finished", kwargs.get("isRoundFinished"))
        round_id = kwargs.get("round_id", kwargs.get("roundId"))
        game_id = kwargs.get("game_id", kwargs.get("gameId"))
        pass_key = kwargs.get("pass_key")

    user_id = "" if user_id is None else str(user_id)
    bet = "" if bet is None else unquote_plus(str(bet))             # <-- decode before hashing
    win = "" if win is None else str(win)
    is_round_finished = _normalize_bool_to_bsg(is_round_finished)
    round_id = "" if round_id is None else str(round_id)
    game_id = "" if game_id is None else str(game_id)
    pass_key = "" if pass_key is None else str(pass_key)

    concat = f"{user_id}{bet}{win}{is_round_finished}{round_id}{game_id}{pass_key}"
    digest = md5_hex(concat)
    print(f"[BSG/betResult] concat='{concat}' expected_md5='{digest}'")
    return digest
