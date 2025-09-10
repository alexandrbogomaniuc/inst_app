from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Any, Dict, Iterable, Tuple


def _now_str() -> str:
    # e.g. "09 Sep 2025 17:44:21"
    return datetime.now().strftime("%d %b %Y %H:%M:%S")


def _render_request_fields(fields: Any) -> str:
    """
    Accepts:
      - dict[str, str]
      - list[tuple[str, str]] / iterable of pairs
      - None
    and renders inside <REQUEST> ... </REQUEST>.
    """
    if not fields:
        return "<REQUEST/>"

    items: Iterable[Tuple[str, str]]
    if isinstance(fields, dict):
        items = fields.items()
    else:
        # try to treat it as an iterable of (k, v)
        items = list(fields)

    parts = ["<REQUEST>"]
    for k, v in items:
        k = escape(str(k)).upper()
        v = "" if v is None else escape(str(v))
        parts.append(f"    <{k}>{v}</{k}>")
    parts.append("</REQUEST>")
    return "\n".join(parts)


def envelope_fail(code: int, message: str, *, request_fields: Any = None) -> str:
    req = _render_request_fields(request_fields)
    msg = escape(str(message))
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<EXTSYSTEM>\n"
        f"{req}\n"
        f"  <TIME>{_now_str()}</TIME>\n"
        "  <RESPONSE>\n"
        "    <RESULT>FAILED</RESULT>\n"
        f"    <CODE>{code}</CODE>\n"
        f"    <MESSAGE>{msg}</MESSAGE>\n"
        "  </RESPONSE>\n"
        "</EXTSYSTEM>"
    )


def envelope_ok(
    inner: str | None = None,
    *,
    user_id: int | None = None,
    username: str | None = None,
    currency: str | None = None,
    balance_cents: int | None = None,
    request_fields: Any = None,
) -> str:
    """
    Flexible OK wrapper used by auth/account/balance and some placeholders.

    Modes:
      1) inner XML string is provided -> embed it inside <RESPONSE> ... </RESPONSE>
      2) user account form (USERID, USERNAME, CURRENCY, BALANCE)
      3) balance-only form (BALANCE)
      4) plain OK
    """
    req = _render_request_fields(request_fields)
    time = _now_str()

    # Mode 1: embed custom inner
    if inner is not None:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<EXTSYSTEM>\n"
            f"{req}\n"
            f"  <TIME>{time}</TIME>\n"
            "  <RESPONSE>\n"
            f"{inner}\n"
            "  </RESPONSE>\n"
            "</EXTSYSTEM>"
        )

    # Mode 2: full account/auth shape
    if user_id is not None and username is not None and currency is not None and balance_cents is not None:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<EXTSYSTEM>\n"
            f"{req}\n"
            f"  <TIME>{time}</TIME>\n"
            "  <RESPONSE>\n"
            "    <RESULT>OK</RESULT>\n"
            f"    <USERID>{user_id}</USERID>\n"
            f"    <USERNAME>{escape(username)}</USERNAME>\n"
            f"    <CURRENCY>{escape(currency)}</CURRENCY>\n"
            f"    <BALANCE>{int(balance_cents)}</BALANCE>\n"
            "  </RESPONSE>\n"
            "</EXTSYSTEM>"
        )

    # Mode 3: balance-only
    if balance_cents is not None and user_id is None and username is None and currency is None:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<EXTSYSTEM>\n"
            f"{req}\n"
            f"  <TIME>{time}</TIME>\n"
            "  <RESPONSE>\n"
            "    <RESULT>OK</RESULT>\n"
            f"    <BALANCE>{int(balance_cents)}</BALANCE>\n"
            "  </RESPONSE>\n"
            "</EXTSYSTEM>"
        )

    # Mode 4: plain OK
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<EXTSYSTEM>\n"
        f"{req}\n"
        f"  <TIME>{time}</TIME>\n"
        "  <RESPONSE>\n"
        "    <RESULT>OK</RESULT>\n"
        "  </RESPONSE>\n"
        "</EXTSYSTEM>"
    )


def envelope_bet_ok(
    *,
    ext_system_transaction_id: str | None = None,
    balance_cents: int | None = None,
    request_fields: Any = None,
    **kwargs,
) -> str:
    """
    Bet result OK.
    Back-compat: also accepts 'extsystem_transaction_id' via **kwargs.
    """
    if ext_system_transaction_id is None and "extsystem_transaction_id" in kwargs:
        ext_system_transaction_id = kwargs["extsystem_transaction_id"]

    if ext_system_transaction_id is None:
        raise TypeError("ext_system_transaction_id is required")

    if balance_cents is None:
        raise TypeError("balance_cents is required")

    req = _render_request_fields(request_fields)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<EXTSYSTEM>\n"
        f"{req}\n"
        f"  <TIME>{_now_str()}</TIME>\n"
        "  <RESPONSE>\n"
        "    <RESULT>OK</RESULT>\n"
        f"    <EXTSYSTEMTRANSACTIONID>{escape(str(ext_system_transaction_id))}</EXTSYSTEMTRANSACTIONID>\n"
        f"    <BALANCE>{int(balance_cents)}</BALANCE>\n"
        "  </RESPONSE>\n"
        "</EXTSYSTEM>"
    )


def envelope_refund_ok(
    *,
    ext_system_transaction_id: str | None = None,
    request_fields: Any = None,
    **kwargs,
) -> str:
    """
    Refund OK.
    Back-compat: also accepts 'extsystem_transaction_id' via **kwargs.
    """
    if ext_system_transaction_id is None and "extsystem_transaction_id" in kwargs:
        ext_system_transaction_id = kwargs["extsystem_transaction_id"]

    if ext_system_transaction_id is None:
        raise TypeError("ext_system_transaction_id is required")

    req = _render_request_fields(request_fields)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<EXTSYSTEM>\n"
        f"{req}\n"
        f"  <TIME>{_now_str()}</TIME>\n"
        "  <RESPONSE>\n"
        "    <RESULT>OK</RESULT>\n"
        f"    <EXTSYSTEMTRANSACTIONID>{escape(str(ext_system_transaction_id))}</EXTSYSTEMTRANSACTIONID>\n"
        "  </RESPONSE>\n"
        "</EXTSYSTEM>"
    )
