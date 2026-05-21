import os
import io
import json
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


def fetch_full_nasdaq_tickers() -> list[str]:
    """
    Fetch the complete list of NASDAQ-listed tickers from NASDAQ's public FTP directory.

    Source: ftp.nasdaqtrader.com/symboldirectory/nasdaqlisted.txt
    This is a free, unauthenticated text file updated each trading day.
    Falls back to the curated _FALLBACK_UNIVERSE list if the fetch fails.

    Filters applied:
    - Exclude test securities (symbol ends with 'test' or starts with '$')
    - Exclude ETFs (market_category not in ['Q', 'G', 'S', 'M'])
    - Exclude special warrant/preferred symbols (contain '.', '+', '-')
    Returns at most 5,000 tickers; in practice NASDAQ has ~3,300 common stocks.
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

    try:
        url = "https://ftp.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        lines = resp.text.strip().splitlines()

        tickers: list[str] = []
        for line in lines[1:]:  # Skip header row
            parts = line.split("|")
            if len(parts) < 3:
                continue
            symbol = parts[0].strip()
            etf_flag = parts[6].strip() if len(parts) > 6 else ""

            # Skip ETFs, test symbols, special characters
            if not symbol:
                continue
            if "." in symbol or "+" in symbol or "$" in symbol:
                continue
            if symbol.lower().endswith("test"):
                continue
            if etf_flag.upper() == "Y":  # ETF flag
                continue
            tickers.append(symbol)

        if len(tickers) < 100:
            raise ValueError(f"Suspiciously few tickers returned: {len(tickers)}")

        _nasdaq_ticker_cache = tickers
        _nasdaq_ticker_fetched_at = datetime.now(timezone.utc)
        logger.info(f"Fetched {len(tickers)} NASDAQ tickers from nasdaqtrader.com.")
        return tickers

    except Exception as e:
        logger.warning(f"Failed to fetch NASDAQ ticker list ({e}). Using fallback universe "
                       f"({len(_FALLBACK_UNIVERSE)} tickers).")
        return _FALLBACK_UNIVERSE


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
    """Fetch price history and compute technical indicators for one ticker."""
    try:
        tk = yf.Ticker(ticker)
        # 3-month daily data for trend detection, moving averages, and RSI
        hist = tk.history(period="3mo", interval="1d")
        if hist.empty or len(hist) < 5:
            return None

        closes = hist["Close"]
        volumes = hist["Volume"]
        latest_close = float(closes.iloc[-1])
        prev_close = float(closes.iloc[-2]) if len(closes) >= 2 else latest_close

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
        mom_20d = round((latest_close / float(closes.iloc[-21]) - 1) * 100, 2) if len(closes) >= 21 else None

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
            "avg_daily_vol_20": avg_daily_vol_20,   # 20-day avg daily volume (liquidity check)
            "vol_vs_avg_10": vol_ratio_10,           # Relative volume vs 10-day avg
            "vol_vs_avg_20": vol_ratio_20,           # Relative volume vs 20-day avg (key signal)
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

    Rejection criteria (all hard stops):
    - Average daily volume < 50,000 shares → liquidity risk at sell time
    - Earnings this week → too unpredictable
    - 5-day momentum > +20% → likely exhausted, due for pullback
    - Price well below both SMA-20 and SMA-50 (> 3%) → confirmed downtrend
    - Heavy negative momentum on both timeframes → falling knife
    - RSI > 85 → extremely overbought

    Note: Penny stocks (price < $1) are NOT filtered here — they are handled
    by the volume check (very low-volume pennies won't pass the 50k threshold).
    """
    filtered = []
    rejected = []

    for t in technicals:
        ticker  = t["ticker"]
        price   = t.get("price", 0)
        sma_20  = t.get("sma_20")
        sma_50  = t.get("sma_50")
        rsi     = t.get("rsi_14")
        mom_5d  = t.get("mom_5d")
        mom_20d = t.get("mom_20d")
        avg_vol = t.get("avg_daily_vol_20", 0) or 0
        earnings = t.get("earnings_this_week", False)

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

        # Reject: price WELL below both SMA-20 and SMA-50 (strong downtrend)
        if sma_20 and sma_50 and price < sma_20 * 0.97 and price < sma_50 * 0.97:
            rejected.append(f"{ticker}(well_below_SMA20&50)")
            continue

        # Reject: heavy negative momentum on both timeframes
        if mom_5d is not None and mom_20d is not None:
            if mom_5d < -5.0 and mom_20d < -8.0:
                rejected.append(f"{ticker}(downtrend:5d={mom_5d}%,20d={mom_20d}%)")
                continue

        # Reject: extremely overbought
        if rsi and rsi > 85:
            rejected.append(f"{ticker}(overbought_RSI={rsi})")
            continue

        filtered.append(t)

    if rejected:
        logger.info(f"Pre-filter rejected {len(rejected)} ticker(s): {', '.join(rejected[:20])}")
    logger.info(f"Pre-filter passed {len(filtered)}/{len(technicals)} tickers.")
    return filtered


