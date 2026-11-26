"""
In-App Alerting & Notification Manager
======================================
Handles structured in-app alerts with:
  - Severity levels: info, warning, critical
  - Deduplication & configurable cooldown to prevent alert spam
  - Operator acknowledgement & auto-resolution tracking
  - Critical data-quality pause gate queried by RiskEngine
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

VALID_SEVERITIES = ("info", "warning", "critical")
CRITICAL_PAUSE_CATEGORIES = ("data_quality", "reconciliation")


def emit_alert(
    db,
    alert_key: str,
    severity: str,
    category: str,
    title: str,
    message: str,
    details: Optional[dict] = None,
    cooldown_minutes: Optional[int] = None,
):
    """
    Emit an in-app alert if not suppressed by deduplication cooldown.
    Also writes a corresponding entry to system_logs so operators see it
    in both the Data Health / Alerts panel and System Logs.
    """
    from models import SystemAlert
    from database import log_event

    sev = severity.lower() if severity else "info"
    if sev not in VALID_SEVERITIES:
        sev = "info"

    if cooldown_minutes is None:
        try:
            from strategy.config import get_system_config
            cfg = get_system_config(db)
            cooldown_minutes = int(cfg.get("alert_cooldown_minutes", 60))
        except Exception:
            cooldown_minutes = 60

    now = datetime.now(timezone.utc)

    try:
        # Deduplication check: look for recent unacknowledged & unresolved alert with same key
        cutoff = now - timedelta(minutes=max(0, cooldown_minutes))
        existing = (
            db.query(SystemAlert)
            .filter(
                SystemAlert.alert_key == alert_key,
                SystemAlert.resolved == False,  # noqa: E712
                SystemAlert.acknowledged == False,  # noqa: E712
                SystemAlert.created_at >= cutoff,
            )
            .order_by(SystemAlert.created_at.desc())
            .first()
        )
        if existing is not None:
            logger.debug(
                "[Alerting] Suppressed duplicate alert '%s' (cooldown %dm).",
                alert_key,
                cooldown_minutes,
            )
            return None

        alert = SystemAlert(
            alert_key=alert_key,
            severity=sev,
            category=category,
            title=title[:200],
            message=message,
            details_json=json.dumps(details or {}, default=str),
            acknowledged=False,
            resolved=False,
            created_at=now,
        )
        db.add(alert)
        db.commit()
        db.refresh(alert)

        log_level = "ERROR" if sev == "critical" else ("WARNING" if sev == "warning" else "INFO")
        emoji = "🚨" if sev == "critical" else ("⚠️" if sev == "warning" else "ℹ️")
        log_event(db, category, f"{emoji} [{sev.upper()}] {title}: {message}", log_level)

        return alert
    except Exception as exc:
        logger.error("[Alerting] Failed to emit alert '%s': %s", alert_key, exc)
        try:
            db.rollback()
        except Exception:
            pass
        return None


def acknowledge_alert(db, alert_id: int, username: str = "admin") -> Optional[dict]:
    """
    Acknowledge an alert by ID. Marks acknowledged=True with timestamp and user.
    If all critical data_quality/reconciliation alerts are acknowledged or resolved,
    the RiskEngine critical pause is automatically lifted.
    """
    from models import SystemAlert
    from database import log_event

    alert = db.query(SystemAlert).filter(SystemAlert.id == alert_id).first()
    if not alert:
        return None

    now = datetime.now(timezone.utc)
    alert.acknowledged = True
    alert.acknowledged_at = now
    alert.acknowledged_by = username
    db.commit()

    log_event(
        db,
        "system",
        f"✅ Alert #{alert_id} ({alert.alert_key}) acknowledged by {username}.",
        "INFO",
    )

    paused, reason = is_dq_critical_paused(db)
    return {
        "id": alert.id,
        "alert_key": alert.alert_key,
        "acknowledged": True,
        "acknowledged_by": username,
        "acknowledged_at": now.isoformat(),
        "dq_critical_paused": paused,
        "dq_pause_reason": reason,
    }


def resolve_alert_by_key(db, alert_key: str) -> int:
    """
    Mark all active (unresolved) alerts matching `alert_key` as resolved.
    Returns count of alerts resolved.
    """
    from models import SystemAlert

    try:
        now = datetime.now(timezone.utc)
        active = (
            db.query(SystemAlert)
            .filter(
                SystemAlert.alert_key == alert_key,
                SystemAlert.resolved == False,  # noqa: E712
            )
            .all()
        )
        for a in active:
            a.resolved = True
            a.resolved_at = now
        if active:
            db.commit()
        return len(active)
    except Exception as exc:
        logger.error("[Alerting] Failed to resolve alert_key '%s': %s", alert_key, exc)
        try:
            db.rollback()
        except Exception:
            pass
        return 0


def is_dq_critical_paused(db) -> tuple[bool, str]:
    """
    Check if any unacknowledged, unresolved CRITICAL data-quality or
    reconciliation alert is currently active.

    Fail-safe: if DB query fails, returns (False, 'ok') only if DB is not
    configured, otherwise logs error.
    """
    if db is None:
        return False, "ok"

    from models import SystemAlert

    try:
        crit = (
            db.query(SystemAlert)
            .filter(
                SystemAlert.severity == "critical",
                SystemAlert.category.in_(CRITICAL_PAUSE_CATEGORIES),
                SystemAlert.acknowledged == False,  # noqa: E712
                SystemAlert.resolved == False,  # noqa: E712
            )
            .order_by(SystemAlert.created_at.desc())
            .first()
        )
        if crit is not None:
            return True, f"dq_critical_pause({crit.alert_key}: {crit.title})"
        return False, "ok"
    except Exception as exc:
        logger.error("[Alerting] Error checking critical pause state: %s", exc)
        return False, "ok"
