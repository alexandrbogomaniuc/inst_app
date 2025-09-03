from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from igw.app.config import settings

# Use the UPPERCASE name defined in Settings
engine = create_engine(settings.DB_URL, pool_pre_ping=True, future=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
