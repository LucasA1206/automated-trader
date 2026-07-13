"""
Data Layer — Phase 1
====================
Fetches and caches all market data needed by the pipeline:
  - OHLCV history (1-year daily bars via yfinance)
  - Batch universe price/volume pre-filter data
  - Fundamentals (market cap, sector, revenue growth, FCF, etc.)
  - Earnings calendar (next earnings date per ticker)
  - VIX current level and recent history
  - SPY regime data (200-day SMA, trend)
  - Economic calendar (FOMC, CPI, NFP dates via FRED)

Design principles (per blueprint Section 10/13/17):
  - Every external call wrapped with retry + exponential backoff
  - On final failure: log + return None (never guess)
  - Cached results have a TTL; never serve stale data to order placement
  - Cross-check: sanity-check any single-bar move > 50% as likely data error
"""

import os
import time
import logging
import threading
import math
from datetime import datetime, timezone, timedelta, date
from typing import Optional
import concurrent.futures

import requests
import yfinance as yf
import pandas as pd

logger = logging.getLogger(__name__)

# ─── Cache storage ────────────────────────────────────────────────────────────
_cache_lock = threading.Lock()
_ohlcv_cache: dict[str, dict] = {}          # ticker -> {"data": df, "fetched": datetime}
_fundamentals_cache: dict[str, dict] = {}   # ticker -> {"data": dict, "fetched": datetime}
_earnings_cache: dict[str, dict] = {}       # ticker -> {"date": date|None, "fetched": datetime}
_regime_cache: dict = {}                    # "spy" -> {..., "fetched": datetime}
_vix_cache: dict = {}                       # "vix" -> {..., "fetched": datetime}
_econ_calendar_cache: dict = {}             # "econ" -> {"dates": list, "fetched": datetime}
_batch_price_cache: dict[str, dict] = {}   # ticker -> {"price", "avg_dollar_vol_20d", "fetched"}

# TTLs
_OHLCV_TTL_HOURS = 6
_FUNDAMENTALS_TTL_HOURS = 24
_EARNINGS_TTL_HOURS = 24
_REGIME_TTL_MINUTES = 30
_VIX_TTL_MINUTES = 30
_ECON_TTL_HOURS = 24
_BATCH_PRICE_TTL_HOURS = 4

# Batch download chunk size for universe pre-filter.
# 100 keeps Yahoo Finance rate-limiter happy; 200 was too aggressive.
_BATCH_CHUNK_SIZE = 100


# ─── Retry helper ─────────────────────────────────────────────────────────────

def _retry(fn, retries: int = 3, base_delay: float = 1.0, label: str = ""):
    """Call fn() with exponential backoff. Returns None on all failures."""
    for attempt in range(1, retries + 1):
        try:
            return fn()
        except Exception as exc:
            wait = base_delay * (2 ** (attempt - 1))
            if attempt < retries:
                logger.warning(
                    "%s attempt %d/%d failed: %s — retrying in %.1fs",
                    label or "call", attempt, retries, exc, wait,
                )
                time.sleep(wait)
            else:
                logger.error("%s failed after %d attempts: %s", label or "call", retries, exc)
    return None


def _is_cache_fresh(entry: dict, ttl_hours: float = None, ttl_minutes: float = None) -> bool:
    if not entry or "fetched" not in entry:
        return False
    age = datetime.now(timezone.utc) - entry["fetched"]
    if ttl_minutes is not None:
        return age.total_seconds() < ttl_minutes * 60
    if ttl_hours is not None:
        return age.total_seconds() < ttl_hours * 3600
    return False


# ─── Sanity check ─────────────────────────────────────────────────────────────

