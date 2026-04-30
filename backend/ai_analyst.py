import os
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

# ─── Full NASDAQ Universe (~500 tickers passed to Gemini as context) ─────────
# Gemini can recommend any of these — organised by sector
NASDAQ_UNIVERSE = [
    # ── Mega-cap Tech ──────────────────────────────────────────────────────────
    "AAPL", "MSFT", "NVDA", "GOOGL", "GOOG", "AMZN", "META", "TSLA", "AVGO",
    "ASML", "AMD", "QCOM", "ARM", "INTC", "TXN", "ADI", "MCHP", "AMAT",
    "LRCX", "KLAC", "NXPI", "SWKS", "MRVL", "ON", "MPWR", "WOLF", "SMCI",
    "MU", "WDC", "STX", "NTAP",

    # ── Software / Cloud ───────────────────────────────────────────────────────
    "ADBE", "CRM", "NOW", "WDAY", "VEEV", "TEAM", "HUBS", "DDOG", "NET",
    "ZS", "PANW", "CRWD", "OKTA", "S", "MNDY", "BILL", "SMAR", "BOX",
    "DOCN", "DOMO", "NCNO", "PCOR", "ESTC", "MDB", "GTLB", "CFLT", "SNOW",
    "PLTR", "COIN", "MSTR", "RBLX", "SHOP", "AFRM", "SOFI", "UPST", "LC",
    "SQ", "PYPL", "SSNC", "MANH", "PAYC", "GWRE", "AVLR", "RELY", "TOST",
    "BRZE", "ALTR", "DT", "APTI", "SDGR", "PATH", "AI", "BBAI", "SOUN",
    "GFAI", "IREN", "CORZ", "CIFR", "BTBT", "CLSK",

    # ── Semiconductors (extended) ──────────────────────────────────────────────
    "SNPS", "CDNS", "LSCC", "ACLS", "ONTO", "ICHR", "FORM", "CCMP", "AMKR",
    "QRVO", "LITE", "IIVI", "COHU", "UCTT", "KLIC", "AEHR", "AXTI",
    "POWI", "DIOD", "SLAB", "AMBA", "ALGM", "MTSI", "AIOT", "CRUS",

    # ── Internet / E-commerce / Digital Media ─────────────────────────────────
    "EBAY", "ETSY", "CHWY", "W", "DKNG", "PENN", "LYFT", "UBER", "DASH",
    "ABNB", "BKNG", "EXPE", "TRIP", "YELP", "IAC", "ZG", "RDFN", "OPEN",
    "TZOO", "NFLX", "ROKU", "SPOT", "SONO", "PARAA", "SIRI",

    # ── EVs / Clean Energy / Autonomous ───────────────────────────────────────
    "RIVN", "LCID", "NIO", "XPEV", "LI", "NKLA", "GOEV", "WKHS", "FFIE",
    "FSR", "PTRA", "BLNK", "CHPT", "EVGO", "PLUG", "FCEL", "BLDP",
    "FSLR", "ENPH", "SEDG", "ARRY", "RUN", "NOVA", "MAXN", "CSIQ",
    "JOBY", "ACHR", "LILM", "WATT",

    # ── Biotech / Pharma / Life Sciences ──────────────────────────────────────
    "REGN", "VRTX", "MRNA", "BIIB", "ALNY", "ILMN", "BMRN", "INCY",
    "EXAS", "NBIX", "ACAD", "RARE", "RCKT", "NTLA", "BEAM", "EDIT",
    "CRSP", "FATE", "IOVA", "KRTX", "PTGX", "TGTX", "PRAX", "RXRX",
    "ARQT", "IMVT", "TBPH", "DNLI", "IONS", "ARGX", "KRYS", "APGE",
    "RVMD", "NKTX", "BLUE", "FOLD", "AVXL", "CDTX", "CGEM", "IMCR",
    "VCEL", "NUVL", "ARVN", "KYMR", "MGNX", "MIRM", "ALLO", "GRPH",
    "ROIV", "LNTH", "ACLX", "SNDX", "PMVP", "TARS", "OKLO",

    # ── Medical Devices / Health Tech ─────────────────────────────────────────
    "ISRG", "IDXX", "DXCM", "PODD", "ALGN", "MASI", "HOLX", "TECH",
    "NEOG", "NUVA", "HSIC", "XRAY", "ZBH", "NTRA", "PACB", "AXNX",
    "INSP", "SWAV", "TNDM", "NARI", "ATRS", "LIVN",

    # ── Financial / Fintech ────────────────────────────────────────────────────
    "HOOD", "MELI", "NU", "PAGS", "DLO", "NUVEI", "GPN", "EVRI",
    "FOUR", "PAX", "PAYO", "IIIV", "RPAY", "PRSO",

    # ── Cybersecurity ─────────────────────────────────────────────────────────
    "FTNT", "CYBR", "TENB", "RPD", "QLYS", "VRNS", "SAIL", "RBRK",

    # ── Cloud Infrastructure / Networking ─────────────────────────────────────
    "CSCO", "ANET", "JNPR", "FFIV", "NTGR", "VIAV", "INFN", "CALX",
    "CIEN", "SMTC", "SMAR",

    # ── Consumer Tech / Devices ───────────────────────────────────────────────
    "AAPL", "HPQ", "LOGI", "GPRO", "HEAR", "VZIO", "SONO",

    # ── AI / Data / Analytics ─────────────────────────────────────────────────
    "CWAN", "VERX", "PDFS", "CNXC", "PRCT", "APPF", "ALRM", "KNSA",
    "ATNI", "GFAI", "BBAI", "SOUN", "BIGB", "AMSWA", "CLBT", "PTLO",

    # ── Retail / Consumer Discretionary ───────────────────────────────────────
    "COST", "AMZN", "LULU", "ORLY", "CASY", "FIVE", "ROST", "DLTR",
    "TSCO", "ULTA", "DECK", "CROX", "SKX", "ONON", "BOOT", "BIRK",

    # ── Telecom / Communications ──────────────────────────────────────────────
    "TMUS", "LBRDK", "LBRDA", "CHTR", "SHEN", "GSAT", "AST",

    # ── Travel / Hospitality ──────────────────────────────────────────────────
    "ABNB", "BKNG", "EXPE", "MMYT", "TRVG", "DESP", "SEERA",

    # ── Food / Beverage ───────────────────────────────────────────────────────
    "SBUX", "PZZA", "WING", "SHAK", "BROS", "CAVA", "TXRH",

    # ── Industrial / Aerospace ────────────────────────────────────────────────
    "AXON", "KTOS", "RKLB", "SPCE", "LUNR", "MNTS", "ASTS", "SATL",

    # ── Crypto / Blockchain ───────────────────────────────────────────────────
    "COIN", "MSTR", "MARA", "RIOT", "CLSK", "CORZ", "IREN", "BTBT", "HUT",
    "BTDR", "WULF", "CIFR", "BITF",
]

