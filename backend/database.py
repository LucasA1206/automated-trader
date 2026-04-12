import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
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
    
    # Safely migrate existing trades table to add 'mode' column
    try:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE trades ADD COLUMN mode VARCHAR(20) DEFAULT 'paper' NOT NULL"))
    except Exception:
        pass  # Column likely already exists

    db = SessionLocal()
    try:
        defaults = {
            "trading_mode": "paper",      # paper | live
            "account_type": "trading_cash",   # trading_cash | investment_cash
            "paper_strategy": "cash",         # cash | margin comparison preset
            "daily_budget_pct": "50",         # derived from paper_strategy
            "max_positions": "3",             # derived from paper_strategy
            "scan_enabled": "true",       # pause/resume auto scanning
            "margin_upgrade_alerted": "false",
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
