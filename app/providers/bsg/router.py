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
    BSG calls this before launching the game. Responds with EXTSYSTEM XML (RESULT/USERID/USERNAME/CURRENCY/BALANCE).
    """
    bank_id = resolve_bank_id(bankId)
    bank = get_bank_settings(bank_id)
    protocol = (bank.BSG_PROTOCOL or "xml").lower()

    if protocol != "xml":
        xml = envelope_fail(400, "Bank protocol mismatch: expected xml",
                            request_fields=_echo_fields(token, hash))
        return Response(content=xml, media_type="application/xml")

    if not _hash_ok(token, bank.BSG_PASS_KEY, hash):
        xml = envelope_fail(401, "INVALID_HASH", request_fields=_echo_fields(token, hash))
        return Response(content=xml, media_type="application/xml")

    try:
        payload = decode_token(token)
    except Exception as e:
        xml = envelope_fail(401, f"INVALID_TOKEN {e}", request_fields=_echo_fields(token, hash))
        return Response(content=xml, media_type="application/xml")

    uid: Optional[int] = None
    if isinstance(payload.get("sub"), str) and payload["sub"].isdigit():
        uid = int(payload["sub"])
    if uid is None and isinstance(payload.get("uid"), int):
        uid = payload["uid"]

    if uid is None:
        xml = envelope_fail(401, "INVALID_TOKEN no user in token", request_fields=_echo_fields(token, hash))
        return Response(content=xml, media_type="application/xml")

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

    player: Player | None = db.query(Player).filter(Player.userId == uid).first()
    username = player.user_name if (player and player.user_name) else f"user_{uid}"
    currency = bank.BSG_DEFAULT_CURRENCY or "USD"
    balance_cents = _wallet_cents(db, uid, currency)

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
    bankId: int | None = Query(None),
    userId: int | None = Query(None),
    hash: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """
    BSG 'Get Balance' (XML flavor)
    Request: bankId, userId, hash (where hash = MD5(userId + PASS_KEY))
    Response:
      <EXTSYSTEM>
        <REQUEST><USERID>...</USERID></REQUEST>
        <TIME>...</TIME>
        <RESPONSE><RESULT>OK</RESULT><BALANCE>...</BALANCE></RESPONSE>
      </EXTSYSTEM>

    BALANCE must be in minor units (cents). Example: 7456.23 -> 745623.
    """
    resolved_bank_id = resolve_bank_id(bankId)
    bank = get_bank_settings(resolved_bank_id)
    protocol = (bank.BSG_PROTOCOL or "xml").lower()

    # Only modify this endpoint’s behavior; keep others as-is.
    if protocol != "xml":
        # JSON banks (future): return a lightweight JSON shape.
        if userId is None or not hash:
            return _media_response(
                {"result": "failed", "code": 400, "reason": "missing userId or hash",
                 "request": {"USERID": str(userId) if userId is not None else ""}},
                "json",
            )
        expected = md5_hex(f"{userId}{bank.BSG_PASS_KEY}")
        if expected.lower() != hash.lower():
            return _media_response(
                {"result": "failed", "code": 401, "reason": "invalid hash",
                 "request": {"USERID": str(userId)}},
                "json",
            )
        currency = bank.BSG_DEFAULT_CURRENCY or "USD"
        balance_cents = _wallet_cents(db, userId, currency)
        return _media_response({"result": "ok", "balance_cents": balance_cents, "userId": userId}, "json")

    # XML flow:
    # Build REQUEST echo with USERID ONLY (per provider example).
    request_fields = {"USERID": str(userId) if userId is not None else ""}

    if userId is None or not hash:
        xml = envelope_fail(400, "missing userId or hash", request_fields=request_fields)
        return Response(content=xml, media_type="application/xml")

    expected = md5_hex(f"{userId}{bank.BSG_PASS_KEY}")
    if expected.lower() != hash.lower():
        xml = envelope_fail(401, "INVALID_HASH", request_fields=request_fields)
        return Response(content=xml, media_type="application/xml")

    # Get balance in minor units (cents) from the bank’s default currency wallet.
    currency = bank.BSG_DEFAULT_CURRENCY or "USD"
    balance_cents = _wallet_cents(db, userId, currency)

    # Return EXTSYSTEM with only BALANCE in RESPONSE (no USERNAME/CURRENCY here).
    xml = envelope_ok(balance_cents=balance_cents, request_fields=request_fields)
    return Response(content=xml, media_type="application/xml")


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
    bankId: int | None = Query(None),
    userId: int | None = Query(None),
    hash: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """
    BSG 'Get Account info' — XML EXTSYSTEM with RESULT/USERID/USERNAME/CURRENCY/BALANCE.
    """
    resolved_bank_id = resolve_bank_id(bankId)
    bank = get_bank_settings(resolved_bank_id)
    protocol = (bank.BSG_PROTOCOL or "xml").lower()

    req_fields = {"USERID": str(userId) if userId is not None else "", "HASH": hash or ""}

    if protocol != "xml":
        if userId is None or not hash:
            return _media_response(
                {"result": "failed", "code": 400, "reason": "missing userId or hash", "request": req_fields},
                "json",
            )
        expected = md5_hex(f"{userId}{bank.BSG_PASS_KEY}")
        if expected.lower() != hash.lower():
            return _media_response(
                {"result": "failed", "code": 401, "reason": "invalid hash", "request": req_fields},
                "json",
            )
        player: Player | None = db.query(Player).filter(Player.userId == userId).first()
        if not player:
            return _media_response(
                {"result": "failed", "code": 404, "reason": "user not found", "request": req_fields},
                "json",
            )
        currency = bank.BSG_DEFAULT_CURRENCY or "USD"
        balance_cents = _wallet_cents(db, userId, currency)
        return _media_response(
            {
                "result": "ok",
                "userId": userId,
                "username": player.user_name or f"user_{userId}",
                "currency": currency,
                "balance_cents": balance_cents,
                "request": req_fields,
            },
            "json",
        )

    if userId is None or not hash:
        xml = envelope_fail(400, "missing userId or hash", request_fields=req_fields)
        return Response(content=xml, media_type="application/xml")

    expected = md5_hex(f"{userId}{bank.BSG_PASS_KEY}")
    if expected.lower() != (hash or "").lower():
        xml = envelope_fail(401, "INVALID_HASH", request_fields=req_fields)
        return Response(content=xml, media_type="application/xml")

    player: Player | None = db.query(Player).filter(Player.userId == userId).first()
    if not player:
        xml = envelope_fail(404, "USER_NOT_FOUND", request_fields=req_fields)
        return Response(content=xml, media_type="application/xml")

    currency = bank.BSG_DEFAULT_CURRENCY or "USD"
    balance_cents = _wallet_cents(db, userId, currency)

    xml = envelope_ok(
        user_id=userId,
        username=player.user_name or f"user_{userId}",
        currency=currency,
        balance_cents=balance_cents,
        request_fields=req_fields,
    )
    return Response(content=xml, media_type="application/xml")
