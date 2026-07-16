"""
Universe Filter — Phase 2
=========================
Applies the mandatory pass/fail gates from blueprint Section 4/5 Step 1.

Mandatory filters (failing any = excluded, regardless of score):
  1. Price ≥ $5
  2. 20-day average dollar volume ≥ $10,000,000/day
  3. Market cap ≥ $500M
  4. Price > 200-day SMA
  5. No earnings within next 3 trading days
  6. Not on a halt/restriction list
  7. ATR% within 2%–6% band
  8. FCF not deeply negative combined with weak balance sheet (compound condition)

Also handles the two-stage scan order from blueprint Section 2:
  Stage 1: cheap batch filter (price, dollar volume) → ~300-500 survivors
  Stage 2: expensive technical filter (SMA, ATR, relative strength) → 80-150 survivors

Key design: filters are applied cheapest-first to avoid unnecessary API calls.
"""

import logging
import math
from datetime import datetime, timezone
from typing import Optional
import concurrent.futures
import time

import pandas as pd

from strategy.data_layer import (
    fetch_ohlcv_batch,
    fetch_ohlcv,
    fetch_fundamentals,
    fetch_fundamentals_batch,
    is_near_earnings,
    is_economic_blackout_day,
    fetch_spy_returns,
)

logger = logging.getLogger(__name__)

# Hard-coded filter thresholds.
# Core downside-protection filters (price > 200 SMA, RS > SPY) are NOT relaxed here.
MIN_PRICE = 5.0                         # $5 floor (blueprint Section 4 mandatory)
MIN_AVG_DOLLAR_VOL_20D = 10_000_000.0  # $10M/day (blueprint: ensures liquidity for execution)
MIN_MARKET_CAP = 500_000_000.000       # $500M (blueprint: stability/quality preference)
ATR_PCT_MIN = 2.0                       # 2% of price — excludes ETFs/illiquid names
ATR_PCT_MAX = 6.0                       # 6% of price (blueprint Section 4)
RS_TOP_PERCENTILE = 0.30               # Must be in top 30% by relative strength (blueprint Section 4)

# Minimum pool size for relative RS percentile cut.
# Below this, use an absolute floor instead to avoid destroying small pools.
RS_RELATIVE_CUT_MIN_POOL = 20
# Absolute RS floors (3-month return vs SPY, in %)
RS_ABS_FLOOR_LARGE_POOL = 0.0    # Must beat SPY over 3 months (large pool ≥ 20)
RS_ABS_FLOOR_SMALL_POOL = -5.0   # Within 5% of SPY (small pool < 20)

# Earnings blackout window in trading days (blueprint: 3 days)
EARNINGS_BLACKOUT_TRADING_DAYS = 3


def _compute_atr(df: pd.DataFrame, period: int = 14) -> Optional[float]:
    """Compute 14-day ATR from OHLCV DataFrame. Returns absolute ATR value."""
    if df is None or len(df) < period + 1:
        return None
    try:
        highs  = df["High"]
        lows   = df["Low"]
        closes = df["Close"]
        tr_list = []
        for i in range(1, period + 1):
            h = float(highs.iloc[-(i)])
            lo = float(lows.iloc[-(i)])
            c_prev = float(closes.iloc[-(i + 1)])
            true_range = max(h - lo, abs(h - c_prev), abs(lo - c_prev))
            tr_list.append(true_range)
        return sum(tr_list) / len(tr_list)
    except Exception:
        return None


def _compute_atr_pct(df: pd.DataFrame, period: int = 14) -> Optional[float]:
    """Compute ATR as % of current price (normalized volatility metric)."""
    atr = _compute_atr(df, period)
    if atr is None:
        return None
    try:
        current_price = float(df["Close"].iloc[-1])
        if current_price <= 0:
            return None
        return round(atr / current_price * 100, 3)
    except Exception:
        return None


def _compute_sma(series: pd.Series, window: int) -> Optional[float]:
    """Compute SMA for a price series. Returns None if insufficient data."""
    if series is None or len(series) < window:
        return None
    val = series.rolling(window).mean().iloc[-1]
    return float(val) if not math.isnan(val) else None