def verify_ticker_momentum(ticker: str) -> bool:
    """Quick pre-buy check: reject stocks that are actively crashing."""
    try:
        tk = yf.Ticker(ticker)
        hist = tk.history(period="5d", interval="1d")
        if hist.empty or len(hist) < 3:
            return True

        closes = hist["Close"]
        latest = float(closes.iloc[-1])
        three_days_ago = float(closes.iloc[0]) if len(closes) >= 3 else latest
        change = (latest / three_days_ago - 1) * 100

        if change < -5.0:
            logger.warning(f"Pre-buy check FAILED for {ticker}: down {change:.1f}% over recent sessions")
            return False
        return True
    except Exception as e:
        logger.warning(f"Pre-buy momentum check error for {ticker}: {e}")
        return True


def _quick_screen_universe(
    universe: list[str],
    top_n: int = 75,
) -> list[tuple[str, float]]:
    """
    Dynamically screen the full ticker universe to find today's best candidates.

    Uses yfinance batch download to fetch 1-month daily data for every ticker,
    compute quick technical metrics, and rank them by a composite score.

    Changes from previous version:
    - Accepts the full NASDAQ universe (~3,300+ tickers); processes in batches
      to stay within yfinance limits.
    - Removed the penny-stock price filter (price < $5 skip) — liquidity is now
      checked via avg_daily_vol_20 instead.
    - Added avg_vol_20 check: skip if < 50,000 shares/day (liquidity risk).
    - Returns top_n=75 instead of 50 to give Gemini more candidates.
    """
    logger.info(f"Dynamic screening {len(universe)} tickers to find top {top_n}...")

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
                period="1mo",
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
                    volumes = ticker_df["Volume"].dropna()

                    if len(closes) < 10:
                        continue

                    latest    = float(closes.iloc[-1])
                    prev_close = float(closes.iloc[-2]) if len(closes) >= 2 else latest

                    # ── Liquidity gate — skip low-volume stocks ──
                    avg_vol_20 = float(volumes.rolling(20).mean().iloc[-1]) if len(volumes) >= 20 else 0.0
                    if avg_vol_20 < 50_000:
                        continue

                    # ── Quick metrics ──
                    mom_1d  = ((latest / prev_close) - 1) * 100 if prev_close > 0 else 0.0
                    mom_5d  = ((latest / float(closes.iloc[-6]))  - 1) * 100 if len(closes) >= 6  else 0.0
                    mom_10d = ((latest / float(closes.iloc[-11])) - 1) * 100 if len(closes) >= 11 else 0.0
                    ema_8   = float(closes.ewm(span=8,  adjust=False).mean().iloc[-1]) if len(closes) >= 8  else latest
                    ema_21  = float(closes.ewm(span=21, adjust=False).mean().iloc[-1]) if len(closes) >= 21 else latest
                    sma_10  = float(closes.rolling(10).mean().iloc[-1]) if len(closes) >= 10 else latest
                    sma_20  = float(closes.rolling(20).mean().iloc[-1]) if len(closes) >= 20 else latest
                    above_sma10 = latest > sma_10
                    above_sma20 = latest > sma_20
                    ema_bullish = ema_8 > ema_21
                    rsi = _compute_rsi(closes) or 50.0
                    vol_ratio = float(volumes.iloc[-1]) / avg_vol_20 if avg_vol_20 > 0 else 1.0

                    # ── MACD quick check ──
                    macd_bullish = False
                    if len(closes) >= 26:
                        ema12 = closes.ewm(span=12, adjust=False).mean()
                        ema26 = closes.ewm(span=26, adjust=False).mean()
                        macd_line   = ema12 - ema26
                        signal_line = macd_line.ewm(span=9, adjust=False).mean()
                        macd_bullish = float(macd_line.iloc[-1]) > float(signal_line.iloc[-1])

                    # ── Composite score ──
                    score = 0.0

                    # Momentum (biggest weight)
                    score += mom_1d  * 3.0
                    score += mom_5d  * 2.0
                    score += mom_10d * 1.0

                    # Hard rejection: already up > 20% in 5 days → likely exhausted
                    if mom_5d > 20.0:
                        continue

                    # RSI sweet-spot
                    if 40 <= rsi <= 65:
                        score += 15
                    elif 30 <= rsi <= 75:
                        score += 5
                    elif rsi > 80:
                        score -= 20
                    else:
                        score -= 10

                    # Trend alignment
                    score += 10 if above_sma20 else -10
                    score += 5  if above_sma10 else -5
                    score += 8  if ema_bullish  else -4
                    score += 8  if macd_bullish else -5

                    # Relative volume (1.5x+ is a strong signal per requirements)
                    if vol_ratio > 2.0:
                        score += 20
                    elif vol_ratio > 1.5:
                        score += 14
                    elif vol_ratio > 1.2:
                        score += 7
                    elif vol_ratio > 1.0:
                        score += 3

                    # Core mega-cap bonus
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
        f"Selected top {len(hot_list)}. "
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
Your job is to identify stocks that are highly likely to trend upward over the next 3–5 trading days.

