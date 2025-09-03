# igw/app/models.py
from __future__ import annotations

from sqlalchemy import (
    Column,
    Integer,
    String,
    Date,
    DateTime,
    Numeric,
    ForeignKey,
    func,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


# ----------------------------
# players
# ----------------------------
class Player(Base):
    __tablename__ = "players"

    # NOTE: DB column names are preserved exactly via the first argument to Column(...)
    user_id = Column("userId", Integer, primary_key=True, autoincrement=True)

    # present in your DB (nullable)
    user_name = Column("user_name", String(255))

    # IMPORTANT: this matches your table (snake_case)
    ext_user_id = Column("ext_user_id", String(100), index=True)

    first_name = Column("first_name", String(100))
    last_name = Column("last_name", String(100))
    email = Column("email", String(255), unique=True, nullable=False)
    password_hash = Column("password_hash", String(255), nullable=False)
    language_code = Column("language_code", String(2), nullable=False, default="en")
    registration_date = Column(
        "registration_date", DateTime, server_default=func.current_timestamp()
    )
    status = Column("status", String(20), default="active")
    date_of_birth = Column("date_of_birth", Date)
    phone_number = Column("phone_number", String(20))
    country = Column("country", String(100))

    # relationships
    wallets = relationship(
        "Wallet", back_populates="player", cascade="all, delete-orphan"
    )
    sessions = relationship(
        "Session", back_populates="player", cascade="all, delete-orphan"
    )
    free_round_bonuses = relationship(
        "FreeRoundBonus", back_populates="player", cascade="all, delete-orphan"
    )
    gameplay_transactions = relationship(
        "GameplayTransaction", back_populates="player", cascade="all, delete-orphan"
    )
    bonus_transactions = relationship(
        "BonusTransaction", back_populates="player", cascade="all, delete-orphan"
    )
    audit_logs = relationship(
        "AuditLog", back_populates="player", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Player userId={self.user_id} email={self.email!r}>"


# ----------------------------
# sessions
# ----------------------------
class Session(Base):
    __tablename__ = "sessions"

    session_id = Column("session_id", Integer, primary_key=True, autoincrement=True)
    user_id = Column("userId", Integer, ForeignKey("players.userId"), nullable=False)
    token = Column("token", String(255), unique=True, nullable=False)
    login_time = Column("login_time", DateTime, server_default=func.current_timestamp())
    logout_time = Column("logout_time", DateTime)
    status = Column("status", String(10), default="active")
    login_ip = Column("Login_IP", String(255), unique=True, nullable=False)

    player = relationship("Player", back_populates="sessions")


# ----------------------------
# wallets
# ----------------------------
class Wallet(Base):
    __tablename__ = "wallets"

    wallet_id = Column("wallet_id", Integer, primary_key=True, autoincrement=True)
    user_id = Column("userId", Integer, ForeignKey("players.userId"), nullable=False)
    wallet_type = Column("wallet_type", String(10), nullable=False)  # e.g. CASH/BONUS
    balance = Column("balance", Numeric(15, 2), default=0)
    currency_code = Column("currency_code", String(3), nullable=False, default="USD")
    last_updated = Column(
        "last_updated", DateTime, server_default=func.current_timestamp()
    )

    player = relationship("Player", back_populates="wallets")
    gameplay_transactions = relationship(
        "GameplayTransaction", back_populates="wallet", cascade="all, delete-orphan"
    )
    deposit_withdrawal_transactions = relationship(
        "DepositWithdrawalTransaction",
        back_populates="wallet",
        cascade="all, delete-orphan",
    )


# ----------------------------
# free_round_bonuses
# ----------------------------
class FreeRoundBonus(Base):
    __tablename__ = "free_round_bonuses"

    bonus_id = Column("bonus_id", Integer, primary_key=True, autoincrement=True)
    user_id = Column("userId", Integer, ForeignKey("players.userId"), nullable=False)
    granted_date = Column(
        "granted_date", DateTime, server_default=func.current_timestamp()
    )
    rounds = Column("rounds", Integer, default=0)
    start_date = Column("start_date", DateTime)
    expiry_date = Column("expiry_date", DateTime)
    ex_bonus_id = Column("ex_bonus_id", Integer, nullable=False)
    description = Column("description", String(255))
    status = Column("status", String(255))

    player = relationship("Player", back_populates="free_round_bonuses")
    bonus_transactions = relationship(
        "BonusTransaction", back_populates="bonus", cascade="all, delete-orphan"
    )


# ----------------------------
# gameplay_transactions
# ----------------------------
class GameplayTransaction(Base):
    __tablename__ = "gameplay_transactions"

    transaction_id = Column(
        "transaction_id", Integer, primary_key=True, autoincrement=True
    )
    user_id = Column("userId", Integer, ForeignKey("players.userId"), nullable=False)
    wallet_id = Column(
        "wallet_id", Integer, ForeignKey("wallets.wallet_id"), nullable=False
    )
    transaction_type = Column("transaction_type", String(10), nullable=False)
    amount = Column("amount", Numeric(15, 2), default=0)
    transaction_date = Column(
        "transaction_date", DateTime, server_default=func.current_timestamp()
    )
    description = Column("description", String(255))
    external_transaction_id = Column("external_transaction_id", String(255))
    external_gamesession_id = Column("external_gamesession_id", String(255))
    external_gameround_id = Column("external_gameround_id", String(255))
    external_game_id = Column("external_game_id", String(255))
    is_round_finished = Column("ISROUNDFINISHED", String(255))

    player = relationship("Player", back_populates="gameplay_transactions")
    wallet = relationship("Wallet", back_populates="gameplay_transactions")


# ----------------------------
# deposit_withdrawal_transactions
# ----------------------------
class DepositWithdrawalTransaction(Base):
    __tablename__ = "deposit_withdrawal_transactions"

    transaction_id = Column(
        "transaction_id", Integer, primary_key=True, autoincrement=True
    )
    wallet_id = Column(
        "wallet_id", Integer, ForeignKey("wallets.wallet_id"), nullable=False
    )
    transaction_type = Column("transaction_type", String(10), nullable=False)
    amount = Column("amount", Numeric(15, 2), nullable=False)
    transaction_date = Column(
        "transaction_date", DateTime, server_default=func.current_timestamp()
    )
    description = Column("description", String(255))
    external_service_reference = Column("external_service_reference", String(255))
    external_transaction_id = Column("external_transaction_id", String(255))
    status = Column("status", String(10), default="pending")
    currency_code = Column("currency_code", String(3), nullable=False, default="USD")

    wallet = relationship("Wallet", back_populates="deposit_withdrawal_transactions")


# ----------------------------
# bonus_transactions
# ----------------------------
class BonusTransaction(Base):
    __tablename__ = "bonus_transactions"

    transaction_id = Column(
        "transaction_id", Integer, primary_key=True, autoincrement=True
    )
    user_id = Column("userid", Integer, ForeignKey("players.userId"), nullable=False)
    transaction_type = Column("transaction_type", String(10), nullable=False)
    amount = Column("amount", Numeric(15, 2), nullable=False)
    transaction_date = Column(
        "transaction_date", DateTime, server_default=func.current_timestamp()
    )
    description = Column("description", String(255))
    external_transaction_id = Column("external_transaction_id", String(255))
    bonus_id = Column(
        "bonus_id", Integer, ForeignKey("free_round_bonuses.bonus_id"), nullable=True
    )
    external_game_id = Column("external_game_id", String(255))
    is_round_finished = Column("ISROUNDFINISHED", String(255))

    player = relationship("Player", back_populates="bonus_transactions")
    bonus = relationship("FreeRoundBonus", back_populates="bonus_transactions")


# ----------------------------
# audit_logs
# ----------------------------
class AuditLog(Base):
    __tablename__ = "audit_logs"

    log_id = Column("log_id", Integer, primary_key=True, autoincrement=True)
    user_id = Column("userId", Integer, ForeignKey("players.userId"))
    action = Column("action", String(255), nullable=False)
    timestamp = Column("timestamp", DateTime, server_default=func.current_timestamp())
    ip_address = Column("ip_address", String(45))

    player = relationship("Player", back_populates="audit_logs")