def _compute_relative_strength(df: pd.DataFrame, spy_ret_63d: float, spy_ret_126d: float) -> dict:
    """
    Compute relative strength vs SPY at 63-day (3m) and 126-day (6m) horizons.
    Returns {"rs_63d": float|None, "rs_126d": float|None}
    """
    closes = df["Close"]
    result = {"rs_63d": None, "rs_126d": None}
    try:
        current = float(closes.iloc[-1])
        if len(closes) >= 63:
            base_63 = float(closes.iloc[-63])
            stock_ret_63 = ((current / base_63) - 1) * 100 if base_63 > 0 else None
            if stock_ret_63 is not None and spy_ret_63d is not None:
                result["rs_63d"] = round(stock_ret_63 - spy_ret_63d, 2)
        if len(closes) >= 126:
            base_126 = float(closes.iloc[-126])
            stock_ret_126 = ((current / base_126) - 1) * 100 if base_126 > 0 else None
            if stock_ret_126 is not None and spy_ret_126d is not None:
                result["rs_126d"] = round(stock_ret_126 - spy_ret_126d, 2)
    except Exception:
        pass
    return result


def _compute_52w_high_proximity(df: pd.DataFrame) -> Optional[float]:
    """Return % distance from 52-week high (negative = below high)."""
    if df is None or len(df) < 5:
        return None
    try:
        period = min(252, len(df))
        high_52w = float(df["High"].iloc[-period:].max())
        current  = float(df["Close"].iloc[-1])
        if high_52w <= 0:
            return None
        return round((current - high_52w) / high_52w * 100, 2)
    except Exception:
        return None


# ─── Stage 1: Cheap batch pre-filter ─────────────────────────────────────────

def stage1_price_volume_filter(
    tickers: list[str],
) -> tuple[list[str], dict[str, str]]:
    """
    Apply the cheapest mandatory filters using batch OHLCV data.
    Filters applied: price ≥ $5, 20d avg dollar volume ≥ $10M.
    Returns: (survivors, rejection_reasons)
    """
    logger.info("[Filter] Stage 1: price/volume pre-filter on %d tickers.", len(tickers))
    batch_data = fetch_ohlcv_batch(tickers, period="22d")  # ~1 month

    survivors: list[str] = []
    rejection_reasons: dict[str, str] = {}

    for ticker in tickers:
        df = batch_data.get(ticker)
        if df is None or df.empty:
            rejection_reasons[ticker] = "no_price_data"
            continue

        # Price check
        try:
            price = float(df["Close"].iloc[-1])
        except Exception:
            rejection_reasons[ticker] = "price_parse_error"
            continue

        if price < MIN_PRICE:
            rejection_reasons[ticker] = f"price_too_low(${price:.2f}<${MIN_PRICE})"
            continue

        # 20-day avg dollar volume check
        try:
            vols = df["Volume"]
            closes = df["Close"]
            period = min(20, len(df))
            avg_vol = float(vols.iloc[-period:].mean())
            avg_price = float(closes.iloc[-period:].mean())
            avg_dollar_vol = avg_vol * avg_price
        except Exception:
            rejection_reasons[ticker] = "volume_parse_error"
            continue

        if avg_dollar_vol < MIN_AVG_DOLLAR_VOL_20D:
            rejection_reasons[ticker] = (
                f"avg_dollar_vol_too_low(${avg_dollar_vol/1e6:.1f}M<${MIN_AVG_DOLLAR_VOL_20D/1e6:.0f}M)"
            )
            continue

        survivors.append(ticker)

    logger.info(
        "[Filter] Stage 1 complete: %d/%d survived. %d rejected.",
        len(survivors), len(tickers), len(rejection_reasons),
    )
    return survivors, rejection_reasons


# ─── Stage 2: Technical mandatory filters ─────────────────────────────────────

