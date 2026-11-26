import os
import sys
import unittest
from datetime import datetime, timezone, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models import Base, Trade, ShadowEvaluation
from strategy.shadow_tracker import (
    record_shadow_decision,
    update_open_shadow_outcomes,
    classify_evidence_strength,
    compute_shadow_summary,
)


class TestFeature4ShadowTracking(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        Session = sessionmaker(bind=self.engine)
        self.db = Session()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_shadow_decision_and_forward_outcomes(self):
        # 1. Record a shadow decision (entry=$100, atr=$2.5 -> stop~$96.25, 1.5R target~$105.625)
        row = record_shadow_decision(
            self.db,
            ticker="NVDA",
            gate_name="gap_veto",
            mode="shadow",
            would_have_blocked=True,
            hypothetical_action="block",
            entry_price=100.0,
            atr_abs=2.5,
            market_state={"regime": "risk_on", "vix": 16.0},
            details="Test gap veto",
        )
        self.assertIsNotNone(row)
        self.assertEqual(row.outcome_status, "open")
        self.assertLess(row.stop_price, 100.0)
        self.assertGreater(row.partial_target_price, 100.0)

        # Ensure zero live/paper Trade rows were created or modified
        self.assertEqual(self.db.query(Trade).count(), 0)

        # 2. Price hits 1.5R partial target -> stays open, partial_taken=True, stop raised to breakeven
        partial_px = row.partial_target_price
        res1 = update_open_shadow_outcomes(
            self.db,
            price_fetcher=lambda t: {"high": partial_px + 1.0, "low": 99.0, "close": partial_px + 0.5},
        )
        self.assertEqual(res1["resolved"], 0)
        self.assertEqual(res1["still_open"], 1)
        self.db.refresh(row)
        self.assertTrue(row.partial_taken)
        self.assertGreater(row.trailing_stop_price, 100.0)

        # 3. Trailing stop hit -> resolves with positive blended return
        trail_stop = row.trailing_stop_price
        res2 = update_open_shadow_outcomes(
            self.db,
            price_fetcher=lambda t: {"high": trail_stop + 1.0, "low": trail_stop - 0.5, "close": trail_stop},
        )
        self.assertEqual(res2["resolved"], 1)
        self.assertEqual(res2["still_open"], 0)
        self.db.refresh(row)
        self.assertEqual(row.outcome_status, "resolved")
        self.assertEqual(row.exit_reason, "trailing_stop_after_partial")
        self.assertGreater(row.hypothetical_pnl_pct, 0.0)

    def test_near_miss_time_exit(self):
        nm = record_shadow_decision(
            self.db,
            ticker="AMD",
            gate_name="near_miss_score",
            mode="near_miss",
            would_have_blocked=True,
            hypothetical_action="near_miss_score",
            entry_price=100.0,
            atr_abs=2.0,
            is_near_miss=True,
        )
        self.assertTrue(nm.is_near_miss)
        future = datetime.now(timezone.utc) + timedelta(days=25)
        res = update_open_shadow_outcomes(
            self.db,
            price_fetcher=lambda t: {"high": 101.0, "low": 99.0, "close": 100.5},
            now_override=future,
        )
        self.assertEqual(res["resolved"], 1)
        self.db.refresh(nm)
        self.assertEqual(nm.exit_reason, "time_exit")
        self.assertEqual(nm.hypothetical_pnl_pct, 0.5)

    def test_evidence_strength_rubric(self):
        ev_insuff = classify_evidence_strength(10, -2.0, 3.0, 30.0, 60.0, min_sample=20)
        self.assertEqual(ev_insuff["label"], "insufficient")
        self.assertFalse(ev_insuff["recommend_promotion"])

        ev_weak = classify_evidence_strength(25, 2.0, 2.2, 50.0, 51.0, min_sample=20)
        self.assertEqual(ev_weak["label"], "weak")
        self.assertFalse(ev_weak["recommend_promotion"])

        ev_mod = classify_evidence_strength(25, 0.0, 1.5, 45.0, 55.0, min_sample=20)
        self.assertEqual(ev_mod["label"], "moderate")
        self.assertFalse(ev_mod["recommend_promotion"])

        ev_strong = classify_evidence_strength(45, -1.0, 2.5, 35.0, 55.0, min_sample=20, strong_sample=40)
        self.assertEqual(ev_strong["label"], "strong")
        self.assertFalse(ev_strong["recommend_promotion"])

    def test_compute_shadow_summary(self):
        # Add 1 resolved blocked gate decision and 1 near-miss
        r = record_shadow_decision(
            self.db, "MSFT", "sector_gate", "shadow", True, "block", entry_price=200.0, atr_abs=4.0
        )
        r.outcome_status = "resolved"
        r.hypothetical_pnl_pct = -3.0
        record_shadow_decision(
            self.db, "AAPL", "near_miss_score", "near_miss", True, "near_miss_score", entry_price=150.0, is_near_miss=True
        )
        self.db.commit()

        summary = compute_shadow_summary(self.db)
        self.assertIn("sector_gate", summary["rules"])
        self.assertEqual(summary["rules"]["sector_gate"]["evidence"]["label"], "insufficient")
        self.assertEqual(summary["near_misses"]["total"], 1)


if __name__ == "__main__":
    unittest.main()
