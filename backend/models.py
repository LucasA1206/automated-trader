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
    # sold_half = 1.5R partial exit done; remainder still open
    # closing = sell order in-flight (concurrency guard)
    # closed = fully exited
    # error = order failed
    status = Column(String(20), default="open", nullable=False)
    mode = Column(String(20), default="paper", nullable=False)
    pnl = Column(Float, nullable=True)          # Final realised P&L on full close
    pnl_pct = Column(Float, nullable=True)
    # Realised gain from the 1.5R partial half-sell — banked here so it is
    # never overwritten when the remaining half is closed later.
    realised_partial_pnl = Column(Float, default=0.0, nullable=True)
    fees = Column(Float, default=0.0, nullable=True)
    order_id = Column(String(50), nullable=True)
    ai_reason = Column(Text, nullable=True)

    # ── New blueprint fields (added via migration in database.py) ────────────
    # ATR-based stop placed at IBKR at time of entry
    stop_price = Column(Float, nullable=True)
    # IBKR order ID for the native stop order
    stop_order_id = Column(String(50), nullable=True)
    # 1.5R partial exit target price
    partial_target_price = Column(Float, nullable=True)
    # Whether the 1.5R partial has been executed
    partial_sold = Column(Boolean, default=False, nullable=True)
    # Current trailing stop price (updated by Chandelier exit)
    trailing_stop_price = Column(Float, nullable=True)
    # Entry composite score (from scoring engine, for journaling)
    entry_composite_score = Column(Float, nullable=True)
    # ATR value at time of entry (used for exit calculations)
    atr_at_entry = Column(Float, nullable=True)
    # Sector at entry (for risk engine sector-cap gate)
    sector = Column(String(50), nullable=True)

    # Strategy engine: 'momentum' (default) | 'mean_reversion'
    strategy_engine = Column(String(30), default="momentum", nullable=True)
    # Progressive +0.75R breakeven stop flag: True once stop has moved to breakeven + cushion
    breakeven_moved = Column(Boolean, default=False, nullable=True)

    # ── Phase 5 Alpha & Confirmation Logging ─────────────────────────────────
    spy_price_at_entry = Column(Float, nullable=True)
    spy_price_at_exit = Column(Float, nullable=True)
    beta_at_entry = Column(Float, nullable=True)
    market_tier_at_entry = Column(String(10), nullable=True)
    intraday_confirmed_at_entry = Column(Boolean, nullable=True)
    breadth_at_entry = Column(Float, nullable=True)
    vix_at_entry = Column(Float, nullable=True)
    sector_rank_at_entry = Column(Integer, nullable=True)
    spy_return_pct = Column(Float, nullable=True)
    expected_return_pct = Column(Float, nullable=True)
    alpha_pct = Column(Float, nullable=True)

    def __repr__(self):
        return f"<Trade id={self.id} ticker={self.ticker} status={self.status}>"


class AIPick(Base):
    """Stores each day's AI-approved scan candidates for display in the UI."""
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


class ScanResult(Base):
    """
    Stores the output of each daily pre-market scan run.
    One row per scan execution (typically one per trading day at 07:30 ET).
    Includes regime status, candidate metrics, and the final action taken.
    """
    __tablename__ = "scan_results"

    id = Column(Integer, primary_key=True, index=True)
    scan_date = Column(Date, nullable=False, index=True)
    # regime_status: "risk_on" | "caution" | "risk_off"
    regime_status = Column(String(20), nullable=True)
    regime_details = Column(Text, nullable=True)
    candidates_count = Column(Integer, default=0)       # Total shortlist after all filters
    high_conviction_count = Column(Integer, default=0)  # Score >= 70
    marginal_count = Column(Integer, default=0)         # Score 55-69
    # action_taken: "trade" | "no_trade" | "regime_off" | "risk_blocked" | "ai_rejected"
    action_taken = Column(String(30), nullable=True)
    # JSON array of all scored candidates with metrics
    candidates_json = Column(Text, nullable=True)
    # JSON dict of rejection reasons per ticker
    rejection_summary = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    def __repr__(self):
        return f"<ScanResult date={self.scan_date} regime={self.regime_status} action={self.action_taken}>"


