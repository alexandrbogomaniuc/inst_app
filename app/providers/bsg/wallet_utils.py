from sqlalchemy.orm import Session
from igw.app.models import Wallet

def get_wallet_balance(db: Session, user_id: int, currency: str) -> int:
    w = db.query(Wallet).filter(Wallet.userId == user_id, Wallet.currency_code == currency).first()
    if not w:
        return 0
    return int(w.balance or 0)

def apply_delta(db: Session, user_id: int, currency: str, delta: int) -> int:
    w = (
        db.query(Wallet)
        .filter(Wallet.userId == user_id, Wallet.currency_code == currency)
        .with_for_update()
        .first()
    )
    if not w:
        raise ValueError("Wallet not found")
    new_balance = int(w.balance or 0) + int(delta)
    w.balance = new_balance
    db.add(w)
    return new_balance
