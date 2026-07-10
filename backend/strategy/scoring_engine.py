"""
Scoring Engine — Phase 2
========================
Implements the weighted composite scoring algorithm from blueprint Section 5.

Score = sum(metric_sub_score × weight) / max_possible_score × 100  →  0–100

Each metric is normalized to a 0–1 sub-score (percentile rank within the
surviving universe OR absolute threshold mapping) before multiplying by weight.

Weights per blueprint Section 4/5:
  Momentum/RS (3m+6m):    15   — Core edge: cross-sectional momentum signal
  52-week high proximity:  8   — No overhead supply = continuation setup
  Relative volume:         8   — Confirms real buying interest
  RSI 40-55:               8   — Pullback entry zone within uptrend
  Sector RS:               5   — Swimming with the tide
  Market cap band:         5   — Liquidity/stability preference ($2B–$50B sweet spot)
  ADX (trend strength):    6   — Trend quality, soft mandatory (0 if ADX < 15)
  Breakout/BB quality:     6   — Coiled spring before move
  Revenue growth:          6   — Fundamental backing for momentum
  MACD histogram:          5   — Momentum turning confirmation
  EPS growth:              5   — Quality overlay
  FCF quality:             5   — Cash generation (semi-mandatory)
  Debt/EBITDA:             4   — Balance sheet risk
  Float size:              4   — Execution risk preference
  Bollinger position:      4   — Entry zone confirmation
  Beta:                    3   — Systemic risk filter
  Profit margin / ROE:     3   — Quality proxy
  Analyst revisions:       3   — External conviction signal
  Institutional ownership: 2   — Scrutiny/quality proxy
  Insider buying:          2   — Conviction signal (rare but meaningful)
  Options activity:        2   — Unusual conviction (optional)
  Short interest penalty: -3   — Squeeze risk caution (>20% float)
  Gap history penalty:    -3   — Overnight tail risk

Total positive weights: ~115. Normalized to 0-100 output.

CRITICAL: Score never overrides a failed mandatory filter (Section 5 Step 1).
          This module only runs AFTER universe_filter.py has approved candidates.
"""

import logging
import math
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# ─── Weight constants (blueprint Section 4/5) ─────────────────────────────────
WEIGHTS = {
    "relative_strength":     15,  # 3m + 6m combined momentum
    "high_52w_proximity":     8,  # distance from 52-week high
    "relative_volume":        8,  # current vol vs 20d avg
    "rsi_zone":               8,  # RSI 40-55 pullback zone
    "sector_rs":              5,  # sector relative strength
    "market_cap_band":        5,  # $2B–$50B preference
    "adx_trend":              6,  # ADX ≥ 20 trend quality
    "breakout_quality":       6,  # Bollinger band width contraction
    "revenue_growth":         6,  # YoY revenue growth
    "macd_histogram":         5,  # MACD histogram direction
    "eps_growth":             5,  # EPS growth YoY
    "fcf_quality":            5,  # Free cash flow positive
    "debt_ratio":             4,  # net debt/EBITDA < 3x
    "float_size":             4,  # float ≥ 20M preference
    "bollinger_position":     4,  # price position in band
    "beta":                   3,  # 0.8–1.8 band preference
    "profit_margins":         3,  # quality proxy
    "analyst_revisions":      3,  # external conviction
    "institutional_own":      2,  # 20%–90% range preferred
    "insider_buying":         2,  # scoring bonus only (sparse data)
    "options_activity":       2,  # optional conviction signal
}

PENALTIES = {
    "short_interest":        -3,  # > 20% float short interest
    "gap_history":           -3,  # frequent large overnight gaps
}

MAX_POSITIVE_WEIGHT = sum(WEIGHTS.values())  # ~115

# Scoring thresholds per blueprint Section 5 Step 3
SCORE_HIGH_CONVICTION = 70.0    # Full size eligibility
SCORE_MARGINAL = 55.0           # Half size, capacity-limited
SCORE_NO_TRADE = 55.0           # Below this = not tradable


