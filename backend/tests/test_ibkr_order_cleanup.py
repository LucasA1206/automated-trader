import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Mock ib_insync before importing trader
sys.modules.setdefault("ib_insync", MagicMock())

from trader import IBKRClient


def _make_open_trade(symbol: str, action: str, order_type: str, order_id: int, client_id: int, status: str = "PreSubmitted"):
    return SimpleNamespace(
        contract=SimpleNamespace(symbol=symbol),
        order=SimpleNamespace(
            action=action,
            orderType=order_type,
            orderId=order_id,
            clientId=client_id,
            auxPrice=10.0,
            totalQuantity=100,
        ),
        orderStatus=SimpleNamespace(status=status),
    )


class TestIBKROrderCleanup(unittest.TestCase):
    def setUp(self):
        self.client = IBKRClient(trading_mode="paper")
        self.client.ib = MagicMock()
        self.client.ib.isConnected.return_value = True
        self.client.ib.client = SimpleNamespace(clientId=500)

    def test_modify_stop_order_cancels_prior_clientid_stops_before_replacing(self):
        old_stop_1 = _make_open_trade("CDNA", "SELL", "STP", order_id=11, client_id=243)
        old_stop_2 = _make_open_trade("CDNA", "SELL", "STP", order_id=12, client_id=244)
        other_ticker = _make_open_trade("AAPL", "SELL", "STP", order_id=13, client_id=243)

        self.client.ib.reqAllOpenOrders.return_value = [old_stop_1, old_stop_2, other_ticker]
        self.client.place_stop_order = MagicMock(return_value={
            "success": True, "ticker": "CDNA", "shares": 50, "stop_price": 21.5, "order_id": "99"
        })

        res = self.client.modify_stop_order("CDNA", "11", 21.5, 50)
        self.assertTrue(res["success"])
        self.assertEqual(res["order_id"], "99")

        # Both orphaned CDNA stops cancelled; AAPL stop untouched
        cancelled_orders = [call.args[0] for call in self.client.ib.cancelOrder.call_args_list]
        self.assertIn(old_stop_1.order, cancelled_orders)
        self.assertIn(old_stop_2.order, cancelled_orders)
        self.assertNotIn(other_ticker.order, cancelled_orders)
        self.client.place_stop_order.assert_called_once_with("CDNA", 50, 21.5)

    def test_modify_stop_order_same_clientid_modifies_inplace_and_dedupes(self):
        current_stop = _make_open_trade("CDNA", "SELL", "STP", order_id=25, client_id=500)
        dup_stop = _make_open_trade("CDNA", "SELL", "STP", order_id=19, client_id=243)
        self.client.ib.reqAllOpenOrders.return_value = [current_stop, dup_stop]

        res = self.client.modify_stop_order("CDNA", "25", 22.0, 50)
        self.assertTrue(res["success"])
        self.assertTrue(res.get("modified"))
        self.assertEqual(current_stop.order.auxPrice, 22.0)
        self.assertEqual(current_stop.order.totalQuantity, 50)

        # Duplicate cancelled, current modified in-place
        self.client.ib.cancelOrder.assert_called_once_with(dup_stop.order)
        self.client.ib.placeOrder.assert_called_once()

    def test_cancel_all_orders_for_ticker(self):
        s1 = _make_open_trade("CDNA", "SELL", "STP", order_id=1, client_id=100, status="PreSubmitted")
        s2 = _make_open_trade("CDNA", "SELL", "LMT", order_id=2, client_id=101, status="Submitted")
        already_done = _make_open_trade("CDNA", "SELL", "STP", order_id=3, client_id=102, status="Cancelled")
        other = _make_open_trade("MSFT", "SELL", "STP", order_id=4, client_id=100, status="PreSubmitted")

        self.client.ib.reqAllOpenOrders.return_value = [s1, s2, already_done, other]
        count = self.client.cancel_all_orders_for_ticker("CDNA")

        self.assertEqual(count, 2)
        cancelled_orders = [call.args[0] for call in self.client.ib.cancelOrder.call_args_list]
        self.assertEqual(len(cancelled_orders), 2)
        self.assertIn(s1.order, cancelled_orders)
        self.assertIn(s2.order, cancelled_orders)


if __name__ == "__main__":
    unittest.main()
