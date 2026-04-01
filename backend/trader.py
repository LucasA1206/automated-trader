import os
import math
import time
import random
import asyncio
import logging
from datetime import datetime, timezone
from ib_insync import IB, Stock, MarketOrder, util

logger = logging.getLogger(__name__)

# IB Gateway connection settings
IB_HOST = os.getenv("IB_HOST", "127.0.0.1")

# The gnzsnz/ib-gateway Docker image uses socat to expose:
#   container port 4003 -> internal IB live port 4001
#   container port 4004 -> internal IB paper port 4002
# When connecting via Railway internal network, use these external container ports.
PAPER_PORT = int(os.getenv("IB_PORT", "4004"))       # 4004 = paper (socat relay)
LIVE_PORT = int(os.getenv("IB_PORT_LIVE", "4003"))   # 4003 = live  (socat relay)


def get_ib_port(trading_mode: str) -> int:
    return LIVE_PORT if trading_mode == "live" else PAPER_PORT


def safe_float(value, fallback: float = 0.0) -> float:
    """Return a JSON-safe float, replacing NaN/inf with fallback."""
    try:
        f = float(value)
        return f if math.isfinite(f) else fallback
    except (TypeError, ValueError):
        return fallback


class IBKRClient:
    """Manages connection and trading operations with IB Gateway."""

    def __init__(self, trading_mode: str = "paper"):
        self.trading_mode = trading_mode
        self.port = get_ib_port(trading_mode)
        self.ib = IB()

    def connect(self, retries: int = 5, delay: int = 10) -> bool:
        """Connect to IB Gateway with retry logic.

        Uses a random clientId (10–999) per connection so that concurrent
        FastAPI requests don't fight over the same IB Gateway client slot.
        FastAPI sync route handlers run in AnyIO worker threads with no
        asyncio event loop — we create one here before ib_insync needs it.
        """
        # Ensure this thread has an asyncio event loop (AnyIO worker threads don't).
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                raise RuntimeError("closed")
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        client_id = random.randint(10, 999)

        for attempt in range(retries):
            try:
                # Clean up old connection if any, and create a fresh instance
                # to prevent dirty background asyncio tasks from failing the retry.
                if hasattr(self, 'ib') and self.ib.isConnected():
                    self.ib.disconnect()
                self.ib = IB()

                self.ib.connect(
                    host=IB_HOST,
                    port=self.port,
                    clientId=client_id,
                    timeout=30,  # Increased for slow laptop initialization
                    readonly=False,
                )
                logger.info(
                    f"Connected to IB Gateway at {IB_HOST}:{self.port} "
                    f"(mode={self.trading_mode}, clientId={client_id})"
                )
                return True
            except Exception as e:
                err_msg = str(e) or type(e).__name__
                logger.warning(
                    f"IBKR connect attempt {attempt + 1}/{retries} failed: {err_msg}"
                )
                if attempt < retries - 1:
                    # Use a different clientId on next attempt in case of collision
                    client_id = random.randint(10, 999)
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
                    result[av.tag] = safe_float(av.value)
            return result
        except Exception as e:
            logger.error(f"Failed to fetch account summary: {e}")
            return {}

    def get_positions(self) -> list[dict]:
        """Returns all open positions using portfolio data (includes market prices).

        Uses ib.portfolio() instead of reqMktData so we do not need live market
        data subscriptions — the portfolio update event already carries
        marketPrice, marketValue, and unrealizedPNL from the gateway.
        """
        try:
            if not self.ib.isConnected():
                self.connect()

            portfolio_items = self.ib.portfolio()
            result = []

            for item in portfolio_items:
                size = item.position
                if size == 0:
                    continue

                avg_cost = safe_float(item.averageCost)
                mkt_price = safe_float(item.marketPrice, fallback=avg_cost)
                market_value = safe_float(item.marketValue, fallback=mkt_price * size)
                pnl = safe_float(item.unrealizedPNL)
                pnl_pct = ((mkt_price - avg_cost) / avg_cost * 100) if avg_cost else 0.0

                result.append({
                    "ticker": item.contract.symbol,
                    "shares": size,
                    "avg_cost": round(avg_cost, 4),
                    "current_price": round(mkt_price, 4),
                    "market_value": round(market_value, 2),
                    "pnl": round(safe_float(pnl), 2),
                    "pnl_pct": round(safe_float(pnl_pct), 2),
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

            # Request delayed market data (type 3) — no subscription needed.
            # Poll up to 10 s so we survive the initial data-farm connection delay
            # (Warning 2119 "Market data farm is connecting") that hits the first
            # ticker in each scan session.
            self.ib.reqMarketDataType(3)
            mkt = self.ib.reqMktData(contract, "", True, False)
            price = 0.0
            for _ in range(20):   # 20 × 0.5 s = 10 s max
                self.ib.sleep(0.5)
                price = safe_float(mkt.last) or safe_float(mkt.close)
                if price > 0:
                    break
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

            fill_price = price  # fallback
            if trade.fills:
                fill_price = trade.fills[-1].execution.price

            return {
                "success": True,
                "ticker": ticker,
                "shares": shares,
                "price": round(safe_float(fill_price), 4),
                "total_cost": round(safe_float(fill_price) * shares, 2),
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

            fill_price = 0.0
            if trade.fills:
                fill_price = safe_float(trade.fills[-1].execution.price)
            else:
                # Fallback: request delayed price
                self.ib.reqMarketDataType(3)
                mkt = self.ib.reqMktData(contract, "", True, False)
                self.ib.sleep(2)
                fill_price = safe_float(mkt.last) or safe_float(mkt.close)
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
