# igw/app/utils/account.py
from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from sqlalchemy.orm import Session

from igw.app.config import settings
from igw.app.models import Wallet


def _default_currencies() -> List[str]:
    """
    Parse DEFAULT_WALLET_CURRENCIES from settings into a normalized list.
    e.g. "USD,VND" -> ["USD", "VND"]
    """
    raw = settings.DEFAULT_WALLET_CURRENCIES or ""
    return [c.strip().upper() for c in raw.split(",") if c.strip()]


def ensure_wallets_for_user(
    db: Session,
    user_id: int,
    *,
    currencies: Optional[Iterable[str]] = None,
    wallet_type: Optional[str] = None,
    commit: bool = True,
) -> List[Wallet]:
    """
    Ensure the user has one wallet per currency (and wallet_type).
    Creates missing wallets with balance=0.

    Returns the up-to-date list of Wallet ORM objects for those currencies.
    """
    currencies_list = [c.strip().upper() for c in (currencies or _default_currencies()) if c]
    wtype = (wallet_type or settings.DEFAULT_WALLET_TYPE or "CASH").upper()

    created: List[Wallet] = []
    existing: List[Wallet] = []

    for cur in currencies_list:
        wallet = (
            db.query(Wallet)
            .filter(
                Wallet.userId == user_id,
                Wallet.currency_code == cur,
                Wallet.wallet_type == wtype,
            )
            .one_or_none()
        )
        if wallet is None:
            wallet = Wallet(
                userId=user_id,
                wallet_type=wtype,
                currency_code=cur,
                balance=0,
            )
            db.add(wallet)
            created.append(wallet)
        else:
            existing.append(wallet)

    if commit and created:
        db.commit()
        for w in created:
            db.refresh(w)

    return existing + created


def get_wallet_balances(db: Session, user_id: int) -> Dict[str, float]:
    """
    Convenience helper: { 'USD': 0.0, 'VND': 0.0, ... } for the user's wallets.
    """
    rows: List[Wallet] = db.query(Wallet).filter(Wallet.userId == user_id).all()
    balances: Dict[str, float] = {}
    for w in rows:
        # Convert Decimal to float for easy JSON display; switch to str() if you prefer exactness.
        balances[w.currency_code] = float(w.balance or 0)
    return balances
