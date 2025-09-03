# igw/app/utils/account.py
from sqlalchemy.orm import Session

from igw.app.models import Wallet


def ensure_default_wallets(db: Session, user_id: int) -> None:
    """
    Ensure the given user has USD and VND wallets.
    Safe to call multiple times; missing ones will be created.
    """
    existing = {
        w.currency_code
        for w in db.query(Wallet).filter(Wallet.user_id == user_id).all()
    }

    to_create = []
    for cur in ("USD", "VND"):
        if cur not in existing:
            to_create.append(
                Wallet(user_id=user_id, wallet_type="CASH", currency_code=cur, balance=0)
            )

    if to_create:
        db.add_all(to_create)
        # Commit is managed by the caller; use flush here to get IDs if needed.
        db.flush()
