import os
import io
import json
import math
import time
import logging
import requests
import google.generativeai as genai
import yfinance as yf
import concurrent.futures
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
NEWS_API_KEY = os.getenv("NEWS_API_KEY")

# Configure Gemini
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# ─── Fallback curated NASDAQ universe (used if live fetch fails) ───────────────
_FALLBACK_UNIVERSE = [
    # ── Mega-cap Tech ─────────────────────────────────────────────────────────
    "AAPL", "MSFT", "NVDA", "GOOGL", "GOOG", "AMZN", "META", "TSLA", "AVGO",
    "ASML", "AMD", "QCOM", "ARM", "INTC", "TXN", "ADI", "MCHP", "AMAT",
    "LRCX", "KLAC", "NXPI", "SWKS", "MRVL", "ON", "MPWR", "WOLF", "SMCI",
    "MU", "WDC", "STX", "NTAP",
    # ── Software / Cloud ──────────────────────────────────────────────────────
    "ADBE", "CRM", "NOW", "WDAY", "VEEV", "TEAM", "HUBS", "DDOG", "NET",
    "ZS", "PANW", "CRWD", "OKTA", "S", "MNDY", "BILL", "SMAR", "BOX",
    "DOCN", "DOMO", "NCNO", "PCOR", "ESTC", "MDB", "GTLB", "CFLT", "SNOW",
    "PLTR", "COIN", "MSTR", "RBLX", "SHOP", "AFRM", "SOFI", "UPST", "LC",
    "SQ", "PYPL", "SSNC", "MANH", "PAYC", "GWRE", "RELY", "TOST",
    "BRZE", "ALTR", "DT", "SDGR", "PATH", "AI", "BBAI", "SOUN",
    "GFAI", "IREN", "CORZ", "CIFR", "BTBT", "CLSK",
    # ── Semiconductors ────────────────────────────────────────────────────────
    "SNPS", "CDNS", "LSCC", "ACLS", "ONTO", "ICHR", "FORM", "AMKR",
    "QRVO", "LITE", "COHU", "UCTT", "KLIC", "AEHR", "AXTI",
    "POWI", "DIOD", "SLAB", "AMBA", "ALGM", "MTSI", "CRUS",
    # ── Internet / E-commerce ─────────────────────────────────────────────────
    "EBAY", "ETSY", "CHWY", "W", "DKNG", "PENN", "LYFT", "UBER", "DASH",
    "ABNB", "BKNG", "EXPE", "TRIP", "YELP", "IAC", "ZG", "RDFN", "OPEN",
    "NFLX", "ROKU", "SPOT", "PARAA", "SIRI",
    # ── EVs / Clean Energy ────────────────────────────────────────────────────
    "RIVN", "LCID", "NIO", "XPEV", "LI", "NKLA", "BLNK", "CHPT", "EVGO",
    "PLUG", "FCEL", "BLDP", "FSLR", "ENPH", "SEDG", "ARRY", "RUN",
    "JOBY", "ACHR",
    # ── Biotech / Pharma ──────────────────────────────────────────────────────
    "REGN", "VRTX", "MRNA", "BIIB", "ALNY", "ILMN", "BMRN", "INCY",
    "EXAS", "NBIX", "ACAD", "RARE", "RCKT", "NTLA", "BEAM", "EDIT",
    "CRSP", "FATE", "IOVA", "KRTX", "PTGX", "TGTX", "PRAX", "RXRX",
    "ARQT", "IMVT", "IONS", "ARGX", "KRYS", "RVMD", "BLUE", "FOLD",
    "AVXL", "VCEL", "NUVL", "ARVN", "KYMR", "MGNX", "ROIV", "LNTH",
    # ── Medical Devices ───────────────────────────────────────────────────────
    "ISRG", "IDXX", "DXCM", "PODD", "ALGN", "HOLX", "NTRA", "PACB",
    "INSP", "SWAV", "TNDM", "NARI",
    # ── Financial / Fintech ───────────────────────────────────────────────────
    "HOOD", "MELI", "NU", "PAGS", "DLO", "GPN", "FOUR", "RPAY",
    # ── Cybersecurity ─────────────────────────────────────────────────────────
    "FTNT", "CYBR", "TENB", "RPD", "QLYS", "VRNS", "SAIL", "RBRK",
    # ── Cloud Infrastructure ──────────────────────────────────────────────────
    "CSCO", "ANET", "JNPR", "FFIV", "CALX", "CIEN",
    # ── Consumer Tech ─────────────────────────────────────────────────────────
    "HPQ", "LOGI", "GPRO",
    # ── Retail / Consumer ─────────────────────────────────────────────────────
    "COST", "LULU", "ORLY", "CASY", "FIVE", "ROST", "DLTR",
    "TSCO", "ULTA", "DECK", "CROX", "SKX", "ONON",
    # ── Telecom ───────────────────────────────────────────────────────────────
    "TMUS", "CHTR", "GSAT", "AST",
    # ── Food / Beverage ───────────────────────────────────────────────────────
    "SBUX", "PZZA", "WING", "SHAK", "BROS", "CAVA", "TXRH",
    # ── Industrial / Aerospace ────────────────────────────────────────────────
    "AXON", "KTOS", "RKLB", "LUNR", "ASTS",
    # ── Crypto / Blockchain ───────────────────────────────────────────────────
    "COIN", "MSTR", "MARA", "RIOT", "CLSK", "CORZ", "IREN", "BTBT", "HUT",
    "WULF", "BITF",
]

# Remove duplicates while preserving order
_seen: set = set()
_FALLBACK_UNIVERSE = [t for t in _FALLBACK_UNIVERSE if not (t in _seen or _seen.add(t))]

# Core mega-cap tickers — receive a small scoring bonus in the dynamic screen
CORE_TICKERS = {
    "AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN", "TSLA", "AVGO",
    "AMD", "PLTR", "COIN", "CRM", "NFLX", "CRWD",
}

# Module-level cache for the full NASDAQ ticker list
_nasdaq_ticker_cache: list[str] = []
_nasdaq_ticker_fetched_at: datetime | None = None
_NASDAQ_CACHE_TTL_HOURS = 24  # Refresh at most once per day

# Symbols with these single-char suffixes are warrants, rights, preferred shares etc.
_SPECIAL_SUFFIX_CHARS = set("WRUPQZ")


def _parse_nasdaqtrader_file(text: str, source_label: str) -> list[str]:
    """
    Parse a nasdaqtrader.com pipe-delimited symbol directory file.

    Both nasdaqlisted.txt and otherlisted.txt share the same format:
      Column 0: Symbol
      Column 6 (nasdaqlisted) / Column 6 (otherlisted): ETF flag (Y/N)

    The last line of each file is a file-creation timestamp row starting with
    'File Creation Time' — we skip it.

    Returns a cleaned list of common-stock ticker symbols.
    """
    lines = text.strip().splitlines()
    if not lines:
        return []

    header = lines[0]  # noqa — kept for reference but not used
    tickers: list[str] = []
    raw_count = skipped_etf = skipped_special = skipped_test = 0

    for line in lines[1:]:
        # Skip the file-creation timestamp footer row
        if line.startswith("File Creation Time"):
            continue

        parts = line.split("|")
        if len(parts) < 2:
            continue

        symbol = parts[0].strip().upper()
        if not symbol:
            continue

        raw_count += 1

        # ── ETF flag check (column 6 when present) ───────────────────────────
        etf_flag = parts[6].strip().upper() if len(parts) > 6 else ""
        if etf_flag == "Y":
            skipped_etf += 1
            continue

        # ── Filter out non-standard symbols ──────────────────────────────────
        # Warrants, preferred, rights, when-issued etc. typically contain
        # special chars or have a suffix letter after a space
        if any(c in symbol for c in (".", "+", "-", "^", "=", "/")):
            skipped_special += 1
            continue
        if symbol.startswith("$"):
            skipped_special += 1
            continue
        # Reject symbols with embedded spaces (e.g. "AAPL WS" = warrant)
        if " " in symbol:
            skipped_special += 1
            continue
        # Common warrant/preferred suffix patterns: AAPLW, AAPLR, AAPLP, etc.
        # Only apply if symbol > 4 chars and ends in one of the special chars
        if len(symbol) > 4 and symbol[-1] in _SPECIAL_SUFFIX_CHARS:
            # Allow if last char forms part of a known ticker (e.g. GOOGL, PANW)
            # Check: if base (without last char) is unlikely to be a ticker, skip
            # Simple heuristic: reject if last char is appended to a 4+ char base
            base = symbol[:-1]
            if len(base) >= 4:
                skipped_special += 1
                continue

        # Test securities
        if symbol.lower().endswith("test"):
            skipped_test += 1
            continue

        tickers.append(symbol)

    logger.info(
        f"[{source_label}] Parsed {raw_count} rows → kept {len(tickers)} "
        f"(skipped: {skipped_etf} ETFs, {skipped_special} special, {skipped_test} test)"
    )
    return tickers


