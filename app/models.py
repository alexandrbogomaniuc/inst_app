# igw/app/models.py
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Column, Integer, String, Date, DateTime, ForeignKey, Numeric, Enum as SAEnum,
    JSON, TIMESTAMP, text, CHAR
)
from sqlalchemy.orm import relationship

from igw.app.db import Base


class Player(Base):
    __tablename__ = "players"

    userId = Column(Integer, primary_key=True, autoincrement=True)
    user_name = Column(String(255), nullable=True)
    ext_user_id = Column(String(255), nullable=True, index=True, unique=False)
    first_name = Column(String(100), nullable=True)
    last_name = Column(String(100), nullable=True)
    email = Column(String(255), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=True)
    language_code = Column(CHAR(2), nullable=False, server_default="en")
    registration_date = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    status = Column(String(20), nullable=False, server_default="active")
    date_of_birth = Column(Date, nullable=True)
    phone_number = Column(String(20), nullable=True)
    country = Column(String(100), nullable=True)

    wallets = relationship("Wallet", back_populates="player", lazy="selectin")
    sessions = relationship("UserSession", back_populates="player", lazy="selectin")


class Wallet(Base):
    __tablename__ = "wallets"

    wallet_id = Column(Integer, primary_key=True, autoincrement=True)
    userId = Column(Integer, ForeignKey("players.userId"), nullable=False, index=True)
    wallet_type = Column(String(10), nullable=False)
    balance = Column(Numeric(15, 2), nullable=False, server_default="0")
    currency_code = Column(CHAR(3), nullable=False, server_default="USD")
    last_updated = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    player = relationship("Player", back_populates="wallets")


class UserSession(Base):
    __tablename__ = "sessions"

    session_id = Column(Integer, primary_key=True, autoincrement=True)
    userId = Column(Integer, ForeignKey("players.userId"), nullable=False, index=True)
    token = Column(String(512), nullable=False, unique=True)
    session_type = Column(SAEnum("lobby", "game", name="session_type"), nullable=False, server_default="lobby")
    provider = Column(String(32), nullable=True)
    meta = Column(JSON, nullable=True)
    login_time = Column(TIMESTAMP, nullable=True, server_default=text("CURRENT_TIMESTAMP"))
    expires_at = Column(TIMESTAMP, nullable=True)
    logout_time = Column(TIMESTAMP, nullable=True)
    status = Column(String(10), nullable=False, server_default="active")
    Login_IP = Column(String(45), nullable=True)

    player = relationship("Player", back_populates="sessions")