def _stage2_check_single(
    ticker: str,
    spy_ret_63d: float,
    spy_ret_126d: float,
) -> tuple[Optional[dict], Optional[str]]:
    """
    Apply technical mandatory filters to a single ticker.
    Returns (metrics_dict, None) if it passes, or (None, rejection_reason) if it fails.
    """
    df = fetch_ohlcv(ticker, period="1y")
    if df is None or df.empty or len(df) < 50:
        return None, "insufficient_history"

    closes = df["Close"]
    current_price = float(closes.iloc[-1])

    # Price > 200-day SMA (mandatory trend filter — highest-value single filter per blueprint)
    sma_200 = _compute_sma(closes, 200)
    if sma_200 is None:
        # Less than 200 days of data — fall back to 100d SMA (allows ~5 months of history)
        sma_200 = _compute_sma(closes, 100)
        if sma_200 is None:
            return None, "insufficient_history_for_200sma"

    if current_price <= sma_200:
        return None, f"price_below_200sma(${current_price:.2f}<${sma_200:.2f})"

    # ATR% band: 1.5%–12%
    atr_pct = _compute_atr_pct(df, period=14)
    if atr_pct is None:
        return None, "atr_compute_failed"

    if atr_pct < ATR_PCT_MIN:
        return None, f"atr_pct_too_low({atr_pct:.2f}%<{ATR_PCT_MIN}%)"
    if atr_pct > ATR_PCT_MAX:
        return None, f"atr_pct_too_high({atr_pct:.2f}%>{ATR_PCT_MAX}%)"

    # Market cap filter — fetch fundamentals ONLY for surviving tickers to avoid rate limiting
    fundamentals = fetch_fundamentals(ticker)
    market_cap = fundamentals.get("market_cap", 0) if fundamentals else 0
    if market_cap and market_cap < MIN_MARKET_CAP:
        return None, f"market_cap_too_low(${market_cap/1e6:.0f}M<${MIN_MARKET_CAP/1e6:.0f}M)"

    # Relative strength — must be in top 50% (enforced at ranking stage, computed here)
    rs = _compute_relative_strength(df, spy_ret_63d, spy_ret_126d)

    # Compute additional metrics needed by scoring engine
    sma_50  = _compute_sma(closes, 50)
    sma_20  = _compute_sma(closes, 20)
    high_52w_pct = _compute_52w_high_proximity(df)

    # ATR absolute value (needed for position sizing)
    atr_abs = _compute_atr(df, 14)

    # 20-day avg dollar volume (already know it passes from stage 1, recompute for scoring)
    period_vol = min(20, len(df))
    avg_vol_20  = float(df["Volume"].iloc[-period_vol:].mean())
    avg_price_20 = float(closes.iloc[-period_vol:].mean())
    avg_dollar_vol_20 = avg_vol_20 * avg_price_20

    # Current volume vs 20d avg (relative volume)
    latest_vol = float(df["Volume"].iloc[-1])
    rel_vol = round(latest_vol / avg_vol_20, 2) if avg_vol_20 > 0 else None

    return {
        "ticker": ticker,
        "price": round(current_price, 4),
        "sma_20": round(sma_20, 4) if sma_20 else None,
        "sma_50": round(sma_50, 4) if sma_50 else None,
        "sma_200": round(sma_200, 4),
        "atr_pct": round(atr_pct, 3),
        "atr_abs": round(atr_abs, 4) if atr_abs else None,
        "rs_63d": rs.get("rs_63d"),
        "rs_126d": rs.get("rs_126d"),
        "high_52w_pct": high_52w_pct,
        "avg_dollar_vol_20d": round(avg_dollar_vol_20, 0),
        "rel_vol": rel_vol,
        "market_cap": market_cap,
        "float_shares": fundamentals.get("float_shares") if fundamentals else None,
        "sector": fundamentals.get("sector", "Unknown") if fundamentals else "Unknown",
        "industry": fundamentals.get("industry", "Unknown") if fundamentals else "Unknown",
        "revenue_growth_yoy": fundamentals.get("revenue_growth_yoy") if fundamentals else None,
        "eps_growth_yoy": fundamentals.get("eps_growth_yoy") if fundamentals else None,
        "fcf_positive": fundamentals.get("fcf_positive") if fundamentals else None,
        "net_debt_ebitda": fundamentals.get("net_debt_ebitda") if fundamentals else None,
        "profit_margin": fundamentals.get("profit_margin") if fundamentals else None,
        "return_on_equity": fundamentals.get("return_on_equity") if fundamentals else None,
        "institutional_ownership_pct": fundamentals.get("institutional_ownership_pct") if fundamentals else None,
        "short_interest_pct_float": fundamentals.get("short_interest_pct_float") if fundamentals else None,
        "beta": fundamentals.get("beta") if fundamentals else None,
        "ohlcv_df": df,  # retained for scoring engine use (not serialized)
    }, None


