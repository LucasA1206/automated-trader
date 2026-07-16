"""
validation_post_fix.py — Step 3 validation script
Runs the full scoring pipeline for 8 representative tickers using the fixed
data_layer.py and scoring_engine.py, then prints a before/after comparison.
"""
import sys, os, logging, json
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))
logging.basicConfig(level=logging.WARNING)  # suppress info noise for clean output

from dotenv import load_dotenv
load_dotenv(".env.local")

from backend.strategy.data_layer import (
    fetch_ohlcv, fetch_fundamentals, fetch_sector_etf_returns
)
from backend.strategy.scoring_engine import (
    compute_composite_score, WEIGHTS, MAX_POSITIVE_WEIGHT,
    SCORE_HIGH_CONVICTION, SCORE_MARGINAL
)

# Known-broken thresholds (pre-fix) vs restored
PRE_FIX_HIGH  = 65.0
PRE_FIX_MARG  = 45.0
POST_FIX_HIGH = SCORE_HIGH_CONVICTION  # 70.0
POST_FIX_MARG = SCORE_MARGINAL         # 55.0

TICKERS = ["FRD", "STRZ", "SYRE", "CLDT", "GEO", "AMN", "NWPX", "MOV"]

print(f"{'='*90}")
print(f"Post-fix validation — scoring thresholds: HC≥{POST_FIX_HIGH} / Marginal≥{POST_FIX_MARG}")
print(f"{'='*90}\n")

print("Fetching sector ETF returns…")
sector_returns = fetch_sector_etf_returns()
print(f"  Got returns for sectors: {', '.join(sector_returns.keys())}\n")

results = []

for ticker in TICKERS:
    print(f"Processing {ticker}…")
    df = fetch_ohlcv(ticker, period="1y")
    fundamentals = fetch_fundamentals(ticker) or {}

    if df is None or df.empty:
        print(f"  [SKIP] No OHLCV data for {ticker}")
        continue

    closes = df["Close"]
    current_price = float(closes.iloc[-1])
    period_vol = min(20, len(df))
    avg_vol_20  = float(df["Volume"].iloc[-period_vol:].mean())
    avg_price_20 = float(closes.iloc[-period_vol:].mean())
    avg_dollar_vol_20 = avg_vol_20 * avg_price_20
    latest_vol = float(df["Volume"].iloc[-1])
    rel_vol = latest_vol / avg_vol_20 if avg_vol_20 > 0 else 1.0
    period = min(252, len(df))
    high_52w = float(df["High"].iloc[-period:].max())
    high_52w_pct = (current_price - high_52w) / high_52w * 100

    metrics = {
        "ticker": ticker,
        "price": current_price,
        "ohlcv_df": df,
        "rs_63d": 20.0,   # fixed high RS for comparison parity with pre-fix test
        "rs_126d": 20.0,
        "rel_vol": rel_vol,
        "high_52w_pct": high_52w_pct,
        "avg_dollar_vol_20d": avg_dollar_vol_20,
        "market_cap": fundamentals.get("market_cap", 0),
        "float_shares": fundamentals.get("float_shares"),
        "sector": fundamentals.get("sector", "Unknown"),
        "industry": fundamentals.get("industry", "Unknown"),
        "revenue_growth_yoy": fundamentals.get("revenue_growth_yoy"),
        "eps_growth_yoy": fundamentals.get("eps_growth_yoy"),
        "fcf_positive": fundamentals.get("fcf_positive"),
        "net_debt_ebitda": fundamentals.get("net_debt_ebitda"),
        "profit_margin": fundamentals.get("profit_margin"),
        "return_on_equity": fundamentals.get("return_on_equity"),
        "beta": fundamentals.get("beta"),
        "institutional_ownership_pct": fundamentals.get("institutional_ownership_pct"),
        "short_interest_pct_float": fundamentals.get("short_interest_pct_float"),
    }

    result = compute_composite_score(metrics, [metrics], sector_returns)
    results.append((ticker, fundamentals, result))

