"""
Data-Quality Monitoring & Position Reconciliation — Feature 3
=============================================================
Protective & observational monitors that run after each scan and during
market hours. Every monitor is wrapped safely so failures log + alert
without crashing the trading pipeline.

Checks implemented:
  1. Metric coverage check (per scoring metric & achievable score %)
  2. Score distribution check (max, median, p90 & consecutive collapse)
  3. Regime input check (presence, finiteness, freshness)
  4. Price sanity checks (single-bar jumps > 50%, <=0 prices, missing/stale bars)
  5. API health tracking (Finnhub/IBKR/yfinance call counts, errors, latency, no_data spikes)
  6. Cross-source spot check (SPY + sample tickers across sources)
  7. Position & broker-side stop-order reconciliation (DB vs IBKR)
"""

import json
import math
import statistics
import threading
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# Metrics that are permanently unavailable from free sources (not counted as unexpected gaps)
PERMANENT_GAP_METRICS = frozenset({
    "analyst_revisions",
    "insider_buying",
    "options_activity",
})


# ─── Thread-Safe API Health Tracker ──────────────────────────────────────────

class ApiHealthTracker:
    """In-memory, thread-safe tracker for external API calls, errors, rate limits, and latency."""

    def __init__(self):
        self._lock = threading.Lock()
        self._stats: dict[str, dict] = {}

    def record_call(
        self,
        provider: str,
        success: bool,
        latency_ms: float = 0.0,
        rate_limited: bool = False,
        error: str = "",
    ) -> None:
        with self._lock:
            entry = self._stats.setdefault(
                provider,
                {
                    "calls": 0,
                    "errors": 0,
                    "rate_limits": 0,
                    "total_latency_ms": 0.0,
                    "last_error": None,
                    "last_call_at": None,
                },
            )
            entry["calls"] += 1
            if not success:
                entry["errors"] += 1
                entry["last_error"] = error[:200] if error else "unknown_error"
            if rate_limited:
                entry["rate_limits"] += 1
            entry["total_latency_ms"] += max(0.0, float(latency_ms or 0.0))
            entry["last_call_at"] = datetime.now(timezone.utc).isoformat()

    def get_stats(self, provider: Optional[str] = None) -> dict:
        with self._lock:
            if provider is not None:
                raw = self._stats.get(provider, {
                    "calls": 0, "errors": 0, "rate_limits": 0,
                    "total_latency_ms": 0.0, "last_error": None, "last_call_at": None,
                })
                return self._format_provider_stats(raw)
            return {p: self._format_provider_stats(s) for p, s in self._stats.items()}

    def _format_provider_stats(self, raw: dict) -> dict:
        calls = raw["calls"]
        errors = raw["errors"]
        return {
            "calls": calls,
            "errors": errors,
            "error_rate_pct": round((errors / calls * 100.0), 2) if calls > 0 else 0.0,
            "rate_limits": raw["rate_limits"],
            "avg_latency_ms": round((raw["total_latency_ms"] / calls), 1) if calls > 0 else 0.0,
            "last_error": raw["last_error"],
            "last_call_at": raw["last_call_at"],
        }

    def reset(self) -> None:
        with self._lock:
            self._stats.clear()


api_health_tracker = ApiHealthTracker()


# ─── Helper: Persist DataHealthCheck row ─────────────────────────────────────

def _record_check(db, check_name: str, status: str, summary: str, details: Optional[dict] = None) -> None:
    if db is None:
        return
    from models import DataHealthCheck
    try:
        row = DataHealthCheck(
            check_name=check_name,
            status=status,
            summary=summary,
            details_json=json.dumps(details or {}, default=str),
            checked_at=datetime.now(timezone.utc),
        )
        db.add(row)
        db.commit()
    except Exception as exc:
        logger.error("[DataQuality] Failed to persist check '%s': %s", check_name, exc)
        try:
            db.rollback()
        except Exception:
            pass


def _get_cfg(db, config: Optional[dict]) -> dict:
    if config is not None:
        return config
    try:
        from strategy.config import get_system_config
        return get_system_config(db)
    except Exception:
        return {}


# ─── 1. Metric Coverage Check ────────────────────────────────────────────────

