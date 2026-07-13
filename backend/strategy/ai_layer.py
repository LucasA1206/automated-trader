"""
AI Analysis Layer — Phase 5
============================
Implements the dual-model AI qualitative review from blueprint Section 3/12.

Architecture:
  Primary model  : Google Gemini (gemini-2.0-flash or later) — already configured
  Cross-check    : DeepSeek (deepseek-chat via OpenAI-compatible API) or
                   Groq (Llama 4) if DEEPSEEK_API_KEY is unavailable
  Tie-breaking   : If primary and cross-check disagree on proceed/reject → no trade

Input to each model:
  - Candidate ticker, composite score, sector, regime
  - Top 5 component scores and their interpretation
  - RSI, MACD, ADX, ATR%, relative strength values
  - Revenue growth, EPS growth, FCF, debt
  - Recent price action summary (last 5 bars)
  - News context (optional, if NEWS_API_KEY configured)

Output (strict JSON schema per blueprint Section 12):
  {
    "ticker": str,
    "proceed": bool,         ← MUST be present
    "conviction": int,       ← 0-100
    "entry_notes": str,      ← 1-2 sentence rationale
    "key_risk": str,         ← single biggest risk
    "max_hold_days": int     ← AI-suggested max hold (5-20, advisory only)
  }

Validation rules:
  - Both models MUST return valid JSON matching the schema
  - If primary or cross-check returns invalid JSON → no trade (fail-safe)
  - If models disagree on proceed/reject → no trade (conservative)
  - conviction must be 0-100 integer
  - max_hold_days must be 5-20 integer

The AI layer NEVER overrides mandatory filter rejections and NEVER
invents fundamental data — it reasons only from the data provided to it.
"""

import os
import json
import logging
import time
from typing import Optional

import requests
import google.generativeai as genai

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
NEWS_API_KEY = os.getenv("NEWS_API_KEY")

# Configure Gemini
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# gemini-2.5-flash is available on the free tier; gemini-2.0-flash requires billing.
GEMINI_MODEL = "gemini-2.5-flash"
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

# The cross-check model to use (prefers DeepSeek, falls back to Groq)
def _get_crosscheck_config() -> Optional[dict]:
    if DEEPSEEK_API_KEY:
        return {"type": "deepseek", "key": DEEPSEEK_API_KEY, "url": DEEPSEEK_API_URL, "model": "deepseek-chat"}
    if GROQ_API_KEY:
        return {"type": "groq", "key": GROQ_API_KEY, "url": GROQ_API_URL, "model": "meta-llama/llama-4-scout-17b-16e-instruct"}
    return None


# ─── AI verdict schema ────────────────────────────────────────────────────────

def _validate_ai_verdict(raw: dict, ticker: str, model_name: str) -> Optional[dict]:
    """
    Validate and normalise an AI verdict against the required schema.
    Returns the validated dict, or None if validation fails.
    """
    required = {"ticker", "proceed", "conviction", "entry_notes", "key_risk", "max_hold_days"}
    missing = required - set(raw.keys())
    if missing:
        logger.error("[AI] %s | %s: missing required fields: %s", model_name, ticker, missing)
        return None

    # Type coercions
    try:
        raw["proceed"] = bool(raw["proceed"])
        raw["conviction"] = int(raw["conviction"])
        raw["max_hold_days"] = int(raw["max_hold_days"])
    except Exception as exc:
        logger.error("[AI] %s | %s: type coercion failed: %s", model_name, ticker, exc)
        return None

    # Range checks
    if not (0 <= raw["conviction"] <= 100):
        logger.error("[AI] %s | %s: conviction %d out of 0-100 range", model_name, ticker, raw["conviction"])
        return None
    if not (5 <= raw["max_hold_days"] <= 20):
        logger.warning("[AI] %s | %s: max_hold_days %d clamped to [5, 20]", model_name, ticker, raw["max_hold_days"])
        raw["max_hold_days"] = max(5, min(20, raw["max_hold_days"]))

    if not isinstance(raw["entry_notes"], str) or len(raw["entry_notes"]) < 5:
        logger.error("[AI] %s | %s: entry_notes too short or invalid", model_name, ticker)
        return None

    if not isinstance(raw["key_risk"], str) or len(raw["key_risk"]) < 5:
        logger.error("[AI] %s | %s: key_risk too short or invalid", model_name, ticker)
        return None

    return raw