# ─── Technical indicator helpers ──────────────────────────────────────────────

def _compute_rsi(closes: pd.Series, period: int = 14) -> Optional[float]:
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


def _compute_macd_histogram(closes: pd.Series) -> Optional[float]:
    if closes is None or len(closes) < 26:
        return None
    ema12 = closes.ewm(span=12, adjust=False).mean()
    ema26 = closes.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal = macd_line.ewm(span=9, adjust=False).mean()
    histogram = macd_line - signal
    return float(histogram.iloc[-1])


def _compute_adx(df: pd.DataFrame, period: int = 14) -> Optional[float]:
    """Compute ADX from OHLCV DataFrame using Wilder's smoothing."""
    if df is None or len(df) < period * 2:
        return None
    try:
        highs  = df["High"]
        lows   = df["Low"]
        closes = df["Close"]

        plus_dm  = (highs.diff()).clip(lower=0)
        minus_dm = (-lows.diff()).clip(lower=0)
        # True direction: take larger move, zero out the smaller
        condition = plus_dm >= minus_dm
        plus_dm  = plus_dm.where(condition, 0)
        minus_dm = minus_dm.where(~condition, 0)

        tr = pd.concat([
            highs - lows,
            (highs - closes.shift()).abs(),
            (lows  - closes.shift()).abs(),
        ], axis=1).max(axis=1)

        atr_smooth  = tr.ewm(alpha=1/period, adjust=False).mean()
        pdm_smooth  = plus_dm.ewm(alpha=1/period, adjust=False).mean()
        mdm_smooth  = minus_dm.ewm(alpha=1/period, adjust=False).mean()

        pdi = (pdm_smooth / atr_smooth * 100).fillna(0)
        mdi = (mdm_smooth / atr_smooth * 100).fillna(0)
        dx  = ((pdi - mdi).abs() / (pdi + mdi).replace(0, 1) * 100)
        adx = dx.ewm(alpha=1/period, adjust=False).mean()
        val = float(adx.iloc[-1])
        return round(val, 2) if not math.isnan(val) else None
    except Exception:
        return None


def _compute_bollinger(closes: pd.Series, window: int = 20, num_std: float = 2.0) -> Optional[dict]:
    """
    Compute Bollinger Bands and derive:
      - band_width: (upper - lower) / middle (lower = coiling spring)
      - %B position: where price sits in the band (0=lower, 1=upper)
    """
    if closes is None or len(closes) < window:
        return None
    try:
        rolling_mean = closes.rolling(window).mean()
        rolling_std  = closes.rolling(window).std()
        upper = rolling_mean + num_std * rolling_std
        lower = rolling_mean - num_std * rolling_std

        mid_val   = float(rolling_mean.iloc[-1])
        upper_val = float(upper.iloc[-1])
        lower_val = float(lower.iloc[-1])
        current   = float(closes.iloc[-1])

        band_width = (upper_val - lower_val) / mid_val if mid_val > 0 else None
        band_pct_b = ((current - lower_val) / (upper_val - lower_val)
                      if upper_val != lower_val else 0.5)
        return {
            "band_width": round(band_width, 4) if band_width is not None else None,
            "pct_b": round(band_pct_b, 3),
        }
    except Exception:
        return None


def _compute_gap_history_penalty(df: pd.DataFrame, threshold_pct: float = 3.0, lookback: int = 60) -> float:
    """
    Compute a gap-history penalty score (0.0 = no penalty, 1.0 = max penalty).
    Frequent large overnight gaps (> threshold_pct%) raise the penalty.
    """
    if df is None or len(df) < 5:
        return 0.0
    try:
        period = min(lookback, len(df) - 1)
        closes = df["Close"].iloc[-period-1:]
        opens  = df["Open"].iloc[-period:]
        gaps   = ((opens.values - closes.values[:-1]) / closes.values[:-1] * 100)
        large_gaps = sum(1 for g in gaps if abs(g) > threshold_pct)
        freq = large_gaps / period
        # Scale: 0 gaps = 0.0 penalty, 10%+ of days = 1.0 penalty
        return min(freq / 0.10, 1.0)
    except Exception:
        return 0.0


