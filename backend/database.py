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

    # Phase 5 Alpha & Confirmation Logging columns
    new_cols = [
        ("spy_price_at_entry", "FLOAT"),
        ("spy_price_at_exit", "FLOAT"),
        ("beta_at_entry", "FLOAT"),
        ("market_tier_at_entry", "VARCHAR(10)"),
        ("intraday_confirmed_at_entry", "BOOLEAN"),
        ("breadth_at_entry", "FLOAT"),
        ("vix_at_entry", "FLOAT"),
        ("sector_rank_at_entry", "INTEGER"),
        ("spy_return_pct", "FLOAT"),
        ("expected_return_pct", "FLOAT"),
        ("alpha_pct", "FLOAT"),
    ]
    for col_name, col_type in new_cols:
        try:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE trades ADD COLUMN {col_name} {col_type}"))
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
            "max_positions": "8",              # max concurrent positions (updated to 8)
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
            # ── Blueprint Market Gates & Risk System (Three-mode: off | shadow | enforce) ──
            "gate_intraday_confirmation": "shadow",  # SPY > prior close & > VWAP at entry time (>= 10:00 ET)
            "gate_gap_down_veto":         "shadow",  # Block new entries if SPY opens <= -0.7%
            "gate_exposure_tiers":        "shadow",  # Graded Tier A (1.0x) / Tier B (0.5x) / Tier C (0.0x)
            "gate_market_breadth":        "shadow",  # Universe % > 50 SMA caution threshold
            "gate_sector_leadership":     "shadow",  # Allow only top-half sectors by RS vs SPY
            "sizing_beta_aware":          "shadow",  # Scale position down for beta > 1.0 (0.5x to 1.0x cap)
            "exit_market_linked":         "shadow",  # Tighten stops if SPY breaks 50 SMA or 10d swing low
            "gate_earnings_density":      "shadow",  # Reduce size if high % of candidates report in <= 10d
            # Numerical thresholds
            "gap_down_threshold_pct":     "0.7",     # Gap down % threshold to trigger veto (default 0.7%)
            "breadth_threshold_pct":      "40.0",    # Caution breadth threshold (% above 50 SMA)
            "tier_b_size_multiplier":     "0.5",     # Size multiplier for Tier B (default 0.5x)
            "tier_b_score_bump":          "5.0",     # Bump min score for Tier B (e.g. 70 -> 75)
            "vix_stress_level":           "25.0",    # VIX level separating Tier A and Tier C/stress
            "vix_spike_threshold_pct":    "20.0",    # VIX 3-session spike threshold (default 20.0%)
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