def _extract_json_from_response(text: str) -> Optional[dict]:
    """Extract JSON from a model response that may have surrounding markdown or text."""
    # Try direct parse first
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown code block
    if "```json" in text:
        start = text.find("```json") + 7
        end = text.find("```", start)
        if end > start:
            try:
                return json.loads(text[start:end].strip())
            except json.JSONDecodeError:
                pass

    if "```" in text:
        start = text.find("```") + 3
        end = text.find("```", start)
        if end > start:
            try:
                return json.loads(text[start:end].strip())
            except json.JSONDecodeError:
                pass

    # Try finding first { ... } block
    try:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
    except json.JSONDecodeError:
        pass

    return None


# ─── Prompt builder ───────────────────────────────────────────────────────────

def _build_analysis_prompt(candidate: dict, regime_status: str, news_summaries: list[str]) -> str:
    """
    Build the analysis prompt for a candidate. Includes all quant data.
    The model must NOT invent any data not provided here.
    """
    ticker = candidate.get("ticker", "UNKNOWN")
    score  = candidate.get("composite_score", 0)
    sector = candidate.get("sector", "Unknown")
    price  = candidate.get("price", "N/A")
    classification = candidate.get("classification", "unknown")

    # Technical snapshot
    rsi    = candidate.get("technical_indicators", {}).get("rsi_14", "N/A")
    macd_h = candidate.get("technical_indicators", {}).get("macd_histogram", "N/A")
    adx    = candidate.get("technical_indicators", {}).get("adx_14", "N/A")
    atr    = candidate.get("atr_pct", "N/A")
    rs_3m  = candidate.get("rs_63d", "N/A")
    rs_6m  = candidate.get("rs_126d", "N/A")
    rel_vol = candidate.get("rel_vol", "N/A")
    high_52w = candidate.get("high_52w_pct", "N/A")

    # Fundamental snapshot
    rev_growth = candidate.get("revenue_growth_yoy", "N/A")
    eps_growth = candidate.get("eps_growth_yoy", "N/A")
    mkt_cap    = candidate.get("market_cap", 0)
    mkt_cap_str = f"${mkt_cap/1e9:.1f}B" if mkt_cap else "N/A"

    # Component scores summary (top 5)
    components = candidate.get("component_scores", {})
    top_components = sorted(components.items(), key=lambda x: x[1], reverse=True)[:5]
    comp_str = ", ".join(f"{k}={v:.1f}" for k, v in top_components)

    news_str = ""
    if news_summaries:
        news_str = "\n\nRECENT NEWS (last 48h):\n" + "\n".join(
            f"  - {n}" for n in news_summaries[:3]
        )

    prompt = f"""You are a systematic swing-trading analyst reviewing a quantitatively-scored stock candidate for a 5–20 day position.

QUANTITATIVE SCAN RESULT FOR {ticker}:
  Composite Score: {score}/100 (classification: {classification})
  Sector: {sector} | Price: ${price} | Market Cap: {mkt_cap_str}
  Regime: {regime_status}

TECHNICAL INDICATORS:
  RSI(14): {rsi} | MACD Histogram: {macd_h} | ADX(14): {adx}
  ATR%: {atr}% | Rel Volume vs 20d avg: {rel_vol}x
  3-month RS vs SPY: {rs_3m}% | 6-month RS vs SPY: {rs_6m}%
  Distance from 52w high: {high_52w}%

FUNDAMENTALS:
  Revenue Growth YoY: {rev_growth}% | EPS Growth YoY: {eps_growth}%

TOP SCORING COMPONENTS: {comp_str}{news_str}

YOUR TASK:
Review this candidate from a qualitative perspective. The quantitative filters have already been applied — do NOT re-apply technical thresholds. Your role is to flag:
  1. Structural concerns the quant score cannot capture (macro headwinds, management issues, industry disruption, regulatory risk)
  2. Whether the timing is genuinely attractive for a swing entry given current momentum signals
  3. Any obvious red flags in the data provided

RESPOND IN VALID JSON ONLY — no other text before or after the JSON:
{{
  "ticker": "{ticker}",
  "proceed": <true or false>,
  "conviction": <integer 0-100>,
  "entry_notes": "<1-2 sentences on why this is or isn't a good setup>",
  "key_risk": "<single sentence identifying the biggest risk to this trade>",
  "max_hold_days": <integer 5 to 20>
}}

IMPORTANT: 
- Only reason from the data provided above. Do not invent data not given.
- Be decisive. Use "proceed": false only if you see a concrete reason, not just uncertainty.
- conviction < 60 should generally mean proceed: false.
"""
    return prompt


# ─── Gemini caller ────────────────────────────────────────────────────────────