def check_metric_coverage(
    db,
    scored_candidates: list[dict],
    config: Optional[dict] = None,
) -> dict:
    """
    Record % of candidates with a valid (non-null, non-gap) value for every
    scoring metric. Alert if any active metric drops below threshold (default 80%)
    or if average achievable score % drops materially below 100 (default < 75%).
    """
    from strategy.scoring_engine import WEIGHTS
    from strategy.alerting import emit_alert, resolve_alert_by_key

    cfg = _get_cfg(db, config)
    min_cov_pct = float(cfg.get("dq_metric_coverage_min_pct", 80.0))
    min_achievable_pct = float(cfg.get("dq_max_achievable_score_min", 75.0))

    try:
        if not scored_candidates:
            res = {
                "check_name": "metric_coverage",
                "status": "ok",
                "candidate_count": 0,
                "summary": "No scored candidates to evaluate coverage.",
                "coverage": {},
                "achievable_score_pct": 100.0,
            }
            _record_check(db, "metric_coverage", "ok", res["summary"], res)
            return res

        n = len(scored_candidates)
        active_metrics = [m for m in WEIGHTS if m not in PERMANENT_GAP_METRICS]
        active_weight_total = sum(WEIGHTS[m] for m in active_metrics)

        coverage = {}
        low_coverage_metrics = []
        for metric in WEIGHTS:
            valid_cnt = sum(1 for c in scored_candidates if metric not in (c.get("data_gaps") or []))
            pct = round(valid_cnt / n * 100.0, 1)
            coverage[metric] = pct
            if metric in active_metrics and pct < min_cov_pct:
                low_coverage_metrics.append((metric, pct))

        # Average effective_max_weight relative to total active (non-permanent-gap) weight
        avg_eff_weight = sum(
            float(c.get("effective_max_weight", active_weight_total))
            for c in scored_candidates
        ) / n
        achievable_pct = round(
            (avg_eff_weight / active_weight_total * 100.0) if active_weight_total > 0 else 0.0,
            1,
        )

        status = "ok"
        issues = []

        if achievable_pct < min_achievable_pct:
            status = "critical"
            msg = (
                f"Achievable scoring weight collapsed to {achievable_pct:.1f}% "
                f"(< {min_achievable_pct:.1f}% threshold) across {n} candidates."
            )
            issues.append(msg)
            emit_alert(
                db,
                alert_key="dq:scoring_data_collapse",
                severity="critical",
                category="data_quality",
                title="Scoring Data Collapse Detected",
                message=msg,
                details={"achievable_pct": achievable_pct, "low_metrics": low_coverage_metrics},
            )
        else:
            resolve_alert_by_key(db, "dq:scoring_data_collapse")

        if low_coverage_metrics:
            if status == "ok":
                status = "warning"
            for metric, pct in low_coverage_metrics:
                msg = f"Metric '{metric}' coverage dropped to {pct:.1f}% (< {min_cov_pct:.1f}%)."
                issues.append(msg)
                emit_alert(
                    db,
                    alert_key=f"dq:metric_coverage:{metric}",
                    severity="warning",
                    category="data_quality",
                    title=f"Low Metric Coverage: {metric}",
                    message=msg,
                    details={"metric": metric, "coverage_pct": pct, "threshold_pct": min_cov_pct},
                )

        summary = (
            f"Evaluated {n} candidates; achievable weight {achievable_pct:.1f}%."
            + (f" Issues: {'; '.join(issues)}" if issues else " All active metrics healthy.")
        )
        res = {
            "check_name": "metric_coverage",
            "status": status,
            "candidate_count": n,
            "achievable_score_pct": achievable_pct,
            "low_coverage_metrics": low_coverage_metrics,
            "coverage": coverage,
            "summary": summary,
        }
        _record_check(db, "metric_coverage", status, summary, res)
        return res
    except Exception as exc:
        logger.error("[DataQuality] check_metric_coverage error: %s", exc)
        return {"check_name": "metric_coverage", "status": "warning", "summary": f"Monitor error: {exc}"}


# ─── 2. Score Distribution Check ─────────────────────────────────────────────

