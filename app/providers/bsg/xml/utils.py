from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Optional


def _xml_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _fmt_time() -> str:
    # Example: "03 Mar 2023 17:55:21" (UTC)
    return datetime.now(timezone.utc).strftime("%d %b %Y %H:%M:%S")


def _render_request(fields: Optional[Dict[str, str]]) -> str:
    if not fields:
        return "<REQUEST/>"
    parts = ["<REQUEST>"]
    for k, v in fields.items():
        tag = k.upper()
        val = "" if v is None else str(v)
        parts.append(f"<{tag}>{_xml_escape(val)}</{tag}>")
    parts.append("</REQUEST>")
    return "".join(parts)


def envelope_ok(
    content_or_balance_cents: Optional[object] = None,
    *,
    user_id: Optional[int] = None,
    username: Optional[str] = None,
    currency: Optional[str] = None,
    balance_cents: Optional[int] = None,
    request_fields: Optional[Dict[str, str]] = None,
) -> str:
    """
    Flexible OK envelope used by the current router:

    - /authenticate and /account:
        pass user_id, username, currency, balance_cents
        -> RESPONSE has RESULT/USERID/USERNAME/CURRENCY/BALANCE

    - /balance:
        pass balance_cents only
        -> RESPONSE has RESULT/BALANCE

    - placeholders (betResult/refund/bonus):
        pass a *string* as first positional arg; it is injected raw inside <RESPONSE>…</RESPONSE>.
    """

    # If a string payload is given, inject it inside <RESPONSE> as-is.
    if isinstance(content_or_balance_cents, str):
        inner = content_or_balance_cents
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f"<EXTSYSTEM>"
            f"{_render_request(request_fields)}"
            f"<TIME>{_fmt_time()}</TIME>"
            f"<RESPONSE>{inner}</RESPONSE>"
            f"</EXTSYSTEM>"
        )

    # If no user fields provided: treat as a pure BALANCE response.
    if user_id is None and username is None and currency is None:
        cents = balance_cents if balance_cents is not None else int(content_or_balance_cents or 0)
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f"<EXTSYSTEM>"
            f"{_render_request(request_fields)}"
            f"<TIME>{_fmt_time()}</TIME>"
            f"<RESPONSE>"
            f"<RESULT>OK</RESULT>"
            f"<BALANCE>{int(cents)}</BALANCE>"
            f"</RESPONSE>"
            f"</EXTSYSTEM>"
        )

    # Otherwise produce the account/auth shape with user + currency + balance.
    cents = int(balance_cents or 0)
    uid = "" if user_id is None else str(user_id)
    uname = username or ""
    curr = currency or ""

    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f"<EXTSYSTEM>"
        f"{_render_request(request_fields)}"
        f"<TIME>{_fmt_time()}</TIME>"
        f"<RESPONSE>"
        f"<RESULT>OK</RESULT>"
        f"<USERID>{_xml_escape(uid)}</USERID>"
        f"<USERNAME>{_xml_escape(uname)}</USERNAME>"
        f"<CURRENCY>{_xml_escape(curr)}</CURRENCY>"
        f"<BALANCE>{cents}</BALANCE>"
        f"</RESPONSE>"
        f"</EXTSYSTEM>"
    )


def envelope_fail(
    code: int,
    message: str,
    *,
    request_fields: Optional[Dict[str, str]] = None,
) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f"<EXTSYSTEM>"
        f"{_render_request(request_fields)}"
        f"<TIME>{_fmt_time()}</TIME>"
        f"<RESPONSE>"
        f"<RESULT>FAILED</RESULT>"
        f"<CODE>{int(code)}</CODE>"
        f"<MESSAGE>{_xml_escape(message)}</MESSAGE>"
        f"</RESPONSE>"
        f"</EXTSYSTEM>"
    )