# ─── Sub-score normalisation helpers ──────────────────────────────────────────

def _percentile_rank(value: Optional[float], values_in_universe: list) -> float:
    """Normalize a value to [0, 1] by its percentile rank in the universe."""
    if value is None or not values_in_universe:
        return 0.0
    valid = [v for v in values_in_universe if v is not None]
    if not valid:
        return 0.0
    rank = sum(1 for v in valid if v <= value)
    return rank / len(valid)


def _threshold_score(value: Optional[float], thresholds: list[tuple]) -> float:
    """
    Map a value to [0, 1] using a list of (threshold, score) breakpoints.
    Returns the score for the highest threshold the value exceeds.
    thresholds should be sorted ascending: [(min_val, sub_score), ...]
    """
    if value is None:
        return 0.0
    score = 0.0
    for threshold, sub_score in thresholds:
        if value >= threshold:
            score = sub_score
    return min(score, 1.0)


def _bool_score(value: Optional[bool], true_score: float = 1.0) -> float:
    if value is True:
        return true_score
    return 0.0


# ─── Individual metric scorers ────────────────────────────────────────────────

def score_relative_strength(rs_63d: Optional[float], rs_126d: Optional[float],
                             universe_rs_63d: list, universe_rs_126d: list) -> float:
    """Combined 3m + 6m relative strength score (weight: 15). Percentile-ranked."""
    s_63 = _percentile_rank(rs_63d, universe_rs_63d)
    s_126 = _percentile_rank(rs_126d, universe_rs_126d)
    # Weight 3m slightly higher (more recent momentum)
    return (s_63 * 0.6 + s_126 * 0.4)


def score_52w_high_proximity(high_52w_pct: Optional[float]) -> float:
    """Score proximity to 52-week high. Within 10% = max score. (weight: 8)"""
    # pct is negative (stock is below high) — closer to 0 = better
    if high_52w_pct is None:
        return 0.3  # neutral if unknown
    # Within 5% = 1.0, within 10% = 0.7, within 15% = 0.4, beyond = 0.1
    return _threshold_score(-high_52w_pct, [  # negate so higher = closer
        (0.0, 0.1),    # any distance
        (85.0, 0.2),   # more than 15% below
        (90.0, 0.5),   # within 10%
        (95.0, 0.8),   # within 5%
        (99.0, 1.0),   # within 1%
    ])


def score_relative_volume(rel_vol: Optional[float]) -> float:
    """Score relative volume (current vs 20d avg). Blueprint: ≥1.2× preferred. (weight: 8)"""
    return _threshold_score(rel_vol, [
        (0.0,  0.0),
        (0.8,  0.2),
        (1.0,  0.4),
        (1.2,  0.7),
        (1.5,  0.9),
        (2.0,  1.0),
    ])


def score_rsi_zone(rsi: Optional[float]) -> float:
    """
    Score RSI position. Blueprint: target 40–55 pullback zone. (weight: 8)
    Peak score in the pullback zone (not overbought, not oversold).
    """
    if rsi is None:
        return 0.3
    if 40 <= rsi <= 55:
        return 1.0
    if 35 <= rsi < 40 or 55 < rsi <= 60:
        return 0.6
    if 30 <= rsi < 35 or 60 < rsi <= 65:
        return 0.3
    return 0.0  # RSI < 30 (oversold/breaking) or > 65 (overbought)


def score_sector_rs(sector: Optional[str], sector_returns: dict[str, float],
                    universe_sector_returns: list[float]) -> float:
    """Score sector relative strength vs all sectors. (weight: 5)"""
    if not sector or not sector_returns:
        return 0.3
    sector_ret = sector_returns.get(sector)
    if sector_ret is None:
        return 0.3
    return _percentile_rank(sector_ret, universe_sector_returns)


