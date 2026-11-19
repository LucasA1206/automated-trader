"""
Tests for Phase 6: Dual-Engine Mean Reversion, Progressive Breakeven Stops & Data Fallback
"""

import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone
import pandas as pd
import numpy as np

from strategy.mean_reversion_engine import (
    compute_rsi2,
    scan_mean_reversion_candidates,
    check_mean_reversion_exit,
    MEAN_REVERSION_UNIVERSE
)
from strategy.exit_engine import (
    check_exit_conditions,
    PROGRESSIVE_BREAKEVEN_R,
    COMMISSION_CUSHION_PCT
)
import strategy.data_layer as data_layer


class DummyTrade:
    def __init__(self, **kwargs):
        self.ticker = kwargs.get("ticker", "AAPL")
        self.buy_price = kwargs.get("buy_price", 100.0)
        self.stop_price = kwargs.get("stop_price", 96.0)
        self.status = kwargs.get("status", "open")
        self.buy_time = kwargs.get("buy_time", datetime.now(timezone.utc))
        self.atr_at_entry = kwargs.get("atr_at_entry", 2.0)
        self.partial_sold = kwargs.get("partial_sold", False)
        self.partial_target_price = kwargs.get("partial_target_price", 106.0)
        self.trailing_stop_price = kwargs.get("trailing_stop_price", None)
        self.breakeven_moved = kwargs.get("breakeven_moved", False)
        self.strategy_engine = kwargs.get("strategy_engine", "momentum")


class TestDualEngineAndBreakeven(unittest.TestCase):

    def test_compute_rsi2(self):
        """Test RSI-2 calculation on price series with at least 10 rows."""
        prices = pd.Series([100.0, 99.0, 98.0, 97.0, 95.0, 93.0, 91.0, 89.0, 87.0, 85.0, 83.0])
        rsi = compute_rsi2(prices)
        self.assertIsInstance(rsi, float)
        self.assertLess(rsi, 10.0)  # Monotonic drops should yield RSI-2 close to 0

    @patch("strategy.mean_reversion_engine.fetch_ohlcv")
    def test_scan_mean_reversion_candidates(self, mock_fetch):
        """Test candidate qualification when Close > 200 SMA and RSI2 < 10."""
        dates = pd.date_range("2025-01-01", periods=210)
        # First 200 days flat at 100.0 (200 SMA ≈ 100.5)
        # Last 10 days drop from 130 down to 105 (current close 105 > 200 SMA 100.5, but acute RSI2 < 10)
        close_vals = [100.0] * 200 + [130.0, 128.0, 125.0, 122.0, 118.0, 114.0, 111.0, 108.0, 106.0, 105.0]
        df = pd.DataFrame({
            "Open": close_vals,
            "High": [c * 1.01 for c in close_vals],
            "Low": [c * 0.99 for c in close_vals],
            "Close": close_vals,
            "Volume": [1000000] * 210
        }, index=dates)

        mock_fetch.return_value = df

        candidates = scan_mean_reversion_candidates(open_positions=[], max_candidates=2)
        # Should find SPY or QQQ from MEAN_REVERSION_UNIVERSE
        self.assertGreaterEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["strategy_engine"], "mean_reversion")
        self.assertLess(candidates[0]["rsi2"], 10.0)
        self.assertGreater(candidates[0]["price"], candidates[0]["sma_200"])

    def test_mean_reversion_exit_profit_target(self):
        """Exit when gain >= 2.5%."""
        trade = DummyTrade(
            ticker="SPY",
            buy_price=100.0,
            stop_price=96.5,
            strategy_engine="mean_reversion"
        )
        # Current price = 103.0 (+3.0% gain, exceeds 2.5% target)
        exit_signal = check_mean_reversion_exit(
            trade=trade,
            current_price=103.0,
            live_shares=50
        )
        self.assertEqual(exit_signal.action, "full_exit")
        self.assertEqual(exit_signal.reason, "mr_profit_target")
        self.assertEqual(exit_signal.shares_to_sell, 50)

    @patch("strategy.mean_reversion_engine.fetch_ohlcv")
    def test_mean_reversion_exit_sma5_cross(self, mock_fetch):
        """Exit when price crosses above 5-day SMA and held >= 1 day."""
        trade = DummyTrade(
            ticker="QQQ",
            buy_price=100.0,
            stop_price=96.5,
            buy_time=datetime(2025, 1, 1, tzinfo=timezone.utc),  # Held multiple days
            strategy_engine="mean_reversion"
        )
        # 5 days of closes averaging 99.0. Current price = 100.5 (> 99.0)
        df = pd.DataFrame({
            "Close": [98.0, 98.5, 99.0, 99.5, 100.0]
        })
        mock_fetch.return_value = df

        exit_signal = check_mean_reversion_exit(
            trade=trade,
            current_price=100.5,
            live_shares=20
        )
        self.assertEqual(exit_signal.action, "full_exit")
        self.assertEqual(exit_signal.reason, "mr_sma5_rebound")

    def test_progressive_breakeven_trigger(self):
        """Stop is raised to breakeven + 0.2% when price hits +0.75R."""
        trade = DummyTrade(
            ticker="AAPL",
            buy_price=100.0,
            stop_price=96.0,  # 1R = $4.00, 0.75R = $3.00 -> trigger at $103.00
            status="open",
            breakeven_moved=False
        )
        # At $102.50 (< 103.00), no breakeven move
        signal = check_exit_conditions(trade, current_price=102.50, live_shares=100, account_equity=10000.0)
        self.assertEqual(signal.action, "hold")
        self.assertNotEqual(signal.reason, "breakeven_update")

        # At $103.10 (>= 103.00), breakeven_update signal triggered
        signal = check_exit_conditions(trade, current_price=103.10, live_shares=100, account_equity=10000.0)
        self.assertEqual(signal.action, "hold")
        self.assertEqual(signal.reason, "breakeven_update")
        expected_new_stop = round(100.0 * (1.0 + COMMISSION_CUSHION_PCT), 2)
        self.assertAlmostEqual(signal.new_stop_price, expected_new_stop, places=2)

    @patch("strategy.data_layer._fetch_ohlcv_ibkr")
    def test_ibkr_fallback_when_yfinance_blocked(self, mock_ibkr):
        """When yfinance is blocked or fails, data_layer falls back to IBKR."""
        data_layer._yfinance_blocked = True
        mock_ibkr.return_value = pd.DataFrame({
            "Open": [150.0] * 30,
            "High": [155.0] * 30,
            "Low": [149.0] * 30,
            "Close": [154.0] * 30,
            "Volume": [500000] * 30
        })

        try:
            df = data_layer.fetch_ohlcv("NVDA", period="3mo")
            self.assertIsNotNone(df)
            self.assertFalse(df.empty)
            self.assertEqual(df["Close"].iloc[0], 154.0)
            mock_ibkr.assert_called_once_with("NVDA", period="3mo")
        finally:
            data_layer._yfinance_blocked = False


if __name__ == "__main__":
    unittest.main()
