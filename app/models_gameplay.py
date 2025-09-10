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
    Enum as SAEnum,
)
from sqlalchemy.orm import relationship

# Reuse your existing Base from the main models module
from igw.app.models import Base


class GameplayTransaction(Base):
    __tablename__ = "gameplay_transactions"

    transaction_id = Column(Integer, primary_key=True, autoincrement=True)

    userId = Column(Integer, ForeignKey("players.userId"), nullable=False, index=True)
    wallet_id = Column(Integer, ForeignKey("wallets.wallet_id"), nullable=False, index=True)
    bank_id = Column(Integer, nullable=True, index=True)

    # 'bet' | 'win' | 'refund'
    transaction_type = Column(String(10), nullable=False)

    amount = Column(Numeric(15, 2), nullable=False, server_default="0.00")

    status = Column(
        SAEnum("Pending", "Processed", "Failed", name="gameplay_status"),
        nullable=False,
        server_default="Pending",
    )

    transaction_date = Column(TIMESTAMP, nullable=True, server_default=text("CURRENT_TIMESTAMP"))
    description = Column(String(255), nullable=True)

    external_transaction_id = Column(String(255), nullable=True, index=True)
    external_gamesession_id = Column(String(255), nullable=True)
    external_gameround_id = Column(String(255), nullable=True, index=True)
    external_game_id = Column(String(255), nullable=True, index=True)

    ISROUNDFINISHED = Column(String(255), nullable=True)

    # relationships (optional, but handy)
    wallet = relationship("Wallet")
    player = relationship("Player")

    __table_args__ = (
        Index("ix_gameplay_user", "userId"),
        Index("ix_gameplay_round", "external_gameround_id"),
        Index("ix_gameplay_game", "external_game_id"),
        UniqueConstraint(
            "userId",
            "bank_id",
            "transaction_type",
            "external_transaction_id",
            name="uq_gameplay_ext",
        ),
    )