def check_score_distribution(
    db,
    scored_candidates: list[dict],
    config: Optional[dict] = None,
) -> dict:
    """
    Track composite score distribution (max, median, p90) per scan.
    Alert CRITICAL if max score falls below threshold for N consecutive scans.
    """
    from models import DataHealthCheck
    from strategy.alerting import emit_alert, resolve_alert_by_key

    cfg = _get_cfg(db, config)
    collapse_max = float(cfg.get("dq_score_collapse_max_threshold", 60.0))
    consec_required = int(cfg.get("dq_score_collapse_consecutive_scans", 3))

    try:
        scores = sorted([float(c.get("composite_score", 0.0)) for c in scored_candidates])
        if not scores:
            res = {
                "check_name": "score_distribution",
                "status": "ok",
                "count": 0,
                "max": None,
                "median": None,
                "p90": None,
                "summary": "No scored candidates in scan.",
            }
            _record_check(db, "score_distribution", "ok", res["summary"], res)
            return res

        max_score = round(max(scores), 1)
        median_score = round(statistics.median(scores), 1)
        p90_idx = min(len(scores) - 1, int(math.floor(0.9 * (len(scores) - 1))))
        p90_score = round(scores[p90_idx], 1)

        # Count how many prior consecutive scans had max < collapse_max
        prior_depressed = 0
        if db is not None and consec_required > 1:
            recent_checks = (
                db.query(DataHealthCheck)
                .filter(DataHealthCheck.check_name == "score_distribution")
                .order_by(DataHealthCheck.checked_at.desc())
                .limit(consec_required - 1)
                .all()
            )
            for row in recent_checks:
                try:
                    det = json.loads(row.details_json or "{}")
                    if det.get("count", 0) > 0 and float(det.get("max", 100.0)) < collapse_max:
                        prior_depressed += 1
                    else:
                        break
                except Exception:
                    break

        is_current_depressed = max_score < collapse_max
        consecutive_depressed = (prior_depressed + 1) if is_current_depressed else 0

        status = "ok"
        if consecutive_depressed >= consec_required:
            status = "critical"
            msg = (
                f"Max composite score {max_score:.1f} < {collapse_max:.1f} for "
                f"{consecutive_depressed} consecutive scans — likely data collapse."
            )
            emit_alert(
                db,
                alert_key="dq:score_collapse",
                severity="critical",
                category="data_quality",
                title="Score Distribution Collapse",
                message=msg,
                details={
                    "max": max_score,
                    "median": median_score,
                    "p90": p90_score,
                    "consecutive_depressed": consecutive_depressed,
                },
            )
        elif is_current_depressed:
            status = "warning"
            emit_alert(
                db,
                alert_key="dq:score_depressed",
                severity="warning",
                category="data_quality",
                title="Depressed Scan Scores",
                message=f"Max composite score {max_score:.1f} < {collapse_max:.1f} ({consecutive_depressed}/{consec_required} scans).",
                details={"max": max_score, "median": median_score, "p90": p90_score},
            )
        else:
            resolve_alert_by_key(db, "dq:score_collapse")
            resolve_alert_by_key(db, "dq:score_depressed")

        summary = f"Scores (n={len(scores)}): max={max_score}, median={median_score}, p90={p90_score}"
        res = {
            "check_name": "score_distribution",
            "status": status,
            "count": len(scores),
            "max": max_score,
            "median": median_score,
            "p90": p90_score,
            "consecutive_depressed": consecutive_depressed,
            "summary": summary,
        }
        _record_check(db, "score_distribution", status, summary, res)
        return res
    except Exception as exc:
        logger.error("[DataQuality] check_score_distribution error: %s", exc)
        return {"check_name": "score_distribution", "status": "warning", "summary": f"Monitor error: {exc}"}


# ─── 3. Regime Input Check ───────────────────────────────────────────────────

