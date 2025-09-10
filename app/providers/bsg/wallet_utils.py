# -*- coding: utf-8 -*-
"""
Wallet helpers used by BSG endpoints.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP, getcontext
from sqlalchemy.orm import Session

from igw.app.models import Wallet

# sensible precision for money math
getcontext().prec = 28
_CENT = Decimal("0.01")


def _cents_to_decimal(cents: int) -> Decimal:
    """80 -> Decimal('0.80')"""
    return (Decimal(cents) / Decimal(100)).quantize(_CENT, rounding=ROUND_HALF_UP)


def balance_to_cents(wallet: Wallet) -> int:
    """Return wallet balance in integer cents."""
    bal = wallet.balance or Decimal("0")
    return int((bal.quantize(_CENT, rounding=ROUND_HALF_UP)) * 100)


def get_wallet_for_user(db: Session, user_id: int, currency_code: str) -> Wallet:
    """
    Fetch the user's wallet in the given currency, creating it if missing.
    Uses a row lock so concurrent bet/win flows don’t race each other.
    """
    w = (
        db.query(Wallet)
        .filter(Wallet.userId == user_id, Wallet.currency_code == currency_code)
        .with_for_update(of=Wallet)
        .first()
    )
    if not w:
        w = Wallet(
            userId=user_id,
            currency_code=currency_code,
            balance=Decimal("0.00"),
            status="active",
        )
        db.add(w)
        db.flush()  # get wallet_id
    return w


def apply_delta_cents(db: Session, wallet: Wallet, delta_cents: int) -> None:
    """
    Add (or subtract) an amount to the wallet in cents.
    Callers control the transaction/commit.
    """
    delta = _cents_to_decimal(delta_cents)
    current = wallet.balance or Decimal("0.00")
    wallet.balance = (current + delta).quantize(_CENT, rounding=ROUND_HALF_UP)
    db.flush()
