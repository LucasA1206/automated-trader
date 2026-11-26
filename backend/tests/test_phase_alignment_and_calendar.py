import os
import sys
import unittest
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytz
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.modules.setdefault("ib_insync", MagicMock())
sys.modules.setdefault("google", MagicMock())
sys.modules.setdefault("google.generativeai", MagicMock())

from models import Base, Trade, PendingExitIntent
from strategy.market_calendar import (
    get_session_info,
    is_nyse_market_open,
    is_nyse_trading_day,
    ET,
)
from strategy.data_layer import compute_regime_status, _is_valid_spy_dict
from strategy.data_quality import (
    check_regime_inputs,
    reconcile_positions_and_stops,
    repair_missing_stops,
)
from strategy.data_providers import ProviderChain, MarketDataProvider
from ai_analyst import _parse_nasdaqtrader_file
from trader import IBKRClient


class TestPhaseAlignmentAndCalendar(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        Session = sessionmaker(bind=self.engine)
        self.db = Session()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_market_calendar_holiday_weekend_early_close(self):
        # 2026-11-26 is US Thanksgiving (Thursday)
        thanksgiving = date(2026, 11, 26)
        info_tg = get_session_info(thanksgiving)
        self.assertFalse(info_tg["is_trading_day"])
        self.assertTrue(info_tg["is_holiday"])
        self.assertIn("Thanksgiving", info_tg["reason"])
        dt_tg_noon = ET.localize(datetime(2026, 11, 26, 12, 45))
        self.assertFalse(is_nyse_market_open(dt_tg_noon))

        # 2026-11-27 is Day after Thanksgiving -> 13:00 ET early close
        friday_ec = date(2026, 11, 27)
        info_ec = get_session_info(friday_ec)
        self.assertTrue(info_ec["is_trading_day"])
        self.assertTrue(info_ec["is_early_close"])
        self.assertTrue(is_nyse_market_open(ET.localize(datetime(2026, 11, 27, 12, 55))))
        self.assertFalse(is_nyse_market_open(ET.localize(datetime(2026, 11, 27, 13, 5))))

        # 2026-11-28 is Saturday
        self.assertFalse(is_nyse_trading_day(date(2026, 11, 28)))

        # Disagreement with IBKR trading hours fails safe (closed)
        self.assertFalse(is_nyse_market_open(ET.localize(datetime(2026, 11, 27, 11, 0)), ibkr_is_open=False))

    def test_place_sell_order_presubmitted_and_fractional(self):
        client = IBKRClient(trading_mode="paper")
        client.ib = MagicMock()
        client.ib.isConnected.return_value = True

        # PreSubmitted -> success=True, in_flight=True (not treated as failure)
        mock_trade = SimpleNamespace(
            order=SimpleNamespace(orderId=42),
            orderStatus=SimpleNamespace(status="PreSubmitted"),
            fills=[],
            log=[],
        )
        client.ib.placeOrder.return_value = mock_trade
        res = client.place_sell_order("CDNA", 3, limit_price=76.0, wait_seconds=1)
        self.assertTrue(res["success"])
        self.assertTrue(res["in_flight"])
        self.assertFalse(res["filled"])
        self.assertEqual(res["status"], "PreSubmitted")
        client.ib.cancelOrder.assert_not_called()

        # Fractional 0.84 shares -> does NOT truncate to int(0.84) == 0
        mock_trade_frac = SimpleNamespace(
            order=SimpleNamespace(orderId=43),
            orderStatus=SimpleNamespace(status="Filled"),
            fills=[SimpleNamespace(execution=SimpleNamespace(price=90.0), commissionReport=None)],
            log=[],
        )
        client.ib.placeOrder.return_value = mock_trade_frac
        res_frac = client.place_sell_order("SWKS", 0.84, wait_seconds=1)
        self.assertTrue(res_frac["success"])
        self.assertEqual(res_frac["shares"], 0.84)

    def test_stop_reconciliation_states_and_repair(self):
        self.db.add(Trade(ticker="CDNA", shares=3.0, buy_price=80.0, stop_price=75.0, status="open", mode="paper"))
        self.db.add(Trade(ticker="SWKS", shares=0.84, buy_price=90.0, stop_price=85.0, status="open", mode="paper"))
        self.db.commit()

        mock_ibkr = MagicMock()
        mock_ibkr.get_positions.return_value = [
            {"ticker": "CDNA", "shares": 3.0},
            {"ticker": "SWKS", "shares": 0.84},
        ]

        # 1. PreSubmitted stop outside hours for CDNA + fractional SWKS -> NOT critical
        mock_ibkr.get_open_orders.return_value = [
            {"ticker": "CDNA", "action": "SELL", "order_type": "STP", "total_quantity": 3.0, "status": "PreSubmitted"}
        ]
        res_outside = reconcile_positions_and_stops(self.db, mock_ibkr, is_market_open=False)
        self.assertNotEqual(res_outside["status"], "critical")
        self.assertEqual(len(res_outside["queued_stops"]), 1)
        self.assertEqual(len(res_outside["fractional_unprotected"]), 1)

        # 2. Missing stop for CDNA during market hours -> CRITICAL, then repair places GTC stop
        mock_ibkr.get_open_orders.return_value = []
        mock_ibkr.place_stop_order.return_value = {"success": True, "order_id": "777"}
        repaired = repair_missing_stops(self.db, mock_ibkr, is_market_open=True)
        self.assertEqual(len(repaired["repaired"]), 1)
        self.assertEqual(repaired["repaired"][0]["ticker"], "CDNA")
        mock_ibkr.place_stop_order.assert_called_once_with("CDNA", 3, 75.0)

    def test_regime_none_sma200_never_says_below_200sma(self):
        bad_spy = {"price": 500.0, "sma_50": 495.0, "sma_200": None, "above_sma_200": False, "day_return_pct": -0.3}
        self.assertFalse(_is_valid_spy_dict(bad_spy))
        reg = compute_regime_status(spy=bad_spy, vix={"current": 20.0, "prev_1d": 19.5, "prev_3d": 19.0, "spike_3d_pct": 5.2})
        self.assertEqual(reg["regime"], "unavailable")
        self.assertFalse(reg["is_valid"])
        self.assertNotIn("BELOW 200SMA", reg["details"])

        # Valid regime passes check_regime_inputs (key alignment: spy_sma_200)
        good_spy = {"price": 500.0, "sma_50": 495.0, "sma_200": 480.0, "above_sma_200": True, "day_return_pct": 0.3, "source": "SPY"}
        reg_ok = compute_regime_status(spy=good_spy, vix={"current": 16.0, "prev_1d": 16.0, "prev_3d": 15.8, "spike_3d_pct": 1.2})
        self.assertEqual(reg_ok["regime"], "risk_on")
        dq_res = check_regime_inputs(self.db, reg_ok, is_market_open=True)
        self.assertEqual(dq_res["status"], "ok")

    def test_universe_filters_note_suffixes(self):
        sample_file = "\n".join([
            "Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares",
            "AAPL|Apple Inc.|Q|N|N|100|N|N",
            "DHCNL|Diversified Healthcare Trust Notes|Q|N|N|100|N|N",
            "MFICL|MFA Financial Notes|Q|N|N|100|N|N",
            "WHLRL|Wheeler Real Estate Notes|Q|N|N|100|N|N",
            "MSFT|Microsoft Corp|Q|N|N|100|N|N",
        ])
        tickers = _parse_nasdaqtrader_file(sample_file, "nasdaqlisted.txt")
        self.assertIn("AAPL", tickers)
        self.assertIn("MSFT", tickers)
        self.assertNotIn("DHCNL", tickers)
        self.assertNotIn("MFICL", tickers)
        self.assertNotIn("WHLRL", tickers)

    def test_provider_chain_fallback(self):
        class MockPrimary(MarketDataProvider):
            name = "mock_primary"
            def fetch_fundamentals(self, ticker):
                return None

        class MockBackup(MarketDataProvider):
            name = "mock_backup"
            def fetch_fundamentals(self, ticker):
                return {"market_cap": 1e9, "revenue_growth_yoy": None}

        chain = ProviderChain(providers={"fmp": MockPrimary(), "finnhub": MockBackup()})
        res = chain.get_fundamentals("AAPL")
        self.assertIsNotNone(res)
        self.assertEqual(res["_provider"], "finnhub")
        self.assertIsNone(res["revenue_growth_yoy"])


if __name__ == "__main__":
    unittest.main()
