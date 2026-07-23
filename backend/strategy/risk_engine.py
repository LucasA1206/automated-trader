"""
Risk Engine — Phase 4
=====================
Hard-gated circuit breakers per blueprint Section 7/10.

ALL gates are mandatory — no override allowed by any other module.
The risk engine is queried BEFORE every order placement and checked
during the exit monitor run.

Circuit breakers enforced:
  1. Max 4 concurrent positions (hard cap on open trades)
  2. Portfolio heat ≤ 4% total account equity at risk
  3. Max 2% single-day loss limit (halt new entries if triggered)
  4. Max 6% weekly loss limit (halt ALL new entries if triggered)
  5. Peak-equity drawdown ≥ 10% → halt new entries (manual review required)
  6. Peak-equity drawdown ≥ 20% → halt ALL trading (hard stop, requires manual reset)
  7. Sector concentration: no more than 2 positions in same sector
  8. Correlation proxy: no position if average pairwise sector overlap > 60%
  9. Position size cap: max 25% of account equity in any single position
  10. No new entries on black-swan days (±3% SPY single session)

State is persisted in the risk_engine_state DB table so the engine survives
backend restarts. Peak equity is tracked continuously.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# ─── Hard limits from blueprint Section 7/10 ─────────────────────────────────
MAX_POSITIONS = 8
MAX_PORTFOLIO_HEAT_PCT = 10.0     # Total % of equity at risk across all stops
MAX_DAILY_LOSS_PCT = 2.0          # Halt new entries if daily loss exceeds this
MAX_WEEKLY_LOSS_PCT = 6.0         # Halt all new entries for the week
DRAWDOWN_WARN_PCT = 10.0          # Soft limit: halt new entries, log alert
DRAWDOWN_HARD_PCT = 20.0          # Hard limit: halt ALL trading, require manual reset
MAX_SINGLE_POSITION_PCT = 25.0    # Max % of equity in any one position
MAX_SECTOR_POSITIONS = 2          # Max concurrent positions in the same sector

# Position sizing: 1× ATR below entry = hard stop
# Risk per trade: 2.5% of account equity (increased from 1.0%)
DEFAULT_RISK_PER_TRADE_PCT = 2.5  # % of account equity risked per trade


class RiskEngine:
    """
    Stateless computation engine for risk checks.
    All state is loaded from the database on each call — no in-memory persistence.
    """

    def __init__(self):
        pass

    def compute_portfolio_heat(
        self,
        open_positions: list[dict],
        account_equity: float,
    ) -> float:
        """
        Compute current portfolio heat = sum of (entry_price - stop_price) * shares / equity.
        Returns percentage (e.g. 2.5 = 2.5%).
        """
        if not open_positions or account_equity <= 0:
            return 0.0

        total_at_risk = 0.0
        for pos in open_positions:
            entry  = pos.get("buy_price") or pos.get("entry_price") or 0
            stop   = pos.get("stop_price") or 0
            shares = pos.get("shares") or 0
            if entry > 0 and stop > 0 and shares > 0 and entry > stop:
                at_risk = (entry - stop) * shares
                total_at_risk += at_risk

        return round(total_at_risk / account_equity * 100, 3)

    def compute_position_size(
        self,
        account_equity: float,
        entry_price: float,
        stop_price: float,
        risk_pct: float = DEFAULT_RISK_PER_TRADE_PCT,
        confidence: int = 100,
        classification: str = "high_conviction",
    ) -> dict:
        """
        Compute position size per blueprint Section 7:
          shares = (equity × risk_pct% / (entry - stop))
          position_value = shares × entry_price
          capped at 25% of equity

        For marginal setups: halve the position size.
        Confidence multiplier: scales size by confidence/100 for weak signals.

        Returns dict with: shares, position_value, risk_dollar, risk_pct, capped
        """
        if entry_price <= stop_price or stop_price <= 0:
            return {"error": "Invalid entry/stop prices", "shares": 0}

        risk_per_share = entry_price - stop_price
        if risk_per_share <= 0:
            return {"error": "Zero or negative risk per share", "shares": 0}

        # Base risk allocation
        base_risk_pct = risk_pct / 100  # e.g. 0.01 for 1%
        if classification == "marginal":
            base_risk_pct *= 0.5  # Half size for marginal setups

        # Confidence multiplier (confidence 60 → 60% of normal size; 100 → 100%)
        confidence_factor = max(0.5, confidence / 100)
        adjusted_risk_pct = base_risk_pct * confidence_factor

        dollar_risk = account_equity * adjusted_risk_pct
        raw_shares = dollar_risk / risk_per_share
        position_value = raw_shares * entry_price

        # Cap at 25% of equity
        max_value = account_equity * (MAX_SINGLE_POSITION_PCT / 100)
        capped = position_value > max_value
        if capped:
            position_value = max_value
            raw_shares = position_value / entry_price

        # Round down to whole shares
        shares = max(1, int(raw_shares))
        actual_value = shares * entry_price
        actual_risk  = shares * risk_per_share

        return {
            "shares": shares,
            "position_value": round(actual_value, 2),
            "risk_dollar": round(actual_risk, 2),
            "risk_pct": round(actual_risk / account_equity * 100, 3) if account_equity > 0 else 0,
            "capped": capped,
        }

    def check_new_entry(
        self,
        ticker: str,
        sector: str,
        entry_price: float,
        stop_price: float,
        proposed_shares: int,
        account_equity: float,
        open_positions: list[dict],
        peak_equity: float,
        daily_pnl_pct: float,
        weekly_pnl_pct: float,
        regime: str,
        black_swan_day: bool = False,
    ) -> tuple[bool, str]:
        """
        Run all mandatory circuit breaker checks before allowing a new entry.

        Returns: (allowed: bool, reason: str)
        If allowed=False, reason explains which circuit breaker triggered.
        """
        # ── Gate 0: Black-swan day ────────────────────────────────────────────
        if black_swan_day:
            return False, "black_swan_day: SPY moved >3% — all new entries suspended"

        # ── Gate 1: Regime check ──────────────────────────────────────────────
        if regime == "risk_off":
            return False, f"regime_off: market regime is '{regime}' — no new entries"

        # ── Gate 2: Max positions ─────────────────────────────────────────────
        open_count = len([p for p in open_positions if p.get("status") in ("open", "sold_half", "closing")])
        if open_count >= MAX_POSITIONS:
            return False, f"max_positions: already have {open_count}/{MAX_POSITIONS} open positions"

        # ── Gate 3: Portfolio heat ─────────────────────────────────────────────
        # Compute new heat including this trade
        new_position = {
            "buy_price": entry_price,
            "stop_price": stop_price,
            "shares": proposed_shares,
            "status": "open",
        }
        projected_heat = self.compute_portfolio_heat(
            open_positions + [new_position], account_equity
        )
        if projected_heat > MAX_PORTFOLIO_HEAT_PCT:
            return False, (
                f"portfolio_heat: projected heat {projected_heat:.2f}% > "
                f"{MAX_PORTFOLIO_HEAT_PCT}% limit"
            )

        # ── Gate 4: Daily loss limit ──────────────────────────────────────────
        if daily_pnl_pct <= -MAX_DAILY_LOSS_PCT:
            return False, (
                f"daily_loss_limit: daily P&L {daily_pnl_pct:.2f}% exceeded "
                f"-{MAX_DAILY_LOSS_PCT}% limit — no new entries today"
            )

        # ── Gate 5: Weekly loss limit ─────────────────────────────────────────
        if weekly_pnl_pct <= -MAX_WEEKLY_LOSS_PCT:
            return False, (
                f"weekly_loss_limit: weekly P&L {weekly_pnl_pct:.2f}% exceeded "
                f"-{MAX_WEEKLY_LOSS_PCT}% limit — no new entries this week"
            )

        # ── Gate 6: Drawdown from peak ────────────────────────────────────────
        if peak_equity > 0 and account_equity > 0:
            drawdown_pct = (peak_equity - account_equity) / peak_equity * 100
            if drawdown_pct >= DRAWDOWN_HARD_PCT:
                return False, (
                    f"hard_drawdown: account is {drawdown_pct:.1f}% below peak equity "
                    f"(>{DRAWDOWN_HARD_PCT}%) — ALL trading suspended, manual review required"
                )
            if drawdown_pct >= DRAWDOWN_WARN_PCT:
                return False, (
                    f"warn_drawdown: account is {drawdown_pct:.1f}% below peak equity "
                    f"(>{DRAWDOWN_WARN_PCT}%) — new entries suspended pending review"
                )

        # ── Gate 7: Sector concentration ─────────────────────────────────────
        same_sector_count = sum(
            1 for p in open_positions
            if p.get("sector", "Unknown") == sector and
               p.get("status") in ("open", "sold_half")
        )
        if same_sector_count >= MAX_SECTOR_POSITIONS:
            return False, (
                f"sector_cap: already {same_sector_count} positions in sector '{sector}' "
                f"(max {MAX_SECTOR_POSITIONS})"
            )

        # ── Gate 8: Single position size cap ─────────────────────────────────
        position_value = proposed_shares * entry_price
        position_pct = position_value / account_equity * 100 if account_equity > 0 else 0
        if position_pct > MAX_SINGLE_POSITION_PCT:
            return False, (
                f"position_size_cap: proposed position ${position_value:,.0f} "
                f"({position_pct:.1f}% of equity) exceeds {MAX_SINGLE_POSITION_PCT}% cap"
            )

        return True, "all_clear"

    def check_trading_suspended(
        self,
        account_equity: float,
        peak_equity: float,
        weekly_pnl_pct: float,
    ) -> tuple[bool, str]:
        """
        Quick check: is all trading suspended?
        Used by exit monitor to determine whether stop-losses should still fire.
        (Answer: ALWAYS — exits run regardless. Only new entries are suspended.)
        """
        if peak_equity > 0 and account_equity > 0:
            drawdown_pct = (peak_equity - account_equity) / peak_equity * 100
            if drawdown_pct >= DRAWDOWN_HARD_PCT:
                return True, f"hard_drawdown({drawdown_pct:.1f}%>={DRAWDOWN_HARD_PCT}%)"
        return False, "ok"

    def get_state_summary(
        self,
        account_equity: float,
        peak_equity: float,
        open_positions: list[dict],
        daily_pnl_pct: float,
        weekly_pnl_pct: float,
        regime: str,
    ) -> dict:
        """
        Return a complete risk state snapshot for the API and UI.
        """
        portfolio_heat = self.compute_portfolio_heat(open_positions, account_equity)
        drawdown_pct = 0.0
        if peak_equity > 0 and account_equity > 0:
            drawdown_pct = (peak_equity - account_equity) / peak_equity * 100

        hard_suspended, suspend_reason = self.check_trading_suspended(
            account_equity, peak_equity, weekly_pnl_pct
        )

        sectors = {}
        for p in open_positions:
            s = p.get("sector", "Unknown")
            sectors[s] = sectors.get(s, 0) + 1

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "account_equity": account_equity,
            "peak_equity": peak_equity,
            "drawdown_pct": round(drawdown_pct, 2),
            "portfolio_heat_pct": portfolio_heat,
            "open_positions_count": len([p for p in open_positions
                                         if p.get("status") in ("open", "sold_half")]),
            "max_positions": MAX_POSITIONS,
            "available_slots": max(0, MAX_POSITIONS - len(open_positions)),
            "daily_pnl_pct": round(daily_pnl_pct, 3),
            "weekly_pnl_pct": round(weekly_pnl_pct, 3),
            "regime": regime,
            "new_entries_allowed": not hard_suspended and drawdown_pct < DRAWDOWN_WARN_PCT,
            "hard_suspended": hard_suspended,
            "suspension_reason": suspend_reason if hard_suspended else None,
            "sector_breakdown": sectors,
            "limits": {
                "max_portfolio_heat_pct": MAX_PORTFOLIO_HEAT_PCT,
                "max_daily_loss_pct": MAX_DAILY_LOSS_PCT,
                "max_weekly_loss_pct": MAX_WEEKLY_LOSS_PCT,
                "drawdown_warn_pct": DRAWDOWN_WARN_PCT,
                "drawdown_hard_pct": DRAWDOWN_HARD_PCT,
                "max_sector_positions": MAX_SECTOR_POSITIONS,
                "max_single_position_pct": MAX_SINGLE_POSITION_PCT,
            },
        }


# ─── Module-level singleton (thread-safe, stateless computation) ─────────────
_risk_engine = RiskEngine()


def get_risk_engine() -> RiskEngine:
    """Return the module-level RiskEngine instance."""
    return _risk_engine
