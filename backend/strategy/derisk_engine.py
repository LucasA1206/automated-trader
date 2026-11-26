"""
Automatic De-Risking Ladder — Feature 1 (Protective Only)
=========================================================
Compares live performance to documented baselines and escalates risk
controls automatically when results fall outside normal bounds.

Levels (each step strictly reduces risk — never loosens any limit):
  0 = Normal          (1.0x size, +0 score bump, entries allowed)
  1 = Caution         (0.5x size, +5 score bump, entries allowed)
  2 = Pause           (0.0x size, no new entries; existing exits still run)
  3 = Flatten & Halt  (close all positions via execution layer & halt)

Rules:
  - Escalation is automatic.
  - De-escalation is NEVER automatic: requires manual operator confirmation
    via frontend or API, logged with timestamp and actor.
  - Enforced inside RiskEngine as a hard gate.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

LEVEL_NAMES = {
    0: "Normal",
    1: "Caution",
    2: "Pause",
    3: "Flatten & Halt",
}


def _get_cfg(db, config: Optional[dict]) -> dict:
    if config is not None:
        return config
    try:
        from strategy.config import get_system_config
        return get_system_config(db)
    except Exception:
        return {}


def get_derisk_modifiers(level: int, config: Optional[dict] = None) -> dict:
    """
    Return strictly protective risk modifiers for the given de-risk level.
    Size multiplier is clamped to [0.0, 1.0] and score bump >= 0.0 so a
    de-risk state can never increase position size or lower score thresholds.
    """
    cfg = config or {}
    lvl = max(0, min(3, int(level)))

    if lvl == 0:
        return {
            "level": 0,
            "label": LEVEL_NAMES[0],
            "size_multiplier": 1.0,
            "score_bump": 0.0,
            "entries_allowed": True,
            "flatten": False,
        }
    if lvl == 1:
        mult = min(1.0, max(0.0, float(cfg.get("derisk_level1_size_multiplier", 0.5))))
        bump = max(0.0, float(cfg.get("derisk_level1_score_bump", 5.0)))
        return {
            "level": 1,
            "label": LEVEL_NAMES[1],
            "size_multiplier": mult,
            "score_bump": bump,
            "entries_allowed": True,
            "flatten": False,
        }
    if lvl == 2:
        return {
            "level": 2,
            "label": LEVEL_NAMES[2],
            "size_multiplier": 0.0,
            "score_bump": 0.0,
            "entries_allowed": False,
            "flatten": False,
        }
    return {
        "level": 3,
        "label": LEVEL_NAMES[3],
        "size_multiplier": 0.0,
        "score_bump": 0.0,
        "entries_allowed": False,
        "flatten": True,
    }


def _ensure_state_row(db):
    from models import DeRiskState
    row = db.query(DeRiskState).order_by(DeRiskState.id.asc()).first()
    if row is None:
        row = DeRiskState(level=0, reason="Initialized at Level 0 (Normal)")
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def get_derisk_state(db, config: Optional[dict] = None) -> dict:
    """Return the current persisted de-risk state and active modifiers."""
    if db is None:
        return get_derisk_modifiers(0, config)

    cfg = _get_cfg(db, config)
    row = _ensure_state_row(db)
    mods = get_derisk_modifiers(row.level, cfg)
    try:
        metrics = json.loads(row.trigger_metrics_json or "{}")
    except Exception:
        metrics = {}

    return {
        **mods,
        "reason": row.reason or "Normal",
        "trigger_metrics": metrics,
        "escalated_at": row.escalated_at.isoformat() if row.escalated_at else None,
        "deescalated_at": row.deescalated_at.isoformat() if row.deescalated_at else None,
        "deescalated_by": row.deescalated_by,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def compute_live_performance_metrics(
    db,
    account_equity: float,
    peak_equity: float,
    daily_pnl_pct: float = 0.0,
    weekly_pnl_pct: float = 0.0,
    min_sample_trades: int = 20,
) -> dict:
    """
    Compute live drawdown, losing streak, and rolling N-trade performance
    from closed trades in DB.
    """
    from models import Trade

    drawdown_pct = 0.0
    if peak_equity > 0 and account_equity > 0:
        drawdown_pct = max(0.0, (peak_equity - account_equity) / peak_equity * 100.0)

    closed_trades = []
    if db is not None:
        closed_trades = (
            db.query(Trade)
            .filter(Trade.status == "closed", Trade.pnl.isnot(None))
            .order_by(Trade.sell_time.desc(), Trade.id.desc())
            .all()
        )

    # Current consecutive losing streak from most recent closed trade
    losing_streak = 0
    for t in closed_trades:
        if (t.pnl or 0.0) < 0:
            losing_streak += 1
        else:
            break

    total_closed = len(closed_trades)
    sample_ready = total_closed >= min_sample_trades

    rolling_win_rate_pct = None
    rolling_avg_return_pct = None
    if sample_ready and min_sample_trades > 0:
        window = closed_trades[:min_sample_trades]
        wins = sum(1 for t in window if (t.pnl or 0.0) > 0)
        rolling_win_rate_pct = round(wins / len(window) * 100.0, 2)
        rets = [float(t.pnl_pct or 0.0) for t in window]
        rolling_avg_return_pct = round(sum(rets) / len(rets), 3)

    return {
        "account_equity": round(account_equity, 2),
        "peak_equity": round(peak_equity, 2),
        "drawdown_pct": round(drawdown_pct, 2),
        "daily_pnl_pct": round(daily_pnl_pct, 2),
        "weekly_pnl_pct": round(weekly_pnl_pct, 2),
        "losing_streak": losing_streak,
        "total_closed_trades": total_closed,
        "min_sample_trades": min_sample_trades,
        "sample_ready": sample_ready,
        "rolling_win_rate_pct": rolling_win_rate_pct,
        "rolling_avg_return_pct": rolling_avg_return_pct,
    }


def evaluate_derisk_ladder(
    db,
    account_equity: float,
    peak_equity: float,
    daily_pnl_pct: float = 0.0,
    weekly_pnl_pct: float = 0.0,
    critical_system_failure: bool = False,
    config: Optional[dict] = None,
) -> dict:
    """
    Evaluate all de-risk triggers against the active baseline.
    Automatically escalates if a higher level is triggered; NEVER de-escalates.
    Emits an alert and logs an audit event on every escalation.
    """
    from models import DeRiskEvent
    from strategy.baselines import get_active_baseline
    from strategy.alerting import emit_alert

    cfg = _get_cfg(db, config)
    baseline = get_active_baseline(cfg)
    min_sample = int(cfg.get("derisk_min_sample_trades", 20))
    l1_dd_frac = float(cfg.get("derisk_level1_dd_fraction", 0.625))
    div_min_avg_ret = float(cfg.get("derisk_divergence_min_avg_ret_pct", -0.5))

    metrics = compute_live_performance_metrics(
        db=db,
        account_equity=account_equity,
        peak_equity=peak_equity,
        daily_pnl_pct=daily_pnl_pct,
        weekly_pnl_pct=weekly_pnl_pct,
        min_sample_trades=min_sample,
    )

    dd = metrics["drawdown_pct"]
    streak = metrics["losing_streak"]
    l1_dd_threshold = round(baseline["max_drawdown_pct"] * l1_dd_frac, 2)
    l2_dd_threshold = baseline["max_drawdown_pct"]
    l3_dd_threshold = baseline["hard_stop_drawdown_pct"]
    streak_threshold = baseline["longest_losing_streak_p90"]

    triggered_level = 0
    reasons = []

    # Level 3 checks (15% drawdown or critical system failure)
    if dd >= l3_dd_threshold:
        triggered_level = 3
        reasons.append(f"drawdown {dd:.2f}% >= {l3_dd_threshold:.1f}% hard stop")
    if critical_system_failure:
        triggered_level = 3
        reasons.append("critical_system_failure triggered")

    # Level 2 checks (8% drawdown pause, daily/weekly loss limits, or L1 combo)
    if triggered_level < 2:
        if dd >= l2_dd_threshold:
            triggered_level = 2
            reasons.append(f"drawdown {dd:.2f}% >= {l2_dd_threshold:.1f}% pause threshold")
        elif daily_pnl_pct <= -baseline["daily_loss_pct"]:
            triggered_level = 2
            reasons.append(f"daily P&L {daily_pnl_pct:.2f}% <= -{baseline['daily_loss_pct']:.1f}%")
        elif weekly_pnl_pct <= -baseline["weekly_loss_pct"]:
            triggered_level = 2
            reasons.append(f"weekly P&L {weekly_pnl_pct:.2f}% <= -{baseline['weekly_loss_pct']:.1f}%")
        elif dd >= l1_dd_threshold and streak >= streak_threshold:
            triggered_level = 2
            reasons.append(
                f"combined caution triggers: drawdown {dd:.2f}% >= {l1_dd_threshold:.1f}% "
                f"AND losing streak {streak} >= {streak_threshold}"
            )

    # Level 1 checks (fraction of max DD, losing streak, or statistical divergence >= min_sample)
    if triggered_level < 1:
        if dd >= l1_dd_threshold:
            triggered_level = 1
            reasons.append(f"drawdown {dd:.2f}% >= {l1_dd_threshold:.1f}% caution threshold")
        if streak >= streak_threshold:
            triggered_level = 1
            reasons.append(f"losing streak {streak} >= {streak_threshold} (baseline p90)")
        if metrics["sample_ready"]:
            wr = metrics["rolling_win_rate_pct"]
            avg_r = metrics["rolling_avg_return_pct"]
            if wr is not None and wr < baseline["win_rate_min_pct"]:
                triggered_level = 1
                reasons.append(
                    f"rolling {min_sample}-trade win rate {wr:.1f}% < {baseline['win_rate_min_pct']:.1f}% baseline"
                )
            if avg_r is not None and avg_r < div_min_avg_ret:
                triggered_level = 1
                reasons.append(
                    f"rolling {min_sample}-trade avg return {avg_r:.2f}% < {div_min_avg_ret:.2f}%"
                )

    state_row = _ensure_state_row(db)
    current_level = int(state_row.level)
    escalated = False
    should_flatten = False

    if triggered_level > current_level:
        now = datetime.now(timezone.utc)
        reason_str = "; ".join(reasons)
        state_row.level = triggered_level
        state_row.reason = reason_str
        state_row.trigger_metrics_json = json.dumps(metrics)
        state_row.escalated_at = now
        state_row.updated_at = now

        event = DeRiskEvent(
            from_level=current_level,
            to_level=triggered_level,
            action_type="escalate",
            trigger=reason_str[:120],
            details=json.dumps({"metrics": metrics, "baseline_source": baseline["source"]}),
            actor="system",
            created_at=now,
        )
        db.add(event)
        db.commit()

        severity = "critical" if triggered_level >= 2 else "warning"
        emit_alert(
            db,
            alert_key=f"derisk:level_{triggered_level}",
            severity=severity,
            category="derisk",
            title=f"De-Risk Escalated to Level {triggered_level} ({LEVEL_NAMES[triggered_level]})",
            message=f"Escalated {current_level} -> {triggered_level}. Trigger: {reason_str}",
            details={"metrics": metrics, "reasons": reasons, "baseline": baseline},
            cooldown_minutes=0,  # Always alert on level transitions
        )

        escalated = True
        if triggered_level == 3:
            should_flatten = True

    state = get_derisk_state(db, cfg)
    state["escalated"] = escalated
    state["should_flatten"] = should_flatten
    state["baseline"] = baseline
    state["live_metrics"] = metrics
    return state


def manual_deescalate(
    db,
    target_level: int,
    username: str = "admin",
    reason: str = "Operator manual confirmation",
    config: Optional[dict] = None,
) -> dict:
    """
    Manually lower the de-risk level after operator review.
    Never called automatically; validates target_level < current_level.
    """
    from models import DeRiskEvent
    from strategy.alerting import emit_alert, resolve_alert_by_key

    state_row = _ensure_state_row(db)
    current_level = int(state_row.level)
    target = int(target_level)

    if target < 0 or target >= current_level:
        raise ValueError(
            f"Invalid target_level={target}: must be >= 0 and < current_level ({current_level})."
        )

    now = datetime.now(timezone.utc)
    state_row.level = target
    state_row.reason = f"Manually de-escalated from Level {current_level} to Level {target} by {username}: {reason}"
    state_row.deescalated_at = now
    state_row.deescalated_by = username
    state_row.updated_at = now

    event = DeRiskEvent(
        from_level=current_level,
        to_level=target,
        action_type="manual_deescalate",
        trigger=f"manual_confirmation_by_{username}",
        details=reason,
        actor=username,
        created_at=now,
    )
    db.add(event)
    db.commit()

    for lvl in range(target + 1, 4):
        resolve_alert_by_key(db, f"derisk:level_{lvl}")

    emit_alert(
        db,
        alert_key=f"derisk:manual_deescalate_{now.timestamp()}",
        severity="info",
        category="derisk",
        title=f"De-Risk Manually De-Escalated to Level {target} ({LEVEL_NAMES[target]})",
        message=f"Operator {username} confirmed de-escalation {current_level} -> {target}. Reason: {reason}",
        cooldown_minutes=0,
    )

    return get_derisk_state(db, config)
