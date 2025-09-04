# igw/app/db.py
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from igw.app.config import settings

# Accept either DB_URL or db_url in settings (keeps us resilient)
_DB_URL = getattr(settings, "DB_URL", None) or getattr(settings, "db_url", None)
if not _DB_URL:
    raise RuntimeError("Database URL is not configured (DB_URL). Check your .env")

# Example format:
# DB_URL=mysql+pymysql://user:pass@127.0.0.1:3306/apidb
engine = create_engine(
    _DB_URL,
    pool_pre_ping=True,
    pool_recycle=3600,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

# The declarative base used by all ORM models
Base = declarative_base()

def get_db():
    """FastAPI dependency that yields a DB session and closes it afterward."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

__all__ = ["Base", "engine", "SessionLocal", "get_db"]
