import os
import logging
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
# noqa: F401 – all model imports trigger table creation
from models import Base, Setting, AccountSnapshot, ScanResult, TradeJournalEntry  # noqa: F401

_db_logger = logging.getLogger(__name__)


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./blitz_trader.db")

# Railway and Heroku provide postgres:// but SQLAlchemy 2.x requires postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """Create all tables and seed default settings."""
    Base.metadata.create_all(bind=engine)

    # ── Schema migrations (idempotent — each wrapped in try/except) ────────────

    # Add 'mode' column to trades (legacy migration)
    try:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE trades ADD COLUMN mode VARCHAR(20) DEFAULT 'paper' NOT NULL"))
    except Exception:
        pass  # Column already exists

    # Add 'fees' column to trades (legacy migration)
    try:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE trades ADD COLUMN fees FLOAT DEFAULT 0.0"))
    except Exception:
        pass  # Column already exists

    # Add 'realised_partial_pnl' column — banks partial gains from +10% half-sells
    # so they are never lost when the remaining half is closed.
    try:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE trades ADD COLUMN realised_partial_pnl FLOAT DEFAULT 0.0"))
    except Exception:
        pass  # Column already exists

    # ── Blueprint strategy columns ─────────────────────────────────────────────
    # ATR-based stop price placed at IBKR at entry
    try:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE trades ADD COLUMN stop_price FLOAT"))
    except Exception:
        pass

    # IBKR order ID for the native stop order
    try:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE trades ADD COLUMN stop_order_id VARCHAR(50)"))
    except Exception:
        pass

    # 1.5R partial exit target price
    try:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE trades ADD COLUMN partial_target_price FLOAT"))
    except Exception:
        pass

    # Whether the 1.5R partial has been executed
    try:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE trades ADD COLUMN partial_sold BOOLEAN DEFAULT FALSE"))
    except Exception:
        pass

    # Current Chandelier trailing stop price
    try:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE trades ADD COLUMN trailing_stop_price FLOAT"))
    except Exception:
        pass

    # Entry composite score (for journaling / post-trade analysis)
    try:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE trades ADD COLUMN entry_composite_score FLOAT"))
    except Exception:
        pass

    # ATR value at time of entry (used for exit engine calculations)
    try:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE trades ADD COLUMN atr_at_entry FLOAT"))
    except Exception:
        pass

    # Sector at entry (for risk engine sector-cap gate)
    try:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE trades ADD COLUMN sector VARCHAR(50)"))
    except Exception:
        pass

    # ── Default settings seed ──────────────────────────────────────────────────
    db = SessionLocal()
    try:
        defaults = {
            "trading_mode": "paper",           # paper | live
            "account_type": "trading_cash",    # trading_cash | investment_cash
            "paper_strategy": "cash",          # cash | margin comparison preset
            "daily_budget_pct": "100",         # % of available cash per daily cycle
            "max_positions": "4",              # max concurrent positions (blueprint: 4)
            "scan_enabled": "true",            # pause/resume auto scanning
            "trader_enabled": "true",          # Master switch
            "margin_upgrade_alerted": "false",
            "entry_macd_check": "false",       # Intraday MACD turning check (false = loosened/disabled)
            "entry_min_rel_vol": "0.4",        # Minimum relative volume for entry (0.4x)
            "entry_rsi_min": "30",             # RSI entry lower threshold
            "entry_rsi_max": "70",             # RSI entry upper threshold
            "entry_pullback_max_pct": "5.0",   # Max % price above 20-day SMA
            "entry_vwap_required": "false",    # Require price > VWAP for entry
            "entry_adx_min": "15",             # Minimum ADX threshold
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


def log_event(db, category: str, message: str, level: str = "INFO"):
    """
    Write a system log entry to the system_logs table.
    This is the canonical implementation — importable from database or jobs.
    """
    from models import SystemLog
    entry = SystemLog(
        timestamp=datetime.now(timezone.utc),
        level=level,
        category=category,
        message=message,
    )
    db.add(entry)
    db.commit()
    _db_logger.info("[%s] %s", category.upper(), message)


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
