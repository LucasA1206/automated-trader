import os
import sys
import unittest
from datetime import datetime, timezone, timedelta, date
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models import Base, Trade, AccountSnapshot, ScanResult, WeeklyReport, SystemAlert
from strategy.weekly_report import generate_weekly_report


class TestFeature2WeeklyReport(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        Session = sessionmaker(bind=self.engine)
        self.db = Session()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_zero_trades_and_offline_spy_source(self):
        with patch("strategy.weekly_report._fetch_spy_period_return", return_value=(0.0, "unavailable")):
            rep = generate_weekly_report(self.db, period_end=date(2026, 11, 26))

        self.assertEqual(rep["period_returns"]["sample_size"], 0)
        self.assertEqual(rep["period_returns"]["spy_source"], "unavailable")
        self.assertTrue(any("0 closed trades" in line for line in rep["what_to_look_at"]))
        self.assertEqual(self.db.query(WeeklyReport).count(), 1)
        self.assertEqual(self.db.query(SystemAlert).filter(SystemAlert.category == "report").count(), 1)

    def test_handful_of_trades_and_insufficient_data_labels(self):
        now = datetime.now(timezone.utc)
        for i in range(3):
            self.db.add(Trade(
                ticker=f"T{i}",
                sector="Technology",
                shares=10,
                buy_price=100.0,
                stop_price=95.0,
                sell_price=110.0,
                pnl=100.0,
                pnl_pct=10.0,
                alpha_pct=8.0,
                beta_at_entry=1.0,
                market_tier_at_entry="A",
                entry_composite_score=78.0,
                ai_reason="Strong momentum breakout",
                intraday_confirmed_at_entry=True,
                buy_time=now - timedelta(days=3),
                sell_time=now - timedelta(days=1),
                status="closed",
                mode="paper",
            ))
        self.db.add(ScanResult(
            scan_date=now.date(),
            regime_status="risk_on",
            candidates_count=5,
            action_taken="trade",
        ))
        self.db.commit()

        rep = generate_weekly_report(
            self.db,
            period_end=now.date(),
            spy_period_return_pct=1.5,
            config={"weekly_report_min_bucket_trades": 10},
        )
        self.assertEqual(rep["period_returns"]["sample_size"], 3)
        self.assertEqual(rep["trades"][0]["r_multiple"], 2.0)
        tier_a = rep["breakdowns"]["by_market_tier"]["A"]
        self.assertEqual(tier_a["sample_size"], 3)
        self.assertEqual(tier_a["status"], "insufficient data")
        self.assertEqual(rep["baseline_comparison"]["win_rate_status"], "insufficient data")

    def test_sufficient_bucket_status(self):
        now = datetime.now(timezone.utc)
        for i in range(12):
            self.db.add(Trade(
                ticker=f"S{i}",
                sector="Healthcare",
                shares=10,
                buy_price=100.0,
                stop_price=95.0,
                sell_price=105.0,
                pnl=50.0,
                pnl_pct=5.0,
                market_tier_at_entry="A",
                buy_time=now - timedelta(days=2),
                sell_time=now,
                status="closed",
                mode="paper",
            ))
        self.db.commit()

        rep = generate_weekly_report(
            self.db,
            period_end=now.date(),
            spy_period_return_pct=1.0,
            config={"weekly_report_min_bucket_trades": 10},
        )
        tier_a = rep["breakdowns"]["by_market_tier"]["A"]
        self.assertEqual(tier_a["sample_size"], 12)
        self.assertEqual(tier_a["status"], "sufficient")


if __name__ == "__main__":
    unittest.main()
