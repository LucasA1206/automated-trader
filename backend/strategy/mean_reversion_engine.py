"""
Mean-Reversion Engine — Dual-Engine Strategy (Suggestion C)
==========================================================
Provides an uncorrelated, high-win-rate mean-reversion sleeve for liquid ETFs
and mega-cap stocks alongside the core momentum breakout engine.

Strategy:
  1. Universe: Top liquid ETFs & mega-caps (SPY, QQQ, IWM, DIA, AAPL, MSFT, GOOGL, AMZN, NVDA, META).
  2. Trend Gate: Must be in long-term uptrend (Close > 200-day SMA).
  3. Oversold Trigger: 2-period RSI (RSI(2) < 10.0) indicating acute panic stretch.
  4. Exits:
     - Target exit: Close crosses above 5-day SMA OR profit >= +2.5%.
     - Hard stop: 3.5% below entry (or 2x ATR).
     - Time limit: Max 5 trading days hold.
"""

import logging
from datetime import datetime, timezone
from typing import Optional
import pandas as pd
import numpy as np

from strategy.data_layer import fetch_ohlcv
from strategy.exit_engine import ExitSignal, _get_trading_days_since

logger = logging.getLogger(__name__)

# Mean reversion universe: ultra-liquid index ETFs & mega-caps
MEAN_REVERSION_UNIVERSE = [
    "SPY", "QQQ", "IWM", "DIA",
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META"
]

RSI2_OVERSOLD_THRESHOLD = 10.0
SMA_TREND_WINDOW = 200
SMA_EXIT_WINDOW = 5
MR_MAX_HOLD_DAYS = 5
MR_PROFIT_TARGET_PCT = 2.5
MR_STOP_LOSS_PCT = 3.5


def compute_rsi2(closes: pd.Series) -> Optional[float]:
    """Compute 2-period Wilder's RSI."""
    if closes is None or len(closes) < 10:
        return None
    delta = closes.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta.where(delta < 0, 0.0))

    avg_gain = gain.rolling(window=2).mean()
    avg_loss = loss.rolling(window=2).mean()

    last_gain = avg_gain.iloc[-1]
    last_loss = avg_loss.iloc[-1]

    if last_loss == 0.0:
        return 100.0 if last_gain > 0 else 50.0

    rs = last_gain / last_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return round(float(rsi), 2)


def scan_mean_reversion_candidates(
    open_positions: list[dict],
    max_candidates: int = 2,
) -> list[dict]:
    """
    Scans the mean-reversion universe for extreme oversold pullbacks
    in stocks trading comfortably above their 200-day SMA.
    """
    active_tickers = {p.get("ticker") for p in open_positions}
    candidates = []

    for ticker in MEAN_REVERSION_UNIVERSE:
        if ticker in active_tickers:
            continue

        try:
            df = fetch_ohlcv(ticker, period="1y")
            if df is None or df.empty or len(df) < SMA_TREND_WINDOW:
                continue

            closes = df["Close"].dropna()
            current_price = float(closes.iloc[-1])
            sma_200 = float(closes.rolling(SMA_TREND_WINDOW).mean().iloc[-1])

            # Trend Gate: Price must be above 200 SMA (bull trend only)
            if current_price <= sma_200:
                continue

            # Oversold Trigger: 2-period RSI < 10
            rsi2 = compute_rsi2(closes)
            if rsi2 is None or rsi2 >= RSI2_OVERSOLD_THRESHOLD:
                continue

            # Compute ATR14 for dynamic stop placement
            high = df["High"].iloc[-15:]
            low = df["Low"].iloc[-15:]
            prev_close = closes.shift(1).iloc[-15:]
            tr = pd.concat([
                high - low,
                (high - prev_close).abs(),
                (low - prev_close).abs(),
            ], axis=1).max(axis=1)
            atr14 = float(tr.mean())

            # Stop price: max of (entry - 3.5%) or (entry - 2x ATR)
            stop_price = round(max(current_price * (1.0 - (MR_STOP_LOSS_PCT / 100)), current_price - (2.0 * atr14)), 2)
            sma_5 = float(closes.rolling(SMA_EXIT_WINDOW).mean().iloc[-1])
            target_price = round(max(current_price * (1.0 + (MR_PROFIT_TARGET_PCT / 100)), sma_5), 2)

            # Conviction score based on how deeply oversold (e.g. RSI 2 < 5 is higher conviction than < 10)
            conviction = int(max(60, min(95, 100 - (rsi2 * 4))))

            candidates.append({
                "ticker": ticker,
                "strategy_engine": "mean_reversion",
                "price": current_price,
                "limit_price": current_price,
                "stop_price": stop_price,
                "target_price": target_price,
                "partial_target_price": target_price,
                "atr_abs": round(atr14, 2),
                "rsi2": rsi2,
                "sma_200": round(sma_200, 2),
                "sma_5": round(sma_5, 2),
                "composite_score": conviction,
                "sector": "Broad Market / Tech Mega-Cap",
                "tier": "A",
                "size_multiplier": 1.0,
                "entry_notes": f"Dual-Engine Mean Reversion: {ticker} RSI(2)={rsi2:.1f} extreme dip above 200-SMA (${sma_200:.2f}). Target=${target_price:.2f}.",
            })
            logger.info("[MeanReversion] Found oversold candidate: %s | RSI(2)=%.1f | Price=$%.2f > 200-SMA=$%.2f",
                        ticker, rsi2, current_price, sma_200)

        except Exception as exc:
            logger.debug("[MeanReversion] Error evaluating %s: %s", ticker, exc)

    # Sort by lowest RSI2 (most deeply oversold first)
    candidates.sort(key=lambda c: c.get("rsi2", 100.0))
    return candidates[:max_candidates]