# Remove any duplicates while preserving order
seen = set()
NASDAQ_UNIVERSE = [t for t in NASDAQ_UNIVERSE if not (t in seen or seen.add(t))]

# ─── Core mega-cap tickers — get a scoring bonus in the daily screen ──────────
# These move markets so they receive a small bump, but they still need decent
# technicals to make the final top-50 cut.
CORE_TICKERS = {
    "AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN", "TSLA", "AVGO",
    "AMD", "PLTR", "COIN", "CRM", "NFLX", "CRWD",
}



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
        sma_5 = float(closes.rolling(5).mean().iloc[-1]) if len(closes) >= 5 else None
        sma_10 = float(closes.rolling(10).mean().iloc[-1]) if len(closes) >= 10 else None
        sma_20 = float(closes.rolling(20).mean().iloc[-1]) if len(closes) >= 20 else None
        sma_50 = float(closes.rolling(50).mean().iloc[-1]) if len(closes) >= 50 else None

        # RSI
        rsi = _compute_rsi(closes)

        # MACD (12, 26, 9)
        macd_val = None
        macd_signal = None
        if len(closes) >= 26:
            ema12 = closes.ewm(span=12, adjust=False).mean()
            ema26 = closes.ewm(span=26, adjust=False).mean()
            macd_line = ema12 - ema26
            signal_line = macd_line.ewm(span=9, adjust=False).mean()
            macd_val = round(float(macd_line.iloc[-1]), 4)
            macd_signal = round(float(signal_line.iloc[-1]), 4)

        # Volume spike (today vs 10-day average)
        avg_vol_10 = float(volumes.rolling(10).mean().iloc[-1]) if len(volumes) >= 10 else None
        latest_vol = float(volumes.iloc[-1])
        vol_ratio = round(latest_vol / avg_vol_10, 2) if avg_vol_10 and avg_vol_10 > 0 else None

        # Day change
        day_change_pct = round((latest_close - prev_close) / prev_close * 100, 2) if prev_close else 0

        # Multi-timeframe momentum (percentage returns)
        mom_5d = round((latest_close / float(closes.iloc[-6]) - 1) * 100, 2) if len(closes) >= 6 else None
        mom_20d = round((latest_close / float(closes.iloc[-21]) - 1) * 100, 2) if len(closes) >= 21 else None

        return {
            "ticker": ticker,
            "price": round(latest_close, 2),
            "prev_close": round(prev_close, 2),
            "day_change_pct": day_change_pct,
            "mom_5d": mom_5d,
            "mom_20d": mom_20d,
            "sma_5": round(sma_5, 2) if sma_5 else None,
            "sma_10": round(sma_10, 2) if sma_10 else None,
            "sma_20": round(sma_20, 2) if sma_20 else None,
            "sma_50": round(sma_50, 2) if sma_50 else None,
            "rsi_14": rsi,
            "macd": macd_val,
            "macd_signal": macd_signal,
            "volume": int(latest_vol),
            "vol_vs_avg": vol_ratio,
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
    """Check overall NASDAQ market health via QQQ ETF.

    Returns a dict with regime ('bullish', 'neutral', 'bearish'),
    recent QQQ changes, and whether price is above SMA-20.
    Used to scale position sizing and set minimum confidence thresholds.
    """
    try:
        qqq = yf.Ticker("QQQ")
        hist = qqq.history(period="1mo", interval="1d")
        if hist.empty or len(hist) < 5:
            return {"regime": "unknown", "qqq_change_3d": 0, "qqq_change_5d": 0}

        closes = hist["Close"]
        latest = float(closes.iloc[-1])
        change_3d = round((latest / float(closes.iloc[-4]) - 1) * 100, 2) if len(closes) >= 4 else 0
        change_5d = round((latest / float(closes.iloc[-6]) - 1) * 100, 2) if len(closes) >= 6 else 0
        sma_20 = float(closes.rolling(20).mean().iloc[-1]) if len(closes) >= 20 else latest

        if change_3d < -2.0 or (change_5d < -3.0 and latest < sma_20):
            regime = "bearish"
        elif change_3d > 1.0 and latest > sma_20:
            regime = "bullish"
        else:
            regime = "neutral"

        return {
            "regime": regime,
            "qqq_price": round(latest, 2),
            "qqq_change_3d": change_3d,
            "qqq_change_5d": change_5d,
            "qqq_above_sma20": latest > sma_20,
        }
    except Exception as e:
        logger.error(f"Market regime check failed: {e}")
        return {"regime": "unknown", "qqq_change_3d": 0, "qqq_change_5d": 0}


def pre_filter_candidates(technicals: list[dict]) -> list[dict]:
    """Remove stocks that are obviously in downtrends before sending to AI.

    This saves API tokens and prevents the AI from being tempted by
    stocks that look cheap but are actually falling knives.
    """
    filtered = []
    rejected = []

    for t in technicals:
        ticker = t["ticker"]
        price = t.get("price", 0)
        sma_20 = t.get("sma_20")
        sma_50 = t.get("sma_50")
        rsi = t.get("rsi_14")
        mom_5d = t.get("mom_5d")
        mom_20d = t.get("mom_20d")

        # Reject: price below both SMA-20 and SMA-50 (strong downtrend)
        if sma_20 and sma_50 and price < sma_20 and price < sma_50:
            rejected.append(f"{ticker}(below SMA-20 & SMA-50)")
            continue

        # Reject: negative momentum on both timeframes
        if mom_5d is not None and mom_20d is not None:
            if mom_5d < -3.0 and mom_20d < -5.0:
                rejected.append(f"{ticker}(downtrend: 5d={mom_5d}%, 20d={mom_20d}%)")
                continue

        # Reject: heavily overbought (likely to pull back)
        if rsi and rsi > 80:
            rejected.append(f"{ticker}(overbought RSI={rsi})")
            continue

        # Reject: penny stocks
        if price < 5.0:
            rejected.append(f"{ticker}(penny stock ${price})")
            continue

        filtered.append(t)

    if rejected:
        logger.info(f"Pre-filter rejected {len(rejected)} ticker(s): {', '.join(rejected[:15])}")
    logger.info(f"Pre-filter passed {len(filtered)}/{len(technicals)} tickers.")
    return filtered


def verify_ticker_momentum(ticker: str) -> bool:
    """Quick pre-buy check: reject stocks that are actively declining.

    Runs just before order execution to catch stocks that may have
    turned negative between the AI scan and the buy order.
    """
    try:
        tk = yf.Ticker(ticker)
        hist = tk.history(period="5d", interval="1d")
        if hist.empty or len(hist) < 3:
            return True  # Insufficient data — allow the trade

        closes = hist["Close"]
        latest = float(closes.iloc[-1])
        three_days_ago = float(closes.iloc[0]) if len(closes) >= 3 else latest

        change = (latest / three_days_ago - 1) * 100

        if change < -3.0:
            logger.warning(f"Pre-buy check FAILED for {ticker}: down {change:.1f}% over recent sessions")
            return False

        return True
    except Exception as e:
        logger.warning(f"Pre-buy momentum check error for {ticker}: {e}")
        return True  # On error, allow the trade


def _quick_screen_universe(
    universe: list[str],
    top_n: int = 50,
) -> list[tuple[str, float]]:
    """Dynamically screen the full ticker universe to find today's best 50 stocks.

    Uses a free yfinance batch download (no API credits) to fetch 1-month daily
    data for every ticker, compute quick technical metrics, and rank them by a
    composite momentum/trend/RSI/volume score.

    Returns the top_n tickers as (ticker, score) tuples, sorted by score
    descending.  CORE_TICKERS receive a small scoring bonus (+8) so they are
    more likely to appear but are NOT force-included — they still need a
    reasonable setup to make the cut.

    This replaces the old static NASDAQ_HOT_LIST so the scanner adapts daily
    to wherever the momentum is.
    """
    logger.info(f"Dynamic screening {len(universe)} tickers to find top {top_n}...")

    try:
        # Batch download — far faster than individual yf.Ticker() calls
        data = yf.download(
            universe,
            period="1mo",
            interval="1d",
            group_by="ticker",
            threads=True,
            progress=False,
        )

        if data.empty:
            logger.warning("Batch download returned empty data. Using core tickers only.")
            return [(t, 0.0) for t in CORE_TICKERS]

        scores: list[tuple[str, float]] = []

        for ticker in universe:
            try:
                if ticker not in data.columns.get_level_values(0):
                    continue
                ticker_df = data[ticker]
                closes = ticker_df["Close"].dropna()
                volumes = ticker_df["Volume"].dropna()

                if len(closes) < 10:
                    continue

                latest = float(closes.iloc[-1])
                if latest < 5.0:  # skip penny stocks
                    continue

                prev_close = float(closes.iloc[-2]) if len(closes) >= 2 else latest

                # ── Quick metrics ──
                mom_1d = ((latest / prev_close) - 1) * 100 if prev_close > 0 else 0.0
                mom_5d = ((latest / float(closes.iloc[-6])) - 1) * 100 if len(closes) >= 6 else 0.0
                mom_10d = ((latest / float(closes.iloc[-11])) - 1) * 100 if len(closes) >= 11 else 0.0
                sma_10 = float(closes.rolling(10).mean().iloc[-1]) if len(closes) >= 10 else latest
                sma_20 = float(closes.rolling(20).mean().iloc[-1]) if len(closes) >= 20 else latest
                above_sma10 = latest > sma_10
                above_sma20 = latest > sma_20
                rsi = _compute_rsi(closes) or 50.0
                avg_vol = float(volumes.rolling(10).mean().iloc[-1]) if len(volumes) >= 10 else 1.0
                vol_ratio = float(volumes.iloc[-1]) / avg_vol if avg_vol > 0 else 1.0

                # ── MACD quick check ──
                macd_bullish = False
                if len(closes) >= 26:
                    ema12 = closes.ewm(span=12, adjust=False).mean()
                    ema26 = closes.ewm(span=26, adjust=False).mean()
                    macd_line = ema12 - ema26
                    signal_line = macd_line.ewm(span=9, adjust=False).mean()
                    macd_bullish = float(macd_line.iloc[-1]) > float(signal_line.iloc[-1])

                # ── Composite score (higher = better daily candidate) ──
                score = 0.0

                # Momentum (biggest weight — we want stocks moving NOW)
                score += mom_1d * 3.0   # today's gap / move is most important
                score += mom_5d * 2.0   # short-term trend
                score += mom_10d * 1.0  # medium-term trend

                # RSI sweet-spot
                if 40 <= rsi <= 65:
                    score += 15  # ideal buy zone
                elif 30 <= rsi <= 75:
                    score += 5   # acceptable
                elif rsi > 80:
                    score -= 20  # overbought penalty
                else:
                    score -= 10  # oversold / risky

                # Trend alignment
                score += 10 if above_sma20 else -10
                score += 5 if above_sma10 else -5

                # MACD
                score += 8 if macd_bullish else -5

                # Volume surge (institutional interest)
                if vol_ratio > 2.0:
                    score += 15
                elif vol_ratio > 1.5:
                    score += 10
                elif vol_ratio > 1.2:
                    score += 5

                # Core mega-cap bonus — these are more liquid and move markets
                if ticker in CORE_TICKERS:
                    score += 8

                scores.append((ticker, round(score, 2)))
            except Exception:
                continue

        scores.sort(key=lambda x: x[1], reverse=True)

        # Take the top N by score — no force-includes
        hot_list = scores[:top_n]

        top10 = [(t, f"{s:.1f}") for t, s in scores[:10]]
        core_in_list = [t for t, _ in hot_list if t in CORE_TICKERS]
        logger.info(
            f"Dynamic screening complete. Selected {len(hot_list)} tickers. "
            f"Top 10 by score: {top10} | "
            f"Core tickers in hot list: {len(core_in_list)}/{len(CORE_TICKERS)}"
        )
        # Log full hot list for debugging
        logger.info(f"Full hot list: {[t for t, _ in hot_list]}")

        return hot_list

    except Exception as e:
        logger.error(f"Dynamic screening failed ({e}). Falling back to core tickers.")
        return [(t, 0.0) for t in CORE_TICKERS]


def analyse_with_gemini(news_data: list[dict], technicals: list[dict] | None = None, market_regime: dict | None = None) -> list[dict]:
    """
    Uses Gemini to analyse news + technical data and return ranked stock
    recommendations for the current trading day using structured JSON output.

    Returns: list of {"ticker": str, "reason": str, "confidence": float (0-1)}
    """
    if not GEMINI_API_KEY:
        logger.warning("GEMINI_API_KEY not set, skipping AI analysis")
        return []

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Trim headline blob to avoid token limits — 10KB cap
    news_json = json.dumps(news_data, indent=2)
    if len(news_json) > 10000:
        news_json = news_json[:10000] + "\n... (truncated)"

    universe_str = ", ".join(NASDAQ_UNIVERSE)

    # Build technical data section
    tech_section = ""
    if technicals:
        tech_json = json.dumps(technicals, indent=2)
        if len(tech_json) > 8000:
            tech_json = tech_json[:8000] + "\n... (truncated)"
        tech_section = f"""
TECHNICAL DATA (real-time indicators — includes momentum, moving averages, RSI, MACD):
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
            f"  - Regime: {market_regime.get('regime', 'unknown').upper()}"
        )
        if market_regime.get("regime") == "bearish":
            market_caution = (
                "\n⚠️ BEARISH MARKET REGIME DETECTED: The broad market is declining. "
                "Minimum confidence threshold is 0.75. Be VERY selective — only recommend "
                "stocks with exceptional individual catalysts that can buck the market trend. "
                "Consider recommending FEWER stocks (1-2 max)."
            )
        elif market_regime.get("regime") == "neutral":
            market_caution = (
                "\n📊 NEUTRAL MARKET: Minimum confidence threshold is 0.60. "
                "Require solid technical confirmation before recommending."
            )

    prompt = f"""You are an elite quantitative day-trading AI analysing NASDAQ stocks for {today}.
Your job is to identify stocks to BUY at market open that will RISE during the trading day.

QUALITY OVER QUANTITY — recommend 1 to 5 stocks, but only include stocks with genuinely
strong setups. If only 1 stock has a great setup, recommend only 1. Do NOT pad the list
with mediocre picks just to reach 5.

═══ MARKET REGIME ═══
{regime_section}

═══ AUTHORISED TICKER UNIVERSE ═══
{universe_str}

═══ MANDATORY REJECTION CRITERIA ═══
IMMEDIATELY DISQUALIFY any stock matching ANY of these — do NOT recommend it regardless
of how appealing the news looks:
- Price BELOW both SMA-20 AND SMA-50 → confirmed downtrend, do NOT buy "cheap" falling stocks
- RSI > 75 → overbought, will likely pull back today
- Negative momentum on BOTH 5-day (mom_5d < 0) AND 20-day (mom_20d < -3%) → accelerating decline
- Price below $5 → penny stock, unreliable, wide spreads
- Stock already up >8% in recent days → extended, likely to fade/mean-revert
- Any negative news: lawsuits, earnings misses, downgrades, FDA rejections → DISQUALIFY
- MACD bearish crossover (MACD < signal) WITH declining volume → distribution pattern

═══ STRONG BUY REQUIREMENTS (need at least 3 of these) ═══
1. ✅ Positive news catalyst (earnings beat, analyst upgrade, partnership, product launch)
2. ✅ RSI between 40-65 (momentum without being overbought)
3. ✅ Price ABOVE SMA-20 (short-term uptrend confirmed)
4. ✅ Price ABOVE SMA-50 (medium-term trend support)
5. ✅ MACD line ABOVE signal line (bullish crossover)
6. ✅ Volume spike (vol_vs_avg > 1.3) — institutional interest
7. ✅ Positive 5-day momentum (mom_5d > 0%)
8. ✅ Positive 20-day momentum (mom_20d > 0%)

═══ ANALYSIS METHODOLOGY ═══
1. TECHNICAL MOMENTUM (Weight: 35%)
   - Check ALL moving averages: SMA-5, SMA-10, SMA-20, SMA-50
   - Price above SMA-20 AND SMA-50 = strong uptrend ✓
   - MACD line above signal = bullish ✓
   - RSI 40-65 ideal range
   - Volume confirms the move (vol_vs_avg > 1.3)
   - Check mom_5d and mom_20d — BOTH should be positive or one strongly positive

2. NEWS CATALYST (Weight: 30%)
   - Earnings beats / positive guidance / analyst upgrades
   - Product launches, major partnerships, contract wins
   - FDA approvals, clinical trial successes
   - Sector tailwinds (AI spending, rate cuts, etc.)

3. TREND CONFIRMATION (Weight: 20%)
   - Price above SMA-50 = medium-term uptrend
   - Not extended too far above moving averages (<5% above SMA-20)
   - Positive momentum on multiple timeframes

4. RISK MANAGEMENT (Weight: 15%)
   - Prefer liquid, mid-to-large cap stocks for reliable fills
   - In a BEARISH market regime, require STRONGER signals and HIGHER confidence
   - Avoid binary events (earnings within 24h, FDA decisions)

═══ CONFIDENCE SCORING ═══
- 0.80-1.00: Multiple strong catalysts + perfect technicals + volume confirmation
- 0.65-0.79: Good catalyst + supportive technicals (at least 3 buy signals)
- 0.50-0.64: Moderate setup — only recommend if nothing better available
- Below 0.50: Do NOT recommend
{market_caution}

═══ NEWS DATA ═══
{news_json}
{tech_section}
═══ OUTPUT FORMAT ═══
Respond ONLY with a valid JSON array. No markdown fences, no explanation outside the JSON.
Each recommendation MUST reference specific technical data points from the data above.
[
  {{
    "ticker": "NVDA",
    "reason": "Beat Q4 earnings by 22%, 3 analyst upgrades. Technicals: RSI 52, price $820 above SMA-20 ($795) and SMA-50 ($760), MACD bullish crossover, volume 2.1x average, mom_5d +3.2%, mom_20d +8.1% — strong multi-factor buy.",
    "confidence": 0.85
  }}
]"""

    try:
        model = genai.GenerativeModel("gemini-2.5-flash")
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

        # Validate structure and sort by confidence descending
        validated = []
        for rec in recommendations:
            if isinstance(rec, dict) and "ticker" in rec and "reason" in rec:
                validated.append({
                    "ticker": str(rec["ticker"]).upper().strip(),
                    "reason": str(rec.get("reason", "")),
                    "confidence": float(rec.get("confidence", 0.5)),
                })
        validated.sort(key=lambda r: r["confidence"], reverse=True)
        return validated

    except Exception as e:
        logger.error(f"Gemini analysis failed: {e}")
        return []


def run_daily_scan() -> list[dict]:
    """
    Main entry point: scans the market and returns AI-ranked stock picks.

    Pipeline:
    1. Check market regime (QQQ health)
    2. Dynamic-screen the full ~500-ticker universe → best 50 by composite score
    3. Fetch news for those 50 (highest-scored first so the most promising
       tickers are covered even if we hit a rate limit)
    4. Fetch detailed technicals for the 50
    5. Pre-filter obvious losers
    6. Send everything to Gemini for final AI ranking
    """
    logger.info("═══ Starting daily market scan ═══")

    all_news = []

    # Step 1: Fetch broad market / business headlines
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

    # Step 2: Check market regime (QQQ trend)
    logger.info("Checking market regime (QQQ)...")
    market_regime = check_market_regime()
    regime = market_regime.get("regime", "unknown")
    logger.info(
        f"Market regime: {regime.upper()} | QQQ 3d: {market_regime.get('qqq_change_3d')}%, "
        f"5d: {market_regime.get('qqq_change_5d')}%"
    )

    if regime == "bearish":
        logger.warning("⚠️ Bearish market detected — AI will apply stricter filters.")

    # Step 3: Dynamic screen — find today's best 50 stocks from full universe
    scored_hot_list = _quick_screen_universe(NASDAQ_UNIVERSE, top_n=50)
    # scored_hot_list is [(ticker, score), ...] sorted by score desc
    hot_tickers = [t for t, _ in scored_hot_list]

    logger.info(
        f"Hot list: {len(hot_tickers)} best stocks selected for today's analysis. "
        f"Score range: {scored_hot_list[0][1] if scored_hot_list else 'N/A'} → "
        f"{scored_hot_list[-1][1] if scored_hot_list else 'N/A'}"
    )

    # Step 4: Fetch individual ticker news — highest-scored tickers first
    # so the best candidates are covered even if we hit a NewsAPI rate limit
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
        time.sleep(0.25)  # 250 ms gap → ~4 req/s, well under NewsAPI limits

    logger.info(f"Fetched {len(all_news)} news articles across {news_fetched_count} tickers.")

    # Step 5: Fetch detailed technical indicators for the hot list
    logger.info(f"Fetching detailed technicals for {len(hot_tickers)} tickers...")
    technicals = fetch_technicals_batch(hot_tickers, max_workers=10)

    # Step 6: Pre-filter — remove obvious losers before AI analysis
    filtered_technicals = pre_filter_candidates(technicals)

    logger.info(
        f"Sending {len(all_news)} articles + {len(filtered_technicals)} filtered technical "
        f"profiles (from {len(technicals)} total) to Gemini ({regime} regime)..."
    )

    # Step 7: AI analysis with news + filtered technicals + market context
    recommendations = analyse_with_gemini(all_news, filtered_technicals, market_regime)

    picks = [f"{r['ticker']}({r['confidence']:.0%})" for r in recommendations]
    logger.info(f"═══ Scan complete. {len(recommendations)} stock(s) recommended: {picks} ═══")

    return recommendations