def stage2_technical_filter(
    tickers: list[str],
    max_workers: int = 10,
) -> tuple[list[dict], dict[str, str]]:
    """
    Apply technical mandatory filters to stage-1 survivors.
    Fetches 1-year OHLCV + fundamentals per ticker (parallelized).

    Returns: (metrics_list, rejection_reasons)
    where metrics_list contains dicts with all computed technical data.
    """
    logger.info("[Filter] Stage 2: technical filter on %d tickers.", len(tickers))

    # Need SPY returns for relative strength calculation
    spy_returns = fetch_spy_returns()
    spy_ret_63d  = spy_returns["ret_63d"]  if spy_returns else 0.0
    spy_ret_126d = spy_returns["ret_126d"] if spy_returns else 0.0

    survivors: list[dict] = []
    rejection_reasons: dict[str, str] = {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(_stage2_check_single, t, spy_ret_63d, spy_ret_126d): t
            for t in tickers
        }
        for future in concurrent.futures.as_completed(futures):
            ticker = futures[future]
            try:
                metrics, reason = future.result()
                if metrics is not None:
                    survivors.append(metrics)
                else:
                    rejection_reasons[ticker] = reason or "unknown"
            except Exception as exc:
                rejection_reasons[ticker] = f"exception:{exc}"

    logger.info(
        "[Filter] Stage 2 complete: %d/%d survived. %d rejected.",
        len(survivors), len(tickers), len(rejection_reasons),
    )
    return survivors, rejection_reasons


# ─── Stage 3: Event/earnings/economic calendar filter ─────────────────────────

def stage3_event_filter(
    metrics_list: list[dict],
    check_earnings: bool = True,
    check_economic_calendar: bool = True,
) -> tuple[list[dict], dict[str, str]]:
    """
    Apply event-based exclusion filters per blueprint Section 4 (catalyst overlay).

    Filters:
      - Earnings within next 3 trading days (mandatory exclusion)
      - Economic blackout day (FOMC/CPI/NFP) — applied at scan level, not per-stock

    Note: Economic calendar check returns ([], all_rejected) if today is a blackout.
    """
    # Check economic calendar first — if today is a blackout day, skip all entries
    if check_economic_calendar and is_economic_blackout_day():
        logger.warning(
            "[Filter] Stage 3: ECONOMIC BLACKOUT DAY — no new entries. "
            "FOMC/CPI/NFP release date. Flagging all candidates as blocked."
        )
        return [], {m["ticker"]: "economic_blackout_day" for m in metrics_list}

    survivors: list[dict] = []
    rejection_reasons: dict[str, str] = {}

    for m in metrics_list:
        ticker = m["ticker"]
        if check_earnings and is_near_earnings(ticker, EARNINGS_BLACKOUT_TRADING_DAYS):
            rejection_reasons[ticker] = "earnings_within_3d"
            continue
        survivors.append(m)

    logger.info(
        "[Filter] Stage 3 complete: %d/%d survived event filter.",
        len(survivors), len(metrics_list),
    )
    return survivors, rejection_reasons


# ─── FCF compound mandatory filter ───────────────────────────────────────────

def apply_fcf_compound_filter(metrics_list: list[dict]) -> tuple[list[dict], dict[str, str]]:
    """
    Apply the compound FCF + balance sheet mandatory filter (blueprint Section 5 Step 1):
    'FCF not deeply negative COMBINED WITH weak balance sheet'

    This is a compound condition (not FCF alone). A company with negative FCF
    but strong balance sheet (low debt) passes. Only those with BOTH:
      - FCF negative (fcf_positive == False)
      - Debt/EBITDA > 5x (very leveraged)
    are excluded.
    """
    survivors = []
    rejections = {}
    for m in metrics_list:
        fcf_ok = m.get("fcf_positive")
        net_debt_ebitda = m.get("net_debt_ebitda")

        # Only reject if BOTH conditions are met (compound condition per blueprint)
        if fcf_ok is False and net_debt_ebitda is not None and net_debt_ebitda > 5.0:
            rejections[m["ticker"]] = (
                f"fcf_negative_and_high_debt(net_debt_ebitda={net_debt_ebitda:.1f}x)"
            )
        else:
            survivors.append(m)

    if rejections:
        logger.info("[Filter] FCF compound filter: removed %d tickers.", len(rejections))
    return survivors, rejections


# ─── Relative strength threshold ─────────────────────────────────────────────

