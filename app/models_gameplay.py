from __future__ import annotations

from sqlalchemy import Column, Integer, String, DECIMAL, TIMESTAMP, text
from igw.app.db import Base


class GameplayTransaction(Base):
    __tablename__ = "gameplay_transactions"

    transaction_id = Column(Integer, primary_key=True, autoincrement=True)
    userId = Column(Integer, nullable=False)
    wallet_id = Column(Integer, nullable=False)
    transaction_type = Column(String(10), nullable=False)  # 'bet' | 'win' | 'refund' | etc.
    amount = Column(DECIMAL(15, 2), default=0)             # store dollars/currency units (e.g., 0.80)
    transaction_date = Column(TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"))
    description = Column(String(255))
    external_transaction_id = Column(String(255))
    external_gamesession_id = Column(String(255))
    external_gameround_id = Column(String(255))
    external_game_id = Column(String(255))
    ISROUNDFINISHED = Column(String(255))
