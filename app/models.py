from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy import Column, Integer, String, Date, CHAR, TIMESTAMP, ForeignKey, DECIMAL, text

Base = declarative_base()

class Player(Base):
    __tablename__ = "players"

    userId = Column(Integer, primary_key=True, autoincrement=True)
    # keep snake_case column names that match your DB
    ext_user_id = Column(String(100), index=True)             # Instagram (or other) external id
    user_name   = Column(String(100))                         # IG username when we can get it
    first_name  = Column(String(100))
    last_name   = Column(String(100))
    email       = Column(String(255), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=False)
    language_code = Column(CHAR(2), nullable=False, server_default="en")
    registration_date = Column(TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"))
    status      = Column(String(20), server_default="active")
    date_of_birth = Column(Date)
    phone_number = Column(String(20))
    country     = Column(String(100))

class Wallet(Base):
    __tablename__ = "wallets"

    wallet_id   = Column(Integer, primary_key=True, autoincrement=True)
    userId      = Column(Integer, ForeignKey("players.userId"), nullable=False, index=True)
    wallet_type = Column(String(10), nullable=False)          # e.g. "main"
    balance     = Column(DECIMAL(15, 2), server_default="0.00")
    currency_code = Column(CHAR(3), nullable=False, server_default="USD")
    last_updated  = Column(TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"))

class Session(Base):
    __tablename__ = "sessions"

    session_id  = Column(Integer, primary_key=True, autoincrement=True)
    userId      = Column(Integer, ForeignKey("players.userId"), nullable=False, index=True)
    token       = Column(String(255), nullable=False, unique=True)
    login_time  = Column(TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"))
    logout_time = Column(TIMESTAMP, nullable=True)
    status      = Column(String(10), server_default="active")
    Login_IP    = Column(String(255), nullable=False)  # matches your schema's case