def score_market_cap_band(market_cap: Optional[float]) -> float:
    """
    Score market cap band preference. $2B–$50B sweet spot per blueprint. (weight: 5)
    Mandatory floor is $500M (already filtered); this rewards the preferred band.
    """
    if not market_cap or market_cap <= 0:
        return 0.0
    cap_b = market_cap / 1e9
    if 2.0 <= cap_b <= 50.0:
        return 1.0
    if 1.0 <= cap_b < 2.0 or 50.0 < cap_b <= 100.0:
        return 0.6
    if 0.5 <= cap_b < 1.0:
        return 0.3
    if cap_b > 100.0:
        return 0.4  # Mega caps: deep liquidity but slower movement
    return 0.1


def score_adx(adx: Optional[float]) -> float:
    """
    Score ADX trend quality. Blueprint: soft mandatory — score 0 if ADX < 15.
    ≥ 20 preferred; ≥ 25 stronger. (weight: 6)
    """
    if adx is None:
        return 0.3
    if adx < 15:
        return 0.0   # Soft mandatory: score 0 below 15
    return _threshold_score(adx, [
        (15, 0.2),
        (20, 0.5),
        (25, 0.8),
        (30, 1.0),
    ])


def score_breakout_quality(band_width: Optional[float],
                           universe_bw: list[float]) -> float:
    """
    Score breakout quality via Bollinger Band width contraction.
    Lower band width = tighter coiling = higher quality setup. (weight: 6)
    Reversed percentile: stocks with lower band_width (tighter compression) score higher.
    """
    if band_width is None:
        return 0.3
    # Invert: lower BW is better (tighter compression = coiled spring)
    return 1.0 - _percentile_rank(band_width, universe_bw)


def score_revenue_growth(rev_growth: Optional[float]) -> float:
    """Score YoY revenue growth. Blueprint: > 0% mandatory-lite, > 10% preferred. (weight: 6)"""
    if rev_growth is None:
        return 0.2
    if rev_growth < 0:
        return 0.0
    return _threshold_score(rev_growth, [
        (0,   0.2),
        (5,   0.4),
        (10,  0.7),
        (20,  0.9),
        (30,  1.0),
    ])


def score_macd_histogram(macd_hist: Optional[float],
                         prev_macd_hist: Optional[float]) -> float:
    """
    Score MACD histogram direction. Blueprint: turning upward after pullback. (weight: 5)
    Positive and rising = strong; negative but rising = setup forming.
    """
    if macd_hist is None:
        return 0.3
    if macd_hist > 0 and (prev_macd_hist is None or macd_hist > prev_macd_hist):
        return 1.0   # Positive and rising
    if macd_hist > 0:
        return 0.7   # Positive but flat/falling
    if macd_hist < 0 and (prev_macd_hist is not None and macd_hist > prev_macd_hist):
        return 0.5   # Negative but recovering (troughing)
    return 0.1       # Negative and falling


def score_eps_growth(eps_growth: Optional[float]) -> float:
    """Score EPS growth YoY. (weight: 5)"""
    if eps_growth is None:
        return 0.2
    if eps_growth < 0:
        return 0.0
    return _threshold_score(eps_growth, [
        (0,   0.2),
        (5,   0.4),
        (10,  0.6),
        (20,  0.8),
        (30,  1.0),
    ])


def score_fcf(fcf_positive: Optional[bool]) -> float:
    """Score free cash flow quality. (weight: 5, semi-mandatory)"""
    if fcf_positive is True:
        return 1.0
    if fcf_positive is None:
        return 0.4  # Unknown: moderate penalty
    return 0.0      # Negative FCF: zero score (heavily penalized)


def score_debt(net_debt_ebitda: Optional[float]) -> float:
    """Score debt level. Blueprint: prefer net debt/EBITDA < 3x. (weight: 4)"""
    if net_debt_ebitda is None:
        return 0.3
    if net_debt_ebitda < 0:
        return 1.0  # Net cash position
    return _threshold_score(-net_debt_ebitda, [  # lower is better → negate
        (-99,  0.0),
        (-5.0, 0.2),
        (-3.0, 0.5),
        (-2.0, 0.7),
        (-1.0, 0.9),
        (0.0,  1.0),  # debt < 0 already handled above
    ])


