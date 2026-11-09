"""
Unit tests for Phase 2:
  - Centralized 3-mode configuration flags ('off', 'shadow', 'enforce')
  - Universe market breadth calculation (missing tickers excluded from denominator)
  - SPY gap-down veto (shadow vs enforce)
  - Graded exposure tiers (Tier A, Tier B, Tier C)
  - Tier-aware position sizing in RiskEngine
"""

import sys
import os
import math
import unittest
from unittest.mock import MagicMock
import pandas as pd

# Mock external network modules if not installed in local environment
if "yfinance" not in sys.modules:
    sys.modules["yfinance"] = MagicMock()
if "finnhub" not in sys.modules:
    sys.modules["finnhub"] = MagicMock()

# Add backend directory to sys.path
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from strategy.config import get_system_config, DEFAULT_CONFIG
from strategy.market_state import (
    compute_market_breadth,
    check_gap_down_veto,
    classify_market_tier,
    set_latest_breadth,
    get_latest_breadth,
)
from strategy.risk_engine import get_risk_engine


def _create_mock_df(n_bars: int, start_price: float, trend: float = 0.0) -> pd.DataFrame:
    """Helper to generate a mock OHLCV dataframe for breadth tests."""
    prices = [start_price + i * trend for i in range(n_bars)]
    return pd.DataFrame({
        "Open": prices,
        "High": [p * 1.01 for p in prices],
        "Low": [p * 0.99 for p in prices],
        "Close": prices,
        "Volume": [1_000_000] * n_bars,
    })


