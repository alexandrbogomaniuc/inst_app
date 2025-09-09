from __future__ import annotations

from datetime import datetime
from typing import Dict, Optional


def _xml_header() -> str:
    return '<?xml version="1.0" encoding="UTF-8"?>'


def _time_now() -> str:
    # Example format: "09 Sep 2025 12:28:52"
    return datetime.utcnow().strftime("%d %b %Y %H:%M:%S")


# =============== AUTH OK (EXTSYSTEM envelope) ===============

def render_auth_extsystem_ok(
    *,
    user_id: int,
    username: str,
    currency: str,
    balance_cents: int,
    request_fields: Optional[Dict[str, str]] = None,
) -> str:
    """
    Build the exact XML that BSG expects for the /authenticate response:

    <EXTSYSTEM>
      <REQUEST><TOKEN>…</TOKEN><HASH>…</HASH></REQUEST>
      <TIME>…</TIME>
      <RESPONSE>
        <RESULT>OK</RESULT>
        <USERID>…</USERID>
        <USERNAME>…</USERNAME>
        <CURRENCY>…</CURRENCY>
        <BALANCE>…</BALANCE>
      </RESPONSE>
    </EXTSYSTEM>
    """
    token = (request_fields or {}).get("TOKEN", "")
    hash_ = (request_fields or {}).get("HASH", "")

    return (
        f"{_xml_header()}"
        f"<EXTSYSTEM>"
        f"<REQUEST>"
        f"<TOKEN>{token}</TOKEN>"
        f"<HASH>{hash_}</HASH>"
        f"</REQUEST>"
        f"<TIME>{_time_now()}</TIME>"
        f"<RESPONSE>"
        f"<RESULT>OK</RESULT>"
        f"<USERID>{user_id}</USERID>"
        f"<USERNAME>{username}</USERNAME>"
        f"<CURRENCY>{currency}</CURRENCY>"
        f"<BALANCE>{balance_cents}</BALANCE>"
        f"</RESPONSE>"
        f"</EXTSYSTEM>"
    )


# =============== Flexible wrappers kept for other endpoints ===============

def envelope_ok(
    content: Optional[str] = None,
    *,
    # For AUTH OK (EXTSYSTEM) flow:
    user_id: Optional[int] = None,
    username: Optional[str] = None,
    currency: Optional[str] = None,
    balance_cents: Optional[int] = None,
    request_fields: Optional[Dict[str, str]] = None,
) -> str:
    """
    Usage:
      A) AUTH OK (produce EXTSYSTEM envelope):
         envelope_ok(user_id=..., username=..., currency=..., balance_cents=..., request_fields={"TOKEN": "...", "HASH": "..."})

      B) Generic OK (pass raw <response>…</response> XML):
         envelope_ok("<response>...</response>")
    """
    if (
        user_id is not None
        and username is not None
        and currency is not None
        and balance_cents is not None
    ):
        return render_auth_extsystem_ok(
            user_id=user_id,
            username=username,
            currency=currency,
            balance_cents=balance_cents,
            request_fields=request_fields or {},
        )

    body = content or "<response><result>ok</result></response>"
    s = body.strip()
    if s.startswith("<?xml"):
        return body
    return f"{_xml_header()}{body}"


def envelope_fail(
    code: int,
    message: str,
    *,
    request_fields: Optional[Dict[str, str]] = None,
    token: Optional[str] = None,
    hash: Optional[str] = None,
) -> str:
    """
    Failure envelope (EXTSYSTEM) that echoes TOKEN/HASH if provided.
    """
    if request_fields:
        token = request_fields.get("TOKEN")
        hash = request_fields.get("HASH")

    req_parts = []
    if token:
        req_parts.append(f"<TOKEN>{token}</TOKEN>")
    if hash:
        req_parts.append(f"<HASH>{hash}</HASH>")
    req_xml = f"<REQUEST>{''.join(req_parts)}</REQUEST>" if req_parts else "<REQUEST/>"

    return (
        f"{_xml_header()}"
        f"<EXTSYSTEM>"
        f"{req_xml}"
        f"<TIME>{_time_now()}</TIME>"
        f"<RESPONSE>"
        f"<RESULT>FAILED</RESULT>"
        f"<CODE>{code}</CODE>"
        f"<MESSAGE>{message}</MESSAGE>"
        f"</RESPONSE>"
        f"</EXTSYSTEM>"
    )