def score_float(float_shares: Optional[float]) -> float:
    """Score float size. Blueprint: ≥ 20M preferred to avoid low-float volatility. (weight: 4)"""
    if not float_shares or float_shares <= 0:
        return 0.2
    float_m = float_shares / 1e6  # in millions
    return _threshold_score(float_m, [
        (0,    0.1),
        (10,   0.3),
        (20,   0.6),
        (50,   0.8),
        (100,  1.0),
    ])


def score_bollinger_position(pct_b: Optional[float]) -> float:
    """
    Score Bollinger Band position for entry timing. Blueprint: mid-band pullback preferred. (weight: 4)
    %B ~ 0.3–0.5 = in pullback zone (best); near 1.0 = overbought (worst for entry).
    """
    if pct_b is None:
        return 0.3
    if 0.25 <= pct_b <= 0.50:
        return 1.0
    if 0.15 <= pct_b < 0.25 or 0.50 < pct_b <= 0.65:
        return 0.6
    if 0.0 <= pct_b < 0.15:
        return 0.2  # Near lower band — oversold risk
    if 0.65 < pct_b <= 0.80:
        return 0.3
    return 0.0   # Above upper band — chasing top


def score_beta(beta: Optional[float]) -> float:
    """Score beta. Blueprint: prefer 0.8–1.8 band. (weight: 3)"""
    if beta is None:
        return 0.4
    return _threshold_score(beta, [
        (0.0,  0.1),
        (0.5,  0.4),
        (0.8,  0.8),
        (1.0,  1.0),  # 1.0–1.8 = ideal range
        (1.8,  0.6),
        (2.5,  0.1),
    ]) if beta <= 2.5 else 0.0


def score_profit_margins(profit_margin: Optional[float]) -> float:
    """Score profit margins. (weight: 3)"""
    if profit_margin is None:
        return 0.2
    if profit_margin < 0:
        return 0.0
    return _threshold_score(profit_margin, [
        (0,    0.1),
        (5,    0.4),
        (10,   0.6),
        (15,   0.8),
        (20,   1.0),
    ])


def score_institutional_ownership(inst_own_pct: Optional[float]) -> float:
    """Score institutional ownership. Blueprint: 20%–90% preferred. (weight: 2)"""
    if inst_own_pct is None:
        return 0.3
    if 20 <= inst_own_pct <= 90:
        return 1.0
    if 10 <= inst_own_pct < 20:
        return 0.5
    if inst_own_pct > 90:
        return 0.3  # Heavy crowding risk
    return 0.1      # Very low institutional interest


def score_short_interest_penalty(short_pct: Optional[float]) -> float:
    """
    Penalty for high short interest. Blueprint: > 20% float = caution flag. (weight: -3)
    Returns 0.0–1.0 (1.0 = full penalty applied).
    """
    if short_pct is None:
        return 0.0
    if short_pct > 30:
        return 1.0
    if short_pct > 20:
        return 0.6
    if short_pct > 15:
        return 0.2
    return 0.0


# ─── Composite scoring ────────────────────────────────────────────────────────