def fetch_full_nasdaq_tickers() -> list[str]:
    """
    Fetch the complete list of NASDAQ-listed tickers from NASDAQ's public FTP directory.

    Sources (both fetched and merged):
      1. nasdaqlisted.txt  — NASDAQ Global Select / Global / Capital Market stocks
      2. otherlisted.txt   — NYSE, NYSE MKT, ARCA, BATS stocks also quoted on NASDAQ

    Both files are free, unauthenticated, and updated every trading day.
    Falls back to the curated _FALLBACK_UNIVERSE if all fetches fail.

    Filters applied (via _parse_nasdaqtrader_file):
      - ETF flag = Y → skip
      - Special chars (. + - ^ = /) → skip (warrants, rights, preferred)
      - Symbols starting with $ → skip
      - Symbols with spaces → skip (e.g. when-issued)
      - 5+-char symbols ending in W/R/U/P/Q/Z → likely warrant/right, skip
      - Symbols ending in 'test' → test securities, skip
    """
    global _nasdaq_ticker_cache, _nasdaq_ticker_fetched_at

    # Return cache if fresh enough
    if (
        _nasdaq_ticker_cache
        and _nasdaq_ticker_fetched_at
        and (datetime.now(timezone.utc) - _nasdaq_ticker_fetched_at).total_seconds()
        < _NASDAQ_CACHE_TTL_HOURS * 3600
    ):
        logger.info(f"Using cached NASDAQ ticker list ({len(_nasdaq_ticker_cache)} tickers).")
        return _nasdaq_ticker_cache

    # ── Source 1: NASDAQ-listed securities ───────────────────────────────────
    nasdaq_tickers: list[str] = []
    try:
        url1 = "https://ftp.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
        logger.info(f"Fetching NASDAQ universe from {url1} ...")
        resp1 = requests.get(url1, timeout=20)
        resp1.raise_for_status()
        nasdaq_tickers = _parse_nasdaqtrader_file(resp1.text, "nasdaqlisted")
        logger.info(f"nasdaqlisted.txt: {len(nasdaq_tickers)} common-stock symbols loaded.")
    except Exception as e:
        logger.warning(f"nasdaqlisted.txt fetch failed ({e}). Trying DataHub fallback...")
        # ── Source 1b: DataHub CDN mirror of nasdaqlisted (updated daily) ────
        try:
            url1b = "https://datahub.io/core/nasdaq-listings/r/nasdaq-listed-symbols.csv"
            resp1b = requests.get(url1b, timeout=20)
            resp1b.raise_for_status()
            # Parse CSV (Symbol,Company Name,...,ETF,...)
            lines = resp1b.text.strip().splitlines()
            _header = lines[0].lower().split(",")
            sym_idx = 0   # column 0 is always Symbol
            etf_idx = _header.index("etf") if "etf" in _header else 7
            for line in lines[1:]:
                if line.startswith("File Creation Time"):
                    continue
                # Handle quoted CSV fields
                import csv as _csv
                row = next(_csv.reader([line]))
                if len(row) < 2:
                    continue
                symbol = row[sym_idx].strip().upper()
                if not symbol:
                    continue
                etf_flag = row[etf_idx].strip().upper() if len(row) > etf_idx else ""
                if etf_flag == "Y":
                    continue
                if any(c in symbol for c in (".", "+", "-", "^", "=", "/")):
                    continue
                if symbol.startswith("$") or " " in symbol:
                    continue
                if len(symbol) > 4 and symbol[-1] in _SPECIAL_SUFFIX_CHARS and len(symbol[:-1]) >= 4:
                    continue
                if symbol.lower().endswith("test"):
                    continue
                nasdaq_tickers.append(symbol)
            logger.info(f"DataHub fallback: {len(nasdaq_tickers)} NASDAQ tickers loaded.")
        except Exception as e2:
            logger.warning(f"DataHub fallback also failed: {e2}")

    # ── Source 2: Other-listed securities (NYSE, ARCA, BATS, etc.) ────────────
    other_tickers: list[str] = []
    try:
        url2 = "https://ftp.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"
        logger.info(f"Fetching other-listed securities from {url2} ...")
        resp2 = requests.get(url2, timeout=20)
        resp2.raise_for_status()
        other_tickers = _parse_nasdaqtrader_file(resp2.text, "otherlisted")
        logger.info(f"otherlisted.txt: {len(other_tickers)} common-stock symbols loaded.")
    except Exception as e:
        logger.warning(f"otherlisted.txt fetch failed: {e}")

    # ── Merge, deduplicate, validate ─────────────────────────────────────────
    seen: set[str] = set()
    merged: list[str] = []
    for t in nasdaq_tickers + other_tickers:
        if t not in seen:
            seen.add(t)
            merged.append(t)

    if len(merged) < 100:
        logger.warning(
            f"Only {len(merged)} tickers after merge — suspiciously low. "
            f"Falling back to curated universe ({len(_FALLBACK_UNIVERSE)} tickers)."
        )
        return _FALLBACK_UNIVERSE

    _nasdaq_ticker_cache = merged
    _nasdaq_ticker_fetched_at = datetime.now(timezone.utc)
    logger.info(
        f"\u2705 Full ticker universe ready: {len(merged)} unique symbols "
        f"({len(nasdaq_tickers)} NASDAQ + {len(other_tickers)} other, deduplicated)."
    )
    return merged


# ─── News fetching ────────────────────────────────────────────────────────────

def fetch_news_for_ticker(ticker: str) -> list[dict]:
    """Fetch recent news articles for a given ticker via NewsAPI."""
    if not NEWS_API_KEY:
        logger.warning("NEWS_API_KEY not set, skipping news fetch")
        return []
    try:
        url = "https://newsapi.org/v2/everything"
        params = {
            "q": f"{ticker} stock",
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": 5,
            "apiKey": NEWS_API_KEY,
        }
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code == 429:
            logger.warning(f"NewsAPI rate limit hit on {ticker} — stopping ticker news fetches.")
            return None  # Signal to caller to stop fetching
        resp.raise_for_status()
        data = resp.json()
        articles = data.get("articles", [])
        return [
            {
                "ticker": ticker,
                "title": a.get("title", ""),
                "description": a.get("description", ""),
                "publishedAt": a.get("publishedAt", ""),
                "source": a.get("source", {}).get("name", ""),
            }
            for a in articles
            if a.get("title")
        ]
    except Exception as e:
        logger.error(f"Failed to fetch news for {ticker}: {e}")
        return []


