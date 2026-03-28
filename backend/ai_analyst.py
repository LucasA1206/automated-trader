import os
import json
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

# Well-known NASDAQ 100 tickers to anchor our search
NASDAQ_WATCHLIST = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN", "TSLA", "AVGO", "ASML",
    "AMD", "INTC", "QCOM", "ARM", "SMCI", "MU", "SNOW", "PLTR", "CRWD",
    "NET", "ZS", "DDOG", "MNDY", "COIN", "MSTR", "RBLX", "SHOP", "ADBE",
    "CRM", "NOW", "PANW", "OKTA", "TEAM", "HUBS", "BILL", "AFRM", "SOFI",
    "RIVN", "LCID", "NIO", "XPEV", "F", "GM", "LYFT", "UBER", "DASH",
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

    prompt = f"""You are an elite day-trader AI assistant analysing NASDAQ stocks for {today}.

Below is a collection of recent news articles for various stocks and the broader market.
Your task is to identify up to 5 NASDAQ-listed stocks that are MOST LIKELY to have a 
positive price movement TODAY (intraday) based on the news sentiment, earnings surprises, 
product announcements, analyst upgrades, or other bullish catalysts.

IMPORTANT RULES:
- Only recommend stocks with STRONG bullish evidence from the news.
- Do NOT recommend stocks with neutral or mixed news.
- If fewer than 3 stocks meet the criteria, return only those that do. Return empty array if none qualify.
- Focus on stocks that are likely to see a 1–5%+ intraday gain.
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
        model = genai.GenerativeModel("gemini-1.5-flash")
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

    # Step 2: Fetch ticker-specific news for watchlist (limited to avoid API rate limits)
    scan_tickers = NASDAQ_WATCHLIST[:20]
    for ticker in scan_tickers:
        articles = fetch_news_for_ticker(ticker)
        all_news.extend(articles)

    logger.info(f"Fetched {len(all_news)} news articles. Sending to Gemini...")

    # Step 3: AI analysis
    recommendations = analyse_with_gemini(all_news)

    logger.info(f"Scan complete. {len(recommendations)} stock(s) recommended: "
                f"{[r['ticker'] for r in recommendations]}")

    return recommendations