def check_regime_inputs(
    db,
    regime_data: Optional[dict],
    breadth_data: Optional[dict] = None,
    config: Optional[dict] = None,
    is_market_open: bool = False,
) -> dict:
    """
    Verify every regime input (SPY price/SMAs, VIX, breadth, daily change)
    is present, finite, and fresh. Missing/NaN/stale inputs emit a critical
    alert (forcing RiskEngine pause) and fail safe.
    """
    from strategy.alerting import emit_alert, resolve_alert_by_key

    cfg = _get_cfg(db, config)
    max_age_min = int(cfg.get("dq_regime_max_age_minutes", 120))

    try:
        issues = []
        if not regime_data or not isinstance(regime_data, dict):
            issues.append("regime_data is missing/None")
        else:
            if regime_data.get("is_valid") is False or regime_data.get("regime") in ("unavailable", "unknown", None):
                issues.append(f"regime marked invalid ({regime_data.get('regime')})")

            required_nums = ["spy_price", "spy_sma_200", "vix", "spy_day_return_pct"]
            for field in required_nums:
                val = regime_data.get(field)
                if val is None:
                    issues.append(f"{field} is None")
                else:
                    try:
                        fval = float(val)
                        if not math.isfinite(fval):
                            issues.append(f"{field} is NaN/Inf")
                    except (TypeError, ValueError):
                        issues.append(f"{field} is non-numeric ({val})")

            # Freshness check if timestamp/fetched provided
            ts_raw = regime_data.get("timestamp") or regime_data.get("fetched")
            if ts_raw:
                try:
                    if isinstance(ts_raw, str):
                        ts_dt = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
                    else:
                        ts_dt = ts_raw
                    if ts_dt.tzinfo is None:
                        ts_dt = ts_dt.replace(tzinfo=timezone.utc)
                    age_min = (datetime.now(timezone.utc) - ts_dt).total_seconds() / 60.0
                    if age_min > max_age_min:
                        issues.append(f"regime data stale ({age_min:.0f}m > {max_age_min}m)")
                except Exception:
                    pass

        if breadth_data is not None and isinstance(breadth_data, dict):
            bp = breadth_data.get("breadth_pct")
            if bp is not None:
                try:
                    if not math.isfinite(float(bp)):
                        issues.append("breadth_pct is NaN/Inf")
                except (TypeError, ValueError):
                    issues.append("breadth_pct non-numeric")

        if issues:
            # Always critical if regime fails during market hours or scan
            severity = "critical"
            msg = f"Regime inputs failed validation: {'; '.join(issues)}"
            emit_alert(
                db,
                alert_key="dq:regime_inputs_invalid",
                severity=severity,
                category="data_quality",
                title="Regime Inputs Unavailable / Invalid",
                message=msg,
                details={"issues": issues, "is_market_open": is_market_open},
            )
            res = {
                "check_name": "regime_inputs",
                "status": "critical",
                "valid": False,
                "issues": issues,
                "summary": msg,
            }
            _record_check(db, "regime_inputs", "critical", msg, res)
            return res

        resolve_alert_by_key(db, "dq:regime_inputs_invalid")
        summary = (
            f"Regime inputs valid & finite (SPY=${regime_data.get('spy_price')}, "
            f"VIX={regime_data.get('vix')})."
        )
        res = {
            "check_name": "regime_inputs",
            "status": "ok",
            "valid": True,
            "issues": [],
            "summary": summary,
        }
        _record_check(db, "regime_inputs", "ok", summary, res)
        return res
    except Exception as exc:
        logger.error("[DataQuality] check_regime_inputs error: %s", exc)
        return {"check_name": "regime_inputs", "status": "critical", "valid": False, "summary": f"Monitor error: {exc}"}


# ─── 4. Price Sanity Checks ──────────────────────────────────────────────────

