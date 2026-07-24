"""
Exit Engine — Phase 6
=====================
Implements all exit rules from blueprint Section 9.

Exit rules (checked in priority order per blueprint):
  1. Hard stop-loss: price falls to (or below) ATR-based stop
     → Sell all shares immediately (order already placed at IBKR as a native stop)
     → Software stop is the safety net in case IBKR stop didn't execute
  2. 1.5R partial exit: price reaches 1.5R above entry
     → Sell 50% of shares (bank profits), move stop to breakeven
     → trade.status = "sold_half"
  3. Trailing stop (Chandelier Exit): price > 2× ATR above highest high since entry
     → Update stop upward; sell if price falls through updated trail
  4. MA trend break: price closes below 20-day SMA (held ≥ 5 days since entry)
     → Soft exit signal — exit on next day's open (logged, not immediate)
  5. Time exit (soft): price > 0 but no meaningful progress after 10 days
     → Log warning; remain in position (monitor more closely)
  6. Time exit (hard): still open after 20 trading days
     → Exit regardless of price (blueprint Section 9 hard limit)
  7. ATR expansion exit: ATR doubles from entry (volatility regime change)
     → Risk management exit — position characteristics changed materially
  8. Pre-event exit: earnings within 2 trading days
     → Exit to avoid binary catalyst exposure

Stop placement rules (blueprint Section 9):
  - Initial stop: 1.5–2× ATR below entry (closer to 1.5× when ADX > 25)
  - Breakeven stop: after 1.5R partial, move stop to entry price
  - Chandelier trail: highest high since entry minus 2× ATR (never move backward)
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from strategy.data_layer import fetch_ohlcv, is_near_earnings, estimate_vwap

logger = logging.getLogger(__name__)

# Constants per blueprint Section 9
INITIAL_STOP_ATR_MULTIPLIER_DEFAULT = 1.75  # 1.5–2× range; use 1.75 by default
INITIAL_STOP_ATR_MULTIPLIER_STRONG  = 1.50  # Tighter when ADX > 25
PARTIAL_EXIT_R_MULTIPLE = 1.5   # Sell 50% at 1.5R
TRAIL_ATR_MULTIPLIER = 2.0      # Chandelier: highest_high - 2× ATR
MA_TREND_BREAK_WINDOW = 20      # 20-day SMA for trend break
MIN_DAYS_FOR_MA_EXIT = 5        # Must hold ≥ 5 days before MA exit applies
TIME_EXIT_SOFT_DAYS = 10        # Log warning, continue monitoring
TIME_EXIT_HARD_DAYS = 20        # Mandatory exit
ATR_EXPANSION_FACTOR = 2.0      # Exit if ATR doubles since entry
EARNINGS_BLACKOUT_TRADING_DAYS = 2  # Exit if earnings within 2 trading days


def compute_initial_stop(
    entry_price: float,
    atr14: float,
    adx14: Optional[float] = None,
) -> float:
    """
    Compute the initial hard stop price using ATR.
    Tighter stop (1.5×) when trend is very strong (ADX > 25).
    Standard stop (1.75×) otherwise.

    Returns stop_price (always below entry_price).
    """
    multiplier = (
        INITIAL_STOP_ATR_MULTIPLIER_STRONG
        if adx14 and adx14 > 25
        else INITIAL_STOP_ATR_MULTIPLIER_DEFAULT
    )
    stop = entry_price - (atr14 * multiplier)
    return round(max(stop, entry_price * 0.85), 4)  # Floor at 15% below entry


def compute_partial_target(entry_price: float, stop_price: float) -> float:
    """
    Compute the 1.5R partial exit target.
    R = entry_price - stop_price (risk per share)
    Target = entry_price + 1.5 × R
    """
    r = entry_price - stop_price
    return round(entry_price + (PARTIAL_EXIT_R_MULTIPLE * r), 4)


def compute_chandelier_trail(
    highest_high_since_entry: float,
    atr14: float,
) -> float:
    """
    Compute the Chandelier Exit trailing stop.
    = highest_high_since_entry - (ATR14 × TRAIL_MULTIPLIER)

    Note: never move the trailing stop backward (only upward from the initial stop).
    """
    trail = highest_high_since_entry - (atr14 * TRAIL_ATR_MULTIPLIER)
    return round(trail, 4)


def _get_trading_days_since(buy_time: datetime) -> int:
    """Approximate trading days since buy_time (calendar days × 5/7)."""
    if buy_time is None:
        return 0
    now = datetime.now(timezone.utc)
    if buy_time.tzinfo is None:
        buy_time = buy_time.replace(tzinfo=timezone.utc)
    calendar_days = (now - buy_time).days
    return int(calendar_days * 5 / 7)


class ExitSignal:
    """Encapsulates an exit decision from the exit engine."""

    def __init__(
        self,
        action: str,          # "hold", "partial_exit", "full_exit"
        reason: str,          # e.g. "stop_loss", "1.5r_partial", "time_hard", ...
        urgency: str,         # "immediate", "next_open", "monitor"
        new_stop_price: Optional[float] = None,
        shares_to_sell: Optional[int] = None,
        details: str = "",
    ):
        self.action = action
        self.reason = reason
        self.urgency = urgency
        self.new_stop_price = new_stop_price
        self.shares_to_sell = shares_to_sell
        self.details = details

    def is_exit(self) -> bool:
        return self.action in ("partial_exit", "full_exit")

    def is_full_exit(self) -> bool:
        return self.action == "full_exit"

    def __repr__(self):
        return f"<ExitSignal action={self.action} reason={self.reason} urgency={self.urgency}>"


def check_exit_conditions(
    trade,                         # Trade DB object (from models.py)
    current_price: float,
    live_shares: int,
    account_equity: float,
) -> ExitSignal:
    """
    Evaluate all exit conditions for an open trade.
    Returns an ExitSignal with the most urgent applicable action.

    Priority (highest to lowest):
      1. Hard stop-loss (immediate)
      2. ATR expansion (immediate)
      3. Pre-event exit (immediate if earnings tomorrow)
      4. 1.5R partial exit (immediate)
      5. Trailing stop update (monitor — update stop, not an exit unless breached)
      6. MA trend break (next open)
      7. Time exit hard/soft (next open / monitor)
    """
    ticker    = trade.ticker
    entry     = trade.buy_price
    stop      = trade.stop_price
    status    = trade.status
    buy_time  = trade.buy_time
    atr_entry = getattr(trade, "atr_at_entry", None)
    partial_sold = getattr(trade, "partial_sold", False)
    partial_target = getattr(trade, "partial_target_price", None)
    current_trail  = getattr(trade, "trailing_stop_price", None)

    if not entry or entry <= 0:
        return ExitSignal("hold", "no_entry_price", "monitor",
                          details="Entry price not recorded — cannot check exit conditions")

    holding_days = _get_trading_days_since(buy_time)
    pct_change = (current_price - entry) / entry * 100

    # ── 1. Hard stop-loss ────────────────────────────────────────────────────
    effective_stop = stop or (entry * 0.95)  # Fallback: 5% stop if not set

    # Compute fallback targets if missing on legacy/auto-registered trades
    if not partial_target and entry > 0 and effective_stop > 0 and entry > effective_stop:
        partial_target = compute_partial_target(entry, effective_stop)
    if not atr_entry and entry > 0 and effective_stop > 0 and entry > effective_stop:
        atr_entry = (entry - effective_stop) / 1.75
    if current_price <= effective_stop:
        return ExitSignal(
            action="full_exit",
            reason="stop_loss",
            urgency="immediate",
            shares_to_sell=live_shares,
            details=(
                f"Price ${current_price:.4f} hit stop ${effective_stop:.4f} "
                f"({pct_change:+.2f}% from entry ${entry:.4f})"
            ),
        )

    # ── 2. ATR expansion exit ────────────────────────────────────────────────
    if atr_entry and atr_entry > 0:
        # Fetch current ATR (approximate via recent OHLCV)
        df = fetch_ohlcv(ticker, period="60d")
        if df is not None and len(df) >= 15:
            from strategy.universe_filter import _compute_atr
            current_atr = _compute_atr(df, 14)
            if current_atr and current_atr >= atr_entry * ATR_EXPANSION_FACTOR:
                return ExitSignal(
                    action="full_exit",
                    reason="atr_expansion",
                    urgency="immediate",
                    shares_to_sell=live_shares,
                    details=(
                        f"ATR expanded from {atr_entry:.3f} to {current_atr:.3f} "
                        f"({current_atr/atr_entry:.1f}× — volatility regime changed)"
                    ),
                )

    # ── 3. Pre-event exit (earnings within 2 trading days) ──────────────────
    if holding_days >= 2 and is_near_earnings(ticker, EARNINGS_BLACKOUT_TRADING_DAYS):
        return ExitSignal(
            action="full_exit",
            reason="pre_event_exit",
            urgency="immediate",
            shares_to_sell=live_shares,
            details=f"Earnings within {EARNINGS_BLACKOUT_TRADING_DAYS} trading days — exiting to avoid binary catalyst",
        )

    # ── 4. 1.5R partial exit ─────────────────────────────────────────────────
    if status == "open" and not partial_sold and partial_target:
        if current_price >= partial_target:
            half_shares = max(1, live_shares // 2)
            return ExitSignal(
                action="partial_exit",
                reason="1_5r_partial",
                urgency="immediate",
                shares_to_sell=half_shares,
                new_stop_price=entry,  # Move stop to breakeven after partial
                details=(
                    f"Price ${current_price:.4f} reached 1.5R target ${partial_target:.4f} "
                    f"({pct_change:+.2f}%). Selling {half_shares}/{live_shares} shares, "
                    f"moving stop to breakeven ${entry:.4f}."
                ),
            )

    # ── 5. Trailing stop (Chandelier) ─────────────────────────────────────────
    # After partial exit or after 5 days, activate Chandelier trail
    if (status == "sold_half" or holding_days >= 5) and atr_entry:
        df = fetch_ohlcv(ticker, period="60d")
        if df is not None and len(df) >= 3:
            # Highest high since entry (approximate: highest in recent period)
            recent_period = min(holding_days + 3, len(df))
            highest_high = float(df["High"].iloc[-recent_period:].max())
            new_trail = compute_chandelier_trail(highest_high, atr_entry)

            # Never move trail backward
            current_effective_trail = current_trail or effective_stop
            updated_trail = max(new_trail, current_effective_trail)

            if current_price <= updated_trail and status != "open":
                # Trail breached — exit
                return ExitSignal(
                    action="full_exit",
                    reason="trailing_stop",
                    urgency="immediate",
                    shares_to_sell=live_shares,
                    details=(
                        f"Price ${current_price:.4f} broke chandelier trail "
                        f"${updated_trail:.4f} (highest_high=${highest_high:.4f})"
                    ),
                )
            elif updated_trail > current_effective_trail:
                # Update trail upward — not an exit, just update the stop
                return ExitSignal(
                    action="hold",
                    reason="trail_update",
                    urgency="monitor",
                    new_stop_price=updated_trail,
                    details=(
                        f"Chandelier trail updated: ${current_effective_trail:.4f} → ${updated_trail:.4f}"
                    ),
                )

    # ── 6. MA trend break ────────────────────────────────────────────────────
    if holding_days >= MIN_DAYS_FOR_MA_EXIT:
        df = fetch_ohlcv(ticker, period="60d")
        if df is not None and len(df) >= MA_TREND_BREAK_WINDOW:
            sma_20 = float(df["Close"].rolling(MA_TREND_BREAK_WINDOW).mean().iloc[-1])
            if current_price < sma_20:
                return ExitSignal(
                    action="full_exit",
                    reason="ma_trend_break",
                    urgency="next_open",
                    shares_to_sell=live_shares,
                    details=(
                        f"Price ${current_price:.4f} closed below 20-day SMA ${sma_20:.4f} "
                        f"after {holding_days} trading days"
                    ),
                )

    # ── 7a. Time exit HARD (20 trading days) ─────────────────────────────────
    if holding_days >= TIME_EXIT_HARD_DAYS:
        return ExitSignal(
            action="full_exit",
            reason="time_exit_hard",
            urgency="next_open",
            shares_to_sell=live_shares,
            details=f"Hard time limit: {holding_days} trading days held (limit: {TIME_EXIT_HARD_DAYS})",
        )

    # ── 7b. Time exit SOFT (10 trading days, no progress) ────────────────────
    if holding_days >= TIME_EXIT_SOFT_DAYS and pct_change < 2.0:
        return ExitSignal(
            action="hold",
            reason="time_exit_soft_warning",
            urgency="monitor",
            details=(
                f"Soft time warning: {holding_days} days held, only {pct_change:+.2f}% gain. "
                f"Consider exiting if momentum doesn't improve."
            ),
        )

    # ── No exit signal ────────────────────────────────────────────────────────
    return ExitSignal(
        action="hold",
        reason="holding",
        urgency="monitor",
        details=f"{holding_days}d held, {pct_change:+.2f}% from entry",
    )
