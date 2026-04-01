import os
import json
import time
import logging
import requests
import google.generativeai as genai
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


def analyse_with_gemini(news_data: list[dict]) -> list[dict]:
    """
    Uses Gemini to analyse news and return ranked stock recommendations
    for the current trading day using structured JSON output.

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

    prompt = f"""You are an elite day-trader AI assistant analysing NASDAQ stocks for {today}.

You have access to news about a wide universe of NASDAQ-listed stocks. Below is the full list 
of tickers you are authorised to recommend from:
{universe_str}

Below is a collection of recent news articles for various stocks and the broader market.
Your task is to identify up to 5 stocks from the universe above that are MOST LIKELY to have
a positive price movement TODAY (intraday) based on news sentiment, earnings surprises,
product announcements, analyst upgrades, FDA approvals, contract wins, or other bullish catalysts.

IMPORTANT RULES:
- Only recommend stocks with STRONG bullish evidence from the news.
- You may ONLY recommend tickers that appear in the universe list above.
- Do NOT recommend stocks with neutral or mixed news.
- If fewer than 3 stocks meet the criteria, return only those that do. Return an empty array if none qualify.
- Focus on stocks likely to see a 1–5%+ intraday gain.
- Confidence is 0.0 to 1.0 where 1.0 = extremely confident.

News Data:
{news_json}

Respond ONLY with a valid JSON array. No markdown, no explanation outside the JSON.
Format:
[
  {{
    "ticker": "NVDA",
    "reason": "Beat earnings expectations by 15%, analyst upgrades from 3 firms.",
    "confidence": 0.92
  }},
  ...
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

        # Validate structure
        validated = []
        for rec in recommendations:
            if isinstance(rec, dict) and "ticker" in rec and "reason" in rec:
                validated.append({
                    "ticker": str(rec["ticker"]).upper().strip(),
                    "reason": str(rec.get("reason", "")),
                    "confidence": float(rec.get("confidence", 0.5)),
                })
        return validated

    except Exception as e:
        logger.error(f"Gemini analysis failed: {e}")
        return []


def run_daily_scan() -> list[dict]:
    """
    Main entry point: scans the market and returns AI-ranked stock picks.
    Fetches news for watchlist tickers + top movers, then asks Gemini to rank.
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
    # Full universe of 500+ tickers is passed to Gemini as context above
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

    logger.info(f"Fetched {len(all_news)} news articles. Sending to Gemini...")

    # Step 3: AI analysis
    recommendations = analyse_with_gemini(all_news)

    logger.info(f"Scan complete. {len(recommendations)} stock(s) recommended: "
                f"{[r['ticker'] for r in recommendations]}")

    return recommendations
