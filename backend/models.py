from sqlalchemy import Column, Integer, String, Float, DateTime, Text, Boolean
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
    # open = bought but not yet sold, closed = sold, error = failed
    status = Column(String(20), default="open", nullable=False)
    mode = Column(String(20), default="paper", nullable=False)
    pnl = Column(Float, nullable=True)
    pnl_pct = Column(Float, nullable=True)
    fees = Column(Float, default=0.0, nullable=True)
    order_id = Column(String(50), nullable=True)
    ai_reason = Column(Text, nullable=True)

    def __repr__(self):
        return f"<Trade id={self.id} ticker={self.ticker} status={self.status}>"


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
