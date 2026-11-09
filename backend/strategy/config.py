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
    # Feature flags (three-mode: off | shadow | enforce)
    "gate_intraday_confirmation": "shadow",
    "gate_gap_down_veto":         "shadow",
    "gate_exposure_tiers":        "shadow",
    "gate_market_breadth":        "shadow",
    "gate_sector_leadership":     "shadow",
    "sizing_beta_aware":          "shadow",
    "exit_market_linked":         "shadow",
    "gate_earnings_density":      "shadow",

    # Configurable thresholds
    "gap_down_threshold_pct":     0.7,   # SPY opening gap % below prior close to veto (e.g. 0.7%)
    "breadth_threshold_pct":      40.0,  # % of universe > 50-day SMA caution threshold (default 40%)
    "tier_b_size_multiplier":     0.5,   # Position size multiplier in Tier B (default 0.5x)
    "tier_b_score_bump":          5.0,   # Score threshold bump for Tier B (e.g. 70 -> 75)
    "vix_stress_level":           25.0,  # VIX level triggering caution / Tier C (default 25.0)
    "vix_spike_threshold_pct":    20.0,  # VIX 3-session spike threshold (default 20.0%)
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

        if isinstance(default_val, float):
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
            clean_val = str(val).strip().lower()
            if clean_val in VALID_MODES:
                cfg[key] = clean_val
            else:
                logger.warning("[Config] Invalid mode '%s' for setting '%s', keeping '%s'",
                               val, key, default_val)
                cfg[key] = default_val

    return cfg