class TestPhase2MarketState(unittest.TestCase):
    """Test suite for Phase 2 config, breadth, gap veto, and tiers."""

    def setUp(self):
        self.risk_engine = get_risk_engine()
        self.healthy_regime = {
            "regime": "risk_on",
            "is_valid": True,
            "spy_price": 580.0,
            "spy_open": 581.0,
            "spy_prior_close": 579.0,
            "spy_sma_50": 560.0,
            "spy_sma_200": 520.0,
            "spy_above_200": True,
            "spy_above_50": True,
            "spy_day_return_pct": 0.35,
            "vix": 16.5,
            "vix_spike_3d_pct": -2.0,
            "black_swan_day": False,
        }

    # ── 1. Config System Tests ────────────────────────────────────────────────

    def test_default_config_flags_default_to_shadow(self):
        """All new market gates must default to 'shadow'."""
        cfg = get_system_config()
        self.assertEqual(cfg["gate_intraday_confirmation"], "shadow")
        self.assertEqual(cfg["gate_gap_down_veto"], "shadow")
        self.assertEqual(cfg["gate_exposure_tiers"], "shadow")
        self.assertEqual(cfg["gate_market_breadth"], "shadow")
        self.assertEqual(cfg["gate_sector_leadership"], "shadow")
        self.assertEqual(cfg["sizing_beta_aware"], "shadow")
        self.assertEqual(cfg["exit_market_linked"], "shadow")
        self.assertEqual(cfg["gate_earnings_density"], "shadow")

    def test_config_overrides(self):
        """Overrides must be respected cleanly."""
        cfg = get_system_config(overrides={"gate_gap_down_veto": "enforce", "gap_down_threshold_pct": 1.2})
        self.assertEqual(cfg["gate_gap_down_veto"], "enforce")
        self.assertEqual(cfg["gap_down_threshold_pct"], 1.2)

    # ── 2. Market Breadth Tests ───────────────────────────────────────────────

    def test_market_breadth_healthy(self):
        """Verify breadth calculation when >= 40% are above 50 SMA."""
        batch = {
            # 3 stocks above 50 SMA (uptrending)
            "STOCK_UP1": _create_mock_df(60, start_price=10.0, trend=0.5),
            "STOCK_UP2": _create_mock_df(60, start_price=20.0, trend=0.5),
            "STOCK_UP3": _create_mock_df(60, start_price=30.0, trend=0.5),
            # 1 stock below 50 SMA (downtrending)
            "STOCK_DN1": _create_mock_df(60, start_price=50.0, trend=-0.5),
        }
        res = compute_market_breadth(batch, threshold_pct=40.0)
        self.assertEqual(res["total_universe"], 4)
        self.assertEqual(res["valid_count"], 4)
        self.assertEqual(res["missing_count"], 0)
        self.assertEqual(res["above_50d_count"], 3)
        self.assertEqual(res["below_50d_count"], 1)
        self.assertEqual(res["breadth_pct"], 75.0)
        self.assertTrue(res["is_healthy"])

    def test_market_breadth_excludes_missing_data_tickers(self):
        """Missing or insufficient data tickers must be excluded from the denominator."""
        batch = {
            # 1 stock above 50 SMA
            "STOCK_OK": _create_mock_df(60, start_price=10.0, trend=0.5),
            # Missing data / corrupt tickers
            "SHORT_HIST": _create_mock_df(25, start_price=10.0),  # < 50 bars
            "EMPTY_DF": pd.DataFrame(),
            "NONE_DF": None,
        }
        res = compute_market_breadth(batch, threshold_pct=40.0)
        self.assertEqual(res["total_universe"], 4)
        self.assertEqual(res["valid_count"], 1)  # only STOCK_OK
        self.assertEqual(res["missing_count"], 3)
        self.assertEqual(res["above_50d_count"], 1)
        self.assertEqual(res["breadth_pct"], 100.0)
        self.assertTrue(res["is_healthy"])

    def test_market_breadth_weak_triggers_caution(self):
        """Verify breadth < 40% reports is_healthy=False."""
        batch = {
            "STOCK_UP": _create_mock_df(60, start_price=10.0, trend=0.5),
            "STOCK_DN1": _create_mock_df(60, start_price=50.0, trend=-0.5),
            "STOCK_DN2": _create_mock_df(60, start_price=50.0, trend=-0.5),
            "STOCK_DN3": _create_mock_df(60, start_price=50.0, trend=-0.5),
        }
        res = compute_market_breadth(batch, threshold_pct=40.0)
        self.assertEqual(res["valid_count"], 4)
        self.assertEqual(res["above_50d_count"], 1)
        self.assertEqual(res["breadth_pct"], 25.0)
        self.assertFalse(res["is_healthy"])

    # ── 3. Gap-Down Veto Tests ────────────────────────────────────────────────

    def test_gap_down_veto_normal_open(self):
        """Normal opening gap (-0.3% vs -0.7% limit) should not trigger veto."""
        res = check_gap_down_veto(spy_open=578.0, spy_prior_close=580.0, threshold_pct=0.7, mode="shadow")
        self.assertFalse(res["would_veto"])
        self.assertFalse(res["veto_active"])
        self.assertAlmostEqual(res["gap_pct"], -0.345, places=2)

    def test_gap_down_veto_shadow_mode(self):
        """Exceeding gap-down in shadow mode logs would_veto=True but veto_active=False."""
        # 574 vs 580 = -1.03% gap down (> 0.7%)
        res = check_gap_down_veto(spy_open=574.0, spy_prior_close=580.0, threshold_pct=0.7, mode="shadow")
        self.assertTrue(res["would_veto"])
        self.assertFalse(res["veto_active"])  # Shadow mode never blocks
        self.assertLess(res["gap_pct"], -0.7)

    def test_gap_down_veto_enforce_mode(self):
        """Exceeding gap-down in enforce mode activates veto_active=True."""
        res = check_gap_down_veto(spy_open=574.0, spy_prior_close=580.0, threshold_pct=0.7, mode="enforce")
        self.assertTrue(res["would_veto"])
        self.assertTrue(res["veto_active"])

    def test_gap_down_veto_off_mode(self):
        """Off mode completely disables veto."""
        res = check_gap_down_veto(spy_open=550.0, spy_prior_close=580.0, threshold_pct=0.7, mode="off")
        self.assertFalse(res["would_veto"])
        self.assertFalse(res["veto_active"])

    def test_gap_down_veto_missing_inputs_fail_safe(self):
        """Missing inputs in enforce mode must fail safe (activate veto)."""
        res = check_gap_down_veto(spy_open=None, spy_prior_close=580.0, mode="enforce")
        self.assertTrue(res["veto_active"])
        self.assertTrue(res["would_veto"])

    # ── 4. Graded Exposure Tier Tests ─────────────────────────────────────────

    def test_tier_a_healthy_conditions(self):
        """All conditions healthy results in Tier A (1.0x size)."""
        breadth = {"breadth_pct": 55.0, "is_healthy": True}
        gap_veto = {"would_veto": False, "veto_active": False}
        tier = classify_market_tier(
            regime_data=self.healthy_regime,
            breadth_data=breadth,
            gap_veto_data=gap_veto,
        )
        self.assertEqual(tier["tier"], "A")
        self.assertEqual(tier["effective_size_multiplier"], 1.0)
        self.assertEqual(tier["effective_score_bump"], 0.0)
        self.assertFalse(tier["is_tier_c"])

    def test_tier_b_due_to_spy_below_50_sma(self):
        """SPY > 200 SMA but <= 50 SMA triggers Tier B."""
        regime = dict(self.healthy_regime, spy_price=555.0, spy_sma_50=560.0)
        breadth = {"breadth_pct": 55.0, "is_healthy": True}
        tier = classify_market_tier(
            regime_data=regime,
            breadth_data=breadth,
            config={"gate_exposure_tiers": "enforce", "tier_b_size_multiplier": 0.5, "tier_b_score_bump": 5.0},
        )
        self.assertEqual(tier["tier"], "B")
        self.assertEqual(tier["effective_size_multiplier"], 0.5)
        self.assertEqual(tier["effective_score_bump"], 5.0)

    def test_tier_b_due_to_weak_breadth(self):
        """Healthy SPY but breadth < 40% triggers Tier B."""
        breadth = {"breadth_pct": 32.0, "is_healthy": False}
        tier = classify_market_tier(
            regime_data=self.healthy_regime,
            breadth_data=breadth,
            config={"gate_exposure_tiers": "enforce"},
        )
        self.assertEqual(tier["tier"], "B")
        self.assertEqual(tier["effective_size_multiplier"], 0.5)

    def test_tier_b_shadow_mode_keeps_actual_size_full(self):
        """In shadow mode, Tier B logs 0.5x hypothetically but keeps effective size 1.0x."""
        breadth = {"breadth_pct": 30.0, "is_healthy": False}
        tier = classify_market_tier(
            regime_data=self.healthy_regime,
            breadth_data=breadth,
            config={"gate_exposure_tiers": "shadow"},
        )
        self.assertEqual(tier["tier"], "B")
        self.assertEqual(tier["hypothetical_size_multiplier"], 0.5)
        self.assertEqual(tier["hypothetical_score_bump"], 5.0)
        self.assertEqual(tier["effective_size_multiplier"], 1.0)
        self.assertEqual(tier["effective_score_bump"], 0.0)

    def test_tier_c_due_to_spy_below_200_sma(self):
        """SPY <= 200 SMA triggers Tier C (0.0x / no entries)."""
        regime = dict(self.healthy_regime, spy_above_200=False, spy_price=510.0)
        tier = classify_market_tier(regime_data=regime)
        self.assertEqual(tier["tier"], "C")
        self.assertTrue(tier["is_tier_c"])
        self.assertEqual(tier["effective_size_multiplier"], 0.0)

    def test_tier_c_due_to_vix_stress(self):
        """VIX >= 25 triggers Tier C."""
        regime = dict(self.healthy_regime, vix=27.5)
        tier = classify_market_tier(regime_data=regime)
        self.assertEqual(tier["tier"], "C")
        self.assertTrue(tier["is_tier_c"])

    def test_tier_c_due_to_gap_down_veto_enforced(self):
        """Gap-down veto in enforce mode triggers Tier C."""
        gap_veto = {"would_veto": True, "veto_active": True, "gap_pct": -1.2}
        tier = classify_market_tier(
            regime_data=self.healthy_regime,
            gap_veto_data=gap_veto,
            config={"gate_gap_down_veto": "enforce"},
        )
        self.assertEqual(tier["tier"], "C")
        self.assertTrue(tier["is_tier_c"])

    def test_tier_c_on_invalid_or_nan_regime(self):
        """Invalid regime data triggers Tier C fail safe."""
        tier = classify_market_tier(regime_data={"is_valid": False, "regime": "unavailable"})
        self.assertEqual(tier["tier"], "C")
        self.assertTrue(tier["is_tier_c"])

    # ── 5. Position Sizing Integration Tests ──────────────────────────────────

    def test_compute_position_size_tier_a(self):
        """Tier A positions receive standard 1.0x sizing."""
        size = self.risk_engine.compute_position_size(
            account_equity=100000.0,
            entry_price=100.0,
            stop_price=95.0,  # $5 risk per share
            risk_pct=2.5,     # $2500 risk
            confidence=100,
            classification="high_conviction",
            size_multiplier=1.0,
            tier="A",
        )
        self.assertNotIn("error", size)
        self.assertEqual(size["tier"], "A")
        self.assertEqual(size["size_multiplier"], 1.0)
        # $2500 / $5 = 500 shares
        self.assertEqual(size["shares"], 250)  # Capped at 25% of $100k = $25k / $100 = 250 shares

    def test_compute_position_size_tier_b(self):
        """Tier B positions receive 0.5x sizing."""
        size = self.risk_engine.compute_position_size(
            account_equity=100000.0,
            entry_price=100.0,
            stop_price=95.0,  # $5 risk per share
            risk_pct=2.5,     # Base $2500 risk
            confidence=100,
            classification="high_conviction",
            size_multiplier=0.5,  # Halved to $1250 risk
            tier="B",
        )
        self.assertNotIn("error", size)
        self.assertEqual(size["tier"], "B")
        self.assertEqual(size["size_multiplier"], 0.5)
        # $1250 / $5 = 250 shares
        self.assertEqual(size["shares"], 250)
        self.assertEqual(size["risk_dollar"], 1250.0)

    def test_compute_position_size_tier_c_blocks(self):
        """Tier C or size_multiplier=0 must return 0 shares and an error."""
        size = self.risk_engine.compute_position_size(
            account_equity=100000.0,
            entry_price=100.0,
            stop_price=95.0,
            size_multiplier=0.0,
            tier="C",
        )
        self.assertIn("error", size)
        self.assertEqual(size["shares"], 0)


if __name__ == "__main__":
    unittest.main()
