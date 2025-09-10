from __future__ import annotations

from sqlalchemy import (
    Column,
    Integer,
    String,
    Numeric,
    ForeignKey,
    TIMESTAMP,
    text,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import relationship

# Reuse your existing Base from the main models module
from igw.app.models import Base


class GameplayTransaction(Base):
    __tablename__ = "gameplay_transactions"

    transaction_id = Column(Integer, primary_key=True, autoincrement=True)
    userId = Column(Integer, ForeignKey("players.userId"), nullable=False)
    wallet_id = Column(Integer, ForeignKey("wallets.wallet_id"), nullable=False)

    # optional, matches your schema
    bank_id = Column(Integer, nullable=True)

    transaction_type = Column(String(10), nullable=False)  # 'bet','win','refund'
    amount = Column(Numeric(15, 2), server_default=text("0.00"))
    status = Column(String(9), nullable=False, server_default=text("'Pending'"))  # Pending/Processed/Failed
    transaction_date = Column(TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"))
    description = Column(String(255), nullable=True)

    external_transaction_id = Column(String(255), nullable=True)
    external_gamesession_id = Column(String(255), nullable=True)
    external_gameround_id = Column(String(255), nullable=True)
    external_game_id = Column(String(255), nullable=True)
    ISROUNDFINISHED = Column(String(255), nullable=True)

    # relationships (optional)
    player = relationship("Player", backref="gameplay_transactions")
    wallet = relationship("Wallet", backref="gameplay_transactions")

    __table_args__ = (
        UniqueConstraint("userId", "bank_id", "transaction_type", "external_transaction_id", name="uq_gameplay_ext"),
        Index("ix_gameplay_user", "userId"),
        Index("ix_gameplay_round", "external_gameround_id"),
        Index("ix_gameplay_game", "external_game_id"),
    )
