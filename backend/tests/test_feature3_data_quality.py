import os
import sys
import math
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models import Base, Trade, SystemAlert, DataHealthCheck
from strategy.alerting import emit_alert, acknowledge_alert, is_dq_critical_paused
from strategy.data_quality import (
    check_metric_coverage,
    check_score_distribution,
    check_regime_inputs,
    check_price_sanity,
    check_api_health,
    run_cross_source_spot_check,
    reconcile_positions_and_stops,
    api_health_tracker,
)
from strategy.risk_engine import RiskEngine


class TestFeature3DataQuality(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        Session = sessionmaker(bind=self.engine)
        self.db = Session()
        self.risk_engine = RiskEngine()
        api_health_tracker.reset()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _assert_risk_engine_blocks(self):
        allowed, reason = self.risk_engine.check_new_entry(
            ticker="AAPL",
            sector="Technology",
            entry_price=150.0,
            stop_price=145.0,
            proposed_shares=10,
            account_equity=10000.0,
            open_positions=[],
            peak_equity=10000.0,
            daily_pnl_pct=0.0,
            weekly_pnl_pct=0.0,
            regime="risk_on",
            db=self.db,
        )
        self.assertFalse(allowed)
        self.assertIn("data_quality_pause", reason)

    def _assert_risk_engine_allows(self):
        allowed, reason = self.risk_engine.check_new_entry(
            ticker="AAPL",
            sector="Technology",
            entry_price=150.0,
            stop_price=145.0,
            proposed_shares=10,
            account_equity=10000.0,
            open_positions=[],
            peak_equity=10000.0,
            daily_pnl_pct=0.0,
            weekly_pnl_pct=0.0,
            regime="risk_on",
            db=self.db,
        )
        self.assertTrue(allowed, f"Expected allowed, got blocked: {reason}")

    def test_nan_and_stale_regime_inputs_pause_entries(self):
        # NaN VIX
        res = check_regime_inputs(
            self.db,
            {"regime": "risk_on", "is_valid": True, "spy_price": 500.0, "spy_sma200": 480.0, "vix": float("nan"), "spy_day_return_pct": 0.2},
            is_market_open=True,
        )
        self.assertEqual(res["status"], "critical")
        self._assert_risk_engine_blocks()

        # Acknowledge clears pause, then test stale timestamp
        alert = self.db.query(SystemAlert).filter(SystemAlert.alert_key == "dq:regime_inputs_invalid").first()
        self.assertIsNotNone(alert)
        acknowledge_alert(self.db, alert.id, "tester")
        self._assert_risk_engine_allows()

        stale_ts = (datetime.now(timezone.utc) - timedelta(hours=4)).isoformat()
        res_stale = check_regime_inputs(
            self.db,
            {"regime": "risk_on", "is_valid": True, "spy_price": 500.0, "spy_sma200": 480.0, "vix": 15.0, "spy_day_return_pct": 0.2, "timestamp": stale_ts},
            config={"dq_regime_max_age_minutes": 60},
            is_market_open=True,
        )
        self.assertEqual(res_stale["status"], "critical")
        self._assert_risk_engine_blocks()

    def test_metric_coverage_0_pct_and_scoring_collapse(self):
        # Single metric drops to 0% coverage, plus achievable weight drops below 75%
        candidates = [
            {"ticker": "AAPL", "data_gaps": ["revenue_growth", "eps_growth", "fcf_quality", "debt_ratio", "profit_margins", "institutional_own", "beta", "sector_rs"], "effective_max_weight": 60.0},
            {"ticker": "MSFT", "data_gaps": ["revenue_growth", "eps_growth", "fcf_quality", "debt_ratio", "profit_margins", "institutional_own", "beta", "sector_rs"], "effective_max_weight": 60.0},
        ]
        res = check_metric_coverage(self.db, candidates)
        self.assertEqual(res["status"], "critical")
        self.assertEqual(res["coverage"]["revenue_growth"], 0.0)
        self._assert_risk_engine_blocks()

    def test_score_distribution_consecutive_collapse(self):
        low_candidates = [{"ticker": "A", "composite_score": 45.0}, {"ticker": "B", "composite_score": 52.0}]
        cfg = {"dq_score_collapse_max_threshold": 60.0, "dq_score_collapse_consecutive_scans": 3}

        r1 = check_score_distribution(self.db, low_candidates, config=cfg)
        self.assertEqual(r1["status"], "warning")
        r2 = check_score_distribution(self.db, low_candidates, config=cfg)
        self.assertEqual(r2["status"], "warning")
        r3 = check_score_distribution(self.db, low_candidates, config=cfg)
        self.assertEqual(r3["status"], "critical")
        self._assert_risk_engine_blocks()

    def test_price_sanity_60pct_jump_and_held_zero_price(self):
        dates = pd.date_range(end=datetime.now(timezone.utc), periods=5, freq="D")
        df_jump = pd.DataFrame({"Close": [100.0, 102.0, 101.0, 165.0, 166.0]}, index=dates)
        res_warn = check_price_sanity(self.db, ohlcv_map={"NVDA": df_jump}, open_positions=[])
        self.assertEqual(res_warn["status"], "warning")
        self.assertTrue(any("single_bar_jump" in a["issue"] for a in res_warn["anomalies"]))

        res_crit = check_price_sanity(
            self.db,
            ohlcv_map={},
            open_positions=[{"ticker": "AMD", "current_price": 0.0}],
            is_market_open=True,
        )
        self.assertEqual(res_crit["status"], "critical")
        self._assert_risk_engine_blocks()

    def test_api_health_and_cross_source_spot_check(self):
        for _ in range(6):
            api_health_tracker.record_call("finnhub", success=False, latency_ms=120.0, rate_limited=True, error="429")
        res_api = check_api_health(self.db, no_data_count=60, total_universe=100)
        self.assertEqual(res_api["status"], "warning")

        res_spot = run_cross_source_spot_check(self.db, price_pairs={"SPY": (500.0, 520.0)}, config={"dq_cross_source_tolerance_pct": 2.0})
        self.assertEqual(res_spot["status"], "warning")
        self.assertEqual(len(res_spot["discrepancies"]), 1)

    def test_position_reconciliation_mismatch_and_missing_stop(self):
        # DB has AAPL open 10 shares
        self.db.add(Trade(
            ticker="AAPL",
            shares=10,
            buy_price=150.0,
            stop_price=145.0,
            status="open",
            mode="paper",
        ))
        self.db.commit()

        # Case 1: IBKR has AAPL 10 shares, but NO stop order -> CRITICAL
        mock_ibkr = MagicMock()
        mock_ibkr.get_positions.return_value = [{"ticker": "AAPL", "shares": 10}]
        mock_ibkr.get_open_orders.return_value = []
        res_missing_stop = reconcile_positions_and_stops(self.db, mock_ibkr, is_market_open=True)
        self.assertEqual(res_missing_stop["status"], "critical")
        self.assertEqual(len(res_missing_stop["missing_stops"]), 1)
        self._assert_risk_engine_blocks()

        # Case 2: IBKR has AAPL 10 shares + valid STP order -> OK and resolves
        mock_ibkr.get_open_orders.return_value = [
            {"ticker": "AAPL", "action": "SELL", "order_type": "STP", "total_quantity": 10, "status": "PreSubmitted"}
        ]
        res_ok = reconcile_positions_and_stops(self.db, mock_ibkr, is_market_open=True)
        self.assertEqual(res_ok["status"], "ok")
        self._assert_risk_engine_allows()

        # Case 3: Position mismatch (IBKR has 5 shares instead of 10) -> CRITICAL
        mock_ibkr.get_positions.return_value = [{"ticker": "AAPL", "shares": 5}]
        res_mismatch = reconcile_positions_and_stops(self.db, mock_ibkr, is_market_open=True)
        self.assertEqual(res_mismatch["status"], "critical")
        self.assertEqual(len(res_mismatch["mismatches"]), 1)
        self._assert_risk_engine_blocks()

    def test_alert_deduplication_cooldown(self):
        a1 = emit_alert(self.db, "dq:test_dup", "warning", "data_quality", "Dup Test", "First")
        a2 = emit_alert(self.db, "dq:test_dup", "warning", "data_quality", "Dup Test", "Second")
        self.assertIsNotNone(a1)
        self.assertIsNone(a2)


if __name__ == "__main__":
    unittest.main()