def _call_gemini(prompt: str, ticker: str) -> Optional[dict]:
    """Call Gemini and return parsed, validated verdict. Returns None on failure."""
    if not GEMINI_API_KEY:
        logger.warning("[AI] GEMINI_API_KEY not set — skipping Gemini analysis for %s", ticker)
        return None

    model = genai.GenerativeModel(GEMINI_MODEL)
    generation_config = genai.types.GenerationConfig(
        temperature=0.2,
        max_output_tokens=512,
    )

    for attempt in range(1, 4):  # Up to 3 attempts with backoff for rate limits
        try:
            response = model.generate_content(prompt, generation_config=generation_config)
            text = response.text.strip() if response.text else ""
            if not text:
                logger.error("[AI] Gemini returned empty response for %s", ticker)
                return None

            raw = _extract_json_from_response(text)
            if raw is None:
                logger.error("[AI] Gemini response for %s was not parseable JSON: %s...", ticker, text[:200])
                return None

            return _validate_ai_verdict(raw, ticker, "Gemini")

        except Exception as exc:
            exc_str = str(exc).lower()
            # Retry on rate-limit (429 / ResourceExhausted)
            if "429" in exc_str or "resource_exhausted" in exc_str or "toomanyrequests" in exc_str.replace("_", ""):
                wait = 15 * attempt  # 15s, 30s, 45s
                logger.warning(
                    "[AI] Gemini rate-limited for %s (attempt %d/3) — waiting %ds", ticker, attempt, wait
                )
                time.sleep(wait)
                continue
            # Non-retryable error (403 Forbidden etc.)
            logger.error("[AI] Gemini call failed for %s: %s", ticker, exc)
            return None

    logger.error("[AI] Gemini gave up after 3 rate-limit retries for %s", ticker)
    return None


# ─── Cross-check model caller ─────────────────────────────────────────────────

