"""
Performance Baselines — Feature 1
=================================
Loads expected performance baselines for comparing live trading results against
backtest expectations.

If no static backtest/Monte Carlo baseline JSON exists yet, falls back to
documented conservative blueprint defaults (8% drawdown halt, 15% full-stop,
3% daily loss, 6% weekly loss).
"""

import json
import os
from typing import Optional

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE_FILE_PATH = os.path.join(_BACKEND_DIR, "strategy", "baseline_metrics.json")


def get_active_baseline(config: Optional[dict] = None) -> dict:
    """
    Return the active baseline dictionary with source and date metadata.
    Checks config first, then optional baseline_metrics.json if present.
    """
    cfg = config or {}

    file_data = {}
    if os.path.exists(BASELINE_FILE_PATH):
        try:
            with open(BASELINE_FILE_PATH, "r", encoding="utf-8") as f:
                file_data = json.load(f) or {}
        except Exception:
            file_data = {}

    return {
        "source": file_data.get("source") or cfg.get("baseline_source", "blueprint_conservative_defaults"),
        "date": file_data.get("date") or cfg.get("baseline_date", "2026-11-26"),
        "has_backtest_file": bool(file_data),
        "max_drawdown_pct": float(file_data.get("max_drawdown_pct", cfg.get("baseline_max_drawdown_pct", 8.0))),
        "hard_stop_drawdown_pct": float(file_data.get("hard_stop_drawdown_pct", cfg.get("baseline_hard_stop_drawdown_pct", 15.0))),
        "daily_loss_pct": float(file_data.get("daily_loss_pct", cfg.get("baseline_daily_loss_pct", 3.0))),
        "weekly_loss_pct": float(file_data.get("weekly_loss_pct", cfg.get("baseline_weekly_loss_pct", 6.0))),
        "longest_losing_streak_p90": int(file_data.get("longest_losing_streak_p90", cfg.get("baseline_longest_losing_streak_p90", 5))),
        "win_rate_min_pct": float(file_data.get("win_rate_min_pct", cfg.get("baseline_win_rate_min_pct", 40.0))),
        "win_rate_max_pct": float(file_data.get("win_rate_max_pct", cfg.get("baseline_win_rate_max_pct", 65.0))),
        "weekly_return_mean_pct": float(file_data.get("weekly_return_mean_pct", cfg.get("baseline_weekly_return_mean_pct", 0.5))),
        "weekly_return_std_pct": float(file_data.get("weekly_return_std_pct", cfg.get("baseline_weekly_return_std_pct", 2.5))),
        "trades_per_week_min": float(file_data.get("trades_per_week_min", cfg.get("baseline_trades_per_week_min", 2.0))),
        "trades_per_week_max": float(file_data.get("trades_per_week_max", cfg.get("baseline_trades_per_week_max", 4.0))),
    }