def compute_composite_score(
    metrics: dict,
    universe_metrics: list[dict],
    sector_returns: dict[str, float],
) -> dict:
    """
    Compute the weighted composite score (0–100) for a single candidate.

    Args:
        metrics:          Ticker metrics dict from universe_filter
        universe_metrics: Full list of all surviving ticker dicts (for percentile ranking)
        sector_returns:   Sector ETF return data (from data_layer)

    Returns dict with:
        composite_score   : float 0–100
        component_scores  : dict of each metric's raw sub-score × weight
        classification    : "high_conviction" | "marginal" | "no_trade"
        technical_data    : dict of computed indicators
    """
    df: pd.DataFrame = metrics.get("ohlcv_df")
    closes = df["Close"] if df is not None else None

    # ── Compute indicators not pre-computed in filter stage ──────────────────
    rsi14 = _compute_rsi(closes, 14) if closes is not None else None
    macd_hist = _compute_macd_histogram(closes) if closes is not None else None
    adx14 = _compute_adx(df, 14) if df is not None else None
    bb = _compute_bollinger(closes, 20, 2.0) if closes is not None else None

    # Previous MACD histogram for direction
    prev_macd_hist = None
    if closes is not None and len(closes) >= 27:
        prev_hist = _compute_macd_histogram(closes.iloc[:-1])
        prev_macd_hist = prev_hist

    gap_penalty_score = _compute_gap_history_penalty(df) if df is not None else 0.0

    # Small-universe guard: with < 5 candidates, percentile-rank scoring is
    # meaningless (1 stock = 100th percentile). Flag it so the scorers can
    # fall back to absolute thresholds.
    _small_universe = len(universe_metrics) < 5

    # ── Collect universe values for percentile ranking ───────────────────────
    u_rs_63d  = [m.get("rs_63d")  for m in universe_metrics if m.get("rs_63d")  is not None]
    u_rs_126d = [m.get("rs_126d") for m in universe_metrics if m.get("rs_126d") is not None]
    u_bw = []
    for m in universe_metrics:
        m_df = m.get("ohlcv_df")
        if m_df is not None:
            m_bb = _compute_bollinger(m_df["Close"], 20, 2.0)
            if m_bb and m_bb.get("band_width") is not None:
                u_bw.append(m_bb["band_width"])

    u_sector_rets = list(sector_returns.values()) if sector_returns else []

    # ── Score each metric ────────────────────────────────────────────────────
    scores: dict[str, float] = {}

    if _small_universe:
        # Small-universe fallback: use absolute RS thresholds instead of
        # percentile ranking, which is meaningless for pools of < 5.
        logger.info(
            "[Scoring] Small universe (%d candidates) — using absolute RS/BW thresholds.",
            len(universe_metrics),
        )
        rs_63d_val = metrics.get("rs_63d")
        rs_126d_val = metrics.get("rs_126d")
        # Map rs to 0–1: negative = bad, 0–10% alpha = moderate, >10% = strong
        def _abs_rs_score(rs: Optional[float]) -> float:
            if rs is None:
                return 0.3
            if rs < 0:
                return max(0.0, 0.3 + rs / 20)   # -5 → 0.05, 0 → 0.3
            return min(1.0, 0.3 + rs / 15)        # +10% → ~1.0
        rs_score_abs = _abs_rs_score(rs_63d_val) * 0.6 + _abs_rs_score(rs_126d_val) * 0.4
        scores["relative_strength"] = rs_score_abs

        # Bollinger band width: use absolute thresholds (< 0.05 tight, > 0.15 wide)
        bw = bb.get("band_width") if bb else None
        if bw is None:
            scores["breakout_quality"] = 0.3
        elif bw < 0.04:
            scores["breakout_quality"] = 1.0
        elif bw < 0.07:
            scores["breakout_quality"] = 0.75
        elif bw < 0.12:
            scores["breakout_quality"] = 0.5
        else:
            scores["breakout_quality"] = 0.2
    else:
        scores["relative_strength"] = score_relative_strength(
            metrics.get("rs_63d"), metrics.get("rs_126d"), u_rs_63d, u_rs_126d
        )
        scores["breakout_quality"] = score_breakout_quality(
            bb.get("band_width") if bb else None, u_bw
        )

    scores["high_52w_proximity"] = score_52w_high_proximity(metrics.get("high_52w_pct"))
    scores["relative_volume"] = score_relative_volume(metrics.get("rel_vol"))
    scores["rsi_zone"] = score_rsi_zone(rsi14)
    scores["sector_rs"] = score_sector_rs(
        metrics.get("sector"), sector_returns, u_sector_rets
    )
    scores["market_cap_band"] = score_market_cap_band(metrics.get("market_cap"))
    scores["adx_trend"] = score_adx(adx14)
    scores["revenue_growth"] = score_revenue_growth(metrics.get("revenue_growth_yoy"))
    scores["macd_histogram"] = score_macd_histogram(macd_hist, prev_macd_hist)
    scores["eps_growth"] = score_eps_growth(metrics.get("eps_growth_yoy"))
    scores["fcf_quality"] = score_fcf(metrics.get("fcf_positive"))
    scores["debt_ratio"] = score_debt(metrics.get("net_debt_ebitda"))
    scores["float_size"] = score_float(metrics.get("float_shares"))
    scores["bollinger_position"] = score_bollinger_position(
        bb.get("pct_b") if bb else None
    )
    scores["beta"] = score_beta(metrics.get("beta"))
    scores["profit_margins"] = score_profit_margins(metrics.get("profit_margin"))
    scores["analyst_revisions"] = 0.3     # Not computed (no free source); neutral score
    scores["institutional_own"] = score_institutional_ownership(
        metrics.get("institutional_ownership_pct")
    )
    scores["insider_buying"] = 0.0        # Not computed (no free real-time source)
    scores["options_activity"] = 0.0      # Not computed (no free options-flow source)

    # Penalties
    penalty_short = score_short_interest_penalty(metrics.get("short_interest_pct_float"))
    penalty_gap   = gap_penalty_score

    # ── Weighted sum ─────────────────────────────────────────────────────────
    positive_total = sum(
        scores[metric] * WEIGHTS[metric]
        for metric in WEIGHTS
    )
    # Penalties reduce from the positive total
    penalty_total = (
        penalty_short * abs(PENALTIES["short_interest"]) +
        penalty_gap   * abs(PENALTIES["gap_history"])
    )

    raw_score = max(0.0, positive_total - penalty_total)
    composite = round(raw_score / MAX_POSITIVE_WEIGHT * 100, 1)

    # ── Classification per blueprint Section 5 Step 3 ────────────────────────
    if composite >= SCORE_HIGH_CONVICTION:
        classification = "high_conviction"
    elif composite >= SCORE_MARGINAL:
        classification = "marginal"
    else:
        classification = "no_trade"

    return {
        "ticker": metrics["ticker"],
        "composite_score": composite,
        "classification": classification,
        "component_scores": {
            k: round(v * WEIGHTS.get(k, 0), 2) for k, v in scores.items()
        },
        "penalties": {
            "short_interest": round(penalty_short * abs(PENALTIES["short_interest"]), 2),
            "gap_history": round(penalty_gap * abs(PENALTIES["gap_history"]), 2),
        },
        "technical_indicators": {
            "rsi_14": rsi14,
            "macd_histogram": round(macd_hist, 4) if macd_hist is not None else None,
            "adx_14": adx14,
            "bb_pct_b": bb.get("pct_b") if bb else None,
            "bb_band_width": bb.get("band_width") if bb else None,
        },
        "price": metrics.get("price"),
        "atr_pct": metrics.get("atr_pct"),
        "atr_abs": metrics.get("atr_abs"),
        "rs_63d": metrics.get("rs_63d"),
        "rs_126d": metrics.get("rs_126d"),
        "sector": metrics.get("sector"),
        "market_cap": metrics.get("market_cap"),
        "days_to_earnings": None,  # Computed separately via data_layer
        "short_interest_pct_float": metrics.get("short_interest_pct_float"),
        "rel_vol": metrics.get("rel_vol"),
        "sma_20": metrics.get("sma_20"),
        "sma_50": metrics.get("sma_50"),
        "sma_200": metrics.get("sma_200"),
        "high_52w_pct": metrics.get("high_52w_pct"),
    }