print(f"\n{'='*90}")
print("RESULTS")
print(f"{'='*90}\n")

HEADER = f"{'Ticker':<6} {'Score':>6} {'EffDenom':>9} {'Gaps':>5} {'Classification':<18} {'ICB Industry → GICS Sector'}"
print(HEADER)
print("-" * len(HEADER))

for ticker, fund, r in results:
    score    = r["composite_score"]
    eff_w    = r["effective_max_weight"]
    gaps     = r["data_gaps"]
    cls      = r["classification"].upper()
    industry = fund.get("industry", "?")
    sector   = fund.get("sector", "?")
    flag     = "✅" if cls == "HIGH_CONVICTION" else ("⚠️" if cls == "MARGINAL" else "❌")
    print(f"{ticker:<6} {score:>6.1f} {eff_w:>9} {len(gaps):>5}   {flag} {cls:<16} {industry} → {sector}")

print()
print("FUNDAMENTAL DATA RECEIVED (raw values from fixed fetch_fundamentals):")
print("-" * 70)
for ticker, fund, r in results:
    gaps = r["data_gaps"]
    rev_g  = fund.get("revenue_growth_yoy")
    eps_g  = fund.get("eps_growth_yoy")
    fcf    = fund.get("fcf_positive")
    nd_eb  = fund.get("net_debt_ebitda")
    margin = fund.get("profit_margin")
    beta   = fund.get("beta")
    print(f"\n{ticker}:")
    print(f"  revenue_growth_yoy : {rev_g!r:>12}  {'⚫ GAP' if 'revenue_growth' in gaps else ''}")
    print(f"  eps_growth_yoy     : {eps_g!r:>12}  {'⚫ GAP' if 'eps_growth' in gaps else ''}")
    print(f"  fcf_positive       : {fcf!r:>12}  {'⚫ GAP' if 'fcf_quality' in gaps else ''}")
    print(f"  net_debt_ebitda    : {nd_eb!r:>12}  {'⚫ GAP' if 'debt_ratio' in gaps else ''}")
    print(f"  profit_margin (%)  : {margin!r:>12}  {'⚫ GAP' if 'profit_margins' in gaps else ''}")
    print(f"  beta               : {beta!r:>12}  {'⚫ GAP' if 'beta' in gaps else ''}")
    print(f"  sector (GICS)      : {fund.get('sector','?')}")
    print(f"  all_gaps           : {', '.join(sorted(gaps)) or 'none'}")

print()
print("PER-METRIC SUB-SCORES (first ticker detail):")
print("-" * 70)
if results:
    _, _, r = results[0]
    sub  = r["sub_scores"]
    gaps = set(r["data_gaps"])
    for k in sorted(WEIGHTS.keys()):
        s  = sub.get(k, 0.0)
        ws = s * WEIGHTS[k]
        gflag = "⚫ EXCLUDED (gap)" if k in gaps else ""
        print(f"  {k:<24} sub={s:.3f}  × {WEIGHTS[k]:>2}  =  {ws:>6.2f}  {gflag}")
    pens = r["penalties"]
    print(f"  {'short_interest_penalty':<24} penalty={pens['short_interest']:.2f}")
    print(f"  {'gap_history_penalty':<24} penalty={pens['gap_history']:.2f}")
    print(f"\n  effective_max_weight = {r['effective_max_weight']} / {MAX_POSITIVE_WEIGHT}")
    print(f"  composite_score      = {r['composite_score']}/100")

print(f"\n{'='*90}")
print(f"Thresholds: HIGH_CONVICTION≥{POST_FIX_HIGH}  MARGINAL≥{POST_FIX_MARG}")
print(f"Pre-fix thresholds were: HC≥{PRE_FIX_HIGH}  MARG≥{PRE_FIX_MARG}")
print(f"{'='*90}")