def check_price_sanity(
    db,
    ohlcv_map: Optional[dict] = None,
    open_positions: Optional[list[dict]] = None,
    config: Optional[dict] = None,
    is_market_open: bool = False,
) -> dict:
    """
    Flag:
      - Zero or negative prices
      - Single-bar moves > threshold (default 50%) without corporate action note
      - Missing recent bars
      - Stale last-trade / quote timestamps on held positions
    """
    from strategy.alerting import emit_alert, resolve_alert_by_key

    cfg = _get_cfg(db, config)
    jump_max_pct = float(cfg.get("dq_price_jump_max_pct", 50.0))
    held_stale_min = int(cfg.get("dq_held_stale_minutes", 30))

    try:
        anomalies = []
        critical_anomalies = []
        now = datetime.now(timezone.utc)

        if ohlcv_map:
            for ticker, df in ohlcv_map.items():
                if df is None or len(df) == 0:
                    anomalies.append({"ticker": ticker, "issue": "empty_ohlcv"})
                    continue

                if "Close" in df.columns:
                    closes = df["Close"].dropna()
                    if len(closes) == 0 or (closes <= 0).any():
                        anomalies.append({"ticker": ticker, "issue": "zero_or_negative_price"})

                    # Check last 5 bars for huge single-bar jump
                    if len(closes) >= 2:
                        recent = closes.iloc[-min(6, len(closes)):]
                        pct_changes = recent.pct_change().dropna().abs() * 100.0
                        max_jump = float(pct_changes.max()) if len(pct_changes) > 0 else 0.0
                        if math.isfinite(max_jump) and max_jump > jump_max_pct:
                            anomalies.append({
                                "ticker": ticker,
                                "issue": f"single_bar_jump_{max_jump:.1f}pct",
                            })

                    # Check bar recency (allow up to 5 calendar days for weekends/holidays)
                    try:
                        last_idx = df.index[-1]
                        if hasattr(last_idx, "to_pydatetime"):
                            last_dt = last_idx.to_pydatetime()
                        elif isinstance(last_idx, datetime):
                            last_dt = last_idx
                        else:
                            last_dt = None
                        if last_dt is not None:
                            if last_dt.tzinfo is None:
                                last_dt = last_dt.replace(tzinfo=timezone.utc)
                            if (now - last_dt).days > 5:
                                anomalies.append({"ticker": ticker, "issue": "missing_recent_bars"})
                    except Exception:
                        pass

        if open_positions:
            for pos in open_positions:
                ticker = pos.get("ticker", "UNKNOWN")
                px = pos.get("current_price") or pos.get("buy_price")
                if px is None or not math.isfinite(float(px)) or float(px) <= 0:
                    critical_anomalies.append({"ticker": ticker, "issue": "held_invalid_price"})

                ts_raw = pos.get("quote_timestamp") or pos.get("last_updated")
                if is_market_open and ts_raw:
                    try:
                        ts_dt = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
                        if ts_dt.tzinfo is None:
                            ts_dt = ts_dt.replace(tzinfo=timezone.utc)
                        age_min = (now - ts_dt).total_seconds() / 60.0
                        if age_min > held_stale_min:
                            anomalies.append({
                                "ticker": ticker,
                                "issue": f"stale_held_quote_{age_min:.0f}m",
                            })
                    except Exception:
                        pass

        status = "ok"
        if critical_anomalies:
            status = "critical"
            msg = f"Critical price sanity failures on held positions: {critical_anomalies}"
            emit_alert(
                db,
                alert_key="dq:price_sanity_critical",
                severity="critical",
                category="data_quality",
                title="Critical Price Sanity Failure",
                message=msg,
                details={"critical": critical_anomalies, "warnings": anomalies},
            )
        elif anomalies:
            status = "warning"
            resolve_alert_by_key(db, "dq:price_sanity_critical")
            msg = f"Price sanity warnings ({len(anomalies)}): {anomalies[:5]}"
            emit_alert(
                db,
                alert_key="dq:price_sanity_warning",
                severity="warning",
                category="data_quality",
                title="Price Sanity Warning",
                message=msg,
                details={"anomalies": anomalies},
            )
        else:
            resolve_alert_by_key(db, "dq:price_sanity_critical")
            resolve_alert_by_key(db, "dq:price_sanity_warning")

        summary = (
            f"Checked {len(ohlcv_map or {})} OHLCV series & {len(open_positions or [])} held positions. "
            f"Critical={len(critical_anomalies)}, Warnings={len(anomalies)}."
        )
        res = {
            "check_name": "price_sanity",
            "status": status,
            "critical_anomalies": critical_anomalies,
            "anomalies": anomalies,
            "summary": summary,
        }
        _record_check(db, "price_sanity", status, summary, res)
        return res
    except Exception as exc:
        logger.error("[DataQuality] check_price_sanity error: %s", exc)
        return {"check_name": "price_sanity", "status": "warning", "summary": f"Monitor error: {exc}"}


# ─── 5. API Health Check ─────────────────────────────────────────────────────

def check_api_health(
    db,
    no_data_count: Optional[int] = None,
    total_universe: Optional[int] = None,
    config: Optional[dict] = None,
) -> dict:
    """
    Evaluate Finnhub/IBKR/yfinance API health (error rates, rate limits, latency)
    and check for no_data spikes during scans.
    """
    from strategy.alerting import emit_alert, resolve_alert_by_key

    cfg = _get_cfg(db, config)
    err_threshold = float(cfg.get("dq_api_error_rate_threshold_pct", 20.0))
    min_calls = int(cfg.get("dq_api_min_calls_for_rate", 5))
    no_data_spike_pct = float(cfg.get("dq_no_data_spike_threshold_pct", 50.0))

    try:
        stats = api_health_tracker.get_stats()
        issues = []

        for provider, s in stats.items():
            if s["calls"] >= min_calls and s["error_rate_pct"] > err_threshold:
                issues.append(f"{provider} error rate {s['error_rate_pct']}% ({s['errors']}/{s['calls']})")
            if s["rate_limits"] > 0:
                issues.append(f"{provider} hit {s['rate_limits']} rate-limit(s)")

        no_data_pct = None
        if no_data_count is not None and total_universe and total_universe > 0:
            no_data_pct = round(no_data_count / total_universe * 100.0, 1)
            if no_data_pct > no_data_spike_pct:
                issues.append(f"no_data spike: {no_data_count}/{total_universe} ({no_data_pct}%)")

        status = "ok"
        if issues:
            status = "warning"
            msg = f"API/Data degradation: {'; '.join(issues)}"
            emit_alert(
                db,
                alert_key="dq:api_health",
                severity="warning",
                category="data_quality",
                title="API Health Warning",
                message=msg,
                details={"stats": stats, "no_data_pct": no_data_pct},
            )
        else:
            resolve_alert_by_key(db, "dq:api_health")

        summary = f"API stats tracked for {len(stats)} provider(s)." + (f" Issues: {'; '.join(issues)}" if issues else " Healthy.")
        res = {
            "check_name": "api_health",
            "status": status,
            "providers": stats,
            "no_data_count": no_data_count,
            "total_universe": total_universe,
            "no_data_pct": no_data_pct,
            "summary": summary,
        }
        _record_check(db, "api_health", status, summary, res)
        return res
    except Exception as exc:
        logger.error("[DataQuality] check_api_health error: %s", exc)
        return {"check_name": "api_health", "status": "warning", "summary": f"Monitor error: {exc}"}


