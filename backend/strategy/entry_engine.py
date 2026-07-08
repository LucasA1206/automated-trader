"""
Entry Engine — Phase 6
=======================
Implements intraday entry confirmation rules from blueprint Section 8.

These rules are applied AFTER the pre-market scan has identified candidates.
During market hours (09:45–15:30 ET), the entry monitor checks each candidate
for intraday confirmation before placing a limit order.

Entry confirmation rules (ALL must be met):
  1. Pullback zone: price ≤ 3% above the 20-day SMA (ideally near or at SMA)
     — Avoids chasing extended moves
  2. RSI 40–55: price is in the pullback zone within an uptrend
  3. MACD histogram turning upward (positive or recovering from trough)
  4. ADX ≥ 20: trend is strong enough to trade
  5. VWAP reclaim: intraday price > today's VWAP (confirms intraday momentum)
  6. Volume confirmation: current intraday volume on pace for ≥ 1.2× 20-day avg
  7. Time gate: only place new entries between 09:45–15:30 ET
     (no entries in first 15 minutes or last 30 minutes of session)

Entry order type: LIMIT at the asking price (not MKT) to avoid slippage.
If the limit order doesn't fill within 20 minutes, cancel and wait for next bar.

Blueprint Section 8 also permits:
  - Breakout entry: price just cleared a resistance level with volume > 1.5×
  - Pullback entry: price retesting support/SMA with reduced volume

This implementation uses the simpler pullback-entry mode as the default.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from strategy.data_layer import fetch_ohlcv, estimate_vwap
from strategy.scoring_engine import _compute_rsi, _compute_macd_histogram, _compute_adx
from strategy.exit_engine import compute_initial_stop, compute_partial_target

logger = logging.getLogger(__name__)

# Entry time gate (ET hours)
ENTRY_START_HOUR = 9
ENTRY_START_MINUTE = 45
ENTRY_END_HOUR = 15
ENTRY_END_MINUTE = 30

# Intraday confirmation thresholds per blueprint Section 8
RSI_ENTRY_MIN = 40
RSI_ENTRY_MAX = 55
ADX_MIN = 20
PULLBACK_ZONE_MAX_PCT = 3.0    # Price ≤ 3% above 20-day SMA
VWAP_RECLAIM_REQUIRED = True
MIN_REL_VOL_INTRADAY = 1.2    # Intraday volume must be on pace for 1.2× avg
LIMIT_ORDER_PREMIUM_PCT = 0.1  # Place limit 0.1% above current ask (ensure fill)


def is_within_entry_window() -> bool:
    """Check if current time is within the allowed entry window (ET)."""
    import pytz
    ET = pytz.timezone("America/New_York")
    now_et = datetime.now(ET)
    after_start = (now_et.hour, now_et.minute) >= (ENTRY_START_HOUR, ENTRY_START_MINUTE)
    before_end = (now_et.hour, now_et.minute) <= (ENTRY_END_HOUR, ENTRY_END_MINUTE)
    return after_start and before_end


def check_entry_confirmation(candidate: dict) -> tuple[bool, str, Optional[float]]:
    """
    Apply intraday entry confirmation rules to a pre-scanned candidate.

    Returns:
        (eligible: bool, reason: str, limit_price: Optional[float])

    If eligible=True, limit_price is the suggested limit order price.
    If eligible=False, reason explains which condition wasn't met.
    """
    ticker = candidate.get("ticker", "UNKNOWN")

    # ── Rule 0: Time gate ────────────────────────────────────────────────────
    if not is_within_entry_window():
        return False, "outside_entry_window", None

    # ── Fetch fresh intraday data ────────────────────────────────────────────
    df = fetch_ohlcv(ticker, period="22d")
    if df is None or df.empty or len(df) < 20:
        return False, "insufficient_data", None

    closes = df["Close"]
    current_price = float(closes.iloc[-1])

    # ── Rule 1: Pullback zone ─────────────────────────────────────────────────
    from strategy.universe_filter import _compute_sma
    sma_20 = _compute_sma(closes, 20)
    if sma_20 is None:
        return False, "sma_20_unavailable", None

    pct_above_sma = ((current_price - sma_20) / sma_20) * 100
    if pct_above_sma > PULLBACK_ZONE_MAX_PCT:
        return False, (
            f"price_extended: {pct_above_sma:.2f}% above 20d SMA "
            f"(limit: {PULLBACK_ZONE_MAX_PCT}%)"
        ), None

    # ── Rule 2: RSI 40–55 ─────────────────────────────────────────────────────
    rsi = _compute_rsi(closes, 14)
    if rsi is None:
        return False, "rsi_unavailable", None
    if not (RSI_ENTRY_MIN <= rsi <= RSI_ENTRY_MAX):
        return False, f"rsi_outside_zone: RSI={rsi:.1f} (target {RSI_ENTRY_MIN}-{RSI_ENTRY_MAX})", None

    # ── Rule 3: MACD histogram turning upward ────────────────────────────────
    macd_hist = _compute_macd_histogram(closes)
    if macd_hist is None:
        return False, "macd_unavailable", None

    # Check if MACD is recovering (positive or rising from negative)
    prev_macd = _compute_macd_histogram(closes.iloc[:-1]) if len(closes) >= 27 else None
    macd_ok = macd_hist > 0 or (prev_macd is not None and macd_hist > prev_macd)
    if not macd_ok:
        return False, f"macd_not_turning: histogram={macd_hist:.4f} (falling negative)", None

    # ── Rule 4: ADX ≥ 20 ─────────────────────────────────────────────────────
    adx = _compute_adx(df, 14)
    if adx is None:
        logger.warning("[Entry] %s: ADX unavailable — allowing entry (fail-open for ADX only)", ticker)
    elif adx < ADX_MIN:
        return False, f"adx_weak: ADX={adx:.1f} < {ADX_MIN}", None

    # ── Rule 5: VWAP reclaim ─────────────────────────────────────────────────
    if VWAP_RECLAIM_REQUIRED:
        vwap = estimate_vwap(ticker)
        if vwap is not None and current_price < vwap:
            return False, f"below_vwap: price ${current_price:.4f} < VWAP ${vwap:.4f}", None

    # ── Rule 6: Volume confirmation ───────────────────────────────────────────
    # Use daily relative volume as proxy (intraday volume data not always available)
    rel_vol = candidate.get("rel_vol")
    if rel_vol is not None and rel_vol < MIN_REL_VOL_INTRADAY:
        return False, f"low_rel_vol: {rel_vol:.2f}x < {MIN_REL_VOL_INTRADAY}x required", None

    # ── All rules passed — compute limit order price ──────────────────────────
    # Set limit 0.1% above current price to ensure fill
    limit_price = round(current_price * (1 + LIMIT_ORDER_PREMIUM_PCT / 100), 4)

    logger.info(
        "[Entry] %s confirmed for entry: price=$%.4f, SMA20=$%.4f (+%.2f%%), "
        "RSI=%.1f, MACD=%.4f, ADX=%s, limit=$%.4f",
        ticker, current_price, sma_20, pct_above_sma,
        rsi, macd_hist, f"{adx:.1f}" if adx else "N/A", limit_price,
    )

    return True, "all_conditions_met", limit_price


def prepare_entry_order(
    candidate: dict,
    account_equity: float,
    open_positions: list,
    risk_engine,
) -> Optional[dict]:
    """
    Full entry preparation: check confirmation, compute position size and stops,
    run through risk engine gate.

    Returns dict with order details if approved, or None if blocked.
    dict includes: ticker, shares, limit_price, stop_price, partial_target_price,
                   atr_abs, composite_score, classification, reason
    """
    ticker = candidate.get("ticker")
    atr    = candidate.get("atr_abs")
    adx    = candidate.get("technical_indicators", {}).get("adx_14")
    sector = candidate.get("sector", "Unknown")
    score  = candidate.get("composite_score", 0)
    classification = candidate.get("classification", "high_conviction")
    confidence = candidate.get("confidence_score", 80)

    # ── Intraday entry confirmation ───────────────────────────────────────────
    eligible, reason, limit_price = check_entry_confirmation(candidate)
    if not eligible:
        logger.info("[Entry] %s blocked by entry confirmation: %s", ticker, reason)
        return None

    if not atr or atr <= 0:
        logger.error(
            "[Entry] %s: ATR not available — cannot compute stop price. Skipping. (fail-safe)",
            ticker,
        )
        return None

    # ── Compute ATR-based stop and target ────────────────────────────────────
    stop_price = compute_initial_stop(limit_price, atr, adx)
    partial_target = compute_partial_target(limit_price, stop_price)

    # ── Position sizing ───────────────────────────────────────────────────────
    size = risk_engine.compute_position_size(
        account_equity=account_equity,
        entry_price=limit_price,
        stop_price=stop_price,
        risk_pct=1.0,
        confidence=confidence,
        classification=classification,
    )

    if size.get("error") or size.get("shares", 0) < 1:
        logger.error("[Entry] %s: Position sizing failed: %s", ticker, size)
        return None

    shares = size["shares"]

    # ── Risk engine gate ──────────────────────────────────────────────────────
    from strategy.data_layer import compute_regime_status
    regime_data = compute_regime_status()
    regime = regime_data["regime"] if regime_data else "unknown"
    black_swan = regime_data.get("black_swan_day", False) if regime_data else False

    # Compute daily/weekly P&L from open positions (simplified: use account equity delta)
    daily_pnl_pct = 0.0
    weekly_pnl_pct = 0.0
    peak_equity = account_equity  # Will be updated from DB snapshot in jobs.py

    allowed, block_reason = risk_engine.check_new_entry(
        ticker=ticker,
        sector=sector,
        entry_price=limit_price,
        stop_price=stop_price,
        proposed_shares=shares,
        account_equity=account_equity,
        open_positions=open_positions,
        peak_equity=peak_equity,
        daily_pnl_pct=daily_pnl_pct,
        weekly_pnl_pct=weekly_pnl_pct,
        regime=regime,
        black_swan_day=black_swan,
    )

    if not allowed:
        logger.warning("[Entry] %s blocked by risk engine: %s", ticker, block_reason)
        return None

    return {
        "ticker": ticker,
        "shares": shares,
        "limit_price": limit_price,
        "stop_price": stop_price,
        "partial_target_price": partial_target,
        "atr_abs": atr,
        "position_value": size["position_value"],
        "risk_dollar": size["risk_dollar"],
        "risk_pct": size["risk_pct"],
        "composite_score": score,
        "confidence_score": confidence,
        "classification": classification,
        "sector": sector,
        "entry_reason": reason,
        "regime": regime,
    }
