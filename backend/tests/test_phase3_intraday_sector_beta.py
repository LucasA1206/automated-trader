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
    rank_sectors_by_leadership,
    check_sector_leadership,
    compute_empirical_beta,
    calculate_beta_scalar,
    check_spy_intraday_confirmation,
    check_market_linked_exit_trigger,
    compute_earnings_season_density,
)
from strategy.risk_engine import RiskEngine


class TestPhase3IntradaySectorBeta(unittest.TestCase):

    def test_rank_sectors_by_leadership(self):
        ret_3m = {
            "Technology": 15.0,
            "Healthcare": 8.0,
            "Financials": 12.0,
            "Consumer Cyclical": 10.0,
            "Consumer Defensive": 2.0,
            "Energy": 14.0,
            "Industrials": 9.0,
            "Basic Materials": 5.0,
            "Real Estate": -3.0,
            "Utilities": -5.0,
            "Communication Services": 11.0,
        }
        ret_1m = {
            "Technology": 5.0,
            "Healthcare": 3.0,
            "Financials": 4.0,
            "Consumer Cyclical": 3.5,
            "Consumer Defensive": 0.5,
            "Energy": 6.0,
            "Industrials": 2.5,
            "Basic Materials": 1.0,
            "Real Estate": -1.0,
            "Utilities": -2.0,
            "Communication Services": 4.5,
        }
        res = rank_sectors_by_leadership(ret_3m, ret_1m, spy_3m_return=5.0, spy_1m_return=2.0)
        self.assertEqual(len(res["leaders"]), 6)
        self.assertEqual(len(res["laggards"]), 5)
        # Technology and Energy should definitely be among leaders
        self.assertIn("Technology", res["leaders"])
        self.assertIn("Energy", res["leaders"])
        # Utilities and Real Estate should be laggards
        self.assertIn("Utilities", res["laggards"])
        self.assertIn("Real Estate", res["laggards"])

    def test_check_sector_leadership_shadow_vs_enforce(self):
        leadership = {
            "rankings": {
                "Technology": {"rank": 1, "rs_score": 10.0, "is_leader": True},
                "Utilities": {"rank": 11, "rs_score": -10.0, "is_leader": False},
            }
        }
        # Leader passes in both modes
        res_lead = check_sector_leadership("Technology", leadership, mode="enforce")
        self.assertTrue(res_lead["allowed"])
        self.assertFalse(res_lead["would_block"])

        # Laggard in shadow mode: allowed=True, would_block=True
        res_lag_shadow = check_sector_leadership("Utilities", leadership, mode="shadow")
        self.assertTrue(res_lag_shadow["allowed"])
        self.assertTrue(res_lag_shadow["would_block"])

        # Laggard in enforce mode: allowed=False, would_block=True
        res_lag_enforce = check_sector_leadership("Utilities", leadership, mode="enforce")
        self.assertFalse(res_lag_enforce["allowed"])
        self.assertTrue(res_lag_enforce["would_block"])

    def test_compute_empirical_beta(self):
        np.random.seed(42)
        n = 260
        spy_rets = np.random.normal(0.0005, 0.01, n)
        # High beta stock (beta ~ 1.5)
        stock_rets = 1.5 * spy_rets + np.random.normal(0, 0.005, n)

        spy_closes = pd.Series(100.0 * np.cumprod(1 + spy_rets))
        stock_closes = pd.Series(50.0 * np.cumprod(1 + stock_rets))

        beta = compute_empirical_beta(stock_closes, spy_closes)
        self.assertIsNotNone(beta)
        self.assertAlmostEqual(beta, 1.5, delta=0.25)

    def test_calculate_beta_scalar(self):
        # Beta <= 1.0 -> no reduction (1.0x)
        s1 = calculate_beta_scalar(0.8, mode="enforce")
        self.assertEqual(s1["effective_scalar"], 1.0)

        # Beta = 1.5 -> 1 / 1.5 = 0.667
        s2 = calculate_beta_scalar(1.5, mode="enforce")
        self.assertAlmostEqual(s2["effective_scalar"], 0.667, delta=0.01)

        # Beta = 2.5 -> clamped to 0.50
        s3 = calculate_beta_scalar(2.5, mode="enforce")
        self.assertEqual(s3["effective_scalar"], 0.5)

        # Shadow mode retains effective 1.0 but computes hypothetical scalar
        s4 = calculate_beta_scalar(1.5, mode="shadow")
        self.assertEqual(s4["effective_scalar"], 1.0)
        self.assertAlmostEqual(s4["hypothetical_scalar"], 0.667, delta=0.01)

    def test_risk_engine_beta_scalar_integration(self):
        engine = RiskEngine()
        # Normal 1.0 beta (use 1.0% risk so position is 20,000, under 25% cap)
        base_size = engine.compute_position_size(
            account_equity=100_000,
            entry_price=100.0,
            stop_price=95.0,
            risk_pct=1.0,
            size_multiplier=1.0,
            beta_scalar=1.0,
        )
        # Scaled down beta (0.50x)
        half_size = engine.compute_position_size(
            account_equity=100_000,
            entry_price=100.0,
            stop_price=95.0,
            risk_pct=1.0,
            size_multiplier=1.0,
            beta_scalar=0.5,
        )
        self.assertEqual(half_size["shares"], base_size["shares"] // 2)

    def test_check_spy_intraday_confirmation(self):
        # Before 10:00 ET -> blocks
        mock_data = {"current_price": 505.0, "prior_close": 500.0, "vwap": 502.0}
        res_early = check_spy_intraday_confirmation(
            mode="enforce", test_now_et=(9, 45), mock_spy_data=mock_data
        )
        self.assertFalse(res_early["confirmed"])

        # After 10:00 ET, SPY > prior close and SPY > VWAP -> confirms
        res_ok = check_spy_intraday_confirmation(
            mode="enforce", test_now_et=(10, 15), mock_spy_data=mock_data
        )
        self.assertTrue(res_ok["confirmed"])

        # SPY below VWAP -> blocks in enforce, shadow allows
        mock_weak = {"current_price": 501.0, "prior_close": 500.0, "vwap": 503.0}
        res_weak_enforce = check_spy_intraday_confirmation(
            mode="enforce", test_now_et=(10, 15), mock_spy_data=mock_weak
        )
        self.assertFalse(res_weak_enforce["confirmed"])
        self.assertFalse(res_weak_enforce["would_confirm"])

        res_weak_shadow = check_spy_intraday_confirmation(
            mode="shadow", test_now_et=(10, 15), mock_spy_data=mock_weak
        )
        self.assertTrue(res_weak_shadow["confirmed"])  # allowed in shadow
        self.assertFalse(res_weak_shadow["would_confirm"])

        # Fail-safe: missing data defaults to NO ENTRY
        res_missing = check_spy_intraday_confirmation(
            mode="enforce", test_now_et=(10, 15), mock_spy_data=None
        )
        self.assertFalse(res_missing["confirmed"])


if __name__ == "__main__":
    unittest.main()