def fetch_top_movers_news() -> list[dict]:
    """Fetch broad NASDAQ market-moving news from top headlines."""
    if not NEWS_API_KEY:
        return []
    try:
        url = "https://newsapi.org/v2/top-headlines"
        params = {
            "category": "business",
            "country": "us",
            "pageSize": 30,
            "apiKey": NEWS_API_KEY,
        }
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return data.get("articles", [])
    except Exception as e:
        logger.error(f"Failed to fetch top movers news: {e}")
        return []


# ─── Technical Analysis via yfinance ──────────────────────────────────────────

def _compute_rsi(closes, period: int = 14) -> float | None:
    """Compute RSI from a pandas Series of closing prices."""
    if closes is None or len(closes) < period + 1:
        return None
    delta = closes.diff()
    gain = delta.where(delta > 0, 0.0).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(window=period).mean()
    last_gain = gain.iloc[-1]
    last_loss = loss.iloc[-1]
    if last_loss == 0:
        return 100.0
    rs = last_gain / last_loss
    return round(100 - (100 / (1 + rs)), 2)


def _fetch_technicals_for_ticker(ticker: str) -> dict | None:
    """Fetch price history and compute technical indicators for one ticker.

    Includes volatility metrics (ATR%, daily range, consecutive up days, etc.)
    to support the low-volatility steady-uptrend stock selection strategy.
    """
    try:
        tk = yf.Ticker(ticker)
        # 3-month daily data for trend detection, moving averages, and RSI
        hist = tk.history(period="3mo", interval="1d")
        if hist.empty or len(hist) < 5:
            return None

        closes  = hist["Close"]
        highs   = hist["High"]
        lows    = hist["Low"]
        volumes = hist["Volume"]
        latest_close = float(closes.iloc[-1])
        prev_close   = float(closes.iloc[-2]) if len(closes) >= 2 else latest_close

        # Moving averages
        sma_5  = float(closes.rolling(5).mean().iloc[-1])  if len(closes) >= 5  else None
        sma_10 = float(closes.rolling(10).mean().iloc[-1]) if len(closes) >= 10 else None
        sma_20 = float(closes.rolling(20).mean().iloc[-1]) if len(closes) >= 20 else None
        sma_50 = float(closes.rolling(50).mean().iloc[-1]) if len(closes) >= 50 else None

        # EMAs
        ema_8  = float(closes.ewm(span=8,  adjust=False).mean().iloc[-1]) if len(closes) >= 8  else None
        ema_21 = float(closes.ewm(span=21, adjust=False).mean().iloc[-1]) if len(closes) >= 21 else None

        # RSI
        rsi = _compute_rsi(closes)

        # MACD (12, 26, 9)
        macd_val = macd_signal = None
        if len(closes) >= 26:
            ema12 = closes.ewm(span=12, adjust=False).mean()
            ema26 = closes.ewm(span=26, adjust=False).mean()
            macd_line   = ema12 - ema26
            signal_line = macd_line.ewm(span=9, adjust=False).mean()
            macd_val    = round(float(macd_line.iloc[-1]),   4)
            macd_signal = round(float(signal_line.iloc[-1]), 4)

        # Volume — 10-day AND 20-day average for relative volume
        avg_vol_10 = float(volumes.rolling(10).mean().iloc[-1]) if len(volumes) >= 10 else None
        avg_vol_20 = float(volumes.rolling(20).mean().iloc[-1]) if len(volumes) >= 20 else None
        latest_vol  = float(volumes.iloc[-1])

        vol_ratio_10 = round(latest_vol / avg_vol_10, 2) if avg_vol_10 and avg_vol_10 > 0 else None
        vol_ratio_20 = round(latest_vol / avg_vol_20, 2) if avg_vol_20 and avg_vol_20 > 0 else None

        # Average daily volume (20-day) — used for liquidity screening
        avg_daily_vol_20 = round(avg_vol_20, 0) if avg_vol_20 else None

        # Day change & momentum
        day_change_pct = round((latest_close - prev_close) / prev_close * 100, 2) if prev_close else 0
        mom_5d  = round((latest_close / float(closes.iloc[-6])  - 1) * 100, 2) if len(closes) >= 6  else None
        mom_10d = round((latest_close / float(closes.iloc[-11]) - 1) * 100, 2) if len(closes) >= 11 else None
        mom_20d = round((latest_close / float(closes.iloc[-21]) - 1) * 100, 2) if len(closes) >= 21 else None

        # ── Volatility metrics ─────────────────────────────────────────────────
        # ATR (14-day Average True Range) as % of current price.
        # High ATR% = high daily swing = volatile stock → bad for our strategy.
        atr_pct: float | None = None
        try:
            tr_list = []
            for i in range(1, min(15, len(closes))):
                h = float(highs.iloc[-i])
                l = float(lows.iloc[-i])
                c_prev = float(closes.iloc[-(i + 1)])
                true_range = max(h - l, abs(h - c_prev), abs(l - c_prev))
                tr_list.append(true_range)
            if tr_list and latest_close > 0:
                atr_pct = round(sum(tr_list) / len(tr_list) / latest_close * 100, 2)
        except Exception:
            pass

        # Average daily high-low range as % of close (10-day window).
        # Smaller = more stable price action.
        daily_range_avg_pct: float | None = None
        try:
            n = min(10, len(closes))
            ranges = [
                (float(highs.iloc[-i]) - float(lows.iloc[-i])) / float(closes.iloc[-i]) * 100
                for i in range(1, n + 1)
                if float(closes.iloc[-i]) > 0
            ]
            if ranges:
                daily_range_avg_pct = round(sum(ranges) / len(ranges), 2)
        except Exception:
            pass

        # Number of consecutive days the stock closed UP (streak of green candles).
        # A long positive streak signals a calm, steady uptrend.
        consec_up_days = 0
        try:
            for i in range(1, min(15, len(closes))):
                if float(closes.iloc[-i]) > float(closes.iloc[-(i + 1)]):
                    consec_up_days += 1
                else:
                    break
        except Exception:
            pass

        # Worst single-day percentage drop in the last 5 trading days.
        # A large single-day drop flags a volatile / trend-breaking stock.
        max_daily_drop_5d: float | None = None
        try:
            drops = [
                (float(closes.iloc[-i]) - float(closes.iloc[-(i + 1)])) / float(closes.iloc[-(i + 1)]) * 100
                for i in range(1, min(6, len(closes)))
                if float(closes.iloc[-(i + 1)]) > 0
            ]
            if drops:
                max_daily_drop_5d = round(min(drops), 2)  # most negative = worst day
        except Exception:
            pass

        # Percentage of the last 20 trading days that closed positive.
        # High % = consistent bullish behaviour (not whipsawing).
        pct_days_positive_20d: float | None = None
        try:
            n = min(20, len(closes) - 1)
            if n > 0:
                up_days = sum(
                    1 for i in range(1, n + 1)
                    if float(closes.iloc[-i]) > float(closes.iloc[-(i + 1)])
                )
                pct_days_positive_20d = round(up_days / n * 100, 1)
        except Exception:
            pass

        # Check for earnings in the upcoming week via yfinance calendar
        earnings_this_week = False
        try:
            cal = tk.calendar
            if cal is not None and not cal.empty:
                # calendar index may include 'Earnings Date'
                if "Earnings Date" in cal.index:
                    earn_date = cal.loc["Earnings Date"].iloc[0]
                    if hasattr(earn_date, "date"):
                        earn_date = earn_date.date()
                    today = datetime.now(timezone.utc).date()
                    delta_days = (earn_date - today).days
                    earnings_this_week = 0 <= delta_days <= 7
        except Exception:
            pass

        return {
            "ticker": ticker,
            "price": round(latest_close, 2),
            "prev_close": round(prev_close, 2),
            "day_change_pct": day_change_pct,
            "mom_5d": mom_5d,
            "mom_10d": mom_10d,
            "mom_20d": mom_20d,
            "sma_5":  round(sma_5,  2) if sma_5  else None,
            "sma_10": round(sma_10, 2) if sma_10 else None,
            "sma_20": round(sma_20, 2) if sma_20 else None,
            "sma_50": round(sma_50, 2) if sma_50 else None,
            "ema_8":  round(ema_8,  2) if ema_8  else None,
            "ema_21": round(ema_21, 2) if ema_21 else None,
            "rsi_14": rsi,
            "macd": macd_val,
            "macd_signal": macd_signal,
            "volume": int(latest_vol),
            "avg_daily_vol_20": avg_daily_vol_20,         # 20-day avg daily volume (liquidity check)
            "vol_vs_avg_10": vol_ratio_10,                 # Relative volume vs 10-day avg
            "vol_vs_avg_20": vol_ratio_20,                 # Relative volume vs 20-day avg
            # ── Volatility & stability metrics ───────────────────────────────
            "atr_pct": atr_pct,                            # ATR as % of price (14-day) — lower = more stable
            "daily_range_avg_pct": daily_range_avg_pct,   # Avg daily H-L range % (10-day)
            "consec_up_days": consec_up_days,              # Consecutive green close days
            "max_daily_drop_5d": max_daily_drop_5d,        # Worst single-day % drop in last 5 days
            "pct_days_positive_20d": pct_days_positive_20d,  # % of last 20 days that were positive closes
            "earnings_this_week": earnings_this_week,
        }
    except Exception as e:
        logger.debug(f"Technical fetch failed for {ticker}: {e}")
        return None


