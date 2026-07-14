import sys
import os
import logging
import json

# Add backend directory to path
sys.path.append(os.path.join(os.path.dirname(__file__), 'backend'))
logging.basicConfig(level=logging.INFO)

from dotenv import load_dotenv
load_dotenv('.env.local')

from backend.strategy.data_layer import fetch_ohlcv, fetch_fundamentals
from backend.strategy.scoring_engine import compute_composite_score, WEIGHTS, MAX_POSITIVE_WEIGHT

ticker = "STRZ"
df = fetch_ohlcv(ticker, period="1y")
fundamentals = fetch_fundamentals(ticker)

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
    "rs_63d": 20.0, # Dummy high RS
    "rs_126d": 20.0, # Dummy high RS
    "rel_vol": rel_vol,
    "high_52w_pct": high_52w_pct,
    "avg_dollar_vol_20d": avg_dollar_vol_20,
    "market_cap": fundamentals.get("market_cap", 0) if fundamentals else 0,
    "float_shares": fundamentals.get("float_shares") if fundamentals else None,
    "sector": fundamentals.get("sector", "Unknown") if fundamentals else "Unknown",
    "industry": fundamentals.get("industry", "Unknown") if fundamentals else "Unknown",
    "revenue_growth_yoy": fundamentals.get("revenue_growth_yoy") if fundamentals else None,
    "eps_growth_yoy": fundamentals.get("eps_growth_yoy") if fundamentals else None,
    "fcf_positive": fundamentals.get("fcf_positive") if fundamentals else None,
    "net_debt_ebitda": fundamentals.get("net_debt_ebitda") if fundamentals else None,
    "profit_margin": fundamentals.get("profit_margin") if fundamentals else None,
    "beta": fundamentals.get("beta") if fundamentals else None,
    "institutional_ownership_pct": fundamentals.get("institutional_ownership_pct") if fundamentals else None,
    "short_interest_pct_float": fundamentals.get("short_interest_pct_float") if fundamentals else None,
}

result = compute_composite_score(metrics, [metrics], {})

print("\n--- COMPONENT BREAKDOWN (weighted sub-scores / max weight) ---")
for k, v in sorted(result["component_scores"].items(), key=lambda x: x[1], reverse=True):
    print(f"{k}: {v:.2f} / {WEIGHTS.get(k, 0)}")

print(f"\nRaw Score Sum: {sum(result['component_scores'].values()):.2f}")
print(f"Max Possible Weight: {MAX_POSITIVE_WEIGHT}")
print(f"Normalized Score: {result['composite_score']}/100")
