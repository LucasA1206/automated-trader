"""
Unit tests for regime check fail-safe behavior.
Validates that NaN, missing, or corrupt market inputs treat the regime
as 'unavailable' and strictly block all new entries.
"""
import sys
import os
import math
import unittest
from unittest.mock import MagicMock

# Mock external network modules if not installed in local environment
if "yfinance" not in sys.modules:
    sys.modules["yfinance"] = MagicMock()
if "finnhub" not in sys.modules:
    sys.modules["finnhub"] = MagicMock()

# Add backend directory to sys.path
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from strategy.data_layer import compute_regime_status, _is_valid_spy_dict, _is_valid_vix_dict
from strategy.risk_engine import get_risk_engine


class TestRegimeFailSafe(unittest.TestCase):
    """Test suite for regime input validation and fail-safe blocking."""

    def setUp(self):
        self.valid_spy = {
            "price": 580.0,
            "sma_50": 570.0,
            "sma_200": 530.0,
            "above_sma_200": True,
            "above_sma_50": True,
            "day_return_pct": 0.5,
            "source": "test_mock",
        }
        self.valid_vix = {
            "current": 16.5,
            "prev_1d": 16.8,
            "prev_3d": 17.0,
            "spike_3d_pct": -2.94,
            "source": "test_mock",
        }
        self.risk_engine = get_risk_engine()

    def test_healthy_market_classifies_risk_on(self):
        """Valid bullish SPY and low VIX should produce risk_on."""
        res = compute_regime_status(spy=self.valid_spy, vix=self.valid_vix)
        self.assertTrue(res["is_valid"])
        self.assertEqual(res["regime"], "risk_on")
        self.assertFalse(res["black_swan_day"])

    def test_caution_market_classifies_caution(self):
        """Elevated VIX (25-30) produces caution."""
        vix = dict(self.valid_vix, current=26.5)
        res = compute_regime_status(spy=self.valid_spy, vix=vix)
        self.assertTrue(res["is_valid"])
        self.assertEqual(res["regime"], "caution")

    def test_risk_off_when_spy_below_200_sma(self):
        """SPY below 200 SMA produces risk_off."""
        spy = dict(self.valid_spy, above_sma_200=False, price=520.0)
        res = compute_regime_status(spy=spy, vix=self.valid_vix)
        self.assertTrue(res["is_valid"])
        self.assertEqual(res["regime"], "risk_off")

    def test_risk_off_when_vix_spikes(self):
        """VIX spike > 20% produces risk_off."""
        vix = dict(self.valid_vix, spike_3d_pct=25.0)
        res = compute_regime_status(spy=self.valid_spy, vix=vix)
        self.assertTrue(res["is_valid"])
        self.assertEqual(res["regime"], "risk_off")

    def test_risk_off_on_black_swan_day(self):
        """SPY single day move > 3% triggers black swan and risk_off."""
        spy = dict(self.valid_spy, day_return_pct=-3.5)
        res = compute_regime_status(spy=spy, vix=self.valid_vix)
        self.assertTrue(res["is_valid"])
        self.assertEqual(res["regime"], "risk_off")
        self.assertTrue(res["black_swan_day"])

    # ── NaN Handling Tests ────────────────────────────────────────────────────

    def test_nan_spy_day_return_fails_safe(self):
        """Known bug reproduction: SPY day_return_pct is NaN."""
        spy = dict(self.valid_spy, day_return_pct=float("nan"))
        self.assertFalse(_is_valid_spy_dict(spy))
        res = compute_regime_status(spy=spy, vix=self.valid_vix)
        self.assertFalse(res["is_valid"])
        self.assertEqual(res["regime"], "unavailable")
        self.assertIn("unavailable", res["details"])

    def test_nan_spy_price_fails_safe(self):
        """NaN SPY price must fail safe."""
        spy = dict(self.valid_spy, price=float("nan"))
        self.assertFalse(_is_valid_spy_dict(spy))
        res = compute_regime_status(spy=spy, vix=self.valid_vix)
        self.assertFalse(res["is_valid"])
        self.assertEqual(res["regime"], "unavailable")

    def test_nan_spy_sma_200_fails_safe(self):
        """NaN 200 SMA must fail safe."""
        spy = dict(self.valid_spy, sma_200=float("nan"))
        self.assertFalse(_is_valid_spy_dict(spy))
        res = compute_regime_status(spy=spy, vix=self.valid_vix)
        self.assertFalse(res["is_valid"])
        self.assertEqual(res["regime"], "unavailable")

    def test_nan_vix_current_fails_safe(self):
        """NaN VIX current level must fail safe and NOT default to risk_on."""
        vix = dict(self.valid_vix, current=float("nan"))
        self.assertFalse(_is_valid_vix_dict(vix))
        res = compute_regime_status(spy=self.valid_spy, vix=vix)
        self.assertFalse(res["is_valid"])
        self.assertEqual(res["regime"], "unavailable")

    def test_nan_vix_spike_fails_safe(self):
        """NaN VIX 3d spike must fail safe."""
        vix = dict(self.valid_vix, spike_3d_pct=float("nan"))
        self.assertFalse(_is_valid_vix_dict(vix))
        res = compute_regime_status(spy=self.valid_spy, vix=vix)
        self.assertFalse(res["is_valid"])
        self.assertEqual(res["regime"], "unavailable")

    # ── Missing / Incomplete Data Tests ───────────────────────────────────────

    def test_missing_spy_data_fails_safe(self):
        """Empty or None SPY dict must return unavailable."""
        res = compute_regime_status(spy={}, vix=self.valid_vix)
        self.assertFalse(res["is_valid"])
        self.assertEqual(res["regime"], "unavailable")

    def test_missing_vix_data_fails_safe(self):
        """Empty or None VIX dict must return unavailable."""
        res = compute_regime_status(spy=self.valid_spy, vix={})
        self.assertFalse(res["is_valid"])
        self.assertEqual(res["regime"], "unavailable")

    def test_missing_keys_in_spy_fails_safe(self):
        """SPY dict missing required keys must fail safe."""
        partial_spy = {"price": 550.0}  # missing day_return_pct, above_sma_200, sma_50
        self.assertFalse(_is_valid_spy_dict(partial_spy))
        res = compute_regime_status(spy=partial_spy, vix=self.valid_vix)
        self.assertFalse(res["is_valid"])
        self.assertEqual(res["regime"], "unavailable")

    # ── Downstream Circuit Breaker Blocking Tests ─────────────────────────────

    def test_risk_engine_blocks_on_unavailable_regime(self):
        """Risk engine check_new_entry must block when regime is 'unavailable'."""
        allowed, reason = self.risk_engine.check_new_entry(
            ticker="AAPL",
            sector="Technology",
            entry_price=150.0,
            stop_price=140.0,
            proposed_shares=10,
            account_equity=100000.0,
            open_positions=[],
            peak_equity=100000.0,
            daily_pnl_pct=0.0,
            weekly_pnl_pct=0.0,
            regime="unavailable",
            black_swan_day=False,
        )
        self.assertFalse(allowed)
        self.assertIn("regime_off", reason)
        self.assertIn("unavailable", reason)

    def test_risk_engine_blocks_on_unknown_regime(self):
        """Risk engine check_new_entry must block when regime is 'unknown'."""
        allowed, reason = self.risk_engine.check_new_entry(
            ticker="AAPL",
            sector="Technology",
            entry_price=150.0,
            stop_price=140.0,
            proposed_shares=10,
            account_equity=100000.0,
            open_positions=[],
            peak_equity=100000.0,
            daily_pnl_pct=0.0,
            weekly_pnl_pct=0.0,
            regime="unknown",
            black_swan_day=False,
        )
        self.assertFalse(allowed)
        self.assertIn("regime_off", reason)

    def test_risk_engine_summary_disallows_new_entries_on_unavailable_regime(self):
        """Risk engine get_state_summary must report new_entries_allowed=False."""
        summary = self.risk_engine.get_state_summary(
            account_equity=100000.0,
            peak_equity=100000.0,
            open_positions=[],
            daily_pnl_pct=0.0,
            weekly_pnl_pct=0.0,
            regime="unavailable",
        )
        self.assertFalse(summary["new_entries_allowed"])
        self.assertEqual(summary["regime"], "unavailable")


if __name__ == "__main__":
    unittest.main()