def _sanity_check_ohlcv(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Remove rows where single-bar move > 50% (likely a data error per blueprint Section 17)."""
    if df is None or df.empty:
        return df
    closes = df["Close"]
    pct_change = closes.pct_change().abs()
    bad_rows = pct_change > 0.50
    if bad_rows.any():
        count = bad_rows.sum()
        logger.warning(
            "[DataLayer] %s: removed %d bar(s) with >50%% price move (likely data error).",
            ticker, count,
        )
        df = df[~bad_rows]
    return df


# ─── OHLCV History ────────────────────────────────────────────────────────────

def fetch_ohlcv(ticker: str, period: str = "1y") -> Optional[pd.DataFrame]:
    """
    Fetch daily OHLCV history for a single ticker.
    Returns a DataFrame with columns: Open, High, Low, Close, Volume.
    Returns None on failure (fail-safe: never return partial/stale data for scoring).

    Cache TTL: 6 hours (sufficient for a daily pre-market run).
    """
    with _cache_lock:
        cached = _ohlcv_cache.get(ticker)
    if cached and _is_cache_fresh(cached, ttl_hours=_OHLCV_TTL_HOURS):
        return cached["data"]

    def _fetch():
        tk = yf.Ticker(ticker)
        df = tk.history(period=period, interval="1d", auto_adjust=True)
        # Use 30 as the minimum so that partial/rate-limited responses
        # (which may return only a handful of rows) are retried rather
        # than cached as valid data and later rejected as insufficient_history.
        if df is None or df.empty or len(df) < 30:
            raise ValueError(f"Insufficient history for {ticker}: {len(df) if df is not None else 0} rows")
        df.index = pd.to_datetime(df.index)
        return df

    df = _retry(_fetch, retries=3, base_delay=1.0, label=f"OHLCV({ticker})")
    if df is None:
        return None

    df = _sanity_check_ohlcv(df, ticker)
    if df is None or df.empty:
        return None

    with _cache_lock:
        _ohlcv_cache[ticker] = {"data": df, "fetched": datetime.now(timezone.utc)}
    return df


def fetch_ohlcv_batch(tickers: list[str], period: str = "22d") -> dict[str, pd.DataFrame]:
    """
    Batch-download short OHLCV history for universe pre-filtering (22 trading days ≈ 1 month).
    Much faster than individual fetches — used for the cheap price/volume pre-filter stage.

    Returns dict: ticker -> DataFrame (only tickers with sufficient data are included).
    """
    results: dict[str, pd.DataFrame] = {}
    total = len(tickers)
    fetched = 0
    now = datetime.now(timezone.utc)

    for i in range(0, total, _BATCH_CHUNK_SIZE):
        chunk = tickers[i: i + _BATCH_CHUNK_SIZE]
        chunk_num = i // _BATCH_CHUNK_SIZE + 1
        total_chunks = math.ceil(total / _BATCH_CHUNK_SIZE)
        logger.info(
            "[DataLayer] Batch OHLCV: chunk %d/%d (%d tickers)…",
            chunk_num, total_chunks, len(chunk),
        )

        def _download_chunk(ch=chunk):
            return yf.download(
                ch,
                period=period,
                interval="1d",
                group_by="ticker",
                auto_adjust=True,
                progress=False,
                threads=True,
            )

        raw = _retry(_download_chunk, retries=3, base_delay=2.0, label="BatchOHLCV")
        if raw is None or raw.empty:
            logger.warning(
                "[DataLayer] Batch download returned empty for chunk %d/%d (index %d).",
                chunk_num, total_chunks, i,
            )
            time.sleep(0.5)
            continue

        chunk_fetched = 0
        for ticker in chunk:
            try:
                if isinstance(raw.columns, pd.MultiIndex):
                    # yfinance ≥0.2.40 may return (field, ticker) or (ticker, field)
                    # level order depending on version. Detect which level holds ticker names.
                    level0_vals = raw.columns.get_level_values(0)
                    level1_vals = raw.columns.get_level_values(1)

                    if ticker in level0_vals:
                        # Standard (ticker, field) ordering
                        df = raw[ticker].dropna(how="all")
                    elif ticker in level1_vals:
                        # Swapped (field, ticker) ordering — transpose the selection
                        df = raw.xs(ticker, axis=1, level=1).dropna(how="all")
                    else:
                        # Ticker not present in this batch result at all
                        continue
                elif len(chunk) == 1:
                    # Single-ticker download returns a flat DataFrame
                    df = raw.dropna(how="all")
                else:
                    logger.debug(
                        "[DataLayer] Unexpected column format for %s in batch.", ticker
                    )
                    continue

                if df is None or df.empty or len(df) < 5:
                    continue

                df = _sanity_check_ohlcv(df, ticker)
                if df is not None and not df.empty:
                    results[ticker] = df
                    chunk_fetched += 1
                    fetched += 1
                    # NOTE: Do NOT write the 22-day batch data into the single-ticker
                    # _ohlcv_cache. Stage 2 calls fetch_ohlcv(period="1y") and expects
                    # a full year of data. If we cache 22d here, Stage 2 reads the
                    # cached 22d entry, sees len(df) < 50, and rejects every ticker
                    # as "insufficient_history". The caches serve different purposes
                    # and must not be conflated.
            except Exception as exc:
                logger.debug("[DataLayer] Batch parse failed for %s: %s", ticker, exc)

        logger.debug(
            "[DataLayer] Chunk %d/%d: %d/%d tickers parsed successfully.",
            chunk_num, total_chunks, chunk_fetched, len(chunk),
        )
        # Increased from 0.1s — gives Yahoo Finance rate limiter room to breathe
        time.sleep(0.5)

    logger.info("[DataLayer] Batch OHLCV complete: %d/%d tickers with data.", fetched, total)
    return results


# ─── Fundamentals ─────────────────────────────────────────────────────────────

def fetch_fundamentals(ticker: str) -> Optional[dict]:
    """
    Fetch fundamental data for a ticker via yfinance .info.

    Returns dict with:
      market_cap, float_shares, sector, industry,
      revenue_growth_yoy, eps_growth_yoy, fcf_positive, net_debt_ebitda,
      profit_margin, return_on_equity, institutional_ownership_pct,
      short_interest_pct_float, beta

    Returns None on failure.
    Cache TTL: 24 hours.
    """
    with _cache_lock:
        cached = _fundamentals_cache.get(ticker)
    if cached and _is_cache_fresh(cached, ttl_hours=_FUNDAMENTALS_TTL_HOURS):
        return cached["data"]

    def _fetch():
        tk = yf.Ticker(ticker)
        info = tk.info
        if not info or info.get("quoteType") not in ("EQUITY", "ETF", None):
            raise ValueError(f"No equity info for {ticker}")
        return info

    info = _retry(_fetch, retries=3, base_delay=1.5, label=f"Fundamentals({ticker})")
    if info is None:
        return None

    # Parse out what we need
    market_cap = info.get("marketCap") or 0
    float_shares = info.get("floatShares") or info.get("sharesOutstanding") or 0

    # Revenue growth: yfinance provides revenueGrowth (YoY quarterly) as a decimal
    revenue_growth_yoy = info.get("revenueGrowth")  # e.g. 0.12 = 12%
    if revenue_growth_yoy is not None:
        revenue_growth_yoy = float(revenue_growth_yoy) * 100  # convert to %

    # EPS growth: use epsCurrentYear vs epsPriorYear (trailing) — fallback to earningsGrowth
    eps_growth_yoy = info.get("earningsGrowth")
    if eps_growth_yoy is not None:
        eps_growth_yoy = float(eps_growth_yoy) * 100

    # FCF: yfinance doesn't expose directly in info; use operatingCashflow - capexes
    # Approximate: if operatingCashflow > 0 and freeCashflow > 0 → positive FCF
    operating_cf = info.get("operatingCashflow") or 0
    free_cf = info.get("freeCashflow") or operating_cf  # freeCashflow may be None
    fcf_positive = (free_cf > 0) if free_cf else None

    # Debt: totalDebt / ebitda (approximation)
    total_debt = info.get("totalDebt") or 0
    ebitda = info.get("ebitda") or 0
    net_debt_ebitda = None
    if ebitda and ebitda > 0 and total_debt:
        cash = info.get("totalCash") or 0
        net_debt = total_debt - cash
        net_debt_ebitda = round(net_debt / ebitda, 2)

    profit_margin = info.get("profitMargins")
    if profit_margin is not None:
        profit_margin = float(profit_margin) * 100

    roe = info.get("returnOnEquity")
    if roe is not None:
        roe = float(roe) * 100

    # Institutional ownership
    inst_own_pct = info.get("heldPercentInstitutions")
    if inst_own_pct is not None:
        inst_own_pct = float(inst_own_pct) * 100

    # Short interest
    short_pct_float = info.get("shortPercentOfFloat")
    if short_pct_float is not None:
        short_pct_float = float(short_pct_float) * 100

    beta = info.get("beta")

    data = {
        "ticker": ticker,
        "market_cap": market_cap,
        "float_shares": float_shares,
        "sector": info.get("sector", "Unknown"),
        "industry": info.get("industry", "Unknown"),
        "revenue_growth_yoy": revenue_growth_yoy,
        "eps_growth_yoy": eps_growth_yoy,
        "fcf_positive": fcf_positive,
        "net_debt_ebitda": net_debt_ebitda,
        "profit_margin": profit_margin,
        "return_on_equity": roe,
        "institutional_ownership_pct": inst_own_pct,
        "short_interest_pct_float": short_pct_float,
        "beta": beta,
    }

    with _cache_lock:
        _fundamentals_cache[ticker] = {"data": data, "fetched": datetime.now(timezone.utc)}
    return data


def fetch_fundamentals_batch(tickers: list[str], max_workers: int = 8) -> dict[str, dict]:
    """Fetch fundamentals for multiple tickers in parallel. Returns ticker -> data dict."""
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(fetch_fundamentals, t): t for t in tickers}
        for future in concurrent.futures.as_completed(futures):
            ticker = futures[future]
            try:
                data = future.result()
                if data:
                    results[ticker] = data
            except Exception as exc:
                logger.debug("[DataLayer] Fundamentals batch failed for %s: %s", ticker, exc)
    logger.info("[DataLayer] Fundamentals batch: %d/%d tickers.", len(results), len(tickers))
    return results


# ─── Earnings Calendar ────────────────────────────────────────────────────────

def fetch_next_earnings_date(ticker: str) -> Optional[date]:
    """
    Return the next scheduled earnings date for a ticker.
    Returns None if unavailable.
    This is used for the mandatory earnings-blackout exclusion filter.
    Cache TTL: 24 hours.
    """
    with _cache_lock:
        cached = _earnings_cache.get(ticker)
    if cached and _is_cache_fresh(cached, ttl_hours=_EARNINGS_TTL_HOURS):
        return cached["date"]

    def _fetch():
        tk = yf.Ticker(ticker)
        cal = tk.calendar
        if cal is None:
            return None
        earn_date = None
        if isinstance(cal, dict):
            dates = cal.get("Earnings Date")
            if dates:
                d = dates[0]
                earn_date = d.date() if hasattr(d, "date") else d
        elif hasattr(cal, "empty") and not cal.empty:
            if "Earnings Date" in cal.index:
                d = cal.loc["Earnings Date"].iloc[0]
                earn_date = d.date() if hasattr(d, "date") else d
        return earn_date

    earn_date = _retry(_fetch, retries=2, base_delay=1.0, label=f"EarningsDate({ticker})")

    with _cache_lock:
        _earnings_cache[ticker] = {"date": earn_date, "fetched": datetime.now(timezone.utc)}
    return earn_date


def is_near_earnings(ticker: str, trading_days_buffer: int = 3) -> bool:
    """
    Return True if the ticker has earnings within the next `trading_days_buffer` trading days.
    Uses calendar days as a conservative proxy for trading days.
    """
    earn_date = fetch_next_earnings_date(ticker)
    if earn_date is None:
        return False  # No known earnings — conservative: allow trade
    today = datetime.now(timezone.utc).date()
    # Use 5 calendar days as proxy for 3 trading days (conservative)
    calendar_buffer = trading_days_buffer + 2
    delta = (earn_date - today).days
    return 0 <= delta <= calendar_buffer


# ─── VIX ──────────────────────────────────────────────────────────────────────

def fetch_vix() -> Optional[dict]:
    """
    Fetch current VIX level and 3-session history (for the VIX-spike filter).

    Returns:
      {"current": float, "prev_1d": float, "prev_3d": float, "spike_3d": float}
      where spike_3d = % rise of VIX over last 3 sessions.

    Returns None on failure. Cache TTL: 30 minutes.
    """
    with _cache_lock:
        cached = _vix_cache.get("vix")
    if cached and _is_cache_fresh(cached, ttl_minutes=_VIX_TTL_MINUTES):
        return cached["data"]

    def _fetch():
        tk = yf.Ticker("^VIX")
        hist = tk.history(period="5d", interval="1d")
        if hist is None or hist.empty or len(hist) < 2:
            raise ValueError("Insufficient VIX history")
        closes = hist["Close"]
        current = float(closes.iloc[-1])
        prev_1d = float(closes.iloc[-2]) if len(closes) >= 2 else current
        prev_3d = float(closes.iloc[-4]) if len(closes) >= 4 else prev_1d
        spike_3d = ((current - prev_3d) / prev_3d * 100) if prev_3d > 0 else 0.0
        return {
            "current": round(current, 2),
            "prev_1d": round(prev_1d, 2),
            "prev_3d": round(prev_3d, 2),
            "spike_3d_pct": round(spike_3d, 2),
        }

    data = _retry(_fetch, retries=3, base_delay=2.0, label="VIX")
    if data is None:
        logger.error("[DataLayer] Failed to fetch VIX — regime check cannot proceed safely.")
        return None

    with _cache_lock:
        _vix_cache["vix"] = {"data": data, "fetched": datetime.now(timezone.utc)}
    return data


# ─── SPY Regime ───────────────────────────────────────────────────────────────

def fetch_spy_regime() -> Optional[dict]:
    """
    Fetch SPY trend data for the market regime gate (blueprint Section 6/10).

    Computes:
      - SPY current price vs 200-day SMA (mandatory trend filter)
      - SPY current price vs 50-day SMA
      - 1-day SPY return (for black-swan ±3% intraday detection)
      - regime: "risk_on" | "caution" | "risk_off"

    Returns None on failure (fail-safe: no new entries if regime unknown).
    Cache TTL: 30 minutes.
    """
    with _cache_lock:
        cached = _regime_cache.get("spy")
    if cached and _is_cache_fresh(cached, ttl_minutes=_REGIME_TTL_MINUTES):
        return cached["data"]

    def _fetch():
        tk = yf.Ticker("SPY")
        hist = tk.history(period="1y", interval="1d")
        if hist is None or hist.empty or len(hist) < 50:
            raise ValueError("Insufficient SPY history")
        closes = hist["Close"]
        sma_50  = float(closes.rolling(50).mean().iloc[-1])
        sma_200 = float(closes.rolling(200).mean().iloc[-1]) if len(closes) >= 200 else None
        current = float(closes.iloc[-1])
        prev    = float(closes.iloc[-2])
        day_return_pct = ((current - prev) / prev * 100) if prev > 0 else 0.0
        return {
            "price": round(current, 2),
            "sma_50": round(sma_50, 2),
            "sma_200": round(sma_200, 2) if sma_200 else None,
            "above_sma_200": (current > sma_200) if sma_200 else False,
            "above_sma_50": current > sma_50,
            "day_return_pct": round(day_return_pct, 2),
        }

    data = _retry(_fetch, retries=3, base_delay=2.0, label="SPY_regime")
    if data is None:
        return None

    with _cache_lock:
        _regime_cache["spy"] = {"data": data, "fetched": datetime.now(timezone.utc)}
    return data


def fetch_sector_etf_returns() -> dict[str, float]:
    """
    Fetch 3-month returns for major sector ETFs (used for sector relative strength scoring).
    Returns dict: sector_name -> 3-month return %.
    Cache TTL: 6 hours (alongside OHLCV).
    """
    sector_etfs = {
        "Technology": "XLK",
        "Healthcare": "XLV",
        "Financials": "XLF",
        "Energy": "XLE",
        "Consumer Discretionary": "XLY",
        "Consumer Staples": "XLP",
        "Industrials": "XLI",
        "Materials": "XLB",
        "Utilities": "XLU",
        "Real Estate": "XLRE",
        "Communication Services": "XLC",
    }

    results: dict[str, float] = {}

    def _fetch_return(etf_ticker: str, sector_name: str):
        try:
            hist = yf.Ticker(etf_ticker).history(period="3mo", interval="1d")
            if hist is None or hist.empty or len(hist) < 5:
                return None
            closes = hist["Close"]
            ret = (float(closes.iloc[-1]) / float(closes.iloc[0]) - 1) * 100
            return sector_name, round(ret, 2)
        except Exception as exc:
            logger.debug("[DataLayer] Sector ETF %s failed: %s", etf_ticker, exc)
            return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(_fetch_return, etf, sector) for sector, etf in sector_etfs.items()]
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result:
                sector_name, ret = result
                results[sector_name] = ret

    return results


# ─── Economic Calendar (FRED) ─────────────────────────────────────────────────

def fetch_economic_calendar() -> list[date]:
    """
    Fetch upcoming major macro event dates from FRED (FOMC, CPI, NFP).
    Returns list of dates where no new entries should be opened.
    Cache TTL: 24 hours.

    FRED is free, no API key required for basic calendar lookups.
    Falls back to an empty list on failure (conservative: don't block trading
    if calendar is unavailable — already gated by regime + VIX filters).
    """
    with _cache_lock:
        cached = _econ_calendar_cache.get("econ")
    if cached and _is_cache_fresh(cached, ttl_hours=_ECON_TTL_HOURS):
        return cached["dates"]

    dates: list[date] = []

    # FRED FOMC calendar — publicly available JSON
    # Note: FRED doesn't have a formal free calendar API endpoint for upcoming dates.
    # We use a known public source for FOMC meeting dates.
    # For production: replace with a dedicated calendar service.
    fomc_dates_2025_2026 = [
        # 2025
        date(2025, 1, 29), date(2025, 3, 19), date(2025, 5, 7),
        date(2025, 6, 18), date(2025, 7, 30), date(2025, 9, 17),
        date(2025, 10, 29), date(2025, 12, 10),
        # 2026
        date(2026, 1, 28), date(2026, 3, 18), date(2026, 4, 29),
        date(2026, 6, 17), date(2026, 7, 29), date(2026, 9, 16),
        date(2026, 10, 28), date(2026, 12, 9),
    ]

    today = datetime.now(timezone.utc).date()
    # Filter to upcoming dates only, include day before as a caution buffer
    for d in fomc_dates_2025_2026:
        if d >= today:
            dates.append(d - timedelta(days=1))  # day before
            dates.append(d)  # meeting day

    # CPI and NFP are released on specific days fetched dynamically if possible.
    # For now, use the static FOMC dates as the primary blackout calendar.
    # TODO Phase 8: integrate BLS/FRED API for live CPI/NFP dates.

    with _cache_lock:
        _econ_calendar_cache["econ"] = {"dates": dates, "fetched": datetime.now(timezone.utc)}
    logger.info("[DataLayer] Economic calendar: %d blackout dates loaded.", len(dates))
    return dates


def is_economic_blackout_day() -> bool:
    """Return True if today is a major macro event day (FOMC, CPI, NFP)."""
    blackout_dates = fetch_economic_calendar()
    today = datetime.now(timezone.utc).date()
    return today in blackout_dates


# ─── Compute regime status ────────────────────────────────────────────────────

def compute_regime_status() -> Optional[dict]:
    """
    Compute the full market regime status per blueprint Section 6/10.

    Regime logic:
      risk_off  → SPY below 200-day SMA OR VIX > 30 OR VIX spiked > 20% in 3 sessions
      caution   → SPY near 200-day SMA (within 2%) OR VIX 25-30
      risk_on   → SPY above 200-day SMA AND VIX < 25 AND no spike

    Returns None if any critical data source fails (fail-safe: no new entries).
    """
    spy = fetch_spy_regime()
    vix = fetch_vix()

    if spy is None:
        logger.error("[DataLayer] SPY data unavailable — regime check failed. Defaulting to risk_off.")
        return None

    if vix is None:
        logger.error("[DataLayer] VIX data unavailable — regime check failed. Defaulting to risk_off.")
        return None

    vix_current = vix["current"]
    vix_spike_3d = vix["spike_3d_pct"]
    spy_above_200 = spy.get("above_sma_200", False)
    spy_day_return = spy.get("day_return_pct", 0)

    # Black swan: S&P 500 (SPY) single-session move > ±3%
    black_swan_day = abs(spy_day_return) > 3.0

    # Regime classification
    if not spy_above_200 or vix_current > 30 or vix_spike_3d > 20 or black_swan_day:
        regime = "risk_off"
    elif vix_current >= 25 or (spy.get("sma_200") and spy["price"] < spy["sma_200"] * 1.02):
        regime = "caution"
    else:
        regime = "risk_on"

    details = (
        f"SPY={'above' if spy_above_200 else 'BELOW'} 200SMA, "
        f"VIX={vix_current:.1f}, "
        f"VIX_3d_spike={vix_spike_3d:.1f}%, "
        f"SPY_1d={spy_day_return:+.1f}%"
    )
    if black_swan_day:
        details += " [BLACK-SWAN DAY]"

    return {
        "regime": regime,
        "details": details,
        "spy_price": spy["price"],
        "spy_sma_200": spy.get("sma_200"),
        "spy_above_200": spy_above_200,
        "spy_day_return_pct": spy_day_return,
        "vix": vix_current,
        "vix_spike_3d_pct": vix_spike_3d,
        "black_swan_day": black_swan_day,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ─── SPY relative strength helper ─────────────────────────────────────────────

def fetch_spy_returns() -> Optional[dict]:
    """
    Fetch SPY cumulative returns at 63-day (3m) and 126-day (6m) lookbacks.
    Used to compute relative strength of each stock vs the benchmark.
    """
    def _fetch():
        tk = yf.Ticker("SPY")
        hist = tk.history(period="7mo", interval="1d")
        if hist is None or hist.empty or len(hist) < 63:
            raise ValueError("Insufficient SPY history for RS calculation")
        closes = hist["Close"]
        current = float(closes.iloc[-1])
        ret_63d  = ((current / float(closes.iloc[-63]))  - 1) * 100 if len(closes) >= 63  else None
        ret_126d = ((current / float(closes.iloc[-126])) - 1) * 100 if len(closes) >= 126 else None
        return {"ret_63d": ret_63d, "ret_126d": ret_126d}

    return _retry(_fetch, retries=3, base_delay=2.0, label="SPY_returns")


# ─── Intraday VWAP helper ─────────────────────────────────────────────────────

def estimate_vwap(ticker: str) -> Optional[float]:
    """
    Estimate intraday VWAP using today's 5-minute bars via yfinance.
    Used by the entry engine (Section 8) to confirm price reclaiming VWAP.
    Returns None if intraday data is unavailable.
    """
    def _fetch():
        tk = yf.Ticker(ticker)
        hist = tk.history(period="1d", interval="5m")
        if hist is None or hist.empty:
            return None
        typical = (hist["High"] + hist["Low"] + hist["Close"]) / 3
        vwap = (typical * hist["Volume"]).cumsum() / hist["Volume"].cumsum()
        return float(vwap.iloc[-1])

    return _retry(_fetch, retries=2, base_delay=0.5, label=f"VWAP({ticker})")


# ─── Cache management ─────────────────────────────────────────────────────────

def clear_all_caches():
    """Clear all data caches. Call at the start of each daily scan run."""
    with _cache_lock:
        _ohlcv_cache.clear()
        _fundamentals_cache.clear()
        _earnings_cache.clear()
        _regime_cache.clear()
        _vix_cache.clear()
        _econ_calendar_cache.clear()
        _batch_price_cache.clear()
    logger.info("[DataLayer] All caches cleared for new scan run.")


def get_cache_stats() -> dict:
    """Return cache population counts for monitoring."""
    with _cache_lock:
        return {
            "ohlcv": len(_ohlcv_cache),
            "fundamentals": len(_fundamentals_cache),
            "earnings": len(_earnings_cache),
            "batch_price": len(_batch_price_cache),
            "regime_cached": bool(_regime_cache.get("spy")),
            "vix_cached": bool(_vix_cache.get("vix")),
        }


# ─── Sector ETF returns ───────────────────────────────────────────────────────

# Sector ETF tickers for relative strength calculation
_SECTOR_ETFS = {
    "Technology": "XLK",
    "Healthcare": "XLV",
    "Financials": "XLF",
    "Consumer Cyclical": "XLY",
    "Consumer Defensive": "XLP",
    "Energy": "XLE",
    "Industrials": "XLI",
    "Basic Materials": "XLB",
    "Real Estate": "XLRE",
    "Utilities": "XLU",
    "Communication Services": "XLC",
}

_sector_returns_cache: dict = {}
_sector_returns_lock = threading.Lock()


def fetch_sector_etf_returns(lookback_days: int = 63) -> dict[str, float]:
    """
    Fetch 3-month (63-day) returns for all sector ETFs.
    Used by the scoring engine for sector relative strength scoring.
    Returns dict: {sector_name: return_pct}
    """
    global _sector_returns_cache

    with _sector_returns_lock:
        cached = _sector_returns_cache.get("sectors")
        if cached and (datetime.now(timezone.utc) - cached["fetched"]).total_seconds() < 3600 * 4:
            return cached["data"]

    result: dict[str, float] = {}
    etf_tickers = list(_SECTOR_ETFS.values())
    try:
        df = yf.download(
            etf_tickers,
            period="4mo",
            interval="1d",
            auto_adjust=True,
            progress=False,
            threads=True,
        )["Close"]

        for sector, etf in _SECTOR_ETFS.items():
            try:
                series = df[etf].dropna()
                if len(series) >= lookback_days:
                    ret = ((series.iloc[-1] / series.iloc[-lookback_days]) - 1) * 100
                    result[sector] = round(float(ret), 2)
            except Exception:
                pass
    except Exception as exc:
        logger.warning("[DataLayer] Sector ETF returns fetch failed: %s", exc)

    with _sector_returns_lock:
        _sector_returns_cache["sectors"] = {
            "data": result,
            "fetched": datetime.now(timezone.utc),
        }

    return result