def fetch_technicals_batch(tickers: list[str], max_workers: int = 10) -> list[dict]:
    """Fetch technical indicators for a batch of tickers in parallel."""
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_fetch_technicals_for_ticker, t): t for t in tickers}
        for future in concurrent.futures.as_completed(futures):
            data = future.result()
            if data:
                results.append(data)
    logger.info(f"Fetched technicals for {len(results)}/{len(tickers)} tickers.")
    return results


# ─── Market Regime & Pre-Filtering ────────────────────────────────────────────

def check_market_regime() -> dict:
    """Check overall NASDAQ market health via QQQ ETF."""
    try:
        qqq = yf.Ticker("QQQ")
        hist = qqq.history(period="1mo", interval="1d")

        regime = "unknown"
        latest = change_3d = change_5d = sma_20 = 0.0

        if not hist.empty and len(hist) >= 5:
            closes  = hist["Close"]
            latest  = float(closes.iloc[-1])
            change_3d = round((latest / float(closes.iloc[-4]) - 1) * 100, 2) if len(closes) >= 4 else 0
            change_5d = round((latest / float(closes.iloc[-6]) - 1) * 100, 2) if len(closes) >= 6 else 0
            sma_20  = float(closes.rolling(20).mean().iloc[-1]) if len(closes) >= 20 else latest

            if change_3d < -3.0 or (change_5d < -5.0 and latest < sma_20):
                regime = "bearish"
            elif change_3d > 0.5 and latest > sma_20:
                regime = "bullish"
            else:
                regime = "neutral"

        sectors = {"XLK": "Tech", "XLV": "Healthcare", "XLY": "Consumer", "XLC": "Comm"}
        sector_perf: dict[str, float] = {}
        try:
            sector_data = yf.download(
                list(sectors.keys()), period="10d", interval="1d",
                group_by="ticker", progress=False
            )
            if not sector_data.empty:
                for etf, name in sectors.items():
                    try:
                        df = sector_data[etf] if len(sectors) > 1 else sector_data
                        closes_etf = df["Close"].dropna()
                        if len(closes_etf) >= 6:
                            perf = (float(closes_etf.iloc[-1]) / float(closes_etf.iloc[-6]) - 1) * 100
                            sector_perf[name] = round(perf, 2)
                    except Exception:
                        continue
        except Exception as e:
            logger.error(f"Sector perf check failed: {e}")

        strongest_sectors = sorted(sector_perf.items(), key=lambda x: x[1], reverse=True)[:2]
        sector_str = ", ".join([f"{n} ({p}%)" for n, p in strongest_sectors]) if strongest_sectors else "N/A"

        return {
            "regime": regime,
            "qqq_price": round(latest, 2) if latest else 0.0,
            "qqq_change_3d": change_3d,
            "qqq_change_5d": change_5d,
            "qqq_above_sma20": latest > sma_20 if latest else False,
            "strongest_sectors": sector_str,
        }
    except Exception as e:
        logger.error(f"Market regime check failed: {e}")
        return {"regime": "unknown", "qqq_change_3d": 0, "qqq_change_5d": 0}


def pre_filter_candidates(technicals: list[dict]) -> list[dict]:
    """
    Remove stocks that are obviously unsuitable before sending to AI.

    Strategy focus: LOW-VOLATILITY, STEADY UPTREND stocks only.
    We want stocks that go up gently or stay flat — NOT volatile movers.

    Rejection criteria (all hard stops):
    - Average daily volume < 50,000 shares → liquidity risk at sell time
    - Earnings this week → too unpredictable / binary event risk
    - 5-day momentum > +20% → already ran, likely to pull back
    - Price well below both SMA-20 and SMA-50 (> 3%) → confirmed downtrend
    - Heavy negative momentum on both timeframes → falling knife
    - RSI > 85 → extremely overbought with high mean-reversion risk
    - ATR% > 5% → too volatile (stock swings ±5%+ per day, will hit stop-loss fast)
    - Worst single-day drop in last 5 days < -4% → recent violent move (unstable)
    - Stock currently below SMA-5 AND momentum negative → actively declining right now
    """
    filtered = []
    rejected = []

    for t in technicals:
        ticker   = t["ticker"]
        price    = t.get("price", 0)
        sma_5    = t.get("sma_5")
        sma_20   = t.get("sma_20")
        sma_50   = t.get("sma_50")
        rsi      = t.get("rsi_14")
        mom_5d   = t.get("mom_5d")
        mom_20d  = t.get("mom_20d")
        avg_vol  = t.get("avg_daily_vol_20", 0) or 0
        earnings = t.get("earnings_this_week", False)
        atr_pct  = t.get("atr_pct")
        max_drop = t.get("max_daily_drop_5d")

        # Hard reject: no valid price data (NaN or zero)
        if not price or math.isnan(price) or price <= 0:
            rejected.append(f"{ticker}(price=NaN/0)")
            continue

        # Hard reject: insufficient liquidity (< 50k avg daily volume)
        if avg_vol > 0 and avg_vol < 50_000:
            rejected.append(f"{ticker}(avg_vol={avg_vol:.0f}<50k)")
            continue

        # Hard reject: earnings this week (too binary/unpredictable)
        if earnings:
            rejected.append(f"{ticker}(earnings_this_week)")
            continue

        # Hard reject: already surged > 20% in 5 days (likely to pull back)
        if mom_5d is not None and mom_5d > 20.0:
            rejected.append(f"{ticker}(already+{mom_5d:.1f}%_in_5d)")
            continue

        # Hard reject: price WELL below both SMA-20 and SMA-50 (strong downtrend)
        if sma_20 and sma_50 and price < sma_20 * 0.97 and price < sma_50 * 0.97:
            rejected.append(f"{ticker}(well_below_SMA20&50)")
            continue

        # Hard reject: heavy negative momentum on both timeframes (falling knife)
        if mom_5d is not None and mom_20d is not None:
            if mom_5d < -5.0 and mom_20d < -8.0:
                rejected.append(f"{ticker}(downtrend:5d={mom_5d}%,20d={mom_20d}%)")
                continue

        # Hard reject: extremely overbought
        if rsi and rsi > 85:
            rejected.append(f"{ticker}(overbought_RSI={rsi})")
            continue

        # ── NEW: Volatility hard-rejects ─────────────────────────────────────
        # Hard reject: ATR > 5% of price — stock swings too much per day.
        # A 3% stop-loss has zero buffer against a stock that moves ±5%/day.
        if atr_pct is not None and atr_pct > 5.0:
            rejected.append(f"{ticker}(atr_pct={atr_pct}%>5%)")
            continue

        # Hard reject: stock had a violent single-day drop of more than -4%
        # in the last 5 days — signals instability and potential downtrend.
        if max_drop is not None and max_drop < -4.0:
            rejected.append(f"{ticker}(max_drop_5d={max_drop:.1f}%<-4%)")
            continue

        # Hard reject: stock is below its 5-day SMA AND has negative 5-day momentum
        # — it is actively declining right now, do not buy into a falling stock.
        if sma_5 and price < sma_5 * 0.99 and mom_5d is not None and mom_5d < -2.0:
            rejected.append(f"{ticker}(below_SMA5_and_declining:mom5d={mom_5d}%)")
            continue

        filtered.append(t)

    if rejected:
        logger.info(f"Pre-filter rejected {len(rejected)} ticker(s): {', '.join(rejected[:20])}")
    logger.info(f"Pre-filter passed {len(filtered)}/{len(technicals)} tickers.")
    return filtered


