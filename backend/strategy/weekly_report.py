"""
Automatic Weekly Performance Report — Feature 2 (Observational Only)
====================================================================
Generates a comprehensive weekly report covering:
  - Period returns (strategy vs SPY, alpha, beta, equity curve, drawdown, de-risk level)
  - Trade list (entry/exit reasons, holding period, R-multiple, return vs SPY)
  - Breakdowns by tier, sector, score bucket, AI confidence, entry time, intraday confirmation
  - Scan statistics (scans, regime distribution, no-trade days, rejections, AI approval rate)
  - Baseline comparison
  - Data-quality summary (Feature 3)
  - Shadow-mode summary (Feature 4)
  - Factual "What to look at" summary (strictly numeric, no causal speculation, no param advice)

Honesty Rules:
  - Every statistic carries its sample size (n=X).
  - Any breakdown bucket with < min_bucket_trades (default 10) is labeled "insufficient data".
  - Generates cleanly with 0 trades, a handful of trades, or offline data sources.
"""

import json
import logging
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)


def _get_cfg(db, config: Optional[dict]) -> dict:
    if config is not None:
        return config
    try:
        from strategy.config import get_system_config
        return get_system_config(db)
    except Exception:
        return {}


def _bucket_stats(trades: list, min_bucket_trades: int) -> dict:
    n = len(trades)
    if n == 0:
        return {
            "sample_size": 0,
            "status": "insufficient data",
            "win_rate_pct": None,
            "avg_return_pct": None,
            "avg_alpha_pct": None,
        }
    wins = sum(1 for t in trades if (t.pnl or 0.0) > 0)
    rets = [float(t.pnl_pct or 0.0) for t in trades]
    alphas = [float(t.alpha_pct) for t in trades if t.alpha_pct is not None]

    insufficient = n < min_bucket_trades
    return {
        "sample_size": n,
        "status": "insufficient data" if insufficient else "sufficient",
        "win_rate_pct": round(wins / n * 100.0, 1),
        "avg_return_pct": round(sum(rets) / n, 2),
        "avg_alpha_pct": round(sum(alphas) / len(alphas), 2) if alphas else None,
    }


def _score_bucket(score: Optional[float]) -> str:
    if score is None:
        return "unknown"
    if score < 55.0:
        return "<55"
    if score < 70.0:
        return "55-69"
    if score < 85.0:
        return "70-84"
    return ">=85"


def _confidence_bucket(conf: Optional[float]) -> str:
    if conf is None:
        return "unknown"
    if conf < 60.0:
        return "<60"
    if conf < 80.0:
        return "60-79"
    return ">=80"


def _entry_time_bucket(buy_time: Optional[datetime]) -> str:
    if buy_time is None:
        return "unknown"
    try:
        import pytz
        et = pytz.timezone("America/New_York")
        dt = buy_time if buy_time.tzinfo else buy_time.replace(tzinfo=timezone.utc)
        dt_et = dt.astimezone(et)
        mins = dt_et.hour * 60 + dt_et.minute
        if 9 * 60 + 30 <= mins < 10 * 60 + 30:
            return "09:30-10:30"
        if 10 * 60 + 30 <= mins < 13 * 60:
            return "10:30-13:00"
        if 13 * 60 <= mins <= 15 * 60 + 30:
            return "13:00-15:30"
        return "other"
    except Exception:
        return "unknown"


def _fetch_spy_period_return(period_start: date, period_end: date) -> tuple[float, str]:
    """Fetch SPY % return over [period_start, period_end]. Falls back gracefully."""
    try:
        from strategy.data_layer import fetch_ohlcv
        df = fetch_ohlcv("SPY", period="1mo")
        if df is not None and len(df) >= 2:
            closes = df["Close"].dropna()
            if len(closes) >= 2:
                # Filter by date range if possible
                sub = closes.loc[
                    (closes.index.date >= period_start) & (closes.index.date <= period_end)
                ]
                if len(sub) >= 2:
                    ret = (float(sub.iloc[-1]) - float(sub.iloc[0])) / float(sub.iloc[0]) * 100.0
                    return round(ret, 2), "yfinance"
                ret = (float(closes.iloc[-1]) - float(closes.iloc[-min(6, len(closes))])) / float(closes.iloc[-min(6, len(closes))]) * 100.0
                return round(ret, 2), "yfinance_approx"
    except Exception as exc:
        logger.debug("[WeeklyReport] SPY fetch unavailable: %s", exc)
    return 0.0, "unavailable"


