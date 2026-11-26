import os
import sys
import unittest
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models import Base, Trade, DeRiskState, DeRiskEvent, SystemAlert
from strategy.baselines import get_active_baseline
from strategy.derisk_engine import (
    get_derisk_state,
    get_derisk_modifiers,
    evaluate_derisk_ladder,
    manual_deescalate,
)
from strategy.risk_engine import RiskEngine


class TestFeature1DeRiskLadder(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        Session = sessionmaker(bind=self.engine)
        self.db = Session()
        self.risk_engine = RiskEngine()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _add_closed_trade(self, pnl: float, pnl_pct: float):
        self.db.add(Trade(
            ticker="AAPL",
            shares=10,
            buy_price=100.0,
            sell_price=100.0 + pnl_pct,
            pnl=pnl,
            pnl_pct=pnl_pct,
            status="closed",
            mode="paper",
            sell_time=datetime.now(timezone.utc),
        ))
        self.db.commit()

    def test_conservative_baseline_defaults(self):
        b = get_active_baseline()
        self.assertEqual(b["source"], "blueprint_conservative_defaults")
        self.assertEqual(b["max_drawdown_pct"], 8.0)
        self.assertEqual(b["hard_stop_drawdown_pct"], 15.0)
        self.assertEqual(b["daily_loss_pct"], 3.0)
        self.assertEqual(b["weekly_loss_pct"], 6.0)

    def test_modifiers_never_loosen_limits(self):
        bad_cfg = {"derisk_level1_size_multiplier": 2.5, "derisk_level1_score_bump": -10.0}
        mods = get_derisk_modifiers(1, config=bad_cfg)
        self.assertLessEqual(mods["size_multiplier"], 1.0)
        self.assertGreaterEqual(mods["score_bump"], 0.0)

    def test_level1_drawdown_and_position_sizing(self):
        # 5.5% drawdown >= 5.0% (0.625 * 8%) -> Level 1 Caution
        st = evaluate_derisk_ladder(self.db, account_equity=9450.0, peak_equity=10000.0)
        self.assertEqual(st["level"], 1)
        self.assertTrue(st["escalated"])
        self.assertEqual(st["size_multiplier"], 0.5)
        self.assertEqual(st["score_bump"], 5.0)

        # Verify RiskEngine enforces 0.5x size multiplier (stop distance $15 avoids 25% equity cap)
        s_normal = self.risk_engine.compute_position_size(10000.0, 100.0, 85.0, derisk_level=0, derisk_size_multiplier=1.0)
        s_l1 = self.risk_engine.compute_position_size(10000.0, 100.0, 85.0, derisk_level=1, derisk_size_multiplier=0.5)
        self.assertLess(s_l1["shares"], s_normal["shares"])

    def test_minimum_sample_prevents_small_sample_statistical_trigger(self):
        # 4 losing trades (< 5 streak and < 20 sample) with -2% return -> stays Level 0
        for _ in range(4):
            self._add_closed_trade(-20.0, -2.0)

        st = evaluate_derisk_ladder(self.db, account_equity=9900.0, peak_equity=10000.0)
        self.assertEqual(st["level"], 0)
        self.assertFalse(st["live_metrics"]["sample_ready"])

        # Now add enough alternating/losing trades to reach 20 closed trades with 25% win rate (< 40%)
        # Break streak to isolate statistical divergence trigger
        for i in range(16):
            if i % 4 == 0:
                self._add_closed_trade(10.0, 1.0)
            else:
                self._add_closed_trade(-20.0, -2.0)

        st2 = evaluate_derisk_ladder(self.db, account_equity=9900.0, peak_equity=10000.0)
        self.assertTrue(st2["live_metrics"]["sample_ready"])
        self.assertEqual(st2["level"], 1)
        self.assertIn("win rate", st2["reason"].lower())

    def test_level2_pause_blocks_risk_engine_and_never_auto_deescalates(self):
        # 8.5% drawdown -> Level 2 Pause
        st = evaluate_derisk_ladder(self.db, account_equity=9150.0, peak_equity=10000.0)
        self.assertEqual(st["level"], 2)
        self.assertFalse(st["entries_allowed"])

        # RiskEngine blocks new entry
        allowed, reason = self.risk_engine.check_new_entry(
            ticker="MSFT", sector="Technology", entry_price=200.0, stop_price=190.0,
            proposed_shares=5, account_equity=9150.0, open_positions=[], peak_equity=10000.0,
            daily_pnl_pct=0.0, weekly_pnl_pct=0.0, regime="risk_on", db=self.db,
        )
        self.assertFalse(allowed)
        self.assertIn("derisk_level_2", reason)

        # Even if equity recovers to peak (0% drawdown), de-escalation NEVER happens automatically
        st_rec = evaluate_derisk_ladder(self.db, account_equity=10000.0, peak_equity=10000.0)
        self.assertEqual(st_rec["level"], 2)
        self.assertFalse(st_rec["escalated"])

        # Manual de-escalation moves 2 -> 0 and logs audit event
        with self.assertRaises(ValueError):
            manual_deescalate(self.db, target_level=2, username="lucas")

        st_manual = manual_deescalate(self.db, target_level=0, username="lucas", reason="Reviewed and approved")
        self.assertEqual(st_manual["level"], 0)
        self.assertEqual(st_manual["deescalated_by"], "lucas")

        events = self.db.query(DeRiskEvent).all()
        self.assertEqual(len(events), 2)
        self.assertEqual(events[1].action_type, "manual_deescalate")
        self.assertEqual(events[1].actor, "lucas")

    def test_level3_flatten_and_halt(self):
        # 15.5% drawdown -> Level 3 Flatten & Halt
        st = evaluate_derisk_ladder(self.db, account_equity=8450.0, peak_equity=10000.0)
        self.assertEqual(st["level"], 3)
        self.assertTrue(st["should_flatten"])
        self.assertFalse(st["entries_allowed"])

        alert = self.db.query(SystemAlert).filter(SystemAlert.alert_key == "derisk:level_3").first()
        self.assertIsNotNone(alert)
        self.assertEqual(alert.severity, "critical")


if __name__ == "__main__":
    unittest.main()