def verify_ticker_momentum(ticker: str) -> bool:
    """Pre-buy volatility and momentum gate.

    Rejects stocks that are:
    - Actively falling (down > 3% over last 3 days)
    - Too volatile for a 3% stop-loss (any single day > ±4% in last 5 days)
    - Currently below their 5-day SMA (declining right now)
    - Down on the most recent session (price action going the wrong way)
    """
    try:
        tk = yf.Ticker(ticker)
        hist = tk.history(period="5d", interval="1d")
        if hist.empty or len(hist) < 2:
            return True

        closes = hist["Close"]
        highs  = hist["High"]
        lows   = hist["Low"]
        latest = float(closes.iloc[-1])

        # ── Check 1: 3-day trend — reject if down > 3% ─────────────────────
        three_days_ago = float(closes.iloc[-3]) if len(closes) >= 3 else float(closes.iloc[0])
        change_3d = (latest / three_days_ago - 1) * 100
        if change_3d < -3.0:
            logger.warning(
                f"Pre-buy check FAILED for {ticker}: down {change_3d:.1f}% over 3 sessions (threshold: -3%)"
            )
            return False

        # ── Check 2: Single-day volatility — reject high-swing stocks ──────
        # If ANY day in the last 5 had a > ±4% intra-day swing, the stock is
        # too volatile for a 3% stop-loss. We'll hit it within hours.
        for i in range(len(closes)):
            try:
                c = float(closes.iloc[i])
                h = float(highs.iloc[i])
                l = float(lows.iloc[i])
                if c > 0:
                    intraday_range_pct = (h - l) / c * 100
                    if intraday_range_pct > 6.0:  # High-low range > 6% = very volatile day
                        logger.warning(
                            f"Pre-buy check FAILED for {ticker}: high intra-day range {intraday_range_pct:.1f}% "
                            f"on day {i} (H={h:.2f}, L={l:.2f}, C={c:.2f}). Too volatile."
                        )
                        return False
            except Exception:
                continue

        # ── Check 3: Recent session was a down-day ──────────────────────────
        if len(closes) >= 2:
            prev = float(closes.iloc[-2])
            day_change = (latest - prev) / prev * 100 if prev > 0 else 0
            if day_change < -2.0:
                logger.warning(
                    f"Pre-buy check FAILED for {ticker}: most recent session closed down {day_change:.1f}%."
                )
                return False

        # ── Check 4: Price below 5-day SMA (actively declining) ────────────
        if len(closes) >= 5:
            sma_5 = float(closes.rolling(5).mean().iloc[-1])
            if latest < sma_5 * 0.98:  # More than 2% below SMA-5
                logger.warning(
                    f"Pre-buy check FAILED for {ticker}: price ${latest:.2f} is more than 2% "
                    f"below 5-day SMA ${sma_5:.2f} — actively declining."
                )
                return False

        return True
    except Exception as e:
        logger.warning(f"Pre-buy momentum check error for {ticker}: {e}")
        return True  # Fail open — don't block if we can't fetch data


