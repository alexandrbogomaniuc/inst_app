# igw/app/models.py

from sqlalchemy import (
    Column, Integer, String, DateTime, ForeignKey, JSON, func, Index
)
from sqlalchemy import Enum as SQLEnum   # <-- add this
from sqlalchemy.orm import relationship

from .db import Base

# --- Player (matches your current DB) --------------------------------
class Player(Base):
    __tablename__ = "players"

    userId          = Column(Integer, primary_key=True, autoincrement=True)
    user_name       = Column(String(100))
    ext_user_id     = Column(String(100), index=True)         # ig user id
    first_name      = Column(String(100))
    last_name       = Column(String(100))
    email           = Column(String(255), unique=True, nullable=False)
    password_hash   = Column(String(255))
    language_code   = Column(String(2), nullable=False, default="en")
    registration_date = Column(DateTime, server_default=func.now())
    status          = Column(String(20), default="active")
    date_of_birth   = Column(DateTime)
    phone_number    = Column(String(20))
    country         = Column(String(100))

    wallets   = relationship("Wallet", back_populates="player")
    sessions  = relationship("UserSession", back_populates="player")

# --- Wallet (matches your current DB) --------------------------------
class Wallet(Base):
    __tablename__ = "wallets"

    wallet_id     = Column(Integer, primary_key=True, autoincrement=True)
    userId        = Column(Integer, ForeignKey("players.userId"), nullable=False)
    wallet_type   = Column(String(10), nullable=False, default="CASH")
    balance       = Column(String(32), default="0.00")   # or DECIMAL if you prefer
    currency_code = Column(String(3), nullable=False, default="USD")
    last_updated  = Column(DateTime, server_default=func.now())

    player = relationship("Player", back_populates="wallets")

# --- Sessions (single source of truth for lobby+games) ----------------
class UserSession(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        Index("ix_sessions_user_status", "userId", "status", "session_type"),
        Index("ix_sessions_expires_at", "expires_at"),
    )

    session_id   = Column(Integer, primary_key=True, autoincrement=True)
    userId       = Column(Integer, ForeignKey("players.userId"), nullable=False)
    token        = Column(String(512), unique=True, nullable=False)
    session_type = Column(SQLEnum("lobby", "game", name="session_type_enum"),
                          nullable=False, default="lobby")
    provider     = Column(String(32))               # e.g., "BSG" for game sessions
    meta         = Column(JSON)

    login_time   = Column(DateTime, server_default=func.now(), nullable=False)
    expires_at   = Column(DateTime)
    logout_time  = Column(DateTime)
    status       = Column(String(10), default="active")
    Login_IP     = Column(String(45))

    player = relationship("Player", back_populates="sessions")
