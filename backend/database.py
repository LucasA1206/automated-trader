import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Base, Setting

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./blitz_trader.db")

# Railway and Heroku provide postgres:// but SQLAlchemy 2.x requires postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """Create all tables and seed default settings."""
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        defaults = {
            "trading_mode": "paper",      # paper | live
            "daily_budget_pct": "100",    # percentage of cash to use per day
            "max_positions": "5",         # max simultaneous open trades
            "scan_enabled": "true",       # pause/resume auto scanning
        }
        for key, value in defaults.items():
            existing = db.query(Setting).filter(Setting.key == key).first()
            if not existing:
                db.add(Setting(key=key, value=value))
        db.commit()
    finally:
        db.close()


def get_db():
    """FastAPI dependency: yields a DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_setting(db, key: str, default: str = None) -> str:
    """Helper to fetch a setting value by key."""
    setting = db.query(Setting).filter(Setting.key == key).first()
    return setting.value if setting else default


def set_setting(db, key: str, value: str):
    """Helper to upsert a setting."""
    setting = db.query(Setting).filter(Setting.key == key).first()
    if setting:
        setting.value = value
    else:
        db.add(Setting(key=key, value=value))
    db.commit()
