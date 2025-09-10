from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from igw.app.db import get_db
from igw.app.utils.security import decode_token

from ..settings import get_bank_settings, resolve_bank_id
from ..xml.utils import envelope_ok, envelope_fail
from ..helpers import hash_ok_token, echo_fields

router = APIRouter()


@router.get("/bonusRelease")
async def bonus_release(
    request: Request,
    bankId: int | None = Query(None),
    token: str | None = Query(None),
    hash: str | None = Query(None),
    db: Session = Depends(get_db),
):
    resolved_bank_id = resolve_bank_id(bankId)
    bank = get_bank_settings(resolved_bank_id)
    req_fields = echo_fields(token, hash)

    if not token or not hash:
        xml = envelope_fail(400, "missing token or hash", request_fields=req_fields)
        return Response(content=xml, media_type="application/xml")

    if not hash_ok_token(token, bank.BSG_PASS_KEY, hash):
        xml = envelope_fail(401, "invalid hash", request_fields=req_fields)
        return Response(content=xml, media_type="application/xml")

    sub = decode_token(token)
    if not sub or "uid" not in sub:
        xml = envelope_fail(401, "invalid token", request_fields=req_fields)
        return Response(content=xml, media_type="application/xml")

    xml_inner = "<response><result>ok</result></response>"
    xml = envelope_ok(xml_inner, request_fields=req_fields)
    return Response(content=xml, media_type="application/xml")
