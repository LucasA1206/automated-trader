"""
Centralized Configuration & Feature Flag Management
===================================================
Manages system configuration and feature flags for the systematic trading bot.
Supports three modes per feature: 'off', 'shadow', and 'enforce'.
Defaults every new market gate to 'shadow'.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Valid feature flag modes
VALID_MODES = ("off", "shadow", "enforce")

# Default system settings and thresholds
DEFAULT_CONFIG = {
    # Feature flags (three-mode: off | shadow | enforce) — active enforcement enabled
    "gate_intraday_confirmation": "enforce",
    "gate_gap_down_veto":         "enforce",
    "gate_exposure_tiers":        "enforce",
    "gate_market_breadth":        "enforce",
    "gate_sector_leadership":     "enforce",
    "sizing_beta_aware":          "enforce",
    "exit_market_linked":         "enforce",
    "gate_earnings_density":      "enforce",

    # Configurable thresholds
    "gap_down_threshold_pct":     0.7,   # SPY opening gap % below prior close to veto (e.g. 0.7%)
    "breadth_threshold_pct":      40.0,  # % of universe > 50-day SMA caution threshold (default 40%)
    "tier_b_size_multiplier":     0.5,   # Position size multiplier in Tier B (default 0.5x)
    "tier_b_score_bump":          5.0,   # Score threshold bump for Tier B (e.g. 70 -> 75)
    "vix_stress_level":           25.0,  # VIX level triggering caution / Tier C (default 25.0)
    "vix_spike_threshold_pct":    20.0,  # VIX 3-session spike threshold (default 20.0%)

    # Dual-Engine Architecture & Progressive Stops
    "enable_mean_reversion":      True,  # Enable Mean Reversion sleeve for ETFs/large-caps
    "mean_reversion_allocation_pct": 40.0, # Target % allocation for mean-reversion sleeve
    "breakeven_r_multiple":       0.75,  # Progressive stop step: +0.75R moves stop to breakeven + 0.2%

    # Data-Quality Monitoring & Alerting (Feature 3)
    "dq_metric_coverage_min_pct":         80.0,  # Alert if any active metric's coverage < 80%
    "dq_max_achievable_score_min":        75.0,  # Critical alert if available metric weights < 75%
    "dq_score_collapse_max_threshold":    60.0,  # Alert if max composite score < 60
    "dq_score_collapse_consecutive_scans": 3,    # Consecutive depressed scans before critical alert
    "dq_regime_max_age_minutes":          120,   # Max age (minutes) for regime inputs
    "dq_price_jump_max_pct":              50.0,  # Single-bar price jump sanity threshold (%)
    "dq_held_stale_minutes":              30,    # Max age (minutes) for held position quotes
    "dq_api_error_rate_threshold_pct":    20.0,  # API error rate alert threshold (%)
    "dq_api_min_calls_for_rate":          5,     # Minimum calls before evaluating error rate
    "dq_no_data_spike_threshold_pct":     50.0,  # Alert if no_data rejections exceed % of universe
    "dq_cross_source_tolerance_pct":      2.0,   # Cross-source price discrepancy tolerance (%)
    "alert_cooldown_minutes":             60,    # Deduplication cooldown for repeated alerts

    # Backtest Baselines & De-Risking Ladder (Feature 1)
    # Note: No static backtest/Monte Carlo baseline file exists yet; using conservative
    # blueprint defaults until a real backtest baseline is generated and saved.
    "baseline_source":                    "blueprint_conservative_defaults",
    "baseline_date":                      "2026-11-26",
    "baseline_max_drawdown_pct":          8.0,   # Blueprint 8% drawdown halt (Level 2 pause)
    "baseline_hard_stop_drawdown_pct":    15.0,  # Blueprint 15% full-stop (Level 3 flatten & halt)
    "baseline_daily_loss_pct":            3.0,   # Blueprint 3% daily loss limit
    "baseline_weekly_loss_pct":           6.0,   # Blueprint 6% weekly loss limit
    "baseline_longest_losing_streak_p90": 5,     # 90th percentile expected losing streak
    "baseline_win_rate_min_pct":          40.0,  # Lower bound of expected win-rate range
    "baseline_win_rate_max_pct":          65.0,  # Upper bound of expected win-rate range
    "baseline_weekly_return_mean_pct":    0.5,   # Expected weekly return mean (%)
    "baseline_weekly_return_std_pct":     2.5,   # Expected weekly return std dev (%)
    "baseline_trades_per_week_min":       2.0,   # Expected min weekly trade frequency
    "baseline_trades_per_week_max":       4.0,   # Expected max weekly trade frequency

    # De-risking ladder parameters
    "derisk_level1_size_multiplier":      0.5,   # Level 1 Caution size multiplier
    "derisk_level1_score_bump":           5.0,   # Level 1 Caution minimum score bump
    "derisk_level1_dd_fraction":          0.625, # Trigger Level 1 at 62.5% of 8% DD (= 5.0% DD)
    # Minimum sample size before statistical divergence triggers fire:
    # At 2-4 trades/week, 20 closed trades represents ~5-10 weeks of live data,
    # avoiding overreaction to small-sample variance.
    "derisk_min_sample_trades":           20,
    "derisk_divergence_min_avg_ret_pct":  -0.5,  # Trigger Level 1 if 20-trade avg return < -0.5%

    # Shadow-Mode Tracking & Evidence Rubric (Feature 4)
    "shadow_min_sample_size":             20,    # Min resolved decisions before non-insufficient rating
    "shadow_strong_min_sample_size":      40,    # Min resolved decisions for 'strong' evidence rating
    "shadow_near_miss_score_floor":       50.0,  # Candidates scoring [50, 55) logged as near-misses
    "shadow_max_hold_days":               21,    # Calendar days before hypothetical time exit

    # Weekly Performance Report (Feature 2)
    "weekly_report_day":                  "sat", # Day of week for scheduled report (mon..sun)
    "weekly_report_hour":                 9,     # Hour (ET) for scheduled report
    "weekly_report_minute":               0,     # Minute (ET) for scheduled report
    "weekly_report_min_bucket_trades":    10,    # Label buckets with < N trades as 'insufficient data'
}


def get_system_config(db=None, overrides: Optional[dict] = None) -> dict:
    """
    Retrieve current system configuration and feature flags.
    Reads from DB settings table if available, falling back to DEFAULT_CONFIG.
    Ensures all flag values are valid ('off', 'shadow', 'enforce').
    """
    cfg = dict(DEFAULT_CONFIG)

    if overrides:
        cfg.update(overrides)

    if db is None:
        try:
            from database import SessionLocal
            session = SessionLocal()
            try:
                cfg = _load_from_db(session, cfg)
            finally:
                session.close()
        except Exception as exc:
            logger.debug("[Config] Could not load settings from DB session: %s. Using defaults.", exc)
    else:
        cfg = _load_from_db(db, cfg)

    if overrides:
        cfg.update(overrides)

    return cfg


def _load_from_db(db, cfg: dict) -> dict:
    """Helper to query settings table and cast types."""
    from database import get_setting

    for key, default_val in DEFAULT_CONFIG.items():
        val = get_setting(db, key, None)
        if val is None:
            continue

        if isinstance(default_val, bool):
            cfg[key] = str(val).strip().lower() in ("true", "1", "yes")
        elif isinstance(default_val, float):
            try:
                cfg[key] = float(val)
            except (ValueError, TypeError):
                cfg[key] = default_val
        elif isinstance(default_val, int):
            try:
                cfg[key] = int(val)
            except (ValueError, TypeError):
                cfg[key] = default_val
        elif isinstance(default_val, str):
            if default_val in VALID_MODES:
                clean_val = str(val).strip().lower()
                if clean_val in VALID_MODES:
                    cfg[key] = clean_val
                else:
                    logger.warning("[Config] Invalid mode '%s' for setting '%s', keeping '%s'",
                                   val, key, default_val)
                    cfg[key] = default_val
            else:
                cfg[key] = str(val).strip()

    return cfg