# ─── Tie-breaking ─────────────────────────────────────────────────────────────

def apply_tiebreaking(
    candidates: list[dict],
    open_positions: list[dict],
) -> list[dict]:
    """
    Sort candidates by score, then apply blueprint Section 5 Step 4 tie-breaking
    for candidates within 2 points of each other.

    Tie-breaking order:
      1. Higher liquidity (avg_dollar_vol_20d)
      2. Lower correlation to open positions (proxy: different sector)
      3. Tighter ATR-based stop distance (lower atr_pct)
    """
    open_sectors = {p.get("sector", "Unknown") for p in open_positions}

    def _sort_key(c: dict):
        score = c["composite_score"]
        # Liquidity (higher = better → negate for ascending sort)
        liquidity = -(c.get("avg_dollar_vol_20d") or 0)
        # Sector diversity (0 = new sector, 1 = same sector as open position)
        same_sector = 1 if c.get("sector") in open_sectors else 0
        # ATR distance (lower = tighter stop = better R:R)
        atr = c.get("atr_pct") or 99
        return (-score, same_sector, liquidity, atr)

    return sorted(candidates, key=_sort_key)


# ─── Confidence score ─────────────────────────────────────────────────────────

def compute_confidence_score(
    composite_score: float,
    ai_gemini_score: Optional[int],
    ai_deepseek_score: Optional[int],
    regime: str,
    filter_margin: float,  # How far above mandatory thresholds (0–1)
) -> int:
    """
    Compute the confidence score (0–100) separate from the rank score.
    Per blueprint Section 5 Step 5: gates position SIZE, not selection.

    Components:
      - Quant score margin above threshold (40%)
      - AI model agreement (40%)
      - Regime state (20%)
    """
    # Quant margin: how far above the 70-point threshold (or 55 for marginal)
    threshold = SCORE_HIGH_CONVICTION if composite_score >= SCORE_HIGH_CONVICTION else SCORE_MARGINAL
    margin_above = max(0.0, composite_score - threshold) / (100 - threshold)
    quant_component = int(margin_above * 40)

    # AI agreement component
    if ai_gemini_score is not None and ai_deepseek_score is not None:
        avg_ai = (ai_gemini_score + ai_deepseek_score) / 2
        agreement = 1.0 - (abs(ai_gemini_score - ai_deepseek_score) / 100)
        ai_component = int((avg_ai / 100) * agreement * 40)
    elif ai_gemini_score is not None:
        ai_component = int((ai_gemini_score / 100) * 30)  # Single model: less confident
    else:
        ai_component = 0

    # Regime component
    regime_scores = {"risk_on": 20, "caution": 10, "risk_off": 0}
    regime_component = regime_scores.get(regime, 0)

    confidence = quant_component + ai_component + regime_component
    return min(100, max(0, confidence))


