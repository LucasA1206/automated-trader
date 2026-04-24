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

# ─── Top 50 most active tickers for individual news API calls ────────────────
# (NewsAPI rate limits prevent fetching all 500 individually)
NASDAQ_HOT_LIST = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN", "TSLA", "AVGO", "AMD",
    "INTC", "QCOM", "ARM", "SMCI", "MU", "SNOW", "PLTR", "CRWD", "NET",
    "ZS", "DDOG", "PANW", "COIN", "MSTR", "RBLX", "SHOP", "ADBE", "CRM",
    "NOW", "MNDY", "AFRM", "SOFI", "RIVN", "LCID", "NIO", "XPEV",
    "MRNA", "REGN", "BIIB", "VRTX", "ILMN", "ISRG", "DXCM",
    "FSLR", "ENPH", "PLUG", "JOBY", "ACHR", "RKLB", "HOOD",
]



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
        # 1-month of daily data for moving averages / RSI
        hist = tk.history(period="1mo", interval="1d")
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

        return {
            "ticker": ticker,
            "price": round(latest_close, 2),
            "prev_close": round(prev_close, 2),
            "day_change_pct": day_change_pct,
            "sma_5": round(sma_5, 2) if sma_5 else None,
            "sma_10": round(sma_10, 2) if sma_10 else None,
            "sma_20": round(sma_20, 2) if sma_20 else None,
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


def analyse_with_gemini(news_data: list[dict], technicals: list[dict] | None = None) -> list[dict]:
    """
    Uses Gemini to analyse news + technical data and return ranked stock
    recommendations for the current trading day using structured JSON output.

    Returns: list of {"ticker": str, "reason": str, "confidence": float (0-1)}
    """
    if not GEMINI_API_KEY:
        logger.warning("GEMINI_API_KEY not set, skipping AI analysis")
        return []

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Trim headline blob to avoid token limits — 8KB cap
    news_json = json.dumps(news_data, indent=2)
    if len(news_json) > 8000:
        news_json = news_json[:8000] + "\n... (truncated)"

    universe_str = ", ".join(NASDAQ_UNIVERSE)

    # Build technical data section
    tech_section = ""
    if technicals:
        tech_json = json.dumps(technicals, indent=2)
        if len(tech_json) > 6000:
            tech_json = tech_json[:6000] + "\n... (truncated)"
        tech_section = f"""
TECHNICAL DATA (real-time indicators for key tickers):
{tech_json}
"""

    prompt = f"""You are an elite quantitative day-trading AI analysing NASDAQ stocks for {today}.
Your job is to identify the BEST stocks to BUY at market open that will RISE during the trading day.

═══ AUTHORISED TICKER UNIVERSE ═══
{universe_str}

═══ ANALYSIS METHODOLOGY ═══
Apply ALL of the following factors to score each candidate. Only recommend stocks where
multiple factors converge bullishly:

1. NEWS CATALYST (Weight: 35%)
   - Earnings beats / positive guidance revisions
   - Product launches, major partnerships, or contract wins
   - FDA approvals, clinical trial successes
   - Analyst upgrades with price-target increases
   - Insider buying or institutional accumulation reports
   - Sector-wide tailwinds (e.g. AI spending surge, rate cut expectations)
   NEGATIVE: Lawsuits, recalls, downgrades, executive departures → DISQUALIFY

2. TECHNICAL MOMENTUM (Weight: 30%)
   - RSI between 40–65 is ideal (not overbought, showing momentum)
   - RSI < 30 with a bullish catalyst = oversold bounce opportunity
   - RSI > 75 = AVOID (overbought, likely to pull back)
   - Price above SMA-5 and SMA-10 = short-term uptrend ✓
   - MACD line above signal line = bullish crossover ✓
   - Volume spike (vol_vs_avg > 1.5) confirms conviction

3. PRICE ACTION (Weight: 20%)
   - Gap-up in pre-market on high volume = strong momentum
   - Positive day_change_pct with rising volume = buyers in control
   - Look for stocks breaking above recent resistance

4. RISK MANAGEMENT (Weight: 15%)
   - Avoid penny stocks (price < $5) — too volatile, wide spreads
   - Avoid stocks with negative news even if technicals look good
   - Prefer liquid, mid-to-large cap stocks for reliable fills
   - Avoid stocks already up >8% pre-market (likely to fade)

═══ CONFIDENCE SCORING ═══
- 0.90–1.00: Exceptional — strong catalyst + perfect technicals + high volume
- 0.80–0.89: Strong — clear catalyst + supportive technicals
- 0.70–0.79: Good — decent catalyst OR strong technicals, some uncertainty
- 0.60–0.69: Marginal — weak signal, do NOT recommend unless very compelling
- Below 0.60: Do NOT include

ONLY return stocks you are genuinely confident will rise TODAY (intraday).
If no stocks meet the bar, return an EMPTY array []. Quality over quantity.

═══ NEWS DATA ═══
{news_json}
{tech_section}
═══ OUTPUT FORMAT ═══
Respond ONLY with a valid JSON array. No markdown fences, no explanation outside the JSON.
[
  {{
    "ticker": "NVDA",
    "reason": "Beat Q4 earnings by 22%, 3 analyst upgrades, RSI 52 (bullish momentum), MACD bullish crossover, volume 2.1x average — strong multi-factor buy.",
    "confidence": 0.92
  }}
]"""

    try:
        model = genai.GenerativeModel("gemini-2.5-flash-lite")
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
    Fetches news for watchlist tickers + top movers, fetches real-time
    technical indicators, then asks Gemini to rank.
    """
    logger.info("Starting daily market scan...")

    all_news = []

    # Step 1: Fetch broad market news
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

    # Step 2: Fetch individual ticker news for the hot list (rate-limit safe)
    logger.info(f"Fetching news for {len(NASDAQ_HOT_LIST)} hot-list tickers...")
    rate_limited = False
    for ticker in NASDAQ_HOT_LIST:
        if rate_limited:
            break
        articles = fetch_news_for_ticker(ticker)
        if articles is None:
            # 429 received — stop hammering the API
            rate_limited = True
            logger.warning("NewsAPI rate limit reached. Proceeding with partial news data.")
            break
        all_news.extend(articles)
        time.sleep(0.25)  # 250 ms gap → ~4 req/s, well under NewsAPI limits

    logger.info(f"Fetched {len(all_news)} news articles.")

    # Step 3: Fetch technical indicators for the hot list
    logger.info(f"Fetching technical indicators for {len(NASDAQ_HOT_LIST)} tickers...")
    technicals = fetch_technicals_batch(NASDAQ_HOT_LIST, max_workers=10)

    logger.info(f"Sending {len(all_news)} articles + {len(technicals)} technical profiles to Gemini...")

    # Step 4: AI analysis with both news + technicals
    recommendations = analyse_with_gemini(all_news, technicals)

    logger.info(f"Scan complete. {len(recommendations)} stock(s) recommended: "
                f"{[f\"{r['ticker']}({r['confidence']:.0%})\" for r in recommendations]}")

    return recommendations
