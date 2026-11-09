import unittest
import sys
import os
from unittest.mock import MagicMock
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Mock external network modules
sys.modules["yfinance"] = MagicMock()
sys.modules["finnhub"] = MagicMock()
sys.modules["ib_insync"] = MagicMock()

from strategy.market_state import (
    check_market_linked_exit_trigger,
    compute_earnings_season_density,
)


class TestPhase4ExitsEarnings(unittest.TestCase):

    def test_check_market_linked_exit_trigger_healthy(self):
        # 60 days of upward trending SPY
        dates = pd.date_range("2026-01-01", periods=60)
        closes = [500.0 + i * 0.5 for i in range(60)]
        df = pd.DataFrame({"Close": closes}, index=dates)

        res = check_market_linked_exit_trigger(df)
        self.assertFalse(res["trigger"])

    def test_check_market_linked_exit_trigger_below_50_sma(self):
        # SPY closes at 490 while 50 SMA is ~510
        dates = pd.date_range("2026-01-01", periods=60)
        closes = [510.0 for _ in range(59)] + [490.0]
        df = pd.DataFrame({"Close": closes}, index=dates)

        res = check_market_linked_exit_trigger(df)
        self.assertTrue(res["trigger"])
        self.assertTrue(any("50-day SMA" in r for r in res["reasons"]))

    def test_check_market_linked_exit_trigger_broken_10d_low(self):
        # SPY breaks 10d swing low: prior 10 days (idx 49..58) all 520.0, current close (idx 59) 510.0 < 520.0
        # 50 days (idx 0..48) at 500.0, 10 days (idx 49..58) at 520.0, final at 510.0 (total 60 days)
        dates = pd.date_range("2026-01-01", periods=60)
        closes = [500.0 for _ in range(49)] + [520.0 for _ in range(10)] + [510.0]
        df = pd.DataFrame({"Close": closes}, index=dates)

        res = check_market_linked_exit_trigger(df)
        self.assertTrue(res["trigger"])
        self.assertTrue(any("10-day swing low" in r for r in res["reasons"]))

    def test_earnings_density_normal(self):
        candidates = [
            {"ticker": "AAPL", "days_to_earnings": 45},
            {"ticker": "MSFT", "days_to_earnings": 30},
            {"ticker": "NVDA", "days_to_earnings": 50},
            {"ticker": "GOOGL", "days_to_earnings": 8},  # 1 out of 4 = 25% (<= 25% threshold)
        ]
        res = compute_earnings_season_density(candidates, threshold_pct=30.0, mode="enforce")
        self.assertFalse(res["caution_active"])
        self.assertEqual(res["effective_size_multiplier"], 1.0)

    def test_earnings_density_caution_shadow_and_enforce(self):
        candidates = [
            {"ticker": "AAPL", "days_to_earnings": 5},
            {"ticker": "MSFT", "days_to_earnings": 6},
            {"ticker": "NVDA", "days_to_earnings": 50},
            {"ticker": "GOOGL", "days_to_earnings": 8},  # 3 out of 4 = 75% (> 25%)
        ]
        res_shadow = compute_earnings_season_density(candidates, threshold_pct=25.0, mode="shadow")
        self.assertTrue(res_shadow["caution_active"])
        self.assertEqual(res_shadow["effective_size_multiplier"], 1.0)  # shadow keeps 1.0
        self.assertEqual(res_shadow["hypothetical_size_multiplier"], 0.75)

        res_enforce = compute_earnings_season_density(candidates, threshold_pct=25.0, mode="enforce")
        self.assertTrue(res_enforce["caution_active"])
        self.assertEqual(res_enforce["effective_size_multiplier"], 0.75)  # enforce applies 0.75


if __name__ == "__main__":
    unittest.main()
