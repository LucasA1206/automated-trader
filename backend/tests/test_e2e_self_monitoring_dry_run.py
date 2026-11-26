import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models import Base, Trade, AccountSnapshot, ScanResult
from strategy.config import get_system_config
from strategy.data_quality import (
    check_metric_coverage,
    check_score_distribution,
    check_regime_inputs,
    check_price_sanity,
    check_api_health,
    run_cross_source_spot_check,
    reconcile_positions_and_stops,
)
from strategy.derisk_engine import evaluate_derisk_ladder
from strategy.shadow_tracker import record_shadow_decision, update_open_shadow_outcomes, compute_shadow_summary
from strategy.weekly_report import generate_weekly_report
from strategy.risk_engine import get_risk_engine


class TestEndToEndSelfMonitoringDryRun(unittest.TestCase):
    """
    Full-pipeline dry-run integration test exercising Features 1, 2, 3, and 4
    together without placing real orders.
    """

    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        Session = sessionmaker(bind=self.engine)
        self.db = Session()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_full_pipeline_dry_run(self):
        cfg = get_system_config(self.db)

        # 1. Regime & Data-Quality checks
        regime_data = {
            "regime": "risk_on",
            "is_valid": True,
            "spy_price": 510.0,
            "spy_sma_200": 480.0,
            "vix": 15.2,
            "spy_day_return_pct": 0.45,
        }
        dq_reg = check_regime_inputs(self.db, regime_data, config=cfg, is_market_open=True)
        self.assertEqual(dq_reg["status"], "ok")

        scored = [
            {"ticker": "AAPL", "composite_score": 78.0, "data_gaps": ["analyst_revisions", "insider_buying", "options_activity"], "effective_max_weight": 108.0},
            {"ticker": "MSFT", "composite_score": 72.0, "data_gaps": ["analyst_revisions", "insider_buying", "options_activity"], "effective_max_weight": 108.0},
        ]
        dq_cov = check_metric_coverage(self.db, scored, config=cfg)
        self.assertEqual(dq_cov["status"], "ok")
        dq_dist = check_score_distribution(self.db, scored, config=cfg)
        self.assertEqual(dq_dist["status"], "ok")
        dq_api = check_api_health(self.db, no_data_count=10, total_universe=500, config=cfg)
        self.assertEqual(dq_api["status"], "ok")
        dq_spot = run_cross_source_spot_check(self.db, price_pairs={"SPY": (510.0, 510.2)}, config=cfg)
        self.assertEqual(dq_spot["status"], "ok")

        # 2. Mock IBKR paper reconciliation (no real orders placed)
        mock_ibkr = MagicMock()
        mock_ibkr.get_positions.return_value = []
        mock_ibkr.get_open_orders.return_value = []
        dq_rec = reconcile_positions_and_stops(self.db, mock_ibkr, config=cfg, is_market_open=True)
        self.assertEqual(dq_rec["status"], "ok")

        # 3. De-Risk Ladder & RiskEngine dry-run check
        dr = evaluate_derisk_ladder(self.db, account_equity=10000.0, peak_equity=10000.0, config=cfg)
        self.assertEqual(dr["level"], 0)
        re = get_risk_engine()
        allowed, reason = re.check_new_entry(
            ticker="AAPL", sector="Technology", entry_price=150.0, stop_price=145.0,
            proposed_shares=10, account_equity=10000.0, open_positions=[], peak_equity=10000.0,
            daily_pnl_pct=0.0, weekly_pnl_pct=0.0, regime="risk_on", db=self.db,
        )
        self.assertTrue(allowed, reason)

        # 4. Shadow Tracking dry-run
        record_shadow_decision(self.db, "NVDA", "near_miss_score", "near_miss", True, "near_miss_score", entry_price=120.0, atr_abs=3.0, is_near_miss=True)
        update_open_shadow_outcomes(self.db, price_fetcher=lambda t: {"high": 122.0, "low": 119.0, "close": 121.0}, config=cfg)
        sh = compute_shadow_summary(self.db, cfg)
        self.assertEqual(sh["near_misses"]["total"], 1)

        # 5. Weekly Report generation
        rep = generate_weekly_report(self.db, spy_period_return_pct=0.8, config=cfg, deliver_alert=True)
        self.assertEqual(rep["period_returns"]["sample_size"], 0)
        self.assertIn("data_quality_summary", rep)
        self.assertIn("shadow_summary", rep)


if __name__ == "__main__":
    unittest.main()