def _quick_screen_universe(
    universe: list[str],
    top_n: int = 75,
) -> list[tuple[str, float]]:
    """
    Dynamically screen the full ticker universe to find today's best candidates.

    Strategy focus: LOW-VOLATILITY, STEADY UPTREND stocks.
    We want stocks that are gradually drifting upward, NOT volatile short-term movers.

    Scoring philosophy:
    - HEAVILY PENALISE high ATR/volatility (stocks that swing ±4%+ per day hit stop-losses)
    - REWARD consistent uptrend alignment (price above SMA-5, SMA-10, SMA-20 all together)
    - REWARD sustained multi-week momentum (mom_20d) over explosive short-term spikes
    - REWARD consecutive positive close days (steady drift up)
    - PENALISE large single-day moves (even if positive — they signal volatility)
    - Keep liquidity gate (avg vol >= 50k shares/day)
    """
    logger.info(f"Dynamic screening {len(universe)} tickers to find top {top_n} (low-vol uptrend focus)...")

    scores: list[tuple[str, float]] = []
    BATCH_SIZE = 500  # yfinance handles batches of ~500 well

    universe_batches = [
        universe[i:i + BATCH_SIZE] for i in range(0, len(universe), BATCH_SIZE)
    ]

    for batch_num, batch in enumerate(universe_batches, 1):
        logger.info(f"Screening batch {batch_num}/{len(universe_batches)} ({len(batch)} tickers)...")
        try:
            data = yf.download(
                batch,
                period="2mo",  # Extended to 2 months for better MA and volatility calculations
                interval="1d",
                group_by="ticker",
                threads=True,
                progress=False,
            )

            if data.empty:
                continue

            for ticker in batch:
                try:
                    if ticker not in data.columns.get_level_values(0):
                        continue
                    ticker_df = data[ticker]
                    closes  = ticker_df["Close"].dropna()
                    highs   = ticker_df["High"].dropna()
                    lows    = ticker_df["Low"].dropna()
                    volumes = ticker_df["Volume"].dropna()

                    if len(closes) < 10:
                        continue

                    latest     = float(closes.iloc[-1])
                    prev_close = float(closes.iloc[-2]) if len(closes) >= 2 else latest

                    # ── Liquidity gate — skip low-volume stocks ──────────────────
                    avg_vol_20 = float(volumes.rolling(20).mean().iloc[-1]) if len(volumes) >= 20 else 0.0
                    if avg_vol_20 < 50_000:
                        continue

                    # ── ATR% volatility gate — skip too-volatile stocks ──────────
                    # Stocks with ATR > 5% of price will regularly hit a 3% stop-loss
                    # within hours of purchase. Hard-reject them at the screener level.
                    atr_pct = None
                    try:
                        tr_list = []
                        for i in range(1, min(15, len(closes))):
                            h = float(highs.iloc[-i])
                            l = float(lows.iloc[-i])
                            c_prev = float(closes.iloc[-(i + 1)])
                            true_range = max(h - l, abs(h - c_prev), abs(l - c_prev))
                            tr_list.append(true_range)
                        if tr_list and latest > 0:
                            atr_pct = sum(tr_list) / len(tr_list) / latest * 100
                    except Exception:
                        pass

                    if atr_pct is not None and atr_pct > 5.0:
                        continue  # Too volatile — skip entirely

                    # ── Momentum metrics ─────────────────────────────────────────
                    mom_1d  = ((latest / prev_close) - 1) * 100 if prev_close > 0 else 0.0
                    mom_5d  = ((latest / float(closes.iloc[-6]))  - 1) * 100 if len(closes) >= 6  else 0.0
                    mom_10d = ((latest / float(closes.iloc[-11])) - 1) * 100 if len(closes) >= 11 else 0.0
                    mom_20d = ((latest / float(closes.iloc[-21])) - 1) * 100 if len(closes) >= 21 else 0.0

                    # Hard rejection: already up > 20% in 5 days → likely to reverse
                    if mom_5d > 20.0:
                        continue

                    # Hard rejection: worst single-day drop > 4% in last 5 days → volatile/unstable
                    try:
                        worst_drop = min(
                            (float(closes.iloc[-i]) - float(closes.iloc[-(i + 1)])) / float(closes.iloc[-(i + 1)]) * 100
                            for i in range(1, min(6, len(closes)))
                            if float(closes.iloc[-(i + 1)]) > 0
                        )
                        if worst_drop < -4.0:
                            continue
                    except Exception:
                        pass

                    # ── Trend alignment metrics ──────────────────────────────────
                    sma_5   = float(closes.rolling(5).mean().iloc[-1])  if len(closes) >= 5  else latest
                    sma_10  = float(closes.rolling(10).mean().iloc[-1]) if len(closes) >= 10 else latest
                    sma_20  = float(closes.rolling(20).mean().iloc[-1]) if len(closes) >= 20 else latest
                    ema_8   = float(closes.ewm(span=8,  adjust=False).mean().iloc[-1]) if len(closes) >= 8  else latest
                    ema_21  = float(closes.ewm(span=21, adjust=False).mean().iloc[-1]) if len(closes) >= 21 else latest

                    above_sma5  = latest > sma_5
                    above_sma10 = latest > sma_10
                    above_sma20 = latest > sma_20
                    # Full uptrend alignment: SMA-5 > SMA-10 > SMA-20 and price above all
                    fully_aligned = above_sma5 and above_sma10 and above_sma20 and sma_5 > sma_10 > sma_20
                    ema_bullish   = ema_8 > ema_21

                    rsi       = _compute_rsi(closes) or 50.0
                    vol_ratio = float(volumes.iloc[-1]) / avg_vol_20 if avg_vol_20 > 0 else 1.0

                    # ── Consecutive up-days streak ───────────────────────────────
                    consec_up = 0
                    try:
                        for i in range(1, min(15, len(closes))):
                            if float(closes.iloc[-i]) > float(closes.iloc[-(i + 1)]):
                                consec_up += 1
                            else:
                                break
                    except Exception:
                        pass

                    # ── % positive days in last 20 ───────────────────────────────
                    pct_positive_20d = 50.0
                    try:
                        n = min(20, len(closes) - 1)
                        if n > 0:
                            up_days = sum(
                                1 for i in range(1, n + 1)
                                if float(closes.iloc[-i]) > float(closes.iloc[-(i + 1)])
                            )
                            pct_positive_20d = up_days / n * 100
                    except Exception:
                        pass

                    # ── MACD quick check ─────────────────────────────────────────
                    macd_bullish = False
                    if len(closes) >= 26:
                        ema12 = closes.ewm(span=12, adjust=False).mean()
                        ema26 = closes.ewm(span=26, adjust=False).mean()
                        macd_line   = ema12 - ema26
                        signal_line = macd_line.ewm(span=9, adjust=False).mean()
                        macd_bullish = float(macd_line.iloc[-1]) > float(signal_line.iloc[-1])

                    # ══════════════════════════════════════════════════════════
                    # COMPOSITE SCORE — LOW-VOL STEADY UPTREND STRATEGY
                    # ══════════════════════════════════════════════════════════
                    score = 0.0

                    # ── Sustained momentum (slow and steady wins the race) ────
                    # Weight LONGER-TERM momentum more than short-term spikes.
                    # mom_20d captures the underlying trend; mom_1d is de-emphasised.
                    score += mom_20d * 2.0   # 20-day sustained drift (primary)
                    score += mom_10d * 1.5   # 10-day trend continuation
                    score += mom_5d  * 0.5   # 5-day (small weight — avoid spike chasers)
                    # mom_1d gets a small contribution only if it's a gentle positive day
                    if 0 < mom_1d < 2.0:
                        score += mom_1d * 0.5  # Gentle green day — slight bonus
                    elif mom_1d > 4.0:
                        score -= mom_1d * 0.5  # Big single-day spike — slight penalty

                    # ── Volatility penalty (critical for stop-loss survival) ──
                    # High ATR = high chance of hitting a 3% stop-loss intra-day.
                    if atr_pct is not None:
                        if atr_pct < 1.5:    # Very stable (e.g. large-cap blue chips)
                            score += 20
                        elif atr_pct < 2.5:  # Stable
                            score += 12
                        elif atr_pct < 3.5:  # Moderate — OK
                            score += 4
                        elif atr_pct < 4.5:  # Somewhat volatile — penalty
                            score -= 10
                        else:                # Very volatile — large penalty
                            score -= 25

                    # ── Steady uptrend alignment (key signal for our strategy) ─
                    if fully_aligned:
                        score += 25   # All MAs stacked correctly — strong signal
                    else:
                        if above_sma20:
                            score += 10
                        else:
                            score -= 15  # Below SMA-20 = downtrend
                        if above_sma10:
                            score += 5
                        if above_sma5:
                            score += 3

                    score += 8 if ema_bullish  else -4
                    score += 6 if macd_bullish else -3

                    # ── Consecutive green days (consistency bonus) ────────────
                    if consec_up >= 5:
                        score += 18   # 5+ days in a row going up
                    elif consec_up >= 3:
                        score += 10   # 3-4 days in a row
                    elif consec_up >= 1:
                        score += 4    # At least today is green
                    else:
                        score -= 5    # Closed down today — caution

                    # ── Consistency of positive days (% of 20 days) ──────────
                    if pct_positive_20d >= 70:
                        score += 15   # Very consistent bullish behaviour
                    elif pct_positive_20d >= 60:
                        score += 8
                    elif pct_positive_20d >= 50:
                        score += 2
                    else:
                        score -= 8    # More down-days than up-days recently

                    # ── RSI sweet-spot (uptrending but not overbought) ────────
                    if 45 <= rsi <= 65:
                        score += 15   # Ideal: trending up, room to run
                    elif 35 <= rsi <= 72:
                        score += 5    # Acceptable
                    elif rsi > 75:
                        score -= 15   # Overbought — likely to stall or reverse
                    else:
                        score -= 10   # Oversold — could be a falling knife

                    # ── Volume: prefer normal-to-slightly-elevated (not a spike) ─
                    # We DON'T want volume spikes here — those signal volatility.
                    # Steady moderate volume = institutional accumulation.
                    if 0.9 <= vol_ratio <= 1.5:
                        score += 10   # Normal/modest volume — healthy steady move
                    elif 1.5 < vol_ratio <= 2.5:
                        score += 5    # Slightly elevated — acceptable
                    elif vol_ratio > 2.5:
                        score -= 5    # Volume spike — more likely a volatile day
                    else:
                        score += 2    # Below-average volume — still OK for our strategy

                    # ── Core mega-cap bonus (blue chips tend to be more stable) ─
                    if ticker in CORE_TICKERS:
                        score += 8

                    scores.append((ticker, round(score, 2)))
                except Exception:
                    continue

        except Exception as e:
            logger.error(f"Batch {batch_num} screening failed: {e}")
            continue

    scores.sort(key=lambda x: x[1], reverse=True)
    hot_list = scores[:top_n]

    top10 = [(t, f"{s:.1f}") for t, s in scores[:10]]
    core_in_list = [t for t, _ in hot_list if t in CORE_TICKERS]
    logger.info(
        f"Dynamic screening complete. Screened {len(scores)} tickers. "
        f"Selected top {len(hot_list)} (low-vol uptrend strategy). "
        f"Top 10 by score: {top10} | "
        f"Core tickers in hot list: {len(core_in_list)}/{len(CORE_TICKERS)}"
    )
    logger.info(f"Full hot list: {[t for t, _ in hot_list]}")

    return hot_list


