"""
Market State, Breadth, Gap-Down Veto & Graded Exposure Tiers
============================================================
Implements Section 6 market confirmation and risk state enhancements:
  - Universe market breadth (% of scan universe > 50-day SMA)
  - Gap-down veto (SPY opening gap below prior close)
  - Graded Exposure Tiers (Tier A, Tier B, Tier C)
  - Sector leadership ranking and gating (50% 3m + 50% 1m relative returns)
  - Empirical beta calculation & beta-aware position scaling
  - Intraday SPY confirmation (SPY > prior close & > intraday VWAP after 10:00 ET)
  - Market-linked exit signals (SPY breaks 50 SMA or 10-day swing low)
  - Earnings season density caution
  - Configurable three-mode operation ('off', 'shadow', 'enforce')
"""

import logging
import math
from datetime import datetime, timezone
from typing import Optional
import numpy as np
import pandas as pd

from strategy.config import get_system_config

logger = logging.getLogger(__name__)

# Module-level cache for latest universe breadth
_latest_breadth_cache: Optional[dict] = None


# ─── Market Breadth ───────────────────────────────────────────────────────────

def compute_market_breadth(
    batch_data: dict[str, pd.DataFrame],
    threshold_pct: float = 40.0,
) -> dict:
    """
    Compute market breadth across the scan universe:
    Percentage of universe stocks trading above their own 50-day SMA.

    Handles missing-data tickers explicitly:
      - Tickers with < 50 valid closing bars are excluded from the denominator.
      - Logged with the count of valid vs excluded tickers.

    Returns:
      {
        "breadth_pct": float,      # e.g. 54.2 (% above 50 SMA)
        "above_50d_count": int,
        "below_50d_count": int,
        "valid_count": int,        # denominator
        "missing_count": int,      # excluded count
        "total_universe": int,
        "threshold_pct": float,
        "is_healthy": bool,        # breadth_pct >= threshold_pct
      }
    """
    global _latest_breadth_cache

    if not batch_data:
        logger.warning("[Breadth] Empty batch data provided for breadth calculation.")
        res = {
            "breadth_pct": 0.0,
            "above_50d_count": 0,
            "below_50d_count": 0,
            "valid_count": 0,
            "missing_count": 0,
            "total_universe": 0,
            "threshold_pct": threshold_pct,
            "is_healthy": False,
        }
        _latest_breadth_cache = res
        return res

    above_count = 0
    below_count = 0
    missing_count = 0
    total_universe = len(batch_data)

    for ticker, df in batch_data.items():
        if df is None or not isinstance(df, pd.DataFrame) or df.empty or "Close" not in df.columns:
            missing_count += 1
            continue

        closes = df["Close"].dropna()
        if len(closes) < 50:
            missing_count += 1
            continue

        try:
            current_price = float(closes.iloc[-1])
            sma_50 = float(closes.rolling(50).mean().iloc[-1])
            if math.isnan(current_price) or math.isnan(sma_50) or current_price <= 0:
                missing_count += 1
                continue

            if current_price > sma_50:
                above_count += 1
            else:
                below_count += 1
        except Exception:
            missing_count += 1

    valid_count = above_count + below_count
    breadth_pct = round((above_count / valid_count * 100.0), 2) if valid_count > 0 else 0.0
    is_healthy = breadth_pct >= threshold_pct if valid_count > 0 else False

    res = {
        "breadth_pct": breadth_pct,
        "above_50d_count": above_count,
        "below_50d_count": below_count,
        "valid_count": valid_count,
        "missing_count": missing_count,
        "total_universe": total_universe,
        "threshold_pct": threshold_pct,
        "is_healthy": is_healthy,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    _latest_breadth_cache = res
    logger.info(
        "[Breadth] Universe breadth: %.1f%% above 50d SMA (%d above, %d below, %d missing/excluded from %d total). Healthy=%s",
        breadth_pct, above_count, below_count, missing_count, total_universe, is_healthy
    )
    return res


def get_latest_breadth() -> Optional[dict]:
    """Retrieve the most recently computed market breadth snapshot."""
    global _latest_breadth_cache
    return _latest_breadth_cache


def set_latest_breadth(breadth_dict: dict) -> None:
    """Manually set or mock the market breadth snapshot (e.g. for testing)."""
    global _latest_breadth_cache
    _latest_breadth_cache = breadth_dict


# ─── Gap-Down Veto ────────────────────────────────────────────────────────────

def check_gap_down_veto(
    spy_open: Optional[float],
    spy_prior_close: Optional[float],
    threshold_pct: float = 0.7,
    mode: str = "shadow",
) -> dict:
    """
    Check if SPY opened below prior close by more than threshold_pct (default 0.7%).

    Controlled by mode:
      - 'off': Completely disabled.
      - 'shadow': Compute gap, log veto decision, but do not block trades.
      - 'enforce': Active circuit breaker — blocks all new entries for the day.

    Returns:
      {
        "veto_active": bool,       # True only if enforce mode AND gap triggers veto
        "would_veto": bool,        # True if gap triggers veto regardless of mode
        "gap_pct": float,          # e.g. -0.85
        "threshold_pct": float,
        "mode": str,               # 'off' | 'shadow' | 'enforce'
        "reason": str,
      }
    """
    mode = (mode or "shadow").strip().lower()

    if mode == "off":
        return {
            "veto_active": False,
            "would_veto": False,
            "gap_pct": 0.0,
            "threshold_pct": threshold_pct,
            "mode": "off",
            "reason": "gap_down_veto_disabled",
        }

    # Validate inputs
    if (
        spy_open is None or spy_prior_close is None or
        math.isnan(spy_open) or math.isnan(spy_prior_close) or
        spy_open <= 0 or spy_prior_close <= 0
    ):
        reason = "SPY open or prior close missing/invalid"
        if mode == "enforce":
            logger.error("[GapDownVeto] %s — FAIL-SAFE VETO ACTIVATED (enforce).", reason)
            return {
                "veto_active": True,
                "would_veto": True,
                "gap_pct": 0.0,
                "threshold_pct": threshold_pct,
                "mode": mode,
                "reason": f"fail_safe_veto: {reason}",
            }
        else:
            logger.warning("[GapDownVeto] %s — logged in shadow mode (no block).", reason)
            return {
                "veto_active": False,
                "would_veto": True,
                "gap_pct": 0.0,
                "threshold_pct": threshold_pct,
                "mode": mode,
                "reason": f"shadow_veto: {reason}",
            }

    gap_pct = round(((spy_open - spy_prior_close) / spy_prior_close * 100.0), 3)
    limit = -abs(threshold_pct)
    triggered = gap_pct <= limit

    if triggered:
        reason = f"SPY gapped down {gap_pct:+.2f}% (exceeded -{threshold_pct:.2f}% threshold)"
        if mode == "enforce":
            logger.warning("[GapDownVeto] 🛑 %s — ALL NEW ENTRIES BLOCKED (enforce).", reason)
            veto_active = True
        else:
            logger.info("[GapDownVeto] 👻 [SHADOW VETO] %s — Would block entries (shadow mode: allowing trades).", reason)
            veto_active = False
    else:
        reason = f"SPY open gap {gap_pct:+.2f}% is within normal range (-{threshold_pct:.2f}% threshold)"
        logger.info("[GapDownVeto] ✅ %s.", reason)
        veto_active = False

    return {
        "veto_active": veto_active,
        "would_veto": triggered,
        "gap_pct": gap_pct,
        "threshold_pct": threshold_pct,
        "mode": mode,
        "reason": reason,
    }


# ─── Graded Exposure Tiers ───────────────────────────────────────────────────

def classify_market_tier(
    regime_data: Optional[dict],
    breadth_data: Optional[dict] = None,
    gap_veto_data: Optional[dict] = None,
    config: Optional[dict] = None,
) -> dict:
    """
    Classify the market into Graded Exposure Tiers:

      Tier A (Full Size - 1.0x):
        - SPY > 200-day SMA AND SPY > 50-day SMA
        - VIX < vix_stress_level (default 25.0)
        - VIX 3d spike <= 20%
        - Breadth >= breadth_threshold_pct (default 40%)
        - No gap-down veto

      Tier B (Half Size - 0.5x, minimum score raised by bump):
        - SPY > 200-day SMA, but (SPY <= 50-day SMA OR Breadth < 40%)
        - VIX < vix_stress_level
        - VIX 3d spike <= 20%
        - No gap-down veto

      Tier C (No New Entries - 0.0x):
        - SPY <= 200-day SMA
        - VIX >= vix_stress_level OR VIX 3d spike > 20%
        - Black swan day (SPY 1d move > 3%)
        - Gap-down veto active (or would veto in enforce)
        - Regime data invalid, missing, or NaN

    Controlled by config['gate_exposure_tiers']:
      - 'off': legacy behavior (Tier A / binary risk_off).
      - 'shadow': Log the calculated tier, size multiplier, and score bump,
                  but actual trading size multiplier remains 1.0 (unless Tier C blocks).
      - 'enforce': Applies tier size multiplier (0.5x for B, 0.0x for C) and score bump.
    """
    cfg = config or get_system_config()
    tier_mode = cfg.get("gate_exposure_tiers", "shadow").strip().lower()
    breadth_mode = cfg.get("gate_market_breadth", "shadow").strip().lower()
    gap_mode = cfg.get("gate_gap_down_veto", "shadow").strip().lower()

    vix_stress = float(cfg.get("vix_stress_level", 25.0))
    vix_spike_max = float(cfg.get("vix_spike_threshold_pct", 20.0))
    breadth_min = float(cfg.get("breadth_threshold_pct", 40.0))
    tier_b_size_mult = float(cfg.get("tier_b_size_multiplier", 0.5))
    tier_b_score_bump = float(cfg.get("tier_b_score_bump", 5.0))

    reasons: list[str] = []

    # ── Check for Tier C triggers (Immediate Halts) ───────────────────────────
    is_tier_c = False

    # 1. Regime data validity
    if not regime_data or not regime_data.get("is_valid", False) or regime_data.get("regime") in ("unavailable", "unknown"):
        is_tier_c = True
        reasons.append("regime_data_unavailable_or_invalid")

    # 2. SPY trend vs 200 SMA
    spy_above_200 = bool(regime_data.get("spy_above_200", False)) if regime_data else False
    if not spy_above_200:
        is_tier_c = True
        reasons.append("spy_below_200_sma")

    # 3. VIX stress level
    vix = float(regime_data.get("vix", 99.0)) if regime_data and regime_data.get("vix") is not None else 99.0
    if vix >= vix_stress:
        is_tier_c = True
        reasons.append(f"vix_stress({vix:.1f}>={vix_stress:.1f})")

    # 4. VIX 3-session spike
    vix_spike = float(regime_data.get("vix_spike_3d_pct", 0.0)) if regime_data and regime_data.get("vix_spike_3d_pct") is not None else 0.0
    if vix_spike > vix_spike_max:
        is_tier_c = True
        reasons.append(f"vix_spike({vix_spike:+.1f}%>{vix_spike_max:.1f}%)")

    # 5. Black swan single-day move
    if regime_data and regime_data.get("black_swan_day", False):
        is_tier_c = True
        reasons.append("black_swan_day(spy_move>3%)")

    # 6. Gap-down veto
    if gap_veto_data:
        gap_triggered = gap_veto_data.get("veto_active", False) if gap_mode == "enforce" else gap_veto_data.get("would_veto", False)
        if gap_triggered:
            if gap_mode == "enforce":
                is_tier_c = True
                reasons.append(f"gap_down_veto_enforced({gap_veto_data.get('gap_pct')}%)")
            else:
                reasons.append(f"gap_down_veto_shadowed({gap_veto_data.get('gap_pct')}%)")

    if is_tier_c:
        tier = "C"
        hypothetical_size = 0.0
        hypothetical_bump = 0.0
        effective_size = 0.0
        effective_bump = 0.0
    else:
        # ── Check Tier B triggers ─────────────────────────────────────────────
        is_tier_b = False

        # SPY vs 50 SMA
        spy_price = float(regime_data.get("spy_price", 0.0)) if regime_data else 0.0
        spy_sma_50 = float(regime_data.get("spy_sma_50", 0.0)) if regime_data and regime_data.get("spy_sma_50") is not None else 0.0
        spy_above_50 = (spy_price > spy_sma_50) if (spy_price > 0 and spy_sma_50 > 0) else True

        if not spy_above_50:
            is_tier_b = True
            reasons.append(f"spy_below_50_sma(${spy_price:.2f}<=${spy_sma_50:.2f})")

        # Breadth check
        breadth_healthy = True
        breadth_pct = None
        if breadth_data:
            breadth_pct = float(breadth_data.get("breadth_pct", 0.0))
            if breadth_pct < breadth_min:
                breadth_healthy = False
                reasons.append(f"weak_breadth({breadth_pct:.1f}%<{breadth_min:.1f}%)")
                if breadth_mode in ("enforce", "shadow"):
                    is_tier_b = True

        if is_tier_b:
            tier = "B"
            hypothetical_size = tier_b_size_mult
            hypothetical_bump = tier_b_score_bump

            if tier_mode == "enforce":
                effective_size = tier_b_size_mult
                effective_bump = tier_b_score_bump
            else:
                effective_size = 1.0  # In shadow or off mode, retain full size
                effective_bump = 0.0
        else:
            tier = "A"
            reasons.append("all_conditions_healthy")
            hypothetical_size = 1.0
            hypothetical_bump = 0.0
            effective_size = 1.0
            effective_bump = 0.0

    summary = (
        f"Tier {tier} | HypoSize={hypothetical_size:.1f}x | HypoBump=+{hypothetical_bump:.1f}pts | "
        f"EffSize={effective_size:.1f}x | EffBump=+{effective_bump:.1f}pts | Mode={tier_mode} | "
        f"Reasons: {', '.join(reasons)}"
    )

    if tier_mode == "shadow" and tier == "B":
        logger.info("[Tiers] 👻 [SHADOW TIER] %s", summary)
    elif tier_mode == "enforce":
        logger.info("[Tiers] 🎯 [ENFORCE TIER] %s", summary)
    else:
        logger.info("[Tiers] %s", summary)

    return {
        "tier": tier,
        "effective_size_multiplier": effective_size,
        "effective_score_bump": effective_bump,
        "hypothetical_size_multiplier": hypothetical_size,
        "hypothetical_score_bump": hypothetical_bump,
        "tier_mode": tier_mode,
        "reasons": reasons,
        "summary": summary,
        "is_tier_c": (tier == "C"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ─── Sector Leadership Ranking & Gating ───────────────────────────────────────

# Mapping of the 11 Select Sector SPDR ETFs
SECTOR_ETFS = {
    "Technology": "XLK",
    "Healthcare": "XLV",
    "Financials": "XLF",
    "Consumer Cyclical": "XLY",
    "Consumer Defensive": "XLP",
    "Energy": "XLE",
    "Industrials": "XLI",
    "Basic Materials": "XLB",
    "Real Estate": "XLRE",
    "Utilities": "XLU",
    "Communication Services": "XLC",
}


def rank_sectors_by_leadership(
    sector_3m_returns: dict[str, float],
    sector_1m_returns: dict[str, float],
    spy_3m_return: float = 0.0,
    spy_1m_return: float = 0.0,
) -> dict:
    """
    Ranks sectors by combined relative strength vs SPY:
      Composite RS = 0.50 * (3m_sector - 3m_spy) + 0.50 * (1m_sector - 1m_spy)
    
    Returns:
      {
        "rankings": {sector: {"rank": int, "rs_score": float, "is_leader": bool}},
        "leaders": list[str],     # top 6 sectors (top half of 11)
        "laggards": list[str],    # bottom 5 sectors
      }
    """
    scores = {}
    for sector in SECTOR_ETFS.keys():
        ret_3m = float(sector_3m_returns.get(sector, 0.0))
        ret_1m = float(sector_1m_returns.get(sector, 0.0))
        rs_3m = ret_3m - spy_3m_return
        rs_1m = ret_1m - spy_1m_return
        composite_rs = round(0.50 * rs_3m + 0.50 * rs_1m, 3)
        scores[sector] = composite_rs

    # Sort descending by composite RS
    sorted_sectors = sorted(scores.keys(), key=lambda s: scores[s], reverse=True)
    rankings = {}
    leaders = []
    laggards = []

    for rank_idx, sector in enumerate(sorted_sectors, 1):
        is_leader = rank_idx <= 6  # Top 6 out of 11 is top half
        if is_leader:
            leaders.append(sector)
        else:
            laggards.append(sector)
        rankings[sector] = {
            "rank": rank_idx,
            "rs_score": scores[sector],
            "is_leader": is_leader,
        }

    return {
        "rankings": rankings,
        "leaders": leaders,
        "laggards": laggards,
    }


def check_sector_leadership(
    sector: str,
    leadership_data: Optional[dict],
    mode: str = "shadow",
) -> dict:
    """
    Check if a candidate's sector qualifies as a market leader (top half).
    
    Modes:
      - 'off': Always allows.
      - 'shadow': Evaluates, logs would-block, but allows entry.
      - 'enforce': Active gate — blocks entry if sector is not in top half.
    """
    mode = (mode or "shadow").strip().lower()
    if mode == "off" or not leadership_data:
        return {
            "allowed": True,
            "would_block": False,
            "rank": 0,
            "is_leader": True,
            "mode": mode,
            "reason": "Sector leadership check disabled or data unavailable",
        }

    rankings = leadership_data.get("rankings", {})
    sec_info = rankings.get(sector)

    if not sec_info:
        # Unknown sector: conservative pass with shadow log
        return {
            "allowed": True,
            "would_block": False,
            "rank": 0,
            "is_leader": False,
            "mode": mode,
            "reason": f"Sector '{sector}' not found in 11 GICS sectors",
        }

    rank = sec_info["rank"]
    is_leader = sec_info["is_leader"]
    rs_score = sec_info["rs_score"]

    if is_leader:
        return {
            "allowed": True,
            "would_block": False,
            "rank": rank,
            "is_leader": True,
            "mode": mode,
            "reason": f"Sector '{sector}' is a market leader (rank {rank}/11, RS {rs_score:+.2f}%)",
        }

    # Sector is in bottom half (laggard)
    would_block = True
    if mode == "enforce":
        allowed = False
        msg = f"⛔ Sector '{sector}' blocked: rank {rank}/11 (laggard, RS {rs_score:+.2f}%) [enforce]"
        logger.info("[SectorGate] %s", msg)
    else:
        allowed = True
        msg = f"👻 Sector '{sector}' would be blocked: rank {rank}/11 (laggard, RS {rs_score:+.2f}%) [shadow]"
        logger.info("[SectorGate] %s", msg)

    return {
        "allowed": allowed,
        "would_block": would_block,
        "rank": rank,
        "is_leader": False,
        "mode": mode,
        "reason": msg,
    }


# ─── Empirical Beta Calculation & Sizing Scalar ───────────────────────────────

def compute_empirical_beta(
    stock_closes: pd.Series,
    spy_closes: pd.Series,
    min_periods: int = 126,
) -> Optional[float]:
    """
    Compute empirical 252-day beta against SPY from aligned daily close prices:
      Beta = Cov(R_stock, R_spy) / Var(R_spy)
    
    Returns float rounded to 2 decimal places, or None if insufficient history.
    """
    if stock_closes is None or spy_closes is None:
        return None

    # Align dates and compute daily returns
    df = pd.DataFrame({"stock": stock_closes, "spy": spy_closes}).dropna()
    if len(df) < min_periods:
        return None

    # Limit to most recent 252 trading sessions
    df = df.iloc[-252:]
    stock_ret = df["stock"].pct_change().dropna()
    spy_ret = df["spy"].pct_change().dropna()

    aligned = pd.DataFrame({"r_s": stock_ret, "r_m": spy_ret}).dropna()
    if len(aligned) < min_periods:
        return None

    var_m = aligned["r_m"].var()
    if var_m == 0 or math.isnan(var_m):
        return None

    cov = aligned["r_s"].cov(aligned["r_m"])
    if math.isnan(cov):
        return None

    beta = cov / var_m
    return round(float(beta), 2)


def calculate_beta_scalar(beta: Optional[float], mode: str = "shadow") -> dict:
    """
    Calculate position size scalar based on stock beta:
      formula: scalar = clamp(1.0 / max(beta, 1.0), 0.5, 1.0)
    
    If beta <= 1.0: scalar = 1.0 (no reduction)
    If beta = 1.5:  scalar = 1 / 1.5 = 0.67
    If beta >= 2.0: scalar = 0.50 (maximum 50% haircut)
    
    In 'shadow' mode: effective_scalar = 1.0, hypothetical_scalar = scalar.
    In 'enforce' mode: effective_scalar = scalar.
    In 'off' mode: effective_scalar = 1.0, hypothetical_scalar = 1.0.
    """
    mode = (mode or "shadow").strip().lower()
    if beta is None or math.isnan(beta) or beta <= 0:
        hypo = 1.0
    else:
        hypo = float(np.clip(1.0 / max(float(beta), 1.0), 0.5, 1.0))
        hypo = round(hypo, 3)

    if mode == "enforce":
        eff = hypo
    else:
        eff = 1.0

    return {
        "beta": beta,
        "effective_scalar": eff,
        "hypothetical_scalar": hypo,
        "mode": mode,
        "haircut_pct": round((1.0 - hypo) * 100, 1),
    }


# ─── Intraday SPY Confirmation Gate ───────────────────────────────────────────

def check_spy_intraday_confirmation(
    ib_client=None,
    mode: str = "shadow",
    test_now_et: Optional[tuple[int, int]] = None,
    mock_spy_data: Optional[dict] = None,
) -> dict:
    """
    Check if broader market behavior confirms new long entries at execution time:
      1. Time check: Must be at or after 10:00 ET (avoids first 30m opening whipsaws).
      2. Price vs Prior Close: SPY current price > SPY prior close.
      3. Price vs VWAP: SPY current price > SPY intraday VWAP.
    
    Fail-safe rule:
      If SPY intraday data is missing or corrupted, fail-safe defaults to NO ENTRY (in enforce).
    """
    mode = (mode or "shadow").strip().lower()
    if mode == "off":
        return {
            "confirmed": True,
            "would_confirm": True,
            "mode": mode,
            "reasons": ["Gate disabled (off mode)"],
            "details": "Intraday confirmation disabled.",
        }

    # 1. Time gate (>= 10:00 ET)
    if test_now_et:
        hour, minute = test_now_et
    else:
        import pytz
        ET = pytz.timezone("America/New_York")
        now_et = datetime.now(ET)
        hour, minute = now_et.hour, now_et.minute

    if (hour, minute) < (10, 0):
        reason = f"Time is {hour:02d}:{minute:02d} ET — before 10:00 ET opening whipsaw window"
        return {
            "confirmed": False if mode == "enforce" else True,
            "would_confirm": False,
            "mode": mode,
            "reasons": [reason],
            "details": f"Market confirmation failed: {reason}",
        }

    # 2. Get SPY data
    data = mock_spy_data
    if data is None and ib_client is not None:
        try:
            data = ib_client.get_spy_intraday_data()
        except Exception as exc:
            logger.error("[IntradayConfirm] Failed to retrieve SPY data from IBKR: %s", exc)
            data = None

    if not data or not isinstance(data, dict):
        reason = "SPY intraday data unavailable from IBKR or feed (fail-safe)"
        return {
            "confirmed": False if mode == "enforce" else True,
            "would_confirm": False,
            "mode": mode,
            "reasons": [reason],
            "details": f"Fail-safe activated: {reason}",
        }

    spy_price = data.get("current_price")
    spy_prior_close = data.get("prior_close")
    spy_vwap = data.get("vwap")

    if any(v is None or math.isnan(v) or v <= 0 for v in [spy_price, spy_prior_close, spy_vwap]):
        reason = f"Corrupt SPY price data: price={spy_price}, prior_close={spy_prior_close}, vwap={spy_vwap}"
        return {
            "confirmed": False if mode == "enforce" else True,
            "would_confirm": False,
            "mode": mode,
            "reasons": [reason],
            "details": f"Fail-safe activated: {reason}",
        }

    checks = []
    failed_checks = []

    # SPY > prior close
    if spy_price > spy_prior_close:
        checks.append(f"SPY (${spy_price:.2f}) > prior close (${spy_prior_close:.2f})")
    else:
        failed_checks.append(f"SPY (${spy_price:.2f}) <= prior close (${spy_prior_close:.2f})")

    # SPY > VWAP
    if spy_price > spy_vwap:
        checks.append(f"SPY (${spy_price:.2f}) > VWAP (${spy_vwap:.2f})")
    else:
        failed_checks.append(f"SPY (${spy_price:.2f}) <= VWAP (${spy_vwap:.2f})")

    all_passed = len(failed_checks) == 0

    if all_passed:
        confirmed = True
        would_confirm = True
        summary = f"SPY confirmed: {', '.join(checks)}"
    else:
        would_confirm = False
        confirmed = False if mode == "enforce" else True
        summary = f"SPY unconfirmed: {', '.join(failed_checks)}"

    if mode == "shadow" and not all_passed:
        logger.info("[IntradayConfirm] 👻 [SHADOW BLOCK] %s", summary)
    elif mode == "enforce" and not all_passed:
        logger.info("[IntradayConfirm] ⛔ [ENFORCE BLOCK] %s", summary)
    else:
        logger.info("[IntradayConfirm] %s", summary)

    return {
        "confirmed": confirmed,
        "would_confirm": would_confirm,
        "mode": mode,
        "spy_price": spy_price,
        "prior_close": spy_prior_close,
        "vwap": spy_vwap,
        "reasons": failed_checks if not all_passed else checks,
        "details": summary,
    }


# ─── Market-Linked Exits & Earnings Density (Phase 4 Helpers) ────────────────

def check_market_linked_exit_trigger(spy_ohlcv: pd.DataFrame) -> dict:
    """
    Check if broader market health has deteriorated enough to trigger stop tightening:
      1. SPY closed below its 50-day SMA.
      2. SPY broke below the lowest close of its prior 10 trading sessions.
    
    If triggered, positions tighten stops to min(current_stop, current_price - 1.0 * ATR).
    """
    if spy_ohlcv is None or spy_ohlcv.empty or "Close" not in spy_ohlcv.columns:
        return {"trigger": False, "reasons": ["No SPY OHLCV available"]}

    closes = spy_ohlcv["Close"].dropna()
    if len(closes) < 50:
        return {"trigger": False, "reasons": ["Insufficient SPY history (<50 days)"]}

    current_close = float(closes.iloc[-1])
    sma_50 = float(closes.rolling(50).mean().iloc[-1])
    prior_10_low = float(closes.iloc[-11:-1].min()) if len(closes) >= 11 else current_close

    triggers = []
    if current_close < sma_50:
        triggers.append(f"SPY closed below 50-day SMA (${current_close:.2f} < ${sma_50:.2f})")
    if current_close < prior_10_low:
        triggers.append(f"SPY broke 10-day swing low (${current_close:.2f} < ${prior_10_low:.2f})")

    is_triggered = len(triggers) > 0
    return {
        "trigger": is_triggered,
        "reasons": triggers if is_triggered else ["SPY holding above 50 SMA and 10d swing low"],
        "current_close": current_close,
        "sma_50": sma_50,
        "prior_10_low": prior_10_low,
    }


def compute_earnings_season_density(
    candidates: list[dict],
    threshold_pct: float = 25.0,
    factor: float = 0.75,
    mode: str = "shadow",
) -> dict:
    """
    Caution when > threshold_pct (25%) of candidates report earnings within 10 days.
    Reduces overall candidate position sizing by factor (0.75x).
    """
    mode = (mode or "shadow").strip().lower()
    if not candidates or mode == "off":
        return {
            "caution_active": False,
            "density_pct": 0.0,
            "size_multiplier": 1.0,
            "mode": mode,
            "reason": "Earnings density check inactive",
        }

    near_earnings_count = 0
    total = len(candidates)

    for c in candidates:
        days_to_earnings = c.get("days_to_earnings")
        if days_to_earnings is not None and 0 <= days_to_earnings <= 10:
            near_earnings_count += 1

    density_pct = round((near_earnings_count / total * 100.0), 1)
    is_dense = density_pct >= threshold_pct

    if is_dense:
        hypo_mult = factor
        eff_mult = factor if mode == "enforce" else 1.0
        reason = f"Earnings density {density_pct:.1f}% >= {threshold_pct:.1f}% ({near_earnings_count}/{total} report <=10d)"
    else:
        hypo_mult = 1.0
        eff_mult = 1.0
        reason = f"Earnings density normal ({density_pct:.1f}% < {threshold_pct:.1f}%)"

    return {
        "caution_active": is_dense,
        "density_pct": density_pct,
        "effective_size_multiplier": eff_mult,
        "hypothetical_size_multiplier": hypo_mult,
        "mode": mode,
        "reason": reason,
    }