# ─── 6. Cross-Source Spot Check ──────────────────────────────────────────────

def run_cross_source_spot_check(
    db,
    price_pairs: Optional[dict[str, tuple[float, float]]] = None,
    ibkr_client=None,
    sample_tickers: Optional[list[str]] = None,
    config: Optional[dict] = None,
) -> dict:
    """
    Compare closing/latest prices for SPY and sample tickers across two sources
    (e.g. Finnhub/yfinance vs IBKR). `price_pairs` can be injected directly in tests
    as `{ticker: (source_a_price, source_b_price)}`.
    """
    from strategy.alerting import emit_alert, resolve_alert_by_key

    cfg = _get_cfg(db, config)
    tol_pct = float(cfg.get("dq_cross_source_tolerance_pct", 2.0))

    try:
        pairs = dict(price_pairs or {})

        # Live lookup when price_pairs is not explicitly supplied
        if not pairs:
            tickers = list(dict.fromkeys(["SPY"] + (sample_tickers or [])[:3]))
            from strategy.data_layer import fetch_ohlcv
            for t in tickers:
                try:
                    df = fetch_ohlcv(t, period="5d")
                    if df is not None and len(df) > 0:
                        px_yf = float(df["Close"].iloc[-1])
                        if ibkr_client is not None and getattr(ibkr_client, "ib", None) and ibkr_client.ib.isConnected():
                            # Attempt IBKR lookup via positions or historical bar
                            pass
                        # Fallback: compare yfinance vs Finnhub quote if FINNHUB_API configured
                        try:
                            from strategy.data_layer import _get_finnhub_client
                            fc = _get_finnhub_client()
                            if fc is not None:
                                q = fc.quote(t)
                                px_fh = float(q.get("c") or 0.0)
                                if px_fh > 0 and px_yf > 0:
                                    pairs[t] = (px_yf, px_fh)
                        except Exception:
                            pass
                except Exception:
                    pass

        discrepancies = []
        checked = {}
        for ticker, (px_a, px_b) in pairs.items():
            if px_a and px_b and px_a > 0 and px_b > 0:
                diff_pct = abs(px_a - px_b) / ((px_a + px_b) / 2.0) * 100.0
                checked[ticker] = {"source_a": round(px_a, 4), "source_b": round(px_b, 4), "diff_pct": round(diff_pct, 3)}
                if diff_pct > tol_pct:
                    discrepancies.append({"ticker": ticker, **checked[ticker]})

        status = "ok"
        if discrepancies:
            status = "warning"
            msg = f"Cross-source price discrepancies > {tol_pct}%: {discrepancies}"
            emit_alert(
                db,
                alert_key="dq:cross_source_mismatch",
                severity="warning",
                category="data_quality",
                title="Cross-Source Price Discrepancy",
                message=msg,
                details={"discrepancies": discrepancies, "tolerance_pct": tol_pct},
            )
        else:
            resolve_alert_by_key(db, "dq:cross_source_mismatch")

        summary = (
            f"Spot-checked {len(checked)} ticker(s) (tolerance={tol_pct}%)."
            + (f" {len(discrepancies)} discrepancy(ies)." if discrepancies else " All aligned.")
        )
        res = {
            "check_name": "cross_source_spot_check",
            "status": status,
            "checked": checked,
            "discrepancies": discrepancies,
            "summary": summary,
        }
        _record_check(db, "cross_source_spot_check", status, summary, res)
        return res
    except Exception as exc:
        logger.error("[DataQuality] run_cross_source_spot_check error: %s", exc)
        return {"check_name": "cross_source_spot_check", "status": "warning", "summary": f"Monitor error: {exc}"}