def check_mean_reversion_exit(
    trade,
    current_price: float,
    live_shares: int,
) -> ExitSignal:
    """
    Evaluates exit conditions for a mean-reversion trade:
      1. Hard stop loss breached.
      2. 5-day SMA cross (mean reversion snapped back).
      3. Profit target (+2.5%+) reached.
      4. Max hold days (5 days) exceeded.
    """
    ticker = trade.ticker
    entry = trade.buy_price or 0.0
    stop = trade.stop_price or (entry * 0.965)
    buy_time = trade.buy_time
    holding_days = _get_trading_days_since(buy_time)
    pct_change = ((current_price - entry) / entry * 100) if entry > 0 else 0.0

    # 1. Hard Stop-Loss
    if current_price <= stop:
        return ExitSignal(
            action="full_exit",
            reason="mr_stop_loss",
            urgency="immediate",
            shares_to_sell=live_shares,
            details=f"Mean-reversion stop hit at ${current_price:.2f} (stop was ${stop:.2f}, {pct_change:+.2f}%)",
        )

    # 2. Profit target (>= +2.5%)
    if pct_change >= MR_PROFIT_TARGET_PCT:
        return ExitSignal(
            action="full_exit",
            reason="mr_profit_target",
            urgency="immediate",
            shares_to_sell=live_shares,
            details=f"Mean-reversion profit target reached: ${current_price:.2f} ({pct_change:+.2f}%)",
        )

    # 3. 5-day SMA Mean Reversion Snapback Exit
    df = fetch_ohlcv(ticker, period="60d")
    if df is not None and len(df) >= SMA_EXIT_WINDOW:
        closes = df["Close"].dropna()
        sma_5 = float(closes.rolling(SMA_EXIT_WINDOW).mean().iloc[-1])
        if current_price >= sma_5 and holding_days >= 1:
            return ExitSignal(
                action="full_exit",
                reason="mr_sma5_rebound",
                urgency="immediate",
                shares_to_sell=live_shares,
                details=f"Mean reversion rebound complete: price ${current_price:.2f} crossed above 5-day SMA (${sma_5:.2f}, {pct_change:+.2f}%)",
            )

    # 4. Max hold limit (5 trading days)
    if holding_days >= MR_MAX_HOLD_DAYS:
        return ExitSignal(
            action="full_exit",
            reason="mr_time_exit",
            urgency="immediate",
            shares_to_sell=live_shares,
            details=f"Mean-reversion time limit reached ({holding_days}d >= {MR_MAX_HOLD_DAYS}d, {pct_change:+.2f}%)",
        )

    return ExitSignal(
        action="hold",
        reason="mr_holding",
        urgency="monitor",
        details=f"Mean-reversion holding: {holding_days}d held, {pct_change:+.2f}%",
    )
