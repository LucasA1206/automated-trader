import os
import math
import time
import random
import asyncio
import threading
import logging
from datetime import datetime, timezone
from ib_insync import IB, Stock, MarketOrder, LimitOrder, StopOrder, util

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
        # Fixed per-instance clientId — only rotated on duplicate-client error (code 326).
        # Keeping it stable prevents ghost slots from accumulating on the gateway.
        self._client_id = random.randint(10, 999)
        self._keepalive_thread: threading.Thread | None = None
        self._keepalive_stop = threading.Event()

    def start_keepalive(self, interval: int = 30) -> None:
        """Start a background thread that keeps the IB Gateway connection alive.

        Every `interval` seconds the thread calls ib.reqAccountUpdates() which
        resets the gateway's idle-disconnect timer.  This prevents the gateway
        from dropping us after ~60 s of client silence.
        """
        if self._keepalive_thread and self._keepalive_thread.is_alive():
            return  # already running

        self._keepalive_stop.clear()

        def _loop():
            try:
                loop = asyncio.get_event_loop()
                if loop.is_closed():
                    raise RuntimeError("closed")
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

            logger.info("IBKR keepalive thread started (interval=%ds).", interval)
            while not self._keepalive_stop.wait(timeout=interval):
                try:
                    if self.ib.isConnected():
                        # reqAccountUpdates is a lightweight round-trip that
                        # resets the gateway's idle timer without creating
                        # persistent subscriptions.
                        self.ib.client.reqAccountUpdates(True, "")
                        logger.debug("IBKR keepalive ping sent.")
                    else:
                        logger.warning("IBKR keepalive: connection lost — attempting reconnect.")
                        self.connect()
                except Exception as exc:
                    logger.warning("IBKR keepalive error: %s", exc)
            logger.info("IBKR keepalive thread stopped.")

        self._keepalive_thread = threading.Thread(target=_loop, daemon=True, name="ibkr-keepalive")
        self._keepalive_thread.start()

    def stop_keepalive(self) -> None:
        """Signal the keepalive thread to exit."""
        self._keepalive_stop.set()

    def connect(self, retries: int = 5, delay: int = 10) -> bool:
        """Connect to IB Gateway with retry logic.

        After the TCP handshake succeeds we do a quick health-check:
        we wait up to 5 s to receive account portfolio data from the
        gateway.  If Warning 2110 fires first (IB upstream broken) or
        account data never arrives we treat the attempt as failed.

        clientId is fixed for the lifetime of this IBKRClient instance
        so that failed/retried connections don't pile up as ghost slots
        on the gateway.  It is only rotated when a duplicate-client
        error (code 326) is detected.

        "Connection refused" is treated as a startup-in-progress signal
        (socat is up but the IB Gateway Java process hasn't bound its port
        yet — happens for ~15 s after the daily 11:59 PM auto-restart).
        """
        # Ensure this thread has an asyncio event loop (AnyIO worker threads don't).
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                raise RuntimeError("closed")
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        for attempt in range(retries):
            try:
                # Clean up old connection if any, and create a fresh instance
                # to prevent dirty background asyncio tasks from failing the retry.
                if hasattr(self, 'ib') and self.ib.isConnected():
                    self.ib.disconnect()
                self.ib = IB()

                # Track warning codes that affect retry strategy
                upstream_broken = [False]
                duplicate_client = [False]

                def _on_error(reqId, errorCode, errorString, contract):
                    if errorCode == 2110:
                        upstream_broken[0] = True
                    elif errorCode == 326:   # duplicate clientId
                        duplicate_client[0] = True

                self.ib.errorEvent += _on_error

                self.ib.connect(
                    host=IB_HOST,
                    port=self.port,
                    clientId=self._client_id,
                    timeout=10,   # TCP handshake only; health-check is separate
                    readonly=False,
                )

                # Health-check: wait up to 8 s for account data to arrive.
                # We use accountValues() rather than portfolio() because
                # portfolio() returns empty when there are no open positions
                # (e.g. after the afternoon sell job closes everything),
                # which would cause a false failure.  accountValues() is
                # always non-empty after a successful sync (cash, net liq, etc.)
                deadline = time.monotonic() + 8
                healthy = False
                while time.monotonic() < deadline:
                    if upstream_broken[0] or duplicate_client[0]:
                        break
                    if self.ib.accountValues():   # non-empty → account sync done
                        healthy = True
                        break
                    self.ib.sleep(0.25)

                self.ib.errorEvent -= _on_error

                if duplicate_client[0]:
                    logger.warning(
                        f"IBKR connect attempt {attempt + 1}/{retries} failed: "
                        f"clientId {self._client_id} already in use — rotating."
                    )
                    self.ib.disconnect()
                    self._client_id = random.randint(10, 999)
                elif upstream_broken[0]:
                    logger.warning(
                        f"IBKR connect attempt {attempt + 1}/{retries} failed: "
                        "IB Gateway upstream connection is broken (error 2110). "
                        "The gateway container is running but has no live link to IB servers. "
                        "Try restarting the ib-gateway service on Railway."
                    )
                    self.ib.disconnect()
                elif not healthy:
                    logger.warning(
                        f"IBKR connect attempt {attempt + 1}/{retries} failed: "
                        "Connected to gateway but account data did not arrive in time. "
                        "The gateway may still be initialising — will retry."
                    )
                    self.ib.disconnect()
                else:
                    logger.info(
                        f"Connected to IB Gateway at {IB_HOST}:{self.port} "
                        f"(mode={self.trading_mode}, clientId={self._client_id})"
                    )
                    return True

            except (ConnectionRefusedError, TimeoutError) as e:
                # socat is up but the IB Gateway Java process hasn't bound port 4002 yet,
                # or it dropped the connection before API handshake completed.
                # This happens for ~15-60 s after the daily 11:59 PM auto-restart.
                err_name = type(e).__name__
                logger.warning(
                    f"IBKR connect attempt {attempt + 1}/{retries} failed: "
                    f"{err_name} — IB Gateway is still starting up after its "
                    "daily restart. Will wait 20 s before retrying."
                )
                if attempt < retries - 1:
                    time.sleep(20)
                continue

            except Exception as e:
                err_msg = str(e) or type(e).__name__
                logger.warning(
                    f"IBKR connect attempt {attempt + 1}/{retries} failed: {err_msg}"
                )

            if attempt < retries - 1:
                time.sleep(delay)

        logger.error("Failed to connect to IB Gateway after all retries.")
        return False

    def disconnect(self):
        self.stop_keepalive()
        if self.ib.isConnected():
            self.ib.disconnect()
            logger.info("Disconnected from IB Gateway.")

    def get_account_summary(self) -> dict:
        """Returns key account values: cash, net liquidation, etc. 

        IBKR's `accountValues()` returns tagged values grouped by currency.
        For an AUD-based account we typically see entries like:
          tag=NetLiquidation, currency=USD,  value=<usd amount>
          tag=NetLiquidation, currency=AUD,  value=<aud amount>
          tag=NetLiquidation, currency=BASE, value=<base amount>

        We read directly from the per-currency buckets so that USD and AUD
        values are always correct — no manual exchange-rate math needed for
        the summary cards.

        ExchangeRate is still extracted and returned so the frontend can
        convert P&L figures that are only available in USD.
        """
        try:
            if not self.ib.isConnected():
                self.connect()
            summary = self.ib.accountValues()
            by_curr: dict[str, dict[str, float]] = {}
            for av in summary:
                if av.currency not in by_curr:
                    by_curr[av.currency] = {}
                by_curr[av.currency][av.tag] = safe_float(av.value)

            usd = by_curr.get("USD", {})
            aud = by_curr.get("AUD", {})
            base = by_curr.get("BASE", {})

            # Exchange rates (FROM each currency TO account base currency).
            # Useful for the frontend to convert P&L values.
            usd_rate = usd.get("ExchangeRate") or 1.0
            aud_rate = aud.get("ExchangeRate") or 1.0

            def _pick(tag: str, bucket: dict) -> float:
                """Return the value from `bucket`, falling back to BASE."""
                val = bucket.get(tag)
                if val is not None and val != 0.0:
                    return val
                return base.get(tag, 0.0)

            result = {
                # Core metrics in USD for trades/budget
                "NetLiquidation": _pick("NetLiquidation", usd),
                "AvailableFunds": _pick("AvailableFunds", usd),
                "BuyingPower": _pick("BuyingPower", usd),
                "TotalCashValue": usd.get("TotalCashValue", 0.0),

                # AUD metrics for UI display
                "NetLiquidation_AUD": _pick("NetLiquidation", aud),
                "AvailableFunds_AUD": _pick("AvailableFunds", aud),
                "BuyingPower_AUD": _pick("BuyingPower", aud),
                "TotalCashValue_AUD": aud.get("TotalCashValue", 0.0),

                # Exchange rates so frontend can convert P&L
                "ExchangeRate_USD": usd_rate,
                "ExchangeRate_AUD": aud_rate,
            }
            return result
        except Exception as e:
            logger.error(f"Failed to fetch account summary: {e}")
            return {}

    def get_positions(self) -> list[dict]:
        """Returns all open positions using portfolio data (includes market prices).

        Uses ib.portfolio() instead of reqMktData so we do not need live market
        data subscriptions — the portfolio update event already carries
        marketPrice, marketValue, and unrealizedPNL from the gateway.

        After connect we wait up to 8 s for the portfolio snapshot to arrive so
        that a fresh connection always returns the full list of positions.
        """
        try:
            if not self.ib.isConnected():
                self.connect()

            # Force a fresh portfolio snapshot by requesting account updates.
            # IBKR streams positions one-by-one, so we must wait until the
            # count stabilises (no new positions for 2 s) rather than breaking
            # on the first item — otherwise we miss positions that arrive
            # slightly later in the stream (this caused the stale ARM bug).
            self.ib.client.reqAccountUpdates(True, "")
            self.ib.sleep(1.0)  # Wait for stream to start
            deadline = time.monotonic() + 10  # generous overall timeout
            last_count = 0
            stable_since = None
            while time.monotonic() < deadline:
                self.ib.sleep(0.3)
                current_count = len(self.ib.portfolio())
                if current_count >= 0:
                    if current_count != last_count:
                        # New position(s) just arrived — reset the stability timer
                        last_count = current_count
                        stable_since = time.monotonic()
                    elif stable_since and (time.monotonic() - stable_since) >= 2.0:
                        # Count has been stable for 2 s — all positions received
                        break
                    elif stable_since is None:
                        stable_since = time.monotonic()
            # Cancel the subscription — we got what we needed.
            self.ib.client.reqAccountUpdates(False, "")

            portfolio_items = self.ib.portfolio()
            result = []

            for item in portfolio_items:
                if getattr(item.contract, 'secType', 'STK') != 'STK':
                    continue
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

            logger.info("get_positions: found %d live position(s) in IBKR.", len(result))
            return result
        except Exception as e:
            logger.error(f"Failed to fetch positions: {e}")
            return []

    def place_buy_order(self, ticker: str, budget: float) -> dict:
        """
        Places a market buy order for the given ticker using the specified dollar budget.
        Returns trade details including shares bought and fill price.
        Attempts placement up to 3 times in case of transient market-open rejections.
        """
        max_attempts = 3
        last_error = ""
        
        for attempt in range(1, max_attempts + 1):
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
                order.tif = "DAY"  # Prevent IBKR order-preset TIF override (Error 10349)
                logger.info(f"Placing market BUY order for {ticker} (attempt {attempt}/{max_attempts}): {shares} shares")
                trade = self.ib.placeOrder(contract, order)

                # Wait up to 30 seconds for fill.
                # Market orders are typically filled in <1 s during market hours,
                # but the IBKR paper gateway can be slow and sometimes routes through
                # multiple legs.  We poll every 0.5 s and stop as soon as the order
                # is either Filled, or terminally rejected (Cancelled/Inactive).
                filled = False
                terminal_statuses = {"Cancelled", "Inactive"}
                for _ in range(60):   # 60 × 0.5 s = 30 s max
                    self.ib.sleep(0.5)
                    status = trade.orderStatus.status
                    if status == "Filled":
                        filled = True
                        break
                    if status in terminal_statuses:
                        # Order was definitively rejected — no point waiting further
                        break
                    # PreSubmitted / Submitted / PendingSubmit → still working, keep waiting

                if not filled:
                    status = trade.orderStatus.status
                    # ── IBKR Paper Bug Workaround ──────────────────────────────────────────
                    # The IBKR paper gateway sometimes reports "Cancelled" for orders that
                    # actually filled. Always check trade.fills before giving up — if the
                    # fills list is non-empty the order was filled despite the Cancelled status.
                    if trade.fills:
                        logger.info(
                            "place_buy_order(%s): status=%s but fills detected — treating as filled (IBKR paper bug).",
                            ticker, status,
                        )
                        filled = True
                    else:
                        # Extract detailed messages from trade.log to explain why
                        log_messages = [f"{entry.status}: {entry.message}" for entry in trade.log if entry.message]
                        log_details = "; ".join(log_messages) if log_messages else "No specific log message"
                        
                        # Only try to cancel if it isn't already in a terminal state
                        if status not in terminal_statuses and status != "Filled":
                            try:
                                self.ib.cancelOrder(order)
                                self.ib.sleep(1.0)
                            except Exception:
                                pass
                        
                        error_msg = f"Order did not fill. Status: {status} ({log_details})"
                        logger.warning(f"Attempt {attempt}/{max_attempts} failed for {ticker}: {error_msg}")
                        last_error = error_msg
                        
                        if attempt < max_attempts:
                            sleep_time = 2.0
                            logger.info(f"Sleeping {sleep_time}s before retry for {ticker}...")
                            self.ib.sleep(sleep_time)
                            continue
                        else:
                            return {"success": False, "ticker": ticker, "error": error_msg}

                if filled:
                    fill_price = price  # fallback
                    fees = 0.0
                    if trade.fills:
                        fill_price = trade.fills[-1].execution.price
                        fees = sum(
                            safe_float(f.commissionReport.commission)
                            for f in trade.fills
                            if getattr(f, 'commissionReport', None) and getattr(f.commissionReport, 'commission', None) is not None
                        )

                    # Place stop-loss (-5%) and take-profit (+10%) bracket orders
                    bracket = self.place_bracket_orders(ticker, contract, shares, safe_float(fill_price))

                    result = {
                        "success": True,
                        "ticker": ticker,
                        "shares": shares,
                        "price": round(safe_float(fill_price), 4),
                        "fees": round(fees, 4),
                        "total_cost": round(safe_float(fill_price) * shares, 2),
                        "order_id": str(trade.order.orderId),
                    }
                    result.update(bracket)
                    return result
            except Exception as e:
                error_msg = str(e)
                logger.error(f"Attempt {attempt}/{max_attempts} crashed for {ticker}: {error_msg}")
                last_error = error_msg
                if attempt < max_attempts:
                    self.ib.sleep(2.0)
                    continue
                else:
                    return {"success": False, "ticker": ticker, "error": error_msg}

        # Safety net: all retries exhausted without an explicit return (shouldn't happen,
        # but prevents a silent None return that would cause TypeError in the caller).
        return {"success": False, "ticker": ticker, "error": last_error or "All retry attempts exhausted"}

    def cancel_all_open_orders(self) -> int:
        """
        Cancels every open/pending order on the account, including OCA legs
        (stop-loss and take-profit bracket orders).

        Called before the afternoon sell-all job so that no residual OCA
        orders can interfere with — or re-trigger after — the EOD liquidation.

        Returns the number of orders that were cancelled.
        """
        try:
            if not self.ib.isConnected():
                self.connect()

            open_orders = self.ib.reqAllOpenOrders()
            self.ib.sleep(1.0)   # give the gateway a moment to return all orders

            if not open_orders:
                logger.info("cancel_all_open_orders: no open orders found.")
                return 0

            cancelled = 0
            for trade in open_orders:
                try:
                    status = trade.orderStatus.status
                    # Only cancel orders that are still active
                    if status not in {"Filled", "Cancelled", "Inactive"}:
                        self.ib.cancelOrder(trade.order)
                        cancelled += 1
                        logger.info(
                            "Cancelled order %s for %s (status=%s, OCA=%s)",
                            trade.order.orderId,
                            getattr(trade.contract, "symbol", "?"),
                            status,
                            trade.order.ocaGroup or "none",
                        )
                except Exception as exc:
                    logger.warning(
                        "Could not cancel order %s: %s",
                        getattr(trade, "order", {}).orderId if hasattr(trade, "order") else "?",
                        exc,
                    )

            # Wait a moment so cancellations propagate before we place sells
            self.ib.sleep(2.0)
            logger.info("cancel_all_open_orders: cancelled %d order(s).", cancelled)
            return cancelled

        except Exception as e:
            logger.error("cancel_all_open_orders failed: %s", e)
            return 0

    def place_bracket_orders(
        self,
        ticker: str,
        contract,
        shares: int,
        fill_price: float,
        stop_pct: float = 0.03,
        profit_pct: float = 0.05,
    ) -> dict:
        """
        Places a GTC stop-loss and take-profit OCA pair after a buy fills.

        Both legs are linked via an OCA (One Cancels All) group so that
        whichever triggers first automatically cancels the other.

        Strategy rationale (low-volatility uptrend approach):
        - stop_pct = 3%: Low-vol stocks (ATR < 3%) shouldn't normally move 3%
          against us in a single day, giving adequate protection without being
          triggered by normal intra-day noise.
        - profit_pct = 5%: Realistic target for slow, steady risers within
          1–5 trading days. More aggressive targets (e.g., 10%) are too far
          away for stable stocks to reach reliably.

        Args:
            ticker:      Stock symbol (for logging).
            contract:    Already-qualified IBKR contract object.
            shares:      Number of shares that were bought.
            fill_price:  Actual fill price of the buy order.
            stop_pct:    Fraction below fill price for stop-loss  (default 0.03 = 3%).
            profit_pct:  Fraction above fill price for take-profit (default 0.05 = 5%).

        Returns a dict with stop/TP prices and order IDs (best-effort).
        """
        try:
            stop_price   = round(fill_price * (1 - stop_pct),   4)
            profit_price = round(fill_price * (1 + profit_pct), 4)

            oca_group = f"OCA_{ticker}_{int(time.time())}"

            # Take-profit leg — limit order sells when price rises to profit_price
            tp_order = LimitOrder("SELL", shares, profit_price)
            tp_order.tif       = "GTC"
            tp_order.ocaGroup  = oca_group
            tp_order.ocaType   = 1   # cancel remaining orders with block
            tp_order.transmit  = True

            # Stop-loss leg — stop order sells when price falls to stop_price
            sl_order = StopOrder("SELL", shares, stop_price)
            sl_order.tif       = "GTC"
            sl_order.ocaGroup  = oca_group
            sl_order.ocaType   = 1
            sl_order.transmit  = True

            tp_trade = self.ib.placeOrder(contract, tp_order)
            sl_trade = self.ib.placeOrder(contract, sl_order)
            self.ib.sleep(0.5)   # let the gateway acknowledge both legs

            logger.info(
                "Bracket orders placed for %s: TP=%.4f (orderId=%s), SL=%.4f (orderId=%s), OCA=%s",
                ticker, profit_price, tp_trade.order.orderId,
                stop_price,  sl_trade.order.orderId, oca_group,
            )

            return {
                "stop_loss_price":     stop_price,
                "take_profit_price":   profit_price,
                "stop_loss_order_id":  str(sl_trade.order.orderId),
                "take_profit_order_id": str(tp_trade.order.orderId),
                "oca_group":           oca_group,
            }
        except Exception as e:
            # Bracket failure is non-fatal — the buy already went through.
            logger.error("Failed to place bracket orders for %s: %s", ticker, e)
            return {
                "stop_loss_price":     None,
                "take_profit_price":   None,
                "bracket_error":       str(e),
            }

    def place_sell_order(self, ticker: str, shares: float) -> dict:
        """
        Places a market SELL order (long position close) for the given ticker.

        If `shares` is negative this is a short position — the method
        automatically routes to place_buy_to_cover_order() so the caller
        never has to distinguish between the two cases.

        Returns fill price.
        """
        # Short-position guard: negative shares means we are short — close by buying.
        if shares < 0:
            logger.info(
                "place_sell_order(%s): detected short position (%s shares). "
                "Routing to buy-to-cover.",
                ticker, shares,
            )
            return self.place_buy_to_cover_order(ticker, abs(shares))

        try:
            shares = int(shares)
            if shares <= 0:
                msg = f"Invalid share quantity for {ticker}: resolved={shares}"
                logger.error(msg)
                return {"success": False, "ticker": ticker, "error": msg}

            if not self.ib.isConnected():
                self.connect()

            contract = Stock(ticker, "SMART", "USD")
            self.ib.qualifyContracts(contract)

            order = MarketOrder("SELL", shares)
            order.tif = "DAY"  # Prevent IBKR order-preset TIF override (Error 10349)
            trade = self.ib.placeOrder(contract, order)


            # Wait up to 30 seconds for fill (same logic as place_buy_order).
            filled = False
            terminal_statuses = {"Cancelled", "Inactive"}
            for _ in range(60):   # 60 × 0.5 s = 30 s max
                self.ib.sleep(0.5)
                status = trade.orderStatus.status
                if status == "Filled":
                    filled = True
                    break
                if status in terminal_statuses:
                    break

            if not filled:
                status = trade.orderStatus.status
                log_messages = [f"{entry.status}: {entry.message}" for entry in trade.log if entry.message]
                log_details = "; ".join(log_messages) if log_messages else "No specific log message"
                if status not in terminal_statuses and status != "Filled":
                    try:
                        self.ib.cancelOrder(order)
                    except Exception:
                        pass
                return {"success": False, "ticker": ticker, "error": f"Order did not fill. Status: {status} ({log_details})"}

            fill_price = 0.0
            fees = 0.0
            if trade.fills:
                fill_price = safe_float(trade.fills[-1].execution.price)
                fees = sum(
                    safe_float(f.commissionReport.commission)
                    for f in trade.fills
                    if getattr(f, 'commissionReport', None) and getattr(f.commissionReport, 'commission', None) is not None
                )
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
                "fees": round(fees, 4),
                "total_proceeds": round(fill_price * shares, 2),
            }
        except Exception as e:
            logger.error(f"Sell order failed for {ticker}: {e}")
            return {"success": False, "ticker": ticker, "error": str(e)}

    def place_buy_to_cover_order(self, ticker: str, shares: float) -> dict:
        """
        Closes a short position by placing a BUY order for `shares` shares.

        This is the mirror image of place_sell_order().  Call this directly
        when you know the position is short, or let place_sell_order() route
        here automatically when it receives a negative share count.
        """
        try:
            shares = int(abs(shares))   # safety — always positive
            if shares <= 0:
                msg = f"Invalid share quantity for {ticker}: resolved={shares}"
                logger.error(msg)
                return {"success": False, "ticker": ticker, "error": msg}

            if not self.ib.isConnected():
                self.connect()

            contract = Stock(ticker, "SMART", "USD")
            self.ib.qualifyContracts(contract)

            # BUY order to close the short
            order = MarketOrder("BUY", shares)
            order.tif = "DAY"  # Prevent IBKR order-preset TIF override (Error 10349)
            trade = self.ib.placeOrder(contract, order)

            # Wait up to 30 seconds for fill
            filled = False
            terminal_statuses = {"Cancelled", "Inactive"}
            for _ in range(60):   # 60 × 0.5 s = 30 s max
                self.ib.sleep(0.5)
                status = trade.orderStatus.status
                if status == "Filled":
                    filled = True
                    break
                if status in terminal_statuses:
                    break

            if not filled:
                status = trade.orderStatus.status
                log_messages = [f"{entry.status}: {entry.message}" for entry in trade.log if entry.message]
                log_details = "; ".join(log_messages) if log_messages else "No specific log message"
                if status not in terminal_statuses and status != "Filled":
                    try:
                        self.ib.cancelOrder(order)
                    except Exception:
                        pass
                return {"success": False, "ticker": ticker, "error": f"Buy-to-cover did not fill. Status: {status} ({log_details})"}

            fill_price = 0.0
            fees = 0.0
            if trade.fills:
                fill_price = safe_float(trade.fills[-1].execution.price)
                fees = sum(
                    safe_float(f.commissionReport.commission)
                    for f in trade.fills
                    if getattr(f, 'commissionReport', None) and getattr(f.commissionReport, 'commission', None) is not None
                )
            else:
                self.ib.reqMarketDataType(3)
                mkt = self.ib.reqMktData(contract, "", True, False)
                self.ib.sleep(2)
                fill_price = safe_float(mkt.last) or safe_float(mkt.close)
                self.ib.cancelMktData(contract)

            logger.info(
                "buy-to-cover filled: %s x %d @ %.4f",
                ticker, shares, fill_price,
            )
            return {
                "success": True,
                "ticker": ticker,
                "shares": shares,
                "price": round(fill_price, 4),
                "fees": round(fees, 4),
                # positive = cash paid to close the short (cost not proceeds)
                "total_proceeds": round(fill_price * shares, 2),
                "order_type": "buy_to_cover",
            }
        except Exception as e:
            logger.error(f"Buy-to-cover failed for {ticker}: {e}")
            return {"success": False, "ticker": ticker, "error": str(e)}