def analyse_with_gemini(
    news_data: list[dict],
    technicals: list[dict] | None = None,
    market_regime: dict | None = None,
) -> list[dict]:
    """
    Uses Gemini to analyse news + technical data and return ranked stock
    recommendations for the current trading week.

    Returns: list of {
        "ticker": str,
        "reason": str,
        "confidence": float (0–1),
        "position_size_pct": float (% of capital to allocate)
    }
    """
    if not GEMINI_API_KEY:
        logger.warning("GEMINI_API_KEY not set, skipping AI analysis")
        return []

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Trim headline blob to avoid token limits — 12KB cap
    news_json = json.dumps(news_data, indent=2)
    if len(news_json) > 12000:
        news_json = news_json[:12000] + "\n... (truncated)"

    # Build technical data section (limit to 10KB)
    tech_section = ""
    if technicals:
        tech_json = json.dumps(technicals, indent=2)
        if len(tech_json) > 10000:
            tech_json = tech_json[:10000] + "\n... (truncated)"
        tech_section = f"""
TECHNICAL DATA (real-time indicators):
{tech_json}
"""

    # Build market regime section
    regime_section = "No market regime data available."
    market_caution = ""
    if market_regime:
        regime_section = (
            f"Overall NASDAQ (QQQ) status:\n"
            f"  - 3-day change: {market_regime.get('qqq_change_3d', 'N/A')}%\n"
            f"  - 5-day change: {market_regime.get('qqq_change_5d', 'N/A')}%\n"
            f"  - QQQ above SMA-20: {market_regime.get('qqq_above_sma20', 'N/A')}\n"
            f"  - Strongest Sectors (5d perf): {market_regime.get('strongest_sectors', 'N/A')}\n"
            f"  - Regime: {market_regime.get('regime', 'unknown').upper()}"
        )
        if market_regime.get("regime") == "bearish":
            market_caution = (
                "\n⚠️ BEARISH MARKET REGIME: The broad market is weak. "
                "Minimum confidence threshold is 0.60. Still look for stocks with "
                "individual strength or catalysts that can outperform the index."
            )
        elif market_regime.get("regime") == "neutral":
            market_caution = (
                "\n📊 NEUTRAL MARKET: Minimum confidence threshold is 0.50. "
                "Recommend stocks with decent technical setups and positive catalysts."
            )

    prompt = f"""You are an elite quantitative swing-trading AI analysing NASDAQ stocks for the week of {today}.

═══ STRATEGY MANDATE ═══
Your PRIMARY OBJECTIVE is capital preservation with steady, low-risk gains.
The portfolio has been LOSING money daily because volatile, high-momentum stocks
hit the 3% stop-loss within hours of purchase. You MUST avoid this.

Target stocks that will:
  ✅ STAY around the same price or drift GENTLY UPWARD (1–5% gain over 1–5 days)
  ✅ Have LOW daily volatility — small intra-day swings (ATR < 3% of price ideally)
  ✅ Be in a stable, confirmed uptrend (price above SMA-5, SMA-10, SMA-20 all aligned)
  ✅ Have CONSISTENT recent performance (majority of days closing positive)

  ❌ DO NOT pick explosive short-term movers, meme stocks, or volatile small-caps
  ❌ DO NOT pick stocks with recent big single-day swings (even if upward)
  ❌ DO NOT pick stocks based purely on news hype — price action must confirm the stability

Think of this like picking a reliable car for a long trip — not the fastest sports car
that might spin out, but a steady vehicle that gets you there safely.

═══ TARGET PICKS ═══
Aim for 5 to 12 stocks. Prioritise quality and stability over quantity.
Fewer high-quality low-volatility picks are far better than many volatile ones.

═══ MARKET REGIME ═══
{regime_section}

═══ HARD EXCLUSION CRITERIA (disqualify entirely — no exceptions) ═══
1. ❌ Earnings announced this week (earnings_this_week = true) — binary risk, too unpredictable
2. ❌ Stock has already risen > 20% in the last 5 days (mom_5d > 20%) — exhausted, likely to reverse
3. ❌ Average daily volume < 50,000 shares (avg_daily_vol_20 < 50k) — cannot exit safely
4. ❌ Major negative news: lawsuits, earnings misses, FDA rejections, analyst downgrades
5. ❌ RSI > 80 — severely overbought, high mean-reversion risk
6. ❌ Price significantly (> 3%) below both SMA-20 AND SMA-50 — confirmed downtrend
7. ❌ ATR% > 4% — stock swings too much per day, WILL hit a 3% stop-loss within hours
8. ❌ Any single day in the last 5 had a drop of more than -4% — stock is unstable
9. ❌ Stock is currently below its SMA-5 with negative short-term momentum — actively declining

═══ PRIORITY BUY SIGNALS (ideal: 3 or more of these) ═══
1. ✅ LOW VOLATILITY — atr_pct < 2.5%, daily_range_avg_pct < 3% — stock barely wiggles
2. ✅ STRONG UPTREND ALIGNMENT — price above SMA-5 > SMA-10 > SMA-20 all stacked correctly
3. ✅ CONSISTENT POSITIVE DAYS — pct_days_positive_20d > 60% AND consec_up_days >= 2
4. ✅ SUSTAINED SLOW MOMENTUM — mom_20d > 3% AND mom_10d > 1% (gradual, not a spike)
5. ✅ RSI between 45–65 — trending up steadily, not overbought, not oversold
6. ✅ EMA-8 ABOVE EMA-21 — short-term EMAs confirm the uptrend
7. ✅ MACD line above signal line — trend continuation confirmed
8. ✅ Positive fundamental catalyst (earnings beat, product launch, analyst upgrade)
   that caused a STEADY, measured price rise (not a spike)
9. ✅ Volume at or near average (0.9x–1.5x) — institutional accumulation, not speculation

═══ WARNING SIGNS (reject or heavily discount these patterns) ═══
- Recent volume spike > 3x average (signals speculative activity, high volatility risk)
- Stock up > 5% on any single day in the last 5 days (too volatile)
- RSI > 72 (likely to stall)
- Below-average volume combined with falling price (distribution / weak demand)
- Negative or flat 20-day momentum despite recent short-term bounce (dead-cat bounce risk)

═══ ANALYSIS WEIGHTS ═══
1. Volatility & Stability (35%): atr_pct, daily_range_avg_pct, max_daily_drop_5d, consec_up_days
2. Trend Quality (30%): price vs SMA-5/10/20 alignment, EMA-8/21, MACD, pct_days_positive_20d
3. Sustained Momentum (20%): mom_20d, mom_10d (preferred), mom_5d (minor weight)
4. Risk Management (15%): liquidity, avoid binary events, RSI range, news sentiment

═══ CONFIDENCE & POSITION SIZING ═══
- 0.80–1.00: Low-vol, fully-aligned, consistent uptrend + positive catalyst → position_size_pct = 10–18%
- 0.65–0.79: Good stable setup with 3+ buy signals → position_size_pct = 7–12%
- 0.55–0.64: Decent stable setup, at least 2 signals, moderate volatility → position_size_pct = 3–7%
- Below 0.55: Do NOT recommend — insufficient confidence for capital deployment
{market_caution}
Position sizes should sum to approximately 100% across all picks.
Stable, lower-volatility picks with higher consistency deserve larger allocations.
Avoid giving large allocations to picks that only have 1 signal — spread the risk.

═══ NEWS DATA ═══
{news_json}
{tech_section}
═══ OUTPUT FORMAT ═══
Respond ONLY with a valid JSON array. No markdown fences, no explanation outside the JSON.
Each recommendation MUST reference specific volatility and stability data points (atr_pct,
consec_up_days, pct_days_positive_20d) alongside any news catalyst.
[
  {{
    "ticker": "MSFT",
    "reason": "Classic low-volatility steady uptrend. atr_pct=1.8% (very stable), price $415 above SMA-5($410)>SMA-10($405)>SMA-20($398) all stacked. consec_up_days=4, pct_days_positive_20d=70%. RSI 58 (sweet spot). EMA-8 > EMA-21, MACD bullish. mom_20d +3.2% (slow steady drift). Volume near average (1.1x). Azure cloud growth news adds mild catalyst. Ideal low-vol hold.",
    "confidence": 0.84,
    "position_size_pct": 15
  }}
]"""

    try:
        model = genai.GenerativeModel("gemini-2.5-pro")
        response = model.generate_content(prompt)
        text = response.text.strip()

        # Strip markdown code fences if present
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        text = text.strip()

        recommendations = json.loads(text)
        if not isinstance(recommendations, list):
            raise ValueError("Gemini did not return a list")

        validated = []
        for rec in recommendations:
            if isinstance(rec, dict) and "ticker" in rec and "reason" in rec:
                validated.append({
                    "ticker": str(rec["ticker"]).upper().strip(),
                    "reason": str(rec.get("reason", "")),
                    "confidence": float(rec.get("confidence", 0.5)),
                    "position_size_pct": float(rec.get("position_size_pct", 5.0)),
                })
        validated.sort(key=lambda r: r["confidence"], reverse=True)
        return validated

    except Exception as e:
        logger.error(f"Gemini analysis failed: {e}")
        return []