═══ TARGET ═══
Aim to recommend 5 to 15 stocks. Prioritise quality, but ensure the portfolio is diversified
and not over-concentrated. An empty list or fewer than 5 picks (when viable candidates exist)
is a poor outcome. If the market offers strong setups, populate the full 5–15 range.

═══ MARKET REGIME ═══
{regime_section}

═══ HARD EXCLUSION CRITERIA (disqualify entirely — no exceptions) ═══
1. ❌ Earnings announced this week (earnings_this_week = true) — binary risk, too unpredictable
2. ❌ Stock has already risen > 20% in the last 5 days (mom_5d > 20%) — likely exhausted
3. ❌ Average daily volume < 50,000 shares (avg_daily_vol_20 < 50k) — cannot exit safely
4. ❌ Major negative news: lawsuits, earnings misses, FDA rejections, downgrades
5. ❌ RSI > 85 — extremely overbought with high mean-reversion risk
6. ❌ Price significantly (> 3%) below both SMA-20 AND SMA-50 — confirmed downtrend

═══ PRIORITY BUY SIGNALS (aim for at least 2 of these) ═══
1. ✅ Pre-market green on Monday morning (day_change_pct > 0 at open)
2. ✅ Elevated relative volume (vol_vs_avg_20 >= 1.5x) — institutional interest
3. ✅ Strong positive 5-day momentum (mom_5d > 3%) entering the week
4. ✅ Positive news catalyst in the last 72 hours (earnings beat, analyst upgrade,
      product launch, contract win, FDA approval, sector tailwind)
5. ✅ EMA-8 crossing or holding ABOVE EMA-21 (swing momentum burst)
6. ✅ MACD line above signal line (bullish crossover)
7. ✅ RSI between 50–70 — sweet spot: trending but not overbought
8. ✅ Price ABOVE SMA-20 — short-term uptrend confirmed

═══ DEPRIORITISE (may still include if other signals are very strong) ═══
- No news catalyst — technicals alone can justify inclusion
- RSI 70–85 — include only if news catalyst is very strong
- Low-price stocks — fine to include if volume spike is significant (>= 1.5x 20-day avg)

═══ ANALYSIS WEIGHTS ═══
1. Technical Momentum (35%): EMA-8/21 alignment, SMA-20 position, MACD, vol_vs_avg_20
2. News Catalyst (30%): earnings beats, upgrades, launches, sector tailwinds
3. Trend Confirmation (20%): price vs MAs, multi-timeframe momentum (mom_5d, mom_20d)
4. Risk Management (15%): liquidity, avoid binary events, avoid overbought extremes

═══ CONFIDENCE & POSITION SIZING ═══
- 0.80–1.00: Multiple strong catalysts + excellent technicals → position_size_pct = 12–20%
- 0.65–0.79: Good setup with 2+ buy signals → position_size_pct = 7–12%
- 0.50–0.64: Decent setup, at least 1 strong signal → position_size_pct = 3–7%
- Below 0.50: Do NOT recommend
{market_caution}
Position sizes should sum to approximately 100% across all picks.
Higher confidence picks get larger allocations. Adjust so the total is sensible.

═══ NEWS DATA ═══
{news_json}
{tech_section}
═══ OUTPUT FORMAT ═══
Respond ONLY with a valid JSON array. No markdown fences, no explanation outside the JSON.
Each recommendation MUST reference specific data points from the data above.
[
  {{
    "ticker": "NVDA",
    "reason": "Earnings beat by 22% last week, 3 analyst upgrades to $1,100 PT. Technicals: RSI 58, price $870 above SMA-20 ($840), EMA-8 ($855) > EMA-21 ($830), MACD bullish, vol_vs_avg_20 = 2.3x, mom_5d +4.1%. Strong momentum entering the week with institutional volume confirmation.",
    "confidence": 0.87,
    "position_size_pct": 18
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


def run_daily_scan() -> list[dict]:
    """
    Main entry point: scans the full NASDAQ market and returns AI-ranked stock picks.

    Pipeline:
    1. Fetch the complete NASDAQ ticker universe (dynamic, ~3,300 tickers)
    2. Check market regime (QQQ health)
    3. Dynamic-screen full universe → best 75 by composite momentum/volume score
    4. Fetch news for those 75 (highest-scored first)
    5. Fetch detailed technicals for the 75
    6. Pre-filter obvious losers (low volume, earnings this week, already ran 20%+)
    7. Send everything to Gemini for final AI ranking
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

    logger.info(
        f"Sending {len(all_news)} articles + {len(filtered_technicals)} filtered technical "
        f"profiles (from {len(technicals)} total) to Gemini ({regime} regime)..."
    )

    # Step 8: AI analysis with news + filtered technicals + market context
    recommendations = analyse_with_gemini(all_news, filtered_technicals, market_regime)

    picks = [f"{r['ticker']}({r['confidence']:.0%})" for r in recommendations]
    logger.info(f"═══ Scan complete. {len(recommendations)} stock(s) recommended: {picks} ═══")

    return recommendations