def apply_relative_strength_threshold(
    metrics_list: list[dict],
) -> tuple[list[dict], dict[str, str]]:
    """
    Enforce the mandatory relative-strength requirement.

    Pool-size-aware logic (prevents wiping out all candidates on thin days):

    Large pool (≥ RS_RELATIVE_CUT_MIN_POOL = 20):
      - Apply relative top-30% percentile cut AND require rs_63d > RS_ABS_FLOOR_LARGE_POOL (0%).
      - Stock must beat SPY over 3 months AND be in the top 30% of the surviving pool.

    Small pool (< 20):
      - Skip the relative percentile cut entirely.
      - Only apply absolute floor: rs_63d > RS_ABS_FLOOR_SMALL_POOL (-5%).
      - Prevents the relative cut from destroying all candidates on thin-filter days.

    Tickers with no RS data are passed through with a warning (no RS = no rejection).
    """
    if not metrics_list:
        return [], {}

    valid = [m for m in metrics_list if m.get("rs_63d") is not None]
    if not valid:
        logger.warning("[Filter] No tickers have RS data — skipping RS threshold filter.")
        return metrics_list, {}

    pool_size = len(valid)
    survivors = []
    rejections = {}

    if pool_size >= RS_RELATIVE_CUT_MIN_POOL:
        # Large pool: relative top-30% cut + absolute floor
        rs_values = sorted([m["rs_63d"] for m in valid], reverse=True)
        cutoff_idx = max(0, int(len(rs_values) * RS_TOP_PERCENTILE) - 1)
        rs_cutoff = rs_values[cutoff_idx]
        mode = f"relative(top30%,cutoff={rs_cutoff:.1f}%)+abs_floor({RS_ABS_FLOOR_LARGE_POOL:.0f}%)"

        for m in metrics_list:
            rs = m.get("rs_63d")
            if rs is None:
                survivors.append(m)  # No data → pass through
                continue
            if rs >= rs_cutoff and rs > RS_ABS_FLOOR_LARGE_POOL:
                survivors.append(m)
            else:
                if rs <= RS_ABS_FLOOR_LARGE_POOL:
                    rejections[m["ticker"]] = (
                        f"rs_abs_floor_failed(rs={rs:.1f}%,floor={RS_ABS_FLOOR_LARGE_POOL:.0f}%)"
                    )
                else:
                    rejections[m["ticker"]] = (
                        f"rs_below_top30pct(rs={rs:.1f}%,cutoff={rs_cutoff:.1f}%)"
                    )
    else:
        # Small pool: absolute floor only — do not apply relative cut
        rs_cutoff = RS_ABS_FLOOR_SMALL_POOL
        mode = f"abs_floor_only(pool={pool_size}<{RS_RELATIVE_CUT_MIN_POOL},floor={rs_cutoff:.0f}%)"

        for m in metrics_list:
            rs = m.get("rs_63d")
            if rs is None:
                survivors.append(m)  # No data → pass through
                continue
            if rs > rs_cutoff:
                survivors.append(m)
            else:
                rejections[m["ticker"]] = (
                    f"rs_small_pool_floor_failed(rs={rs:.1f}%,floor={rs_cutoff:.0f}%)"
                )

    logger.info(
        "[Filter] RS threshold [%s]: %d/%d survived.",
        mode, len(survivors), len(metrics_list),
    )
    return survivors, rejections


# ─── Full pipeline entry point ────────────────────────────────────────────────

def run_universe_filter(tickers: list[str]) -> tuple[list[dict], dict[str, str]]:
    """
    Run the full mandatory filter pipeline on the given ticker universe.
    Returns (shortlist_metrics, all_rejection_reasons).

    Order follows blueprint Section 2 scan order: cheapest filters first.
    """
    all_rejections: dict[str, str] = {}

    # 1. Stage 1: cheap batch price/volume filter
    s1_survivors, s1_rejections = stage1_price_volume_filter(tickers)
    all_rejections.update(s1_rejections)

    if not s1_survivors:
        logger.warning("[Filter] No tickers survived stage 1 filter.")
        return [], all_rejections

    # 2. Stage 2: technical mandatory filters (parallelized)
    s2_metrics, s2_rejections = stage2_technical_filter(s1_survivors)
    all_rejections.update(s2_rejections)

    if not s2_metrics:
        logger.warning("[Filter] No tickers survived stage 2 filter.")
        return [], all_rejections

    # 3. FCF compound filter
    s3_metrics, s3_rejections = apply_fcf_compound_filter(s2_metrics)
    all_rejections.update(s3_rejections)

    # 4. Relative strength top-30% threshold
    s4_metrics, s4_rejections = apply_relative_strength_threshold(s3_metrics)
    all_rejections.update(s4_rejections)

    # 5. Stage 3: event/earnings filter
    s5_metrics, s5_rejections = stage3_event_filter(s4_metrics)
    all_rejections.update(s5_rejections)

    logger.info(
        "[Filter] Pipeline complete: %d/%d tickers made the shortlist. "
        "%d total rejections.",
        len(s5_metrics), len(tickers), len(all_rejections),
    )
    return s5_metrics, all_rejections