class TradeJournalEntry(Base):
    """
    Rich per-trade event log (extends Trade with time-series of lifecycle events).
    Each row records one event in a trade's life: entry, partial exit, stop update, etc.
    """
    __tablename__ = "trade_journal_entries"

    id = Column(Integer, primary_key=True, index=True)
    trade_id = Column(Integer, nullable=False, index=True)  # FK to trades.id
    # event_type: entry | partial_exit | stop_update | full_exit |
    #             time_exit | ma_exit | atr_expansion | pre_event_exit |
    #             trail_update | circuit_breaker
    event_type = Column(String(30), nullable=False)
    details = Column(Text, nullable=True)
    composite_score = Column(Float, nullable=True)
    confidence_score = Column(Integer, nullable=True)
    stop_price = Column(Float, nullable=True)
    trailing_stop_price = Column(Float, nullable=True)
    ai_gemini_json = Column(Text, nullable=True)
    ai_crosscheck_json = Column(Text, nullable=True)
    regime_at_event = Column(String(20), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    def __repr__(self):
        return f"<TradeJournalEntry trade_id={self.trade_id} type={self.event_type}>"


class SystemLog(Base):
    __tablename__ = "system_logs"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    level = Column(String(10), default="INFO", nullable=False)  # INFO, ERROR, WARNING
    category = Column(String(20), nullable=False)  # scan, buy, sell, system, ibkr, risk
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
    Captured by job_eod_snapshot() at ~15:45 ET.
    Used to compute the P&L Over Time chart from real account value movements
    and to track peak equity for drawdown circuit breakers.
    """
    __tablename__ = "account_snapshots"
    __table_args__ = (UniqueConstraint("date", name="uq_account_snapshots_date"),)

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False, index=True)
    net_liq_usd = Column(Float, nullable=False)
    net_liq_aud = Column(Float, nullable=True)
    fx_rate = Column(Float, nullable=True)       # USD -> AUD rate at snapshot time
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    def __repr__(self):
        return f"<AccountSnapshot date={self.date} net_liq_usd={self.net_liq_usd}>"


class ShadowEvaluation(Base):
    """
    Tracks hypothetical trade outcomes for gates operating in shadow mode.
    Allows comparing what WOULD have happened if gates were enforced vs baseline.
    """
    __tablename__ = "shadow_evaluations"

    id = Column(Integer, primary_key=True, index=True)
    trade_id = Column(Integer, nullable=True, index=True)
    ticker = Column(String(10), nullable=False, index=True)
    gate_name = Column(String(50), nullable=False)   # e.g. gap_veto, intraday_confirm, sector_gate, tier_b
    mode = Column(String(20), default="shadow", nullable=False)
    would_have_blocked = Column(Boolean, default=False, nullable=False)
    actual_pnl = Column(Float, nullable=True)
    actual_pnl_pct = Column(Float, nullable=True)
    hypothetical_pnl = Column(Float, nullable=True)  # e.g. $0 if blocked
    hypothetical_pnl_pct = Column(Float, nullable=True)
    details = Column(Text, nullable=True)
    # ── Feature 4: Forward Hypothetical Outcome & Near-Miss Tracking ──────────
    is_near_miss = Column(Boolean, default=False, nullable=False)
    hypothetical_action = Column(String(40), nullable=True)  # block | resize_0.5x | near_miss_score | near_miss_filter
    entry_price = Column(Float, nullable=True)
    stop_price = Column(Float, nullable=True)
    partial_target_price = Column(Float, nullable=True)
    trailing_stop_price = Column(Float, nullable=True)
    high_watermark = Column(Float, nullable=True)
    partial_taken = Column(Boolean, default=False, nullable=False)
    market_state_json = Column(Text, nullable=True)
    outcome_status = Column(String(20), default="open", nullable=False)  # open | resolved
    exit_reason = Column(String(50), nullable=True)
    exit_price = Column(Float, nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    def __repr__(self):
        return f"<ShadowEvaluation {self.ticker} gate={self.gate_name} would_block={self.would_have_blocked}>"


class SystemAlert(Base):
    """
    In-app alerts emitted by data-quality monitors, position reconciliation,
    de-risking ladder, and critical failures. Supports deduplication and
    operator acknowledgement.
    """
    __tablename__ = "system_alerts"

    id = Column(Integer, primary_key=True, index=True)
    alert_key = Column(String(120), nullable=False, index=True)
    severity = Column(String(20), default="info", nullable=False)  # info | warning | critical
    category = Column(String(30), nullable=False, index=True)     # data_quality | reconciliation | derisk | report | system
    title = Column(String(200), nullable=False)
    message = Column(Text, nullable=False)
    details_json = Column(Text, nullable=True)
    acknowledged = Column(Boolean, default=False, nullable=False)
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    acknowledged_by = Column(String(100), nullable=True)
    resolved = Column(Boolean, default=False, nullable=False)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    def __repr__(self):
        return f"<SystemAlert id={self.id} [{self.severity}] {self.alert_key}>"


class DataHealthCheck(Base):
    """
    Time-series log of data-quality and reconciliation check results.
    """
    __tablename__ = "data_health_checks"

    id = Column(Integer, primary_key=True, index=True)
    check_name = Column(String(80), nullable=False, index=True)
    status = Column(String(20), nullable=False)  # ok | warning | critical
    summary = Column(Text, nullable=False)
    details_json = Column(Text, nullable=True)
    checked_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    def __repr__(self):
        return f"<DataHealthCheck {self.check_name} status={self.status}>"


class DeRiskState(Base):
    """
    Singleton state row for the Automatic De-Risking Ladder (Feature 1).
    Levels:
      0 = Normal
      1 = Caution (0.5x size, +score bump)
      2 = Pause (no new entries; exits still managed)
      3 = Flatten & Halt (close all positions, manual re-enable required)
    """
    __tablename__ = "derisk_state"

    id = Column(Integer, primary_key=True, index=True)
    level = Column(Integer, default=0, nullable=False)
    reason = Column(Text, nullable=True)
    trigger_metrics_json = Column(Text, nullable=True)
    escalated_at = Column(DateTime(timezone=True), nullable=True)
    deescalated_at = Column(DateTime(timezone=True), nullable=True)
    deescalated_by = Column(String(100), nullable=True)
    updated_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    def __repr__(self):
        return f"<DeRiskState level={self.level}>"


class DeRiskEvent(Base):
    """
    Immutable audit log of every de-risk ladder transition (automatic escalations
    and manual operator de-escalations).
    """
    __tablename__ = "derisk_events"

    id = Column(Integer, primary_key=True, index=True)
    from_level = Column(Integer, nullable=False)
    to_level = Column(Integer, nullable=False)
    action_type = Column(String(30), nullable=False)  # escalate | manual_deescalate
    trigger = Column(String(120), nullable=False)
    details = Column(Text, nullable=True)
    actor = Column(String(100), default="system", nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    def __repr__(self):
        return f"<DeRiskEvent {self.from_level}->{self.to_level} ({self.action_type})>"


class WeeklyReport(Base):
    """
    Persisted weekly performance, data-quality, and shadow-tracking report
    generated automatically (default: Saturday morning) or on demand.
    Observational only.
    """
    __tablename__ = "weekly_reports"

    id = Column(Integer, primary_key=True, index=True)
    period_start = Column(Date, nullable=False, index=True)
    period_end = Column(Date, nullable=False, index=True)
    total_trades = Column(Integer, default=0, nullable=False)
    strategy_return_pct = Column(Float, default=0.0, nullable=False)
    spy_return_pct = Column(Float, default=0.0, nullable=False)
    alpha_pct = Column(Float, default=0.0, nullable=False)
    derisk_level = Column(Integer, default=0, nullable=False)
    report_json = Column(Text, nullable=False)
    summary_text = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    def __repr__(self):
        return f"<WeeklyReport {self.period_start}..{self.period_end} trades={self.total_trades}>"


class PendingExitIntent(Base):
    """
    Persisted idempotent exit intent for open positions (Phase 1).
    Prevents duplicate exit orders and avoids retrying closed-market exits
    every 5 minutes on holidays/weekends.
    """
    __tablename__ = "pending_exit_intents"

    id = Column(Integer, primary_key=True, index=True)
    trade_id = Column(Integer, nullable=False, index=True)
    ticker = Column(String(10), nullable=False, index=True)
    reason = Column(String(50), nullable=False)
    details = Column(Text, nullable=True)
    shares = Column(Float, nullable=False)
    status = Column(String(20), default="pending", nullable=False)  # pending | submitted | filled | failed | cancelled
    order_id = Column(String(50), nullable=True)
    attempt_count = Column(Integer, default=0, nullable=False)
    last_error = Column(Text, nullable=True)
    last_attempt_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    def __repr__(self):
        return f"<PendingExitIntent {self.ticker} reason={self.reason} status={self.status}>"
