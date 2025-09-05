# igw/app/utils/account.py
from __future__ import annotations

from sqlalchemy.orm import Session

from igw.app.config import settings
from igw.app.models import Wallet


def ensure_wallets_for_user(db: Session, user_id: int) -> None:
    """
    Ensure the user has one wallet per currency from DEFAULT_WALLET_CURRENCIES.
    """
    wanted = [c.strip().upper() for c in settings.DEFAULT_WALLET_CURRENCIES.split(",") if c.strip()]
    existing = {w.currency_code.upper() for w in db.query(Wallet).filter(Wallet.userId == user_id).all()}

    for currency in wanted:
        if currency not in existing:
            db.add(Wallet(userId=user_id, wallet_type=settings.DEFAULT_WALLET_TYPE, currency_code=currency))
    db.flush()  # so new ids are visible to caller if needed
