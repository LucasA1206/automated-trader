import os
import time
import asyncio
import logging
from datetime import datetime, timezone
from ib_insync import IB, Stock, MarketOrder, util

logger = logging.getLogger(__name__)

# IB Gateway connection settings
IB_HOST = os.getenv("IB_HOST", "127.0.0.1")
IB_CLIENT_ID = int(os.getenv("IB_CLIENT_ID", "1"))

# The gnzsnz/ib-gateway Docker image uses socat to expose:
#   container port 4003 -> internal IB live port 4001
#   container port 4004 -> internal IB paper port 4002
# When connecting via Railway internal network, use these external container ports.
PAPER_PORT = int(os.getenv("IB_PORT", "4004"))  # 4004 = paper (socat relay)
LIVE_PORT = int(os.getenv("IB_PORT_LIVE", "4003"))  # 4003 = live (socat relay)


def get_ib_port(trading_mode: str) -> int:
    return LIVE_PORT if trading_mode == "live" else PAPER_PORT


class IBKRClient:
    """Manages connection and trading operations with IB Gateway."""

    def __init__(self, trading_mode: str = "paper"):
        self.trading_mode = trading_mode
        self.port = get_ib_port(trading_mode)
        self.ib = IB()

    def connect(self, retries: int = 5, delay: int = 10) -> bool:
        """Connect to IB Gateway with retry logic."""
        # FastAPI sync route handlers run in AnyIO worker threads which have no
        # asyncio event loop. ib_insync requires one, so we create and set one.
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                raise RuntimeError("closed")
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        for attempt in range(retries):
            try:
                if self.ib.isConnected():
                    self.ib.disconnect()
                self.ib.connect(
                    host=IB_HOST,
                    port=self.port,
                    clientId=IB_CLIENT_ID,
                    timeout=20,
                    readonly=False,
                )
                logger.info(
                    f"Connected to IB Gateway at {IB_HOST}:{self.port} "
                    f"(mode={self.trading_mode})"
                )
                return True
            except Exception as e:
                logger.warning(
                    f"IBKR connect attempt {attempt + 1}/{retries} failed: {e}"
                )
                if attempt < retries - 1:
                    time.sleep(delay)
        logger.error("Failed to connect to IB Gateway after all retries.")
        return False

    def disconnect(self):
        if self.ib.isConnected():
            self.ib.disconnect()
            logger.info("Disconnected from IB Gateway.")

    def get_account_summary(self) -> dict:
        """Returns key account values: cash, net liquidation, etc."""
        try:
            if not self.ib.isConnected():
                self.connect()
            summary = self.ib.accountValues()
            result = {}
            for av in summary:
                if av.tag in ("TotalCashValue", "NetLiquidation", "AvailableFunds", "BuyingPower"):
                    result[av.tag] = float(av.value) if av.value else 0.0
            return result
        except Exception as e:
            logger.error(f"Failed to fetch account summary: {e}")
            return {}

    def get_positions(self) -> list[dict]:
        """Returns all open positions with current market data."""
        try:
            if not self.ib.isConnected():
                self.connect()
            positions = self.ib.positions()
            result = []
            for pos in positions:
                contract = pos.contract
                avg_cost = pos.avgCost
                size = pos.position
                if size == 0:
                    continue

                # Request market data snapshot
                mkt_data = None
                try:
                    ticker = self.ib.reqMktData(contract, "", True, False)
                    self.ib.sleep(2)
                    mkt_price = ticker.last or ticker.close or avg_cost
                    pnl = (mkt_price - avg_cost) * size
                    pnl_pct = ((mkt_price - avg_cost) / avg_cost * 100) if avg_cost else 0
                    self.ib.cancelMktData(contract)
                except Exception:
                    mkt_price = avg_cost
                    pnl = 0
                    pnl_pct = 0

                result.append({
                    "ticker": contract.symbol,
                    "shares": size,
                    "avg_cost": round(avg_cost, 4),
                    "current_price": round(mkt_price, 4),
                    "market_value": round(mkt_price * size, 2),
                    "pnl": round(pnl, 2),
                    "pnl_pct": round(pnl_pct, 2),
                })
            return result
        except Exception as e:
            logger.error(f"Failed to fetch positions: {e}")
            return []

    def place_buy_order(self, ticker: str, budget: float) -> dict:
        """
        Places a market buy order for the given ticker using the specified dollar budget.
        Returns trade details including shares bought and fill price.
        """
        try:
            if not self.ib.isConnected():
                self.connect()

            contract = Stock(ticker, "SMART", "USD")
            self.ib.qualifyContracts(contract)

            # Get current price for share quantity calculation
            mkt = self.ib.reqMktData(contract, "", True, False)
            self.ib.sleep(2)
            price = mkt.last or mkt.close
            self.ib.cancelMktData(contract)

            if not price or price <= 0:
                raise ValueError(f"Could not determine market price for {ticker}")

            shares = int(budget / price)
            if shares < 1:
                raise ValueError(
                    f"Budget ${budget:.2f} is too small to buy 1 share of {ticker} at ${price:.2f}"
                )

            order = MarketOrder("BUY", shares)
            trade = self.ib.placeOrder(contract, order)
            self.ib.sleep(3)  # Wait for fill

            # Get fill price
            fill_price = price  # fallback
            if trade.fills:
                fill_price = trade.fills[-1].execution.price

            return {
                "success": True,
                "ticker": ticker,
                "shares": shares,
                "price": round(fill_price, 4),
                "total_cost": round(fill_price * shares, 2),
                "order_id": str(trade.order.orderId),
            }
        except Exception as e:
            logger.error(f"Buy order failed for {ticker}: {e}")
            return {"success": False, "ticker": ticker, "error": str(e)}

    def place_sell_order(self, ticker: str, shares: float) -> dict:
        """
        Places a market sell order for the given ticker and number of shares.
        Returns fill price.
        """
        try:
            if not self.ib.isConnected():
                self.connect()

            contract = Stock(ticker, "SMART", "USD")
            self.ib.qualifyContracts(contract)

            order = MarketOrder("SELL", int(shares))
            trade = self.ib.placeOrder(contract, order)
            self.ib.sleep(3)

            fill_price = 0
            if trade.fills:
                fill_price = trade.fills[-1].execution.price
            else:
                # Fallback: get last price
                mkt = self.ib.reqMktData(contract, "", True, False)
                self.ib.sleep(2)
                fill_price = mkt.last or mkt.close or 0
                self.ib.cancelMktData(contract)

            return {
                "success": True,
                "ticker": ticker,
                "shares": int(shares),
                "price": round(fill_price, 4),
                "total_proceeds": round(fill_price * shares, 2),
            }
        except Exception as e:
            logger.error(f"Sell order failed for {ticker}: {e}")
            return {"success": False, "ticker": ticker, "error": str(e)}
