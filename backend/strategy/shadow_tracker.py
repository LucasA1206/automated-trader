"""
Shadow-Mode & Near-Miss Tracking Engine — Feature 4 (Observational Only)
=======================================================================
Extends ShadowEvaluation logging to record:
  1. Every candidate blocked, resized, or altered by a gate in 'shadow' mode,
     with its hypothetical action and full market state at decision time.
  2. Near-miss candidates (marginal band or narrow mandatory-filter failures).
  3. Forward hypothetical outcomes tracked using the same exit rules as live
     trades (hard stop, 1.5R partial target + breakeven trail, time exit).
  4. Running per-rule statistics and conservative evidence-strength labels
     ('insufficient', 'weak', 'moderate', 'strong') with sample sizes.

Never alters live or paper orders and never auto-promotes rules.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Callable, Optional

logger = logging.getLogger(__name__)


def _get_cfg(db, config: Optional[dict]) -> dict:
    if config is not None:
        return config
    try:
        from strategy.config import get_system_config
        return get_system_config(db)
    except Exception:
        return {}


def record_shadow_decision(
    db,
    ticker: str,
    gate_name: str,
    mode: str,
    would_have_blocked: bool,
    hypothetical_action: str,
    entry_price: Optional[float] = None,
    atr_abs: Optional[float] = None,
    market_state: Optional[dict] = None,
    details: Optional[str] = None,
    is_near_miss: bool = False,
    trade_id: Optional[int] = None,
):
    """
    Persist a hypothetical shadow-gate or near-miss decision with initial
    ATR stop & 1.5R partial target so forward outcomes can be tracked identically
    to live trades. Observational only — never places or alters orders.
    """
    if db is None:
        return None
    from models import ShadowEvaluation

    try:
        stop_px = None
        partial_px = None
        if entry_price and entry_price > 0:
            if atr_abs and atr_abs > 0:
                from strategy.entry_engine import compute_initial_stop, compute_partial_target
                stop_px = compute_initial_stop(entry_price, atr_abs)
                partial_px = compute_partial_target(entry_price, stop_px)
            else:
                stop_px = round(entry_price * 0.95, 4)
                partial_px = round(entry_price * 1.075, 4)

        row = ShadowEvaluation(
            trade_id=trade_id,
            ticker=ticker,
            gate_name=gate_name,
            mode=mode,
            would_have_blocked=bool(would_have_blocked),
            is_near_miss=bool(is_near_miss),
            hypothetical_action=hypothetical_action,
            entry_price=round(float(entry_price), 4) if entry_price else None,
            stop_price=stop_px,
            partial_target_price=partial_px,
            trailing_stop_price=stop_px,
            high_watermark=round(float(entry_price), 4) if entry_price else None,
            partial_taken=False,
            market_state_json=json.dumps(market_state or {}, default=str),
            outcome_status="open",
            details=details,
            created_at=datetime.now(timezone.utc),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row
    except Exception as exc:
        logger.error("[ShadowTracker] Failed to record %s/%s: %s", ticker, gate_name, exc)
        try:
            db.rollback()
        except Exception:
            pass
        return None


def _default_price_fetcher(ticker: str) -> Optional[dict]:
    """Fetch latest daily bar (high, low, close) via data_layer."""
    try:
        from strategy.data_layer import fetch_ohlcv
        df = fetch_ohlcv(ticker, period="5d")
        if df is not None and len(df) > 0:
            last = df.iloc[-1]
            return {
                "high": float(last["High"]),
                "low": float(last["Low"]),
                "close": float(last["Close"]),
            }
    except Exception as exc:
        logger.debug("[ShadowTracker] Price fetch failed for %s: %s", ticker, exc)
    return None


def update_open_shadow_outcomes(
    db,
    price_fetcher: Optional[Callable[[str], Optional[dict]]] = None,
    config: Optional[dict] = None,
    now_override: Optional[datetime] = None,
) -> dict:
    """
    Evaluate all open ShadowEvaluation rows against latest price bars using
    live-equivalent exit rules (stop hit, 1.5R partial + breakeven trail, time exit).
    """
    if db is None:
        return {"updated": 0, "resolved": 0, "still_open": 0}

    from models import ShadowEvaluation

    cfg = _get_cfg(db, config)
    max_hold_days = int(cfg.get("shadow_max_hold_days", 21))
    fetcher = price_fetcher or _default_price_fetcher
    now = now_override or datetime.now(timezone.utc)

    open_rows = (
        db.query(ShadowEvaluation)
        .filter(ShadowEvaluation.outcome_status == "open")
        .all()
    )

    updated = 0
    resolved = 0

    for row in open_rows:
        if not row.entry_price or row.entry_price <= 0:
            continue

        bar = fetcher(row.ticker)
        if not bar:
            continue

        high = float(bar.get("high", bar.get("close", row.entry_price)))
        low = float(bar.get("low", bar.get("close", row.entry_price)))
        close = float(bar.get("close", row.entry_price))
        entry = float(row.entry_price)
        init_stop = float(row.stop_price or (entry * 0.95))
        active_stop = float(row.trailing_stop_price or init_stop)

        # 1. Check stop hit
        if low <= active_stop:
            exit_px = active_stop
            if row.partial_taken and row.partial_target_price:
                part_ret = (row.partial_target_price - entry) / entry * 100.0
                rem_ret = (exit_px - entry) / entry * 100.0
                ret_pct = round(0.5 * part_ret + 0.5 * rem_ret, 2)
                reason = "trailing_stop_after_partial"
            else:
                ret_pct = round((exit_px - entry) / entry * 100.0, 2)
                reason = "stop_hit"

            row.outcome_status = "resolved"
            row.exit_reason = reason
            row.exit_price = round(exit_px, 4)
            row.hypothetical_pnl_pct = ret_pct
            row.resolved_at = now
            updated += 1
            resolved += 1
            continue

        # 2. Check 1.5R partial target
        if not row.partial_taken and row.partial_target_price and high >= row.partial_target_price:
            row.partial_taken = True
            row.trailing_stop_price = round(entry * 1.002, 4)  # breakeven + 0.2%
            row.high_watermark = round(max(float(row.high_watermark or entry), high), 4)
            updated += 1
        elif row.partial_taken:
            hw = max(float(row.high_watermark or entry), high)
            row.high_watermark = round(hw, 4)
            risk_dist = max(entry * 0.02, entry - init_stop)
            trail = round(hw - 1.5 * risk_dist, 4)
            if trail > active_stop:
                row.trailing_stop_price = trail
            updated += 1

        # 3. Check time exit
        created = row.created_at
        if created is not None:
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if (now - created).days >= max_hold_days:
                if row.partial_taken and row.partial_target_price:
                    part_ret = (row.partial_target_price - entry) / entry * 100.0
                    rem_ret = (close - entry) / entry * 100.0
                    ret_pct = round(0.5 * part_ret + 0.5 * rem_ret, 2)
                else:
                    ret_pct = round((close - entry) / entry * 100.0, 2)
                row.outcome_status = "resolved"
                row.exit_reason = "time_exit"
                row.exit_price = round(close, 4)
                row.hypothetical_pnl_pct = ret_pct
                row.resolved_at = now
                updated += 1
                resolved += 1

    if updated > 0:
        try:
            db.commit()
        except Exception as exc:
            logger.error("[ShadowTracker] Commit failed updating outcomes: %s", exc)
            db.rollback()

    still_open = (
        db.query(ShadowEvaluation)
        .filter(ShadowEvaluation.outcome_status == "open")
        .count()
    )
    return {"updated": updated, "resolved": resolved, "still_open": still_open}


def classify_evidence_strength(
    resolved_count: int,
    blocked_avg_ret: Optional[float],
    allowed_avg_ret: Optional[float],
    blocked_win_rate: Optional[float],
    allowed_win_rate: Optional[float],
    min_sample: int = 20,
    strong_sample: int = 40,
) -> dict:
    """
    Conservative evidence-strength rubric.
    Never recommends promotion below `min_sample` resolved observations.
    """
    if resolved_count < min_sample or blocked_avg_ret is None or allowed_avg_ret is None:
        return {
            "label": "insufficient",
            "recommend_promotion": False,
            "reason": f"Only {resolved_count}/{min_sample} resolved decisions — insufficient data.",
        }

    ret_edge = allowed_avg_ret - blocked_avg_ret
    wr_edge = (allowed_win_rate or 0.0) - (blocked_win_rate or 0.0)

    if resolved_count >= strong_sample and ret_edge >= 2.0 and wr_edge >= 10.0:
        return {
            "label": "strong",
            "recommend_promotion": False,  # Never auto-promote; human review still required
            "reason": f"Strong edge (+{ret_edge:.2f}% return, +{wr_edge:.1f}% win rate over n={resolved_count}).",
        }
    if ret_edge >= 1.0 or wr_edge >= 5.0:
        return {
            "label": "moderate",
            "recommend_promotion": False,
            "reason": f"Moderate edge (+{ret_edge:.2f}% return, +{wr_edge:.1f}% win rate over n={resolved_count}).",
        }
    return {
        "label": "weak",
        "recommend_promotion": False,
        "reason": f"Weak/no consistent edge ({ret_edge:+.2f}% return, {wr_edge:+.1f}% win rate over n={resolved_count}).",
    }


def compute_shadow_summary(db, config: Optional[dict] = None) -> dict:
    """
    Compute per-gate shadow statistics, evidence strength labels, and
    near-miss forward outcome summaries.
    """
    from models import ShadowEvaluation, Trade

    cfg = _get_cfg(db, config)
    min_sample = int(cfg.get("shadow_min_sample_size", 20))
    strong_sample = int(cfg.get("shadow_strong_min_sample_size", 40))

    rows = db.query(ShadowEvaluation).order_by(ShadowEvaluation.created_at.desc()).all()
    closed_trades = db.query(Trade).filter(Trade.status == "closed", Trade.pnl_pct.isnot(None)).all()

    allowed_baseline_rets = [float(t.pnl_pct or 0.0) for t in closed_trades]
    allowed_baseline_wr = (
        round(sum(1 for r in allowed_baseline_rets if r > 0) / len(allowed_baseline_rets) * 100.0, 1)
        if allowed_baseline_rets else None
    )
    allowed_baseline_avg = (
        round(sum(allowed_baseline_rets) / len(allowed_baseline_rets), 2)
        if allowed_baseline_rets else None
    )

    gate_buckets: dict[str, list] = {}
    near_misses: list = []

    for r in rows:
        if r.is_near_miss:
            near_misses.append(r)
        else:
            gate_buckets.setdefault(r.gate_name, []).append(r)

    def _subset_metrics(items):
        resolved_items = [x for x in items if x.outcome_status == "resolved" and x.hypothetical_pnl_pct is not None]
        if not resolved_items:
            return {"resolved": 0, "avg_return_pct": None, "win_rate_pct": None}
        rets = [float(x.hypothetical_pnl_pct) for x in resolved_items]
        wins = sum(1 for val in rets if val > 0)
        return {
            "resolved": len(resolved_items),
            "avg_return_pct": round(sum(rets) / len(rets), 2),
            "win_rate_pct": round(wins / len(rets) * 100.0, 1),
        }

    rules_summary = {}
    for gate, items in gate_buckets.items():
        blocked_items = [x for x in items if x.would_have_blocked]
        allowed_items = [x for x in items if not x.would_have_blocked]

        b_stats = _subset_metrics(blocked_items)
        a_stats = _subset_metrics(allowed_items)

        # If no explicit allowed shadow items exist, compare against closed live trades baseline
        comp_avg = a_stats["avg_return_pct"] if a_stats["resolved"] > 0 else allowed_baseline_avg
        comp_wr = a_stats["win_rate_pct"] if a_stats["resolved"] > 0 else allowed_baseline_wr

        evidence = classify_evidence_strength(
            resolved_count=b_stats["resolved"],
            blocked_avg_ret=b_stats["avg_return_pct"],
            allowed_avg_ret=comp_avg,
            blocked_win_rate=b_stats["win_rate_pct"],
            allowed_win_rate=comp_wr,
            min_sample=min_sample,
            strong_sample=strong_sample,
        )

        rules_summary[gate] = {
            "gate_name": gate,
            "total_decisions": len(items),
            "open_count": sum(1 for x in items if x.outcome_status == "open"),
            "resolved_count": sum(1 for x in items if x.outcome_status == "resolved"),
            "would_have_blocked_count": len(blocked_items),
            "blocked_stats": b_stats,
            "allowed_stats": a_stats if a_stats["resolved"] > 0 else {
                "resolved": len(allowed_baseline_rets),
                "avg_return_pct": allowed_baseline_avg,
                "win_rate_pct": allowed_baseline_wr,
                "source": "live_closed_baseline",
            },
            "evidence": evidence,
        }

    nm_stats = _subset_metrics(near_misses)

    return {
        "min_sample_size": min_sample,
        "rules": rules_summary,
        "near_misses": {
            "total": len(near_misses),
            "open": sum(1 for x in near_misses if x.outcome_status == "open"),
            **nm_stats,
            "label": "HYPOTHETICAL NEAR-MISSES (never acted on)",
        },
        "recent_decisions": [
            {
                "id": r.id,
                "ticker": r.ticker,
                "gate_name": r.gate_name,
                "mode": r.mode,
                "is_near_miss": r.is_near_miss,
                "would_have_blocked": r.would_have_blocked,
                "hypothetical_action": r.hypothetical_action,
                "entry_price": r.entry_price,
                "exit_price": r.exit_price,
                "outcome_status": r.outcome_status,
                "exit_reason": r.exit_reason,
                "hypothetical_pnl_pct": r.hypothetical_pnl_pct,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows[:30]
        ],
    }
