"""
Journal & Alerting — Phase 7
============================
Structured logging, trade journaling, and alert dispatch.

journal.py: Persists all scan results and trade events to the DB.
alerting.py: Sends notifications on trade events and circuit breaker triggers.
"""

import logging
import json
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


# ─── Journal functions ────────────────────────────────────────────────────────

def log_scan_result(
    db,
    scan_date,
    regime_status: str,
    regime_details: str,
    candidates_count: int,
    high_conviction_count: int,
    marginal_count: int,
    action_taken: str,
    candidates_json: Optional[list] = None,
    rejection_summary: Optional[dict] = None,
):
    """Persist a daily scan result to the scan_results table."""
    from models import ScanResult
    try:
        record = ScanResult(
            scan_date=scan_date,
            regime_status=regime_status,
            regime_details=regime_details,
            candidates_count=candidates_count,
            high_conviction_count=high_conviction_count,
            marginal_count=marginal_count,
            action_taken=action_taken,
            candidates_json=json.dumps(candidates_json or []),
            rejection_summary=json.dumps(rejection_summary or {}),
            created_at=datetime.now(timezone.utc),
        )
        db.add(record)
        db.commit()
        logger.info(
            "[Journal] Scan result logged: %s | regime=%s | action=%s | %d candidates",
            scan_date, regime_status, action_taken, candidates_count,
        )
    except Exception as exc:
        logger.error("[Journal] Failed to log scan result: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass


def log_trade_event(
    db,
    trade_id: int,
    event_type: str,
    details: str,
    composite_score: Optional[float] = None,
    confidence_score: Optional[int] = None,
    stop_price: Optional[float] = None,
    trailing_stop_price: Optional[float] = None,
    ai_gemini_json: Optional[dict] = None,
    ai_crosscheck_json: Optional[dict] = None,
    regime_at_event: Optional[str] = None,
):
    """Persist a trade lifecycle event to the trade_journal_entries table."""
    from models import TradeJournalEntry
    try:
        entry = TradeJournalEntry(
            trade_id=trade_id,
            event_type=event_type,
            details=details,
            composite_score=composite_score,
            confidence_score=confidence_score,
            stop_price=stop_price,
            trailing_stop_price=trailing_stop_price,
            ai_gemini_json=json.dumps(ai_gemini_json) if ai_gemini_json else None,
            ai_crosscheck_json=json.dumps(ai_crosscheck_json) if ai_crosscheck_json else None,
            regime_at_event=regime_at_event,
            created_at=datetime.now(timezone.utc),
        )
        db.add(entry)
        db.commit()
    except Exception as exc:
        logger.error("[Journal] Failed to log trade event (trade_id=%s, type=%s): %s",
                     trade_id, event_type, exc)
        try:
            db.rollback()
        except Exception:
            pass


def log_circuit_breaker(db, reason: str, details: str = ""):
    """Log a circuit breaker activation to system_logs and risk_engine_state."""
    from database import log_event as _log_event
    try:
        _log_event(db, "risk", f"⛔ CIRCUIT BREAKER: {reason} — {details}", "WARNING")
    except Exception as exc:
        logger.error("[Journal] Failed to log circuit breaker: %s", exc)


def log_no_trade_day(db, reason: str, details: str = ""):
    """Log a 'no trade today' decision. This is a valid, expected system output."""
    from database import log_event as _log_event
    _log_event(db, "scan", f"✅ No trade today: {reason}. {details}")
    logger.info("[Journal] No trade today: %s — %s", reason, details)
