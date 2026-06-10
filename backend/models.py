from sqlalchemy import Column, Integer, String, Float, DateTime, Text, Boolean, Date, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime, timezone

Base = declarative_base()


def utcnow():
    return datetime.now(timezone.utc)


class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String(10), nullable=False, index=True)
    shares = Column(Float, nullable=False)
    buy_price = Column(Float, nullable=True)
    sell_price = Column(Float, nullable=True)
    buy_time = Column(DateTime(timezone=True), nullable=True)
    sell_time = Column(DateTime(timezone=True), nullable=True)
    # open = bought but not yet sold
    # sold_half = half sold at take-profit (+10%), remainder still open
    # closed = fully sold (Friday sell, stop-loss, or manual)
    # error = order failed
    status = Column(String(20), default="open", nullable=False)
    mode = Column(String(20), default="paper", nullable=False)
    pnl = Column(Float, nullable=True)          # Final realised P&L on close (full position)
    pnl_pct = Column(Float, nullable=True)
    # Realised gain from the +10% partial half-sell — banked here so it is never
    # overwritten when the remaining half is closed later.
    realised_partial_pnl = Column(Float, default=0.0, nullable=True)
    fees = Column(Float, default=0.0, nullable=True)
    order_id = Column(String(50), nullable=True)
    ai_reason = Column(Text, nullable=True)

    def __repr__(self):
        return f"<Trade id={self.id} ticker={self.ticker} status={self.status}>"


class AIPick(Base):
    """Stores each week's AI stock recommendations for display in the UI."""
    __tablename__ = "ai_picks"

    id = Column(Integer, primary_key=True, index=True)
    scan_date = Column(Date, nullable=False, index=True)
    ticker = Column(String(10), nullable=False)
    reason = Column(Text, nullable=True)
    confidence = Column(Float, nullable=True)          # 0.0 – 1.0
    position_size_pct = Column(Float, nullable=True)   # Suggested % of capital
    rank = Column(Integer, nullable=True)              # 1 = highest confidence
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    def __repr__(self):
        return f"<AIPick {self.ticker} conf={self.confidence} date={self.scan_date}>"


class SystemLog(Base):
    __tablename__ = "system_logs"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    level = Column(String(10), default="INFO", nullable=False)  # INFO, ERROR, WARNING
    category = Column(String(20), nullable=False)  # scan, buy, sell, system, ibkr
    message = Column(Text, nullable=False)

    def __repr__(self):
        return f"<SystemLog id={self.id} [{self.level}] {self.category}: {self.message[:50]}>"


class Setting(Base):
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(100), unique=True, nullable=False)
    value = Column(Text, nullable=False)

    def __repr__(self):
        return f"<Setting {self.key}={self.value}>"


class AccountSnapshot(Base):
    """Daily end-of-day NetLiquidation snapshot.

    One row per calendar day (enforced by unique constraint on `date`).
    Captured by job_snapshot_net_liq() at ~15:45 ET after positions are sold.
    Used to compute the P&L Over Time chart from real account value movements
    rather than relying on the DB trade P&L fields.
    """
    __tablename__ = "account_snapshots"
    __table_args__ = (UniqueConstraint("date", name="uq_account_snapshots_date"),)

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False, index=True)
    net_liq_usd = Column(Float, nullable=False)
    net_liq_aud = Column(Float, nullable=True)
    fx_rate = Column(Float, nullable=True)       # USD → AUD rate at snapshot time
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    def __repr__(self):
        return f"<AccountSnapshot date={self.date} net_liq_usd={self.net_liq_usd}>"
