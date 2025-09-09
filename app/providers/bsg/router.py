from __future__ import annotations

from hashlib import md5
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from sqlalchemy.orm import Session

from igw.app.db import get_db
from igw.app.models import UserSession
from igw.app.utils.security import create_token, decode_token

from .settings import (
    bsg_settings,           # global/base settings (lru_cached callable)
    get_bank_settings,      # load per-bank env as a pydantic model
    resolve_bank_id,        # helper to resolve incoming bankId or fallback
)

# XML helpers (current API expects request_fields=dict for echoing <REQUEST/>)
from .xml.utils import (
    envelope_ok,
    envelope_fail,
    render_auth_response,
    # You can add more specific renderers later (balance, bet, etc.)
)

router = APIRouter(prefix="/betsoft", tags=["betsoft"])


# ------------------------------- Utilities -------------------------------

def _media_response(payload: Any, protocol: str, *, status_code: int = 200) -> Response:
    """
    Return either XML (string) or JSON based on bank protocol.
    """
    if protocol == "json":
        if isinstance(payload, str):
            # payload shouldn't be string for json, wrap it
            return JSONResponse({"payload": payload}, status_code=status_code)
        return JSONResponse(payload, status_code=status_code)
    # xml
    if not isinstance(payload, str):
        payload = str(payload)
    return HTMLResponse(payload, status_code=status_code, media_type="application/xml")


def _hash_ok(token: str, pass_key: str, their_hash: str | None) -> bool:
    if not their_hash:
        return False
    expected = md5((token + pass_key).encode("utf-8")).hexdigest()
    return expected.lower() == their_hash.lower()


def _echo_fields(token: Optional[str], hash_: Optional[str]) -> Dict[str, str]:
    return {
        "TOKEN": token or "",
        "HASH": hash_ or "",
    }


# ------------------------------- Endpoints -------------------------------

@router.get("/authenticate")
async def authenticate(
    request: Request,
    bankId: int | None = None,
    token: str | None = None,
    hash: str | None = None,
    clientType: str | None = None,
    db: Session = Depends(get_db),
):
    """
    BSG calls this with a LOBBY token. We:
      - verify MD5(token + PASS_KEY)
      - decode the lobby token, extract uid
      - mint a GAME token (shorter TTL)
      - store a 'game' session
      - reply using the bank's protocol (xml/json)
    """
    # Resolve bank + protocol
    resolved_bank_id = resolve_bank_id(bankId)
    bank = get_bank_settings(resolved_bank_id)
    base = bsg_settings()
    protocol = (bank.BSG_PROTOCOL or "xml").lower()

    req_fields = _echo_fields(token, hash)

    # Validate inputs
    if not token or not hash:
        payload = (
            {"result": "failed", "code": 400, "reason": "missing token or hash", "request": req_fields}
            if protocol == "json"
            else envelope_fail(400, "missing token or hash", request_fields=req_fields)
        )
        return _media_response(payload, protocol, status_code=200)

    # Verify hash
    if not _hash_ok(token, bank.BSG_PASS_KEY, hash):
        payload = (
            {"result": "failed", "code": 401, "reason": "invalid hash", "request": req_fields}
            if protocol == "json"
            else envelope_fail(401, "invalid hash", request_fields=req_fields)
        )
        return _media_response(payload, protocol, status_code=200)

    # Decode lobby token
    sub = decode_token(token)
    if not sub or "uid" not in sub:
        payload = (
            {"result": "failed", "code": 401, "reason": "invalid token", "request": req_fields}
            if protocol == "json"
            else envelope_fail(401, "invalid token", request_fields=req_fields)
        )
        return _media_response(payload, protocol, status_code=200)

    user_id = int(sub["uid"])

    # Create GAME token
    game_claims = {
        "uid": user_id,
        "type": "game",
        "provider": "bsg",
        "bankId": resolved_bank_id,
        "gameId": bank.BSG_DEFAULT_GAME_ID,
        "exp_m": base.BSG_TOKEN_GAME_EXP_MIN,
    }
    game_token = create_token(game_claims)

    # Persist game session
    sess = UserSession(
        userId=user_id,
        token=game_token,
        session_type="game",
        provider="bsg",
        status="active",
        Login_IP=(request.client.host if request and request.client else None),
        meta={"bankId": resolved_bank_id, "gameId": bank.BSG_DEFAULT_GAME_ID},
    )
    db.add(sess)
    db.commit()

    # Build reply
    if protocol == "json":
        payload = {
            "result": "ok",
            "userId": user_id,
            "token": game_token,
            "bankId": resolved_bank_id,
            # echo back
            "request": req_fields,
        }
        return _media_response(payload, protocol)

    # XML
    inner = render_auth_response(user_id, game_token, resolved_bank_id)
    xml = envelope_ok(inner, request_fields=req_fields)
    return _media_response(xml, protocol)


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
    xml = envelope_ok("<response><result>ok</result></response>", request_fields=req_fields)
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
    xml = envelope_ok("<response><result>ok</result></response>", request_fields=req_fields)
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

    # TODO: read real wallet balance(s). For now return 0.00 in USD.
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
    xml = envelope_ok("<response><result>ok</result></response>", request_fields=req_fields)
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
    xml = envelope_ok("<response><result>ok</result></response>", request_fields=req_fields)
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
