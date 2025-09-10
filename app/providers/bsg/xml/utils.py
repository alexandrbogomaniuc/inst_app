# -*- coding: utf-8 -*-
"""
XML helpers for BSG (XML protocol).
Keeps the EXTSYSTEM envelope identical across endpoints.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, Optional

_XML_HDR = '<?xml version="1.0" encoding="UTF-8"?>'


def _now_str() -> str:
    # Example: "03 Mar 2023 17:55:21"
    return datetime.utcnow().strftime("%d %b %Y %H:%M:%S")


def _escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _render_request_fields(fields) -> str:
    """
    Accepts either:
      - dict like {"USERID": "36", "HASH": "...", "CASINOTRANSACTIONID": "..."}
      - list/tuple of dicts or (key, value) pairs, e.g.
          [{"USERID": "36"}, {"CASINOTRANSACTIONID": "2629"}, {"HASH": "..."}]
          or [("USERID", "36"), ("HASH", "...")]
    Returns XML of the <REQUEST> block inner nodes.
    """
    if not fields:
        return ""

    # Normalize to a flat dict
    norm: dict[str, str] = {}

    if isinstance(fields, dict):
        norm = {str(k).upper(): "" if v is None else str(v) for k, v in fields.items()}
    elif isinstance(fields, (list, tuple)):
        for item in fields:
            if isinstance(item, dict):
                for k, v in item.items():
                    norm[str(k).upper()] = "" if v is None else str(v)
            elif isinstance(item, (list, tuple)) and len(item) == 2:
                k, v = item
                norm[str(k).upper()] = "" if v is None else str(v)
            # else: ignore unknown shapes
    else:
        # last resort: treat as a single value
        norm["VALUE"] = str(fields)

    parts = []
    for k, v in norm.items():
        parts.append(f"<{k}>{v}</{k}>")
    return "".join(parts)


def _wrap_extsystem(request_fields_xml: str, response_xml: str) -> str:
    return (
        f"{_XML_HDR}\n"
        "<EXTSYSTEM>\n"
        f"  {request_fields_xml}\n"
        f"  <TIME>{_now_str()}</TIME>\n"
        f"  {response_xml}\n"
        "</EXTSYSTEM>"
    )


# ---------------------------------------------------------------------------
# Generic OK / FAIL envelopes used by multiple endpoints
# ---------------------------------------------------------------------------

def envelope_fail(code: int, message: str, *, request_fields: Optional[Dict[str, str]] = None) -> str:
    req = _render_request_fields(request_fields)
    resp = (
        "<RESPONSE>\n"
        "  <RESULT>FAILED</RESULT>\n"
        f"  <CODE>{code}</CODE>\n"
        f"  <MESSAGE>{_escape(message)}</MESSAGE>\n"
        "</RESPONSE>"
    )
    return _wrap_extsystem(req, resp)


def envelope_ok(
    *,
    # account/auth shape
    user_id: Optional[int] = None,
    username: Optional[str] = None,
    currency: Optional[str] = None,
    # balance-only shape (when only BALANCE is expected)
    balance_cents: Optional[int] = None,
    request_fields: Optional[Dict[str, str]] = None,
) -> str:
    """
    Flexible OK envelope:
      - If user_id/username/currency are present, emits those (plus BALANCE if given).
      - If only balance_cents is provided, emits BALANCE only.
    """
    req = _render_request_fields(request_fields)

    lines = ["<RESPONSE>", "  <RESULT>OK</RESULT>"]
    if user_id is not None:
        lines.append(f"  <USERID>{user_id}</USERID>")
    if username is not None:
        lines.append(f"  <USERNAME>{_escape(username)}</USERNAME>")
    if currency is not None:
        lines.append(f"  <CURRENCY>{_escape(currency)}</CURRENCY>")
    if balance_cents is not None:
        lines.append(f"  <BALANCE>{balance_cents}</BALANCE>")
    lines.append("</RESPONSE>")

    resp = "\n".join(lines)
    return _wrap_extsystem(req, resp)


# Back-compat convenience (if some legacy code still calls this):
def render_auth_response(**kwargs) -> str:  # pragma: no cover
    return envelope_ok(**kwargs)


# ---------------------------------------------------------------------------
# Endpoint-specific OK envelopes
# ---------------------------------------------------------------------------

def envelope_bet_ok(
    *,
    request_fields: Dict[str, str],
    extsystem_transaction_id: str,
    balance_cents: int,
) -> str:
    """
    Bet response expected by BSG:
      <RESPONSE>
        <RESULT>OK</RESULT>
        <EXTSYSTEMTRANSACTIONID>...</EXTSYSTEMTRANSACTIONID>
        <BALANCE>...</BALANCE>
      </RESPONSE>
    """
    req = _render_request_fields(request_fields)
    resp = (
        "<RESPONSE>\n"
        "  <RESULT>OK</RESULT>\n"
        f"  <EXTSYSTEMTRANSACTIONID>{_escape(extsystem_transaction_id)}</EXTSYSTEMTRANSACTIONID>\n"
        f"  <BALANCE>{balance_cents}</BALANCE>\n"
        "</RESPONSE>"
    )
    return _wrap_extsystem(req, resp)


def envelope_refund_ok(
    *,
    request_fields: Dict[str, str],
    extsystem_transaction_id: str,
) -> str:
    """
    Refund response expected by BSG:
      <RESPONSE>
        <RESULT>OK</RESULT>
        <EXTSYSTEMTRANSACTIONID>...</EXTSYSTEMTRANSACTIONID>
      </RESPONSE>
    """
    req = _render_request_fields(request_fields)
    resp = (
        "<RESPONSE>\n"
        "  <RESULT>OK</RESULT>\n"
        f"  <EXTSYSTEMTRANSACTIONID>{_escape(extsystem_transaction_id)}</EXTSYSTEMTRANSACTIONID>\n"
        "</RESPONSE>"
    )
    return _wrap_extsystem(req, resp)
