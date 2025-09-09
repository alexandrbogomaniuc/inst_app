from __future__ import annotations

import hashlib
from decimal import Decimal
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from sqlalchemy.orm import Session

from igw.app.db import get_db
from igw.app.models import UserSession, Player, Wallet
from igw.app.utils.security import decode_token

from .settings import bsg_settings, get_bank_settings, resolve_bank_id
from .xml.utils import envelope_ok, envelope_fail

router = APIRouter(prefix="/betsoft", tags=["betsoft"])


# ------------------------------- Utilities -------------------------------

def md5_hex(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def _media_response(payload: Any, protocol: str, *, status_code: int = 200) -> Response:
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


def _hash_ok(token: str, pass_key: str, their_hash: Optional[str]) -> bool:
    if not their_hash:
        return False
    expected = md5_hex(token + pass_key)
    return expected.lower() == their_hash.lower()


def _echo_fields(token: Optional[str], hash_: Optional[str]) -> Dict[str, str]:
    return {"TOKEN": token or "", "HASH": hash_ or ""}


def _wallet_cents(db: Session, uid: int, currency_code: str) -> int:
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
    # Decimal -> cents (minor units)
    return int(Decimal(w.balance) * 100)


# ------------------------------- Endpoints -------------------------------

@router.get("/authenticate")
async def authenticate(
    request: Request,
    token: str = Query(...),
    hash: str = Query(...),
    bankId: int | None = Query(None),
    clientType: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """
    BSG calls this before launching the game.

    For XML banks we must return EXTSYSTEM-style XML:

    <EXTSYSTEM>
      <REQUEST><TOKEN>...</TOKEN><HASH>...</HASH></REQUEST>
      <TIME>...</TIME>
      <RESPONSE>
        <RESULT>OK</RESULT>
        <USERID>...</USERID>
        <USERNAME>...</USERNAME>
        <CURRENCY>...</CURRENCY>
        <BALANCE>...</BALANCE>
      </RESPONSE>
    </EXTSYSTEM>
    """
    # Load bank/provider settings
    bank_id = resolve_bank_id(bankId)
    bank = get_bank_settings(bank_id)
    protocol = (bank.BSG_PROTOCOL or "xml").lower()

    # This flow implements the XML contract; JSON support can be added later.
    if protocol != "xml":
        xml = envelope_fail(400, "Bank protocol mismatch: expected xml",
                            request_fields=_echo_fields(token, hash))
        return Response(content=xml, media_type="application/xml")

    # 1) Hash check
    if not _hash_ok(token, bank.BSG_PASS_KEY, hash):
        xml = envelope_fail(401, "INVALID_HASH", request_fields=_echo_fields(token, hash))
        return Response(content=xml, media_type="application/xml")

    # 2) Decode token and extract uid
    try:
        payload = decode_token(token)
    except Exception as e:
        xml = envelope_fail(401, f"INVALID_TOKEN {e}", request_fields=_echo_fields(token, hash))
        return Response(content=xml, media_type="application/xml")

    uid: Optional[int] = None
    # prefer 'sub' as numeric string
    if isinstance(payload.get("sub"), str) and payload["sub"].isdigit():
        uid = int(payload["sub"])
    # or explicit 'uid'
    if uid is None and isinstance(payload.get("uid"), int):
        uid = payload["uid"]

    if uid is None:
        xml = envelope_fail(401, "INVALID_TOKEN no user in token", request_fields=_echo_fields(token, hash))
        return Response(content=xml, media_type="application/xml")

    # 3) Verify we created this active BSG game session
    sess = (
        db.query(UserSession)
        .filter(
            UserSession.userId == uid,
            UserSession.token == token,
            UserSession.session_type == "game",
            UserSession.provider == "bsg",
            UserSession.status == "active",
        )
        .first()
    )
    if not sess:
        xml = envelope_fail(401, "SESSION_NOT_FOUND", request_fields=_echo_fields(token, hash))
        return Response(content=xml, media_type="application/xml")

    # 4) Gather user info and balance in minor units
    player: Player | None = db.query(Player).filter(Player.userId == uid).first()
    username = player.user_name if (player and player.user_name) else f"user_{uid}"
    currency = bank.BSG_DEFAULT_CURRENCY or "USD"
    balance_cents = _wallet_cents(db, uid, currency)

    # 5) Respond with EXTSYSTEM OK envelope (no token in RESPONSE per BSG sample)
    xml = envelope_ok(
        user_id=uid,
        username=username,
        currency=currency,
        balance_cents=balance_cents,
        request_fields=_echo_fields(token, hash),
    )
    return Response(content=xml, media_type="application/xml")


@router.get("/betResult")
async def bet_result(
    request: Request,
    bankId: int | None = None,
    token: str | None = None,
    hash: str | None = None,
    db: Session = Depends(get_db),
):
    """
    Minimal placeholder: verifies hash and token, returns OK.
    Flesh this out with real wallet debits and result processing.
    """
    resolved_bank_id = resolve_bank_id(bankId)
    bank = get_bank_settings(resolved_bank_id)
    protocol = (bank.BSG_PROTOCOL or "xml").lower()
    req_fields = _echo_fields(token, hash)

    if not token or not hash:
        payload = (
            {"result": "failed", "code": 400, "reason": "missing token or hash", "request": req_fields}
            if protocol == "json" else envelope_fail(400, "missing token or hash", request_fields=req_fields)
        )
        return _media_response(payload, protocol)

    if not _hash_ok(token, bank.BSG_PASS_KEY, hash):
        payload = (
            {"result": "failed", "code": 401, "reason": "invalid hash", "request": req_fields}
            if protocol == "json" else envelope_fail(401, "invalid hash", request_fields=req_fields)
        )
        return _media_response(payload, protocol)

    sub = decode_token(token)
    if not sub or "uid" not in sub:
        payload = (
            {"result": "failed", "code": 401, "reason": "invalid token", "request": req_fields}
            if protocol == "json" else envelope_fail(401, "invalid token", request_fields=req_fields)
        )
        return _media_response(payload, protocol)

    # TODO: implement wager/balance updates and return the real shape
    if protocol == "json":
        return _media_response({"result": "ok", "bankId": resolved_bank_id, "request": req_fields}, protocol)

    xml_inner = "<response><result>ok</result></response>"
    xml = envelope_ok(xml_inner, request_fields=req_fields)
    return _media_response(xml, protocol)


@router.get("/refundBet")
async def refund_bet(
    request: Request,
    bankId: int | None = None,
    token: str | None = None,
    hash: str | None = None,
    db: Session = Depends(get_db),
):
    resolved_bank_id = resolve_bank_id(bankId)
    bank = get_bank_settings(resolved_bank_id)
    protocol = (bank.BSG_PROTOCOL or "xml").lower()
    req_fields = _echo_fields(token, hash)

    if not token or not hash:
        payload = (
            {"result": "failed", "code": 400, "reason": "missing token or hash", "request": req_fields}
            if protocol == "json" else envelope_fail(400, "missing token or hash", request_fields=req_fields)
        )
        return _media_response(payload, protocol)

    if not _hash_ok(token, bank.BSG_PASS_KEY, hash):
        payload = (
            {"result": "failed", "code": 401, "reason": "invalid hash", "request": req_fields}
            if protocol == "json" else envelope_fail(401, "invalid hash", request_fields=req_fields)
        )
        return _media_response(payload, protocol)

    sub = decode_token(token)
    if not sub or "uid" not in sub:
        payload = (
            {"result": "failed", "code": 401, "reason": "invalid token", "request": req_fields}
            if protocol == "json" else envelope_fail(401, "invalid token", request_fields=req_fields)
        )
        return _media_response(payload, protocol)

    if protocol == "json":
        return _media_response({"result": "ok", "bankId": resolved_bank_id, "request": req_fields}, protocol)

    xml_inner = "<response><result>ok</result></response>"
    xml = envelope_ok(xml_inner, request_fields=req_fields)
    return _media_response(xml, protocol)


@router.get("/balance")
async def balance(
    request: Request,
    bankId: int | None = None,
    token: str | None = None,
    hash: str | None = None,
    db: Session = Depends(get_db),
):
    resolved_bank_id = resolve_bank_id(bankId)
    bank = get_bank_settings(resolved_bank_id)
    protocol = (bank.BSG_PROTOCOL or "xml").lower()
    req_fields = _echo_fields(token, hash)

    if not token or not hash:
        payload = (
            {"result": "failed", "code": 400, "reason": "missing token or hash", "request": req_fields}
            if protocol == "json" else envelope_fail(400, "missing token or hash", request_fields=req_fields)
        )
        return _media_response(payload, protocol)

    if not _hash_ok(token, bank.BSG_PASS_KEY, hash):
        payload = (
            {"result": "failed", "code": 401, "reason": "invalid hash", "request": req_fields}
            if protocol == "json" else envelope_fail(401, "invalid hash", request_fields=req_fields)
        )
        return _media_response(payload, protocol)

    sub = decode_token(token)
    if not sub or "uid" not in sub:
        payload = (
            {"result": "failed", "code": 401, "reason": "invalid token", "request": req_fields}
            if protocol == "json" else envelope_fail(401, "invalid token", request_fields=req_fields)
        )
        return _media_response(payload, protocol)

    # TODO: read real wallet balance(s). For now return 0.00 in configured currency.
    if protocol == "json":
        return _media_response(
            {"result": "ok", "balance": {"amount": "0.00", "currency": bank.BSG_DEFAULT_CURRENCY}, "request": req_fields},
            protocol,
        )

    xml_inner = f"<response><result>ok</result><balance>0.00</balance><currency>{bank.BSG_DEFAULT_CURRENCY}</currency></response>"
    xml = envelope_ok(xml_inner, request_fields=req_fields)
    return _media_response(xml, protocol)


@router.get("/bonusWin")
async def bonus_win(
    request: Request,
    bankId: int | None = None,
    token: str | None = None,
    hash: str | None = None,
    db: Session = Depends(get_db),
):
    resolved_bank_id = resolve_bank_id(bankId)
    bank = get_bank_settings(resolved_bank_id)
    protocol = (bank.BSG_PROTOCOL or "xml").lower()
    req_fields = _echo_fields(token, hash)

    if not token or not hash:
        payload = (
            {"result": "failed", "code": 400, "reason": "missing token or hash", "request": req_fields}
            if protocol == "json" else envelope_fail(400, "missing token or hash", request_fields=req_fields)
        )
        return _media_response(payload, protocol)

    if not _hash_ok(token, bank.BSG_PASS_KEY, hash):
        payload = (
            {"result": "failed", "code": 401, "reason": "invalid hash", "request": req_fields}
            if protocol == "json" else envelope_fail(401, "invalid hash", request_fields=req_fields)
        )
        return _media_response(payload, protocol)

    sub = decode_token(token)
    if not sub or "uid" not in sub:
        payload = (
            {"result": "failed", "code": 401, "reason": "invalid token", "request": req_fields}
            if protocol == "json" else envelope_fail(401, "invalid token", request_fields=req_fields)
        )
        return _media_response(payload, protocol)

    if protocol == "json":
        return _media_response({"result": "ok", "bankId": resolved_bank_id, "request": req_fields}, protocol)

    xml_inner = "<response><result>ok</result></response>"
    xml = envelope_ok(xml_inner, request_fields=req_fields)
    return _media_response(xml, protocol)


@router.get("/bonusRelease")
async def bonus_release(
    request: Request,
    bankId: int | None = None,
    token: str | None = None,
    hash: str | None = None,
    db: Session = Depends(get_db),
):
    resolved_bank_id = resolve_bank_id(bankId)
    bank = get_bank_settings(resolved_bank_id)
    protocol = (bank.BSG_PROTOCOL or "xml").lower()
    req_fields = _echo_fields(token, hash)

    if not token or not hash:
        payload = (
            {"result": "failed", "code": 400, "reason": "missing token or hash", "request": req_fields}
            if protocol == "json" else envelope_fail(400, "missing token or hash", request_fields=req_fields)
        )
        return _media_response(payload, protocol)

    if not _hash_ok(token, bank.BSG_PASS_KEY, hash):
        payload = (
            {"result": "failed", "code": 401, "reason": "invalid hash", "request": req_fields}
            if protocol == "json" else envelope_fail(401, "invalid hash", request_fields=req_fields)
        )
        return _media_response(payload, protocol)

    sub = decode_token(token)
    if not sub or "uid" not in sub:
        payload = (
            {"result": "failed", "code": 401, "reason": "invalid token", "request": req_fields}
            if protocol == "json" else envelope_fail(401, "invalid token", request_fields=req_fields)
        )
        return _media_response(payload, protocol)

    if protocol == "json":
        return _media_response({"result": "ok", "bankId": resolved_bank_id, "request": req_fields}, protocol)

    xml_inner = "<response><result>ok</result></response>"
    xml = envelope_ok(xml_inner, request_fields=req_fields)
    return _media_response(xml, protocol)


@router.get("/account")
async def account_info(
    request: Request,
    bankId: int | None = None,
    token: str | None = None,
    hash: str | None = None,
    db: Session = Depends(get_db),
):
    """
    Public (unregistered) account info endpoint. For now we just prove the
    integration is alive. Flesh out as needed by the provider.
    """
    resolved_bank_id = resolve_bank_id(bankId)
    bank = get_bank_settings(resolved_bank_id)
    protocol = (bank.BSG_PROTOCOL or "xml").lower()
    req_fields = _echo_fields(token, hash)

    # This endpoint might not require token/hash, but we'll accept and echo.
    if protocol == "json":
        return _media_response({"result": "ok", "bankId": resolved_bank_id, "request": req_fields}, protocol)

    xml = envelope_ok("<response><result>ok</result></response>", request_fields=req_fields)
    return _media_response(xml, protocol)