# ─── 7. Position & Broker-Side Stop Reconciliation ───────────────────────────

def reconcile_positions_and_stops(
    db,
    ibkr_client,
    config: Optional[dict] = None,
    is_market_open: bool = True,
) -> dict:
    """
    Compare DB open trades against actual IBKR positions & open orders.
    Confirms every open position has a live broker-side stop order (STP / STP LMT).
    Mismatches and missing broker-side stops emit CRITICAL alerts and pause entries.
    """
    from models import Trade
    from strategy.alerting import emit_alert, resolve_alert_by_key

    try:
        db_open_trades = (
            db.query(Trade)
            .filter(Trade.status.in_(["open", "sold_half"]))
            .all()
        )
        db_by_ticker = {}
        for t in db_open_trades:
            db_by_ticker[t.ticker] = {
                "id": t.id,
                "shares": float(t.shares or 0),
                "stop_order_id": t.stop_order_id,
                "stop_price": t.stop_price,
            }

        if ibkr_client is None:
            status = "warning"
            summary = "IBKR client not provided for reconciliation."
            _record_check(db, "position_reconciliation", status, summary, {"db_open_count": len(db_by_ticker)})
            return {"check_name": "position_reconciliation", "status": status, "summary": summary}

        ibkr_positions_list = ibkr_client.get_positions()
        ibkr_by_ticker = {}
        for p in ibkr_positions_list or []:
            sym = p.get("ticker")
            qty = float(p.get("shares") or 0)
            if sym and qty != 0:
                ibkr_by_ticker[sym] = qty

        open_orders = []
        if hasattr(ibkr_client, "get_open_orders"):
            open_orders = ibkr_client.get_open_orders() or []
        elif getattr(ibkr_client, "ib", None) is not None:
            for ot in ibkr_client.ib.openTrades() or []:
                open_orders.append({
                    "ticker": getattr(ot.contract, "symbol", None),
                    "action": getattr(ot.order, "action", None),
                    "order_type": getattr(ot.order, "orderType", None),
                    "total_quantity": float(getattr(ot.order, "totalQuantity", 0) or 0),
                    "order_id": str(getattr(ot.order, "orderId", "")),
                    "status": getattr(getattr(ot, "orderStatus", None), "status", ""),
                })

        mismatches = []
        missing_stops = []

        all_tickers = sorted(set(db_by_ticker.keys()) | set(ibkr_by_ticker.keys()))
        for ticker in all_tickers:
            in_db = ticker in db_by_ticker
            in_ibkr = ticker in ibkr_by_ticker

            if in_db and not in_ibkr:
                mismatches.append({"ticker": ticker, "issue": "in_db_missing_in_ibkr", "db_shares": db_by_ticker[ticker]["shares"]})
                continue
            if in_ibkr and not in_db:
                mismatches.append({"ticker": ticker, "issue": "in_ibkr_missing_in_db", "ibkr_shares": ibkr_by_ticker[ticker]})
                continue

            db_qty = db_by_ticker[ticker]["shares"]
            ibkr_qty = ibkr_by_ticker[ticker]
            if abs(db_qty - ibkr_qty) > 0.01:
                mismatches.append({
                    "ticker": ticker,
                    "issue": "share_quantity_mismatch",
                    "db_shares": db_qty,
                    "ibkr_shares": ibkr_qty,
                })

        # Verify broker-side stop orders for all IBKR open positions
        # Distinguish 3 states: live | queued_outside_hours | missing
        queued_stops = []
        fractional_unprotected = []
        for ticker, qty in ibkr_by_ticker.items():
            if qty <= 0:
                continue
            stop_orders = [
                o for o in open_orders
                if o.get("ticker") == ticker
                and str(o.get("action", "")).upper() == "SELL"
                and str(o.get("order_type", "")).upper() in ("STP", "STP LMT", "TRAIL")
                and str(o.get("status", "")).lower() not in ("cancelled", "apicancelled", "inactive", "filled")
            ]
            covered_qty = sum(float(o.get("total_quantity") or 0) for o in stop_orders)
            if stop_orders and covered_qty >= qty - 0.01:
                has_presubmitted = any(str(o.get("status", "")).lower() == "presubmitted" for o in stop_orders)
                if not is_market_open and has_presubmitted:
                    queued_stops.append({"ticker": ticker, "position_shares": qty, "stop_state": "queued_outside_hours"})
            elif qty < 1.0:
                # IBKR does not support GTC native STP orders on fractional < 1 share positions
                fractional_unprotected.append({
                    "ticker": ticker,
                    "position_shares": qty,
                    "issue": "fractional_unprotected_by_native_stop",
                })
            else:
                missing_stops.append({
                    "ticker": ticker,
                    "position_shares": qty,
                    "stop_covered_shares": covered_qty,
                    "stop_state": "missing",
                })

        status = "ok"
        if mismatches:
            status = "critical"
            msg = f"Position reconciliation mismatch (DB vs IBKR): {mismatches}"
            emit_alert(
                db,
                alert_key="dq:position_mismatch",
                severity="critical",
                category="reconciliation",
                title="Position Mismatch (DB vs IBKR)",
                message=msg,
                details={"mismatches": mismatches},
            )
        else:
            resolve_alert_by_key(db, "dq:position_mismatch")

        if missing_stops:
            status = "critical"
            msg = f"CRITICAL: Open positions missing broker-side stop order: {missing_stops}"
            emit_alert(
                db,
                alert_key="dq:missing_broker_stop",
                severity="critical",
                category="reconciliation",
                title="Missing Broker-Side Stop Order",
                message=msg,
                details={"missing_stops": missing_stops},
            )
        else:
            resolve_alert_by_key(db, "dq:missing_broker_stop")

        if fractional_unprotected and status == "ok":
            status = "warning"
            emit_alert(
                db,
                alert_key="dq:fractional_stop_warning",
                severity="warning",
                category="reconciliation",
                title="Fractional Position Without Native Broker Stop",
                message=f"Fractional <1 share position(s) monitored via software exit only: {fractional_unprotected}",
                details={"fractional_unprotected": fractional_unprotected},
            )

        summary = (
            f"Reconciled {len(all_tickers)} position(s): DB={len(db_by_ticker)}, "
            f"IBKR={len(ibkr_by_ticker)}, mismatches={len(mismatches)}, "
            f"missing_stops={len(missing_stops)}, queued_stops={len(queued_stops)}."
        )
        res = {
            "check_name": "position_reconciliation",
            "status": status,
            "db_positions": len(db_by_ticker),
            "ibkr_positions": len(ibkr_by_ticker),
            "mismatches": mismatches,
            "missing_stops": missing_stops,
            "queued_stops": queued_stops,
            "fractional_unprotected": fractional_unprotected,
            "summary": summary,
        }
        _record_check(db, "position_reconciliation", status, summary, res)
        return res
    except Exception as exc:
        logger.error("[DataQuality] reconcile_positions_and_stops error: %s", exc)
        try:
            emit_alert(
                db,
                alert_key="dq:reconciliation_error",
                severity="warning",
                category="reconciliation",
                title="Position Reconciliation Error",
                message=str(exc),
            )
        except Exception:
            pass
        return {"check_name": "position_reconciliation", "status": "warning", "summary": f"Monitor error: {exc}"}


