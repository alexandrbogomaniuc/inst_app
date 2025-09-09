# igw/app/providers/bsg/xml/utils.py
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Optional
import html
import calendar


def _now_str(dt: Optional[datetime] = None) -> str:
    """
    BSG examples show e.g. "09 Sep 2025 10:34:33".
    We format with English month abbreviations to avoid locale issues.
    """
    dt = dt or datetime.now(timezone.utc).astimezone(None)
    day = f"{dt.day:02d}"
    mon = calendar.month_abbr[dt.month]  # 'Jan', 'Feb', ...
    return f"{day} {mon} {dt.year} {dt.strftime('%H:%M:%S')}"


def _xml_tag(tag: str, value: Optional[str]) -> str:
    if value is None:
        return ""
    return f"<{tag}>{html.escape(str(value))}</{tag}>"


def _render_request_fields(request_fields: Optional[Dict[str, str]]) -> str:
    """
    Helper to render whatever the caller wants to echo back under <REQUEST>.
    Keys are used as tag names (upper-cased for readability).
    """
    if not request_fields:
        return ""
    chunks = []
    for k, v in request_fields.items():
        tag = str(k).upper()
        chunks.append(_xml_tag(tag, v))
    return "".join(chunks)


def envelope_ok(
    response_inner_xml: str,
    *,
    request_fields: Optional[Dict[str, str]] = None,
    now: Optional[datetime] = None,
) -> str:
    """
    Wrap a successful <RESPONSE>...</RESPONSE> inside the EXTSYSTEM envelope.
    `response_inner_xml` must already be valid XML snippet (no outer tags escaped).
    """
    req_xml = _render_request_fields(request_fields)
    time_xml = _xml_tag("TIME", _now_str(now))
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<EXTSYSTEM>"
        f"<REQUEST>{req_xml}</REQUEST>"
        f"{time_xml}"
        f"<RESPONSE>{response_inner_xml}</RESPONSE>"
        "</EXTSYSTEM>"
    )


def envelope_fail(
    code: int | str,
    message: Optional[str] = None,
    *,
    request_fields: Optional[Dict[str, str]] = None,
    now: Optional[datetime] = None,
) -> str:
    """
    Failure envelope. Code goes into <CODE>, message is optional <MESSAGE>.
    """
    req_xml = _render_request_fields(request_fields)
    time_xml = _xml_tag("TIME", _now_str(now))
    inner = f"<RESULT>FAILED</RESULT>{_xml_tag('CODE', code)}{_xml_tag('MESSAGE', message)}"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<EXTSYSTEM>"
        f"<REQUEST>{req_xml}</REQUEST>"
        f"{time_xml}"
        f"<RESPONSE>{inner}</RESPONSE>"
        "</EXTSYSTEM>"
    )


# ---------- Common response builders used by the router ----------

def render_auth_response(user_id: int, game_token: str, bank_id: int | str) -> str:
    """
    Inner XML for a successful Authenticate response.
    """
    return (
        "<RESULT>OK</RESULT>"
        f"{_xml_tag('USERID', user_id)}"
        f"{_xml_tag('TOKEN', game_token)}"
        f"{_xml_tag('BANKID', bank_id)}"
    )


def render_balance_response(balance: str | float, currency: str) -> str:
    """
    Inner XML for a Balance response.
    """
    return (
        "<RESULT>OK</RESULT>"
        f"{_xml_tag('BALANCE', balance)}"
        f"{_xml_tag('CURRENCY', currency)}"
    )


def render_simple_ok(extra_inner_xml: str = "") -> str:
    """
    Inner XML for simple OK responses (e.g., bonusRelease/bonusWin/refund).
    You can append more tags via extra_inner_xml if required by the spec.
    """
    return "<RESULT>OK</RESULT>" + extra_inner_xml