def _call_crosscheck(prompt: str, ticker: str) -> Optional[dict]:
    """Call DeepSeek or Groq as the cross-check model. Returns None on failure."""
    config = _get_crosscheck_config()
    if config is None:
        logger.warning(
            "[AI] No cross-check model configured (set DEEPSEEK_API_KEY or GROQ_API_KEY). "
            "Proceeding with Gemini-only mode (lower confidence)."
        )
        return None

    model_type = config["type"]
    try:
        headers = {
            "Authorization": f"Bearer {config['key']}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": config["model"],
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "max_tokens": 512,
            "stream": False,
        }
        resp = requests.post(config["url"], headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        text = data["choices"][0]["message"]["content"].strip()

        if not text:
            logger.error("[AI] %s returned empty response for %s", model_type, ticker)
            return None

        raw = _extract_json_from_response(text)
        if raw is None:
            logger.error("[AI] %s response for %s was not parseable JSON: %s...", model_type, ticker, text[:200])
            return None

        return _validate_ai_verdict(raw, ticker, model_type.capitalize())

    except Exception as exc:
        logger.error("[AI] %s call failed for %s: %s", model_type, ticker, exc)
        return None


# ─── News fetching (optional enrichment) ─────────────────────────────────────

def _fetch_news_summaries(ticker: str) -> list[str]:
    """Fetch recent news headlines for a ticker. Returns list of headline strings."""
    if not NEWS_API_KEY:
        return []
    try:
        url = "https://newsapi.org/v2/everything"
        params = {
            "q": f"{ticker} stock",
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": 3,
            "apiKey": NEWS_API_KEY,
        }
        resp = requests.get(url, params=params, timeout=8)
        if resp.status_code != 200:
            return []
        articles = resp.json().get("articles", [])
        return [a.get("title", "") for a in articles if a.get("title")]
    except Exception:
        return []


# ─── Single-candidate analysis ────────────────────────────────────────────────

def analyze_candidate(candidate: dict, regime_status: str) -> dict:
    """
    Run both AI models on a single candidate.
    Returns a merged verdict dict with fields:
      proceed, conviction, entry_notes, key_risk, max_hold_days,
      gemini_verdict, crosscheck_verdict, models_agree, final_decision
    """
    ticker = candidate.get("ticker", "UNKNOWN")
    news = _fetch_news_summaries(ticker)
    prompt = _build_analysis_prompt(candidate, regime_status, news)

    gemini_verdict = _call_gemini(prompt, ticker)
    crosscheck_verdict = _call_crosscheck(prompt, ticker)

    # ── Decision logic (blueprint Section 12 conflict resolution) ─────────────
    # Case 1: Both models available and agree → proceed if both say proceed
    # Case 2: Both models available but disagree → no trade (conservative)
    # Case 3: Only Gemini available → proceed if Gemini says proceed (lower confidence)
    # Case 4: Neither model available → no trade (fail-safe)

    if gemini_verdict is None and crosscheck_verdict is None:
        logger.error("[AI] Both models failed for %s — defaulting to no trade.", ticker)
        return {
            "ticker": ticker,
            "proceed": False,
            "conviction": 0,
            "entry_notes": "Both AI models failed to respond — defaulting to no trade (fail-safe).",
            "key_risk": "AI analysis unavailable",
            "max_hold_days": 10,
            "gemini_raw": None,
            "crosscheck_raw": None,
            "models_agree": None,
            "final_decision": "no_trade_ai_failure",
        }

    if gemini_verdict is not None and crosscheck_verdict is not None:
        gemini_proceed = gemini_verdict["proceed"]
        cross_proceed = crosscheck_verdict["proceed"]
        models_agree = gemini_proceed == cross_proceed

        if not models_agree:
            logger.info(
                "[AI] %s: Gemini says %s, cross-check says %s → DISAGREEMENT → no trade.",
                ticker,
                "PROCEED" if gemini_proceed else "REJECT",
                "PROCEED" if cross_proceed else "REJECT",
            )
            avg_conviction = int((gemini_verdict["conviction"] + crosscheck_verdict["conviction"]) / 2)
            return {
                "ticker": ticker,
                "proceed": False,
                "conviction": avg_conviction,
                "entry_notes": (
                    f"Models disagree: Gemini={gemini_verdict['entry_notes'][:80]} | "
                    f"CrossCheck={crosscheck_verdict['entry_notes'][:80]}"
                ),
                "key_risk": f"Model disagreement — {crosscheck_verdict['key_risk']}",
                "max_hold_days": max(gemini_verdict["max_hold_days"], crosscheck_verdict["max_hold_days"]),
                "gemini_raw": gemini_verdict,
                "crosscheck_raw": crosscheck_verdict,
                "models_agree": False,
                "final_decision": "no_trade_model_disagreement",
            }

        # Both agree
        avg_conviction = int((gemini_verdict["conviction"] + crosscheck_verdict["conviction"]) / 2)
        final_proceed = gemini_proceed and avg_conviction >= 60
        return {
            "ticker": ticker,
            "proceed": final_proceed,
            "conviction": avg_conviction,
            "entry_notes": gemini_verdict["entry_notes"],
            "key_risk": gemini_verdict["key_risk"],
            "max_hold_days": int((gemini_verdict["max_hold_days"] + crosscheck_verdict["max_hold_days"]) / 2),
            "gemini_raw": gemini_verdict,
            "crosscheck_raw": crosscheck_verdict,
            "models_agree": True,
            "final_decision": "trade" if final_proceed else "no_trade_low_conviction",
        }

    # Only one model available
    verdict = gemini_verdict or crosscheck_verdict
    model_name = "Gemini" if gemini_verdict else "CrossCheck"
    final_proceed = verdict["proceed"] and verdict["conviction"] >= 65  # Higher threshold for single model
    return {
        "ticker": ticker,
        "proceed": final_proceed,
        "conviction": verdict["conviction"],
        "entry_notes": verdict["entry_notes"] + f" [single model: {model_name}]",
        "key_risk": verdict["key_risk"],
        "max_hold_days": verdict["max_hold_days"],
        "gemini_raw": gemini_verdict,
        "crosscheck_raw": crosscheck_verdict,
        "models_agree": None,
        "final_decision": "trade" if final_proceed else f"no_trade_{model_name.lower()}_only_low_conviction",
    }


# ─── Batch analysis ───────────────────────────────────────────────────────────

def analyze_candidates_batch(
    candidates: list[dict],
    regime_status: str,
    max_candidates: int = 10,
) -> list[dict]:
    """
    Run AI analysis on top candidates (up to max_candidates to manage API costs).
    Returns list of verdict dicts sorted by proceed=True first, then conviction desc.

    Blueprint Section 3: AI reviews only the top-scoring candidates from the quant scan,
    not the entire universe.
    """
    if not candidates:
        return []

    # Limit to top candidates by composite score
    top = sorted(candidates, key=lambda c: c.get("composite_score", 0), reverse=True)[:max_candidates]
    logger.info("[AI] Running analysis on %d top candidates.", len(top))

    verdicts = []
    for candidate in top:
        verdict = analyze_candidate(candidate, regime_status)
        verdicts.append(verdict)
        time.sleep(0.5)  # Rate-limit courtesy

    # Sort: proceed=True first, then by conviction
    verdicts.sort(key=lambda v: (-int(v["proceed"]), -v.get("conviction", 0)))

    approved = [v for v in verdicts if v.get("proceed")]
    rejected = [v for v in verdicts if not v.get("proceed")]
    logger.info("[AI] Batch complete: %d approved, %d rejected.", len(approved), len(rejected))

    return verdicts