def repair_missing_stops(db, ibkr_client, is_market_open: bool = True) -> dict:
    """
    Idempotent repair routine for genuinely missing broker-side stops on
    whole-share open positions. Only places stops during open market hours.
    """
    from models import Trade
    from strategy.alerting import emit_alert

    if not is_market_open:
        return {"repaired": [], "skipped": "market_closed"}

    rec = reconcile_positions_and_stops(db, ibkr_client, is_market_open=True)
    repaired = []
    for m in rec.get("missing_stops", []):
        ticker = m["ticker"]
        qty = int(m["position_shares"])
        if qty < 1:
            continue
        trade = db.query(Trade).filter(Trade.ticker == ticker, Trade.status.in_(["open", "sold_half"])).first()
        stop_px = float(trade.stop_price) if (trade and trade.stop_price) else None
        if stop_px and stop_px > 0:
            res = ibkr_client.place_stop_order(ticker, qty, stop_px)
            if res.get("success") and trade:
                trade.stop_order_id = str(res.get("order_id", ""))
                db.commit()
                repaired.append({"ticker": ticker, "shares": qty, "stop_price": stop_px, "order_id": trade.stop_order_id})
                emit_alert(
                    db,
                    alert_key=f"dq:stop_repaired:{ticker}",
                    severity="info",
                    category="reconciliation",
                    title=f"Repaired Missing Stop Order: {ticker}",
                    message=f"Placed GTC stop for {qty} shares @ ${stop_px:.2f} (order_id={trade.stop_order_id}).",
                    cooldown_minutes=0,
                )
    return {"repaired": repaired}