def generate_weekly_report(
    db,
    period_end: Optional[date] = None,
    lookback_days: int = 7,
    spy_period_return_pct: Optional[float] = None,
    config: Optional[dict] = None,
    deliver_alert: bool = True,
) -> dict:
    """
    Generate, persist, and optionally deliver the weekly performance report.
    Never raises on missing data or offline external sources.
    """
    from models import (
        Trade, TradeJournalEntry, AccountSnapshot, ScanResult, AIPick,
        DataHealthCheck, SystemAlert, WeeklyReport,
    )
    from strategy.baselines import get_active_baseline
    from strategy.derisk_engine import get_derisk_state
    from strategy.shadow_tracker import compute_shadow_summary
    from strategy.alerting import emit_alert

    cfg = _get_cfg(db, config)
    min_bucket = int(cfg.get("weekly_report_min_bucket_trades", 10))
    baseline = get_active_baseline(cfg)
    derisk = get_derisk_state(db, cfg)

    end_d = period_end or datetime.now(timezone.utc).date()
    start_d = end_d - timedelta(days=max(1, lookback_days - 1))
    start_dt = datetime.combine(start_d, datetime.min.time(), tzinfo=timezone.utc)
    end_dt = datetime.combine(end_d, datetime.max.time(), tzinfo=timezone.utc)

    # ── 1. Equity Curve & Drawdown ────────────────────────────────────────────
    snapshots = (
        db.query(AccountSnapshot)
        .filter(AccountSnapshot.date >= start_d, AccountSnapshot.date <= end_d)
        .order_by(AccountSnapshot.date.asc())
        .all()
    )
    all_snapshots = db.query(AccountSnapshot).order_by(AccountSnapshot.date.asc()).all()
    peak_eq = max((float(s.net_liq_usd) for s in all_snapshots), default=0.0)
    latest_eq = float(all_snapshots[-1].net_liq_usd) if all_snapshots else 0.0
    drawdown_pct = round(max(0.0, (peak_eq - latest_eq) / peak_eq * 100.0), 2) if peak_eq > 0 else 0.0

    equity_curve = [
        {"date": s.date.isoformat(), "net_liq_usd": round(float(s.net_liq_usd), 2)}
        for s in snapshots
    ]

    # ── 2. Closed Trades in Period ────────────────────────────────────────────
    closed_trades = (
        db.query(Trade)
        .filter(
            Trade.status == "closed",
            Trade.sell_time >= start_dt,
            Trade.sell_time <= end_dt,
        )
        .order_by(Trade.sell_time.asc())
        .all()
    )

    n_trades = len(closed_trades)
    if len(snapshots) >= 2 and snapshots[0].net_liq_usd > 0:
        strat_ret_pct = round(
            (snapshots[-1].net_liq_usd - snapshots[0].net_liq_usd) / snapshots[0].net_liq_usd * 100.0,
            2,
        )
        ret_source = "account_snapshots"
    elif n_trades > 0:
        strat_ret_pct = round(sum(float(t.pnl_pct or 0.0) for t in closed_trades) / n_trades, 2)
        ret_source = "trade_avg"
    else:
        strat_ret_pct = 0.0
        ret_source = "no_trades"

    if spy_period_return_pct is not None:
        spy_ret_pct = round(float(spy_period_return_pct), 2)
        spy_source = "provided"
    else:
        spy_ret_pct, spy_source = _fetch_spy_period_return(start_d, end_d)

    betas = [float(t.beta_at_entry) for t in closed_trades if t.beta_at_entry is not None]
    avg_beta = round(sum(betas) / len(betas), 2) if betas else 1.0
    alpha_pct = round(strat_ret_pct - (avg_beta * spy_ret_pct), 2)
    wins = sum(1 for t in closed_trades if (t.pnl or 0.0) > 0)
    win_rate_pct = round(wins / n_trades * 100.0, 1) if n_trades > 0 else None

    trade_ids = [t.id for t in closed_trades]
    journal_by_trade: dict[int, dict] = {}
    if trade_ids:
        j_rows = (
            db.query(TradeJournalEntry)
            .filter(TradeJournalEntry.trade_id.in_(trade_ids))
            .order_by(TradeJournalEntry.created_at.asc())
            .all()
        )
        for j in j_rows:
            info = journal_by_trade.setdefault(j.trade_id, {"confidence": None, "exit_reason": None})
            if j.confidence_score is not None:
                info["confidence"] = j.confidence_score
            if j.event_type in ("full_exit", "time_exit", "ma_exit", "atr_expansion", "pre_event_exit"):
                info["exit_reason"] = j.details or j.event_type

    trade_list = []
    for t in closed_trades:
        holding_days = None
        if t.buy_time and t.sell_time:
            bt = t.buy_time if t.buy_time.tzinfo else t.buy_time.replace(tzinfo=timezone.utc)
            st = t.sell_time if t.sell_time.tzinfo else t.sell_time.replace(tzinfo=timezone.utc)
            holding_days = max(0, (st - bt).days)

        r_multiple = None
        if t.buy_price and t.stop_price and t.sell_price and t.buy_price > t.stop_price:
            r_multiple = round((t.sell_price - t.buy_price) / (t.buy_price - t.stop_price), 2)

        j_info = journal_by_trade.get(t.id, {})
        trade_list.append({
            "id": t.id,
            "ticker": t.ticker,
            "entry_reason": t.ai_reason,
            "exit_reason": j_info.get("exit_reason"),
            "holding_days": holding_days,
            "r_multiple": r_multiple,
            "return_pct": round(float(t.pnl_pct or 0.0), 2),
            "spy_return_pct": round(float(t.spy_return_pct or 0.0), 2) if t.spy_return_pct is not None else None,
            "alpha_pct": round(float(t.alpha_pct), 2) if t.alpha_pct is not None else None,
            "pnl": round(float(t.pnl or 0.0), 2),
        })

    # ── 3. Breakdowns (with sample_size & 'insufficient data' label) ──────────
    def _group(key_fn):
        groups: dict[str, list] = {}
        for t in closed_trades:
            k = key_fn(t)
            groups.setdefault(k, []).append(t)
        return {k: _bucket_stats(v, min_bucket) for k, v in groups.items()}

    breakdowns = {
        "min_bucket_trades": min_bucket,
        "by_market_tier": _group(lambda t: t.market_tier_at_entry or "unknown"),
        "by_sector": _group(lambda t: t.sector or "Unknown"),
        "by_score_bucket": _group(lambda t: _score_bucket(t.entry_composite_score)),
        "by_ai_confidence_bucket": _group(lambda t: _confidence_bucket(journal_by_trade.get(t.id, {}).get("confidence"))),
        "by_entry_time": _group(lambda t: _entry_time_bucket(t.buy_time)),
        "by_intraday_confirmation": _group(
            lambda t: (
                "confirmed_true" if t.intraday_confirmed_at_entry is True
                else ("confirmed_false" if t.intraday_confirmed_at_entry is False else "unknown")
            )
        ),
    }

    # ── 4. Scan Statistics ────────────────────────────────────────────────────
    scans = (
        db.query(ScanResult)
        .filter(ScanResult.scan_date >= start_d, ScanResult.scan_date <= end_d)
        .all()
    )
    regime_dist = Counter(s.regime_status or "unknown" for s in scans)
    no_trade_scans = [s for s in scans if (s.action_taken or "") != "trade"]
    no_trade_reasons = Counter(s.action_taken or "no_trade" for s in no_trade_scans)

    rejection_counts: Counter = Counter()
    total_candidates_shortlisted = 0
    for s in scans:
        total_candidates_shortlisted += int(s.candidates_count or 0)
        if s.rejection_summary:
            try:
                rej = json.loads(s.rejection_summary)
                if isinstance(rej, dict):
                    for reason_val in rej.values():
                        rejection_counts[str(reason_val).split(":")[0]] += 1
            except Exception:
                pass

    ai_picks_count = (
        db.query(AIPick)
        .filter(AIPick.scan_date >= start_d, AIPick.scan_date <= end_d)
        .count()
    )
    ai_approval_rate_pct = (
        round(ai_picks_count / total_candidates_shortlisted * 100.0, 1)
        if total_candidates_shortlisted > 0 else None
    )

    scan_stats = {
        "total_scans": len(scans),
        "regime_distribution": dict(regime_dist),
        "no_trade_days_count": len(no_trade_scans),
        "no_trade_reasons": dict(no_trade_reasons),
        "filter_rejection_counts": dict(rejection_counts.most_common(15)),
        "ai_picks_count": ai_picks_count,
        "ai_approval_rate_pct": ai_approval_rate_pct,
    }

    # ── 5. Baseline Comparison ────────────────────────────────────────────────
    wr_in_range = None
    if win_rate_pct is not None and n_trades >= min_bucket:
        wr_in_range = baseline["win_rate_min_pct"] <= win_rate_pct <= baseline["win_rate_max_pct"]

    ret_low = baseline["weekly_return_mean_pct"] - 2.0 * baseline["weekly_return_std_pct"]
    ret_high = baseline["weekly_return_mean_pct"] + 2.0 * baseline["weekly_return_std_pct"]
    ret_in_range = ret_low <= strat_ret_pct <= ret_high

    baseline_comparison = {
        "baseline_source": baseline["source"],
        "baseline_date": baseline["date"],
        "sample_size": n_trades,
        "weekly_return_pct": strat_ret_pct,
        "expected_weekly_return_range_pct": [round(ret_low, 2), round(ret_high, 2)],
        "return_within_expected_range": ret_in_range,
        "win_rate_pct": win_rate_pct,
        "win_rate_status": "insufficient data" if n_trades < min_bucket else ("within_range" if wr_in_range else "outside_range"),
        "expected_win_rate_range_pct": [baseline["win_rate_min_pct"], baseline["win_rate_max_pct"]],
        "drawdown_pct": drawdown_pct,
        "baseline_max_drawdown_pct": baseline["max_drawdown_pct"],
        "trade_frequency": n_trades,
        "expected_trades_per_week": [baseline["trades_per_week_min"], baseline["trades_per_week_max"]],
    }

    # ── 6. Data-Quality Summary (Feature 3) ───────────────────────────────────
    dq_rows = (
        db.query(DataHealthCheck)
        .filter(DataHealthCheck.checked_at >= start_dt, DataHealthCheck.checked_at <= end_dt)
        .all()
    )
    dq_status_counts = Counter(r.status for r in dq_rows)
    alerts_in_period = (
        db.query(SystemAlert)
        .filter(SystemAlert.created_at >= start_dt, SystemAlert.created_at <= end_dt)
        .all()
    )
    alert_severity_counts = Counter(a.severity for a in alerts_in_period)

    data_quality_summary = {
        "total_checks": len(dq_rows),
        "status_counts": dict(dq_status_counts),
        "total_alerts": len(alerts_in_period),
        "alert_severity_counts": dict(alert_severity_counts),
    }

    # ── 7. Shadow-Mode Summary (Feature 4) ────────────────────────────────────
    shadow_summary = compute_shadow_summary(db, cfg)

    # ── 8. Factual "What to look at" Section (No causal speculation/advice) ────
    observations = []
    if n_trades == 0:
        observations.append(f"0 closed trades recorded between {start_d} and {end_d} (n=0).")
    elif n_trades < min_bucket:
        observations.append(
            f"Sample size is small ({n_trades} closed trade(s), below {min_bucket} minimum); "
            f"statistical breakdowns are labeled 'insufficient data'."
        )
    if derisk["level"] > 0:
        observations.append(
            f"De-risk ladder is currently at Level {derisk['level']} ({derisk['label']}): {derisk['reason']}."
        )
    if alert_severity_counts.get("critical", 0) > 0:
        observations.append(
            f"{alert_severity_counts['critical']} critical alert(s) were emitted during the period."
        )
    if not ret_in_range:
        observations.append(
            f"Weekly return ({strat_ret_pct:.2f}%, n={n_trades}) is outside the expected baseline band "
            f"[{ret_low:.2f}%, {ret_high:.2f}%]."
        )
    if spy_source == "unavailable":
        observations.append("SPY benchmark price source was unavailable during report generation; SPY return defaulted to 0.0%.")
    if not observations:
        observations.append(
            f"All monitored metrics within normal range for {start_d} to {end_d} "
            f"(n={n_trades} trade(s), return={strat_ret_pct:.2f}%, SPY={spy_ret_pct:.2f}%)."
        )

    report_payload = {
        "period_start": start_d.isoformat(),
        "period_end": end_d.isoformat(),
        "period_returns": {
            "sample_size": n_trades,
            "strategy_return_pct": strat_ret_pct,
            "return_source": ret_source,
            "spy_return_pct": spy_ret_pct,
            "spy_source": spy_source,
            "avg_beta": avg_beta,
            "alpha_pct": alpha_pct,
            "win_rate_pct": win_rate_pct,
            "drawdown_pct": drawdown_pct,
            "derisk_level": derisk["level"],
            "derisk_label": derisk["label"],
            "equity_curve": equity_curve,
        },
        "trades": trade_list,
        "breakdowns": breakdowns,
        "scan_statistics": scan_stats,
        "baseline_comparison": baseline_comparison,
        "data_quality_summary": data_quality_summary,
        "shadow_summary": shadow_summary,
        "what_to_look_at": observations,
    }

    summary_text = (
        f"Weekly Report ({start_d} to {end_d}) | Trades: n={n_trades} | "
        f"Return: {strat_ret_pct:+.2f}% vs SPY {spy_ret_pct:+.2f}% (Alpha: {alpha_pct:+.2f}%) | "
        f"De-Risk: L{derisk['level']} | Notes: {' '.join(observations)}"
    )

    row = WeeklyReport(
        period_start=start_d,
        period_end=end_d,
        total_trades=n_trades,
        strategy_return_pct=strat_ret_pct,
        spy_return_pct=spy_ret_pct,
        alpha_pct=alpha_pct,
        derisk_level=int(derisk["level"]),
        report_json=json.dumps(report_payload, default=str),
        summary_text=summary_text,
        created_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    if deliver_alert:
        emit_alert(
            db,
            alert_key=f"report:weekly_{end_d.isoformat()}",
            severity="info",
            category="report",
            title=f"Weekly Performance Report ({start_d} to {end_d})",
            message=summary_text,
            details={"report_id": row.id},
            cooldown_minutes=0,
        )

    return {
        "id": row.id,
        "summary_text": summary_text,
        **report_payload,
    }