# ─── Full scoring pipeline entry point ───────────────────────────────────────

def score_all_candidates(
    shortlist_metrics: list[dict],
    sector_returns: dict[str, float],
    regime: str,
    open_positions: list[dict],
) -> tuple[list[dict], list[dict], list[dict]]:
    """
    Score all filter-passing candidates and classify them.

    Returns:
      high_conviction : score ≥ 70 (full size eligible)
      marginal        : score 55–69 (half size, limited slots)
      no_trade        : score < 55 (logged but not actionable)
    """
    scored = []
    for m in shortlist_metrics:
        try:
            result = compute_composite_score(m, shortlist_metrics, sector_returns)
            scored.append(result)
        except Exception as exc:
            logger.error("[Scoring] Failed to score %s: %s", m.get("ticker"), exc)

    scored = apply_tiebreaking(scored, open_positions)

    high_conviction = [c for c in scored if c["classification"] == "high_conviction"]
    marginal        = [c for c in scored if c["classification"] == "marginal"]
    no_trade        = [c for c in scored if c["classification"] == "no_trade"]

    logger.info(
        "[Scoring] Results: %d high-conviction (≥70), %d marginal (55-69), %d no-trade (<55).",
        len(high_conviction), len(marginal), len(no_trade),
    )
    return high_conviction, marginal, no_trade
