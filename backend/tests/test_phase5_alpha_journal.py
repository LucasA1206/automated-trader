import unittest
import sys
import os
from unittest.mock import MagicMock
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Mock external network modules
sys.modules["yfinance"] = MagicMock()
sys.modules["finnhub"] = MagicMock()
sys.modules["ib_insync"] = MagicMock()

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Base, Trade, ShadowEvaluation


class TestPhase5AlphaJournal(unittest.TestCase):

    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

    def tearDown(self):
        self.db.close()

    def test_trade_model_alpha_and_confirmation_fields(self):
        trade = Trade(
            ticker="AAPL",
            shares=50,
            buy_price=150.0,
            sell_price=165.0,
            status="closed",
            mode="paper",
            pnl=750.0,
            pnl_pct=10.0,
            spy_price_at_entry=500.0,
            spy_price_at_exit=525.0,
            spy_return_pct=5.0,
            beta_at_entry=1.2,
            expected_return_pct=6.0,  # 1.2 * 5.0%
            alpha_pct=4.0,            # 10.0% - 6.0%
            market_tier_at_entry="A",
            intraday_confirmed_at_entry=True,
            breadth_at_entry=55.0,
            sector_rank_at_entry=2,
        )
        self.db.add(trade)
        self.db.commit()

        queried = self.db.query(Trade).filter(Trade.ticker == "AAPL").first()
        self.assertIsNotNone(queried)
        self.assertEqual(queried.alpha_pct, 4.0)
        self.assertEqual(queried.expected_return_pct, 6.0)
        self.assertEqual(queried.spy_return_pct, 5.0)
        self.assertEqual(queried.market_tier_at_entry, "A")
        self.assertTrue(queried.intraday_confirmed_at_entry)

    def test_shadow_evaluation_model(self):
        eval_record = ShadowEvaluation(
            ticker="MSFT",
            gate_name="intraday_confirm",
            mode="shadow",
            would_have_blocked=True,
            actual_pnl=-150.0,
            actual_pnl_pct=-3.0,
            hypothetical_pnl=0.0,
            hypothetical_pnl_pct=0.0,
            details="SPY below VWAP at entry time",
        )
        self.db.add(eval_record)
        self.db.commit()

        queried = self.db.query(ShadowEvaluation).filter(ShadowEvaluation.ticker == "MSFT").first()
        self.assertIsNotNone(queried)
        self.assertTrue(queried.would_have_blocked)
        self.assertEqual(queried.hypothetical_pnl, 0.0)
        self.assertEqual(queried.actual_pnl, -150.0)


if __name__ == "__main__":
    unittest.main()