def run_daily_scan() -> tuple[list[dict], list[dict]]:
    """
    Main entry point: scans the full NASDAQ market and returns AI-ranked stock picks
    PLUS the pre-filtered screener candidates for use as a guaranteed fallback.

    Returns a 2-tuple:
      (ai_recommendations, screened_candidates)

      ai_recommendations  — Gemini-ranked picks, may be empty if AI fails / returns nothing.
      screened_candidates — Pre-filtered technical candidates ranked by composite score.
                            Always populated (used as guaranteed buy fallback).

    Pipeline:
    1. Fetch the complete NASDAQ ticker universe (dynamic, ~3,300+ tickers)
    2. Fetch broad market headlines
    3. Check market regime (QQQ health)
    4. Dynamic-screen full universe → best 75 by composite momentum/volume score
    5. Fetch news for those 75 (highest-scored first)
    6. Fetch detailed technicals for the 75
    7. Pre-filter obvious losers (low volume, earnings this week, already ran 20%+)
    8. Send everything to Gemini for final AI ranking
    9. Return AI picks + pre-filtered screener list as fallback
    """
    logger.info("═══ Starting daily market scan ═══")

    # Step 1: Fetch complete NASDAQ universe
    nasdaq_tickers = fetch_full_nasdaq_tickers()
    logger.info(f"NASDAQ universe: {len(nasdaq_tickers)} tickers loaded.")

    all_news = []

    # Step 2: Fetch broad market / business headlines
    top_news = fetch_top_movers_news()
    all_news.extend([
        {
            "ticker": "MARKET",
            "title": a.get("title", ""),
            "description": a.get("description", ""),
            "publishedAt": a.get("publishedAt", ""),
            "source": a.get("source", {}).get("name", ""),
        }
        for a in top_news if a.get("title")
    ])

    # Step 3: Check market regime (QQQ trend)
    logger.info("Checking market regime (QQQ)...")
    market_regime = check_market_regime()
    regime = market_regime.get("regime", "unknown")
    logger.info(
        f"Market regime: {regime.upper()} | QQQ 3d: {market_regime.get('qqq_change_3d')}%, "
        f"5d: {market_regime.get('qqq_change_5d')}%"
    )

    if regime == "bearish":
        logger.warning("⚠️ Bearish market detected — AI will apply stricter filters.")

    # Step 4: Dynamic screen — find today's best 75 stocks from full NASDAQ universe
    scored_hot_list = _quick_screen_universe(nasdaq_tickers, top_n=75)
    hot_tickers = [t for t, _ in scored_hot_list]

    logger.info(
        f"Hot list: {len(hot_tickers)} best stocks selected. "
        f"Score range: {scored_hot_list[0][1] if scored_hot_list else 'N/A'} → "
        f"{scored_hot_list[-1][1] if scored_hot_list else 'N/A'}"
    )

    # Step 5: Fetch individual ticker news — highest-scored tickers first
    logger.info(f"Fetching news for {len(hot_tickers)} hot-list tickers (best-first)...")
    rate_limited = False
    news_fetched_count = 0
    for ticker in hot_tickers:
        if rate_limited:
            break
        articles = fetch_news_for_ticker(ticker)
        if articles is None:
            rate_limited = True
            logger.warning(
                f"NewsAPI rate limit reached after {news_fetched_count} tickers. "
                f"Proceeding with partial news data."
            )
            break
        all_news.extend(articles)
        news_fetched_count += 1
        time.sleep(0.25)  # 250ms gap → ~4 req/s, well under NewsAPI limits

    logger.info(f"Fetched {len(all_news)} news articles across {news_fetched_count} tickers.")

    # Step 6: Fetch detailed technical indicators for the hot list
    logger.info(f"Fetching detailed technicals for {len(hot_tickers)} tickers...")
    technicals = fetch_technicals_batch(hot_tickers, max_workers=10)

    # Step 7: Pre-filter — remove obvious disqualifications before AI analysis
    filtered_technicals = pre_filter_candidates(technicals)

    # Build the screener fallback list — pre-filtered candidates ranked by score.
    # The scored_hot_list preserves composite-score order; we match against
    # filtered_technicals to honour the same exclusion rules.
    filtered_tickers_set = {t["ticker"] for t in filtered_technicals}
    screened_candidates: list[dict] = []
    for ticker, score in scored_hot_list:
        if ticker in filtered_tickers_set:
            # Find the matching technical dict for this ticker
            tech = next((t for t in filtered_technicals if t["ticker"] == ticker), {})
            screened_candidates.append({
                "ticker": ticker,
                "score": round(score, 2),
                "reason": (
                    f"Top screener pick (score={score:.1f}). "
                    f"Price=${tech.get('price', '?')}, "
                    f"RSI={tech.get('rsi_14', '?')}, "
                    f"5d mom={tech.get('mom_5d', '?')}%, "
                    f"vol vs 20d avg={tech.get('vol_vs_avg_20', '?')}x. "
                    f"No AI catalyst data — selected by technical screener as best available."
                ),
                "confidence": 0.0,         # Indicates screener pick, not AI pick
                "position_size_pct": 0.0,  # Will be set to equal split in jobs.py
            })

    logger.info(
        f"Sending {len(all_news)} articles + {len(filtered_technicals)} filtered technical "
        f"profiles (from {len(technicals)} total) to Gemini ({regime} regime)..."
    )

    # Step 8: AI analysis with news + filtered technicals + market context
    recommendations = analyse_with_gemini(all_news, filtered_technicals, market_regime)

    picks = [f"{r['ticker']}({r['confidence']:.0%})" for r in recommendations]
    logger.info(f"═══ Scan complete. AI: {len(recommendations)} pick(s): {picks} | "
                f"Screener fallback: {len(screened_candidates)} candidates ═══")

    return recommendations, screened_candidates
