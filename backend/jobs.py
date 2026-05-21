import logging
import threading
from datetime import datetime, timezone
from database import SessionLocal, get_setting
from models import Trade, SystemLog, AIPick
from ai_analyst import run_daily_scan, verify_ticker_momentum
from trader import IBKRClient

logger = logging.getLogger(__name__)


def _build_strategy_plan(
    trading_mode: str,
    paper_strategy: str,
    available_cash: float,
    net_liq: float,
    db_budget_pct: float,
    db_max_positions: int
) -> tuple[float, int, str]:
    """Return the daily budget, position cap, and a human-readable strategy label."""
    fraction = db_budget_pct / 100.0
    if trading_mode == "live":
        return available_cash * fraction, db_max_positions, f"live cash account / {db_max_positions} stocks / {db_budget_pct}% budget"
    if paper_strategy == "margin":
        return available_cash * fraction, db_max_positions, f"paper margin simulation / {db_max_positions} stocks / {db_budget_pct}% budget"
    return available_cash * fraction, db_max_positions, f"paper cash simulation / {db_max_positions} stocks / {db_budget_pct}% budget"

# ---------------------------------------------------------------------------
# Persistent keepalive — a single IBKRClient that stays connected between jobs
# ---------------------------------------------------------------------------
_persistent_client: IBKRClient | None = None
_persistent_client_lock = threading.Lock()


def start_persistent_keepalive(trading_mode: str = "paper") -> None:
    """Connect a long-lived IBKRClient and keep it alive in the background."""
    global _persistent_client
    with _persistent_client_lock:
        if _persistent_client is not None:
            return  # already running
        client = IBKRClient(trading_mode=trading_mode)
        if client.connect():
            client.start_keepalive(interval=30)
            _persistent_client = client
            logger.info("Persistent IBKR keepalive started (mode=%s).", trading_mode)
        else:
            logger.warning("Persistent IBKR keepalive: could not connect on startup. "
                           "Will retry when a job next runs.")


def stop_persistent_keepalive() -> None:
    """Gracefully shut down the persistent keepalive client."""
    global _persistent_client
    with _persistent_client_lock:
        if _persistent_client is not None:
            _persistent_client.disconnect()
            _persistent_client = None
            logger.info("Persistent IBKR keepalive stopped.")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def log_event(db, category: str, message: str, level: str = "INFO"):
    """Helper to write a system log entry."""
    entry = SystemLog(
        timestamp=datetime.now(timezone.utc),
        level=level,
        category=category,
        message=message,
    )
    db.add(entry)
    db.commit()
    logger.info(f"[{category.upper()}] {message}")


def _reconcile_stale_db_trades(db, live_tickers: set[str], log_fn) -> None:
    """Close any DB trades marked 'open'/'sold_half' for tickers no longer held in IBKR."""
    open_trades = db.query(Trade).filter(Trade.status.in_(["open", "sold_half"])).all()
    for trade in open_trades:
        if trade.ticker not in live_tickers:
            trade.status = "closed"
            trade.sell_time = datetime.now(timezone.utc)
            # sell_price/pnl left as None — we don't know the actual exit price
            db.commit()
            log_fn(db, "sell",
                   f"⚠️ Reconciled stale DB record for {trade.ticker} "
                   f"(marked closed — not found in live IBKR positions).")


def _persist_ai_picks(db, recommendations: list[dict], scan_date) -> None:
    """Save this week's AI picks to the ai_picks table, replacing any same-day records."""
    # Remove old picks for today (in case of a re-scan)
    db.query(AIPick).filter(AIPick.scan_date == scan_date).delete()
    db.commit()

    for rank, rec in enumerate(recommendations, start=1):
        pick = AIPick(
            scan_date=scan_date,
            ticker=rec.get("ticker", "").upper().strip(),
            reason=rec.get("reason", ""),
            confidence=float(rec.get("confidence", 0.0)),
            position_size_pct=float(rec.get("position_size_pct", 0.0)),
            rank=rank,
        )
        db.add(pick)
    db.commit()
    logger.info(f"Persisted {len(recommendations)} AI pick(s) to database for {scan_date}.")


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

def job_morning_scan_and_buy():
    """
    Runs at 09:30 ET weekdays:
    1. Checks if scan is enabled
    2. Runs AI stock scan
    3. Buys top picks using configured budget %
    """
    db = SessionLocal()
    try:
        trader_enabled = get_setting(db, "trader_enabled", "true")
        if trader_enabled.lower() != "true":
            log_event(db, "system", "Trader is globally disabled. Skipping morning job.")
            return

        scan_enabled = get_setting(db, "scan_enabled", "true")
        if scan_enabled.lower() != "true":
            log_event(db, "system", "Auto-scan is disabled. Skipping morning job.")
            return

        trading_mode = get_setting(db, "trading_mode", "paper")
        account_type = get_setting(db, "account_type", "trading_cash")
        paper_strategy = get_setting(db, "paper_strategy", "cash")

        try:
            budget_pct = float(get_setting(db, "daily_budget_pct", "100"))
        except ValueError:
            budget_pct = 100.0

        try:
            max_positions_setting = int(get_setting(db, "max_positions", "5"))
        except ValueError:
            max_positions_setting = 5

        # Connect to IBKR to get account balance
        client = IBKRClient(trading_mode=trading_mode)
        connected = client.connect()
        if not connected:
            log_event(db, "ibkr", "Failed to connect to IB Gateway. Aborting trades.", "ERROR")
            return

        client.start_keepalive(interval=30)

        account = client.get_account_summary()
        available_cash = account.get("AvailableFunds", 0)
        net_liq = account.get("NetLiquidation", 0)

        if available_cash <= 0:
            log_event(db, "ibkr", f"No available funds (${available_cash:.2f}). Aborting.", "ERROR")
            client.disconnect()
            return

        daily_budget, max_positions, strategy_label = _build_strategy_plan(
            trading_mode, paper_strategy, available_cash, net_liq, budget_pct, max_positions_setting
        )

        log_event(db, "scan", f"Starting morning scan. Mode: {trading_mode}, "
                              f"Account: {account_type}, Strategy: {strategy_label}, "
                              f"Budget: ${daily_budget:,.2f}")

        # Step 1: AI Scan
        recommendations = run_daily_scan()
        if not recommendations:
            log_event(db, "scan", "No stocks recommended by AI today. No trades placed.")
            client.disconnect()
            return

        # Sort by highest confidence — AI already filters for quality
        recommendations.sort(key=lambda r: r.get("confidence", 0), reverse=True)

        tickers_str = ", ".join(
            f"{r['ticker']}({r.get('confidence', 0):.0%})" for r in recommendations
        )
        log_event(db, "scan", f"AI recommended {len(recommendations)} stock(s): {tickers_str}")

        # Persist all AI picks to DB for the UI to display
        today_date = datetime.now(timezone.utc).date()
        _persist_ai_picks(db, recommendations, today_date)

        # Step 2: Cap to configured max positions
        pick_limit = min(max_positions, len(recommendations))
        picks = recommendations[:pick_limit]

        # Distribute budget according to position_size_pct if available,
        # otherwise split evenly
        total_pct = sum(r.get("position_size_pct", 0) for r in picks)
        budgets: list[float] = []
        if total_pct > 0:
            for r in picks:
                weight = r.get("position_size_pct", 0) / total_pct
                budgets.append(daily_budget * weight)
        else:
            budgets = [daily_budget / len(picks)] * len(picks)

        log_event(db, "system",
              f"Net Liq: ${net_liq:,.2f} | Available cash: ${available_cash:,.2f} | "
              f"Today's budget: ${daily_budget:,.2f} | "
              f"Buying {len(picks)} stock(s)")

        # Step 3: Place buy orders
        for rec, budget_for_trade in zip(picks, budgets):
            ticker = rec["ticker"]
            reason = rec.get("reason", "")
            confidence = rec.get("confidence", 0)
            pos_size = rec.get("position_size_pct", 0)

            log_event(db, "buy",
                      f"Placing BUY order for {ticker} "
                      f"(confidence={confidence:.0%}, size={pos_size:.0f}%): {reason}")

            # Pre-buy momentum gate
            if not verify_ticker_momentum(ticker):
                log_event(db, "buy",
                          f"⚠️ Skipped {ticker} — failed pre-buy momentum check "
                          f"(down >3% over recent sessions despite AI recommendation)")
                continue

            result = client.place_buy_order(ticker, budget_for_trade)

            if result["success"]:
                trade = Trade(
                    ticker=ticker,
                    shares=result["shares"],
                    buy_price=result["price"],
                    buy_time=datetime.now(timezone.utc),
                    status="open",
                    order_id=result.get("order_id"),
                    ai_reason=reason,
                    mode=trading_mode,
                    fees=result.get("fees", 0.0),
                    realised_partial_pnl=0.0,
                )
                db.add(trade)
                db.commit()
                log_event(db, "buy",
                          f"✅ Bought {result['shares']} shares of {ticker} "
                          f"@ ${result['price']:.2f} "
                          f"(Total: ${result['total_cost']:,.2f})")
            else:
                log_event(db, "buy",
                          f"❌ Buy failed for {ticker}: {result.get('error')}", "ERROR")

        client.disconnect()

    except Exception as e:
        logger.exception(f"Morning scan job crashed: {e}")
        log_event(db, "system", f"Morning scan crashed: {e}", "ERROR")
    finally:
        db.close()


def job_afternoon_sell():
    """
    Runs at 15:30 ET weekdays (30 min before NYSE close):
    Sells ALL open positions held in the IBKR account.

    P&L calculation for closed trades:
    - For 'open' trades: pnl = (sell_price - buy_price) * shares
    - For 'sold_half' trades: pnl = (sell_price - buy_price) * remaining_shares
                                    + trade.realised_partial_pnl

    The realised_partial_pnl column banks the +10% partial gain so it is NEVER
    overwritten here, regardless of how many shares remain.
    """
    db = SessionLocal()
    try:
        trader_enabled = get_setting(db, "trader_enabled", "true")
        if trader_enabled.lower() != "true":
            log_event(db, "system", "Trader is globally disabled. Skipping afternoon sell job.")
            return

        trading_mode = get_setting(db, "trading_mode", "paper")
        log_event(db, "sell", "Starting afternoon sell-all job (30 min before close).")

        client = IBKRClient(trading_mode=trading_mode)
        connected = client.connect()
        if not connected:
            log_event(db, "ibkr",
                      "Failed to connect to IB Gateway for sell job.", "ERROR")
            return

        client.start_keepalive(interval=30)

        live_positions = client.get_positions()
        live_tickers = {p["ticker"] for p in live_positions}

        if not live_positions:
            log_event(db, "sell",
                      "No live positions found in IBKR account. "
                      "Reconciling any stale DB records.")
            _reconcile_stale_db_trades(db, live_tickers, log_event)
            client.disconnect()
            return

        log_event(db, "sell",
                  f"Found {len(live_positions)} live position(s) in IBKR: "
                  f"{', '.join(p['ticker'] for p in live_positions)}")

        # Build lookup of DB open trades by ticker
        open_trades = db.query(Trade).filter(Trade.status.in_(["open", "sold_half"])).all()
        db_trades_by_ticker = {t.ticker: t for t in open_trades}

        sold_tickers: set[str] = set()

        for position in live_positions:
            ticker = position["ticker"]
            live_shares = position["shares"]  # Actual shares currently held (may be halved)

            log_event(db, "sell",
                      f"Placing SELL order for {live_shares} shares of {ticker}...")
            result = client.place_sell_order(ticker, live_shares)

            if result["success"]:
                sell_price = result["price"]
                sold_tickers.add(ticker)

                trade = db_trades_by_ticker.get(ticker)
                if trade:
                    buy_price = trade.buy_price or 0.0
                    partial_already_realised = trade.realised_partial_pnl or 0.0

                    # Correct P&L: use LIVE shares (actual remaining) not trade.shares
                    # (which still reflects the original full buy quantity).
                    remaining_pnl = (sell_price - buy_price) * live_shares
                    total_pnl = remaining_pnl + partial_already_realised

                    # pnl_pct based on the original full position cost
                    original_cost = buy_price * trade.shares if trade.shares else 1
                    pnl_pct = (total_pnl / original_cost * 100) if original_cost else 0.0

                    trade.sell_price = sell_price
                    trade.sell_time = datetime.now(timezone.utc)
                    trade.status = "closed"
                    trade.pnl = round(total_pnl, 2)
                    trade.pnl_pct = round(pnl_pct, 2)

                    sell_fees = result.get("fees", 0.0)
                    trade.fees = round((trade.fees or 0.0) + sell_fees, 4)
                    db.commit()

                    emoji = "🟢" if total_pnl >= 0 else "🔴"
                    partial_note = (f" (incl. +${partial_already_realised:.2f} partial)"
                                    if partial_already_realised else "")
                    log_event(db, "sell",
                              f"{emoji} Sold {live_shares} shares of {ticker} "
                              f"@ ${sell_price:.2f} | P&L: ${total_pnl:+.2f} "
                              f"({pnl_pct:+.2f}%){partial_note} | Fees: ${sell_fees:.2f}")
                else:
                    log_event(db, "sell",
                              f"✅ Sold {live_shares} shares of {ticker} @ ${sell_price:.2f} "
                              f"(untracked position — no matching DB record)")
            else:
                trade = db_trades_by_ticker.get(ticker)
                if trade:
                    trade.status = "error"
                    db.commit()
                log_event(db, "sell",
                          f"❌ Sell failed for {ticker}: {result.get('error')}", "ERROR")

        _reconcile_stale_db_trades(db, live_tickers, log_event)

        client.disconnect()
        log_event(db, "sell", "Afternoon sell job complete.")

    except Exception as e:
        logger.exception(f"Afternoon sell job crashed: {e}")
        log_event(db, "system", f"Afternoon sell job crashed: {e}", "ERROR")
    finally:
        db.close()


def job_monitor_swing_trades():
    """
    Runs periodically during market hours.
    Checks all open positions:
    - If price drops >= 5% from buy_price (stop-loss): sell ALL, record final P&L.
    - If price rises >= 10% from buy_price (take-profit) AND status == 'open':
        sell HALF, bank the gain to realised_partial_pnl, set status = 'sold_half'.

    P&L rules:
    - Take-profit partial sell → writes to trade.realised_partial_pnl (NEVER to trade.pnl).
      trade.pnl is reserved for the final close.
    - Stop-loss full sell → final pnl = (sell_price - buy_price) * all_live_shares
                                       + trade.realised_partial_pnl
    """
    db = SessionLocal()
    try:
        trader_enabled = get_setting(db, "trader_enabled", "true")
        if trader_enabled.lower() != "true":
            return

        trading_mode = get_setting(db, "trading_mode", "paper")
        client = IBKRClient(trading_mode=trading_mode)
        if not client.connect():
            return

        client.start_keepalive(interval=30)
        live_positions = client.get_positions()
        live_tickers = {p["ticker"]: p for p in live_positions}

        open_trades = db.query(Trade).filter(Trade.status.in_(["open", "sold_half"])).all()

        for trade in open_trades:
            ticker = trade.ticker
            if ticker not in live_tickers:
                continue

            pos = live_tickers[ticker]
            current_price = pos["current_price"]
            live_shares = pos["shares"]
            buy_price = trade.buy_price

            if not buy_price:
                continue

            # ── Stop Loss (>= 5% drop from buy price) ──────────────────────────
            if current_price <= buy_price * 0.95:
                log_event(db, "sell",
                          f"📉 Stop Loss triggered for {ticker} "
                          f"(dropped >= 5%). Selling all {live_shares} shares.")
                result = client.place_sell_order(ticker, live_shares)
                if result["success"]:
                    sell_price = result["price"]
                    partial_already_realised = trade.realised_partial_pnl or 0.0

                    # Include any already-realised partial gain
                    remaining_pnl = (sell_price - buy_price) * live_shares
                    total_pnl = remaining_pnl + partial_already_realised

                    original_cost = buy_price * trade.shares if trade.shares else 1
                    pnl_pct = ((sell_price - buy_price) / buy_price * 100)

                    trade.sell_price = sell_price
                    trade.sell_time = datetime.now(timezone.utc)
                    trade.status = "closed"
                    trade.pnl = round(total_pnl, 2)
                    trade.pnl_pct = round(pnl_pct, 2)
                    sell_fees = result.get("fees", 0.0)
                    trade.fees = round((trade.fees or 0.0) + sell_fees, 4)
                    db.commit()

                    partial_note = (f" (incl. +${partial_already_realised:.2f} partial)"
                                    if partial_already_realised else "")
                    log_event(db, "sell",
                              f"📉 Stop-loss closed {ticker}: "
                              f"P&L ${total_pnl:+.2f}{partial_note}")

            # ── Take Profit (>= 10% rise, only on first trigger) ───────────────
            elif current_price >= buy_price * 1.10 and trade.status == "open":
                shares_to_sell = int(live_shares / 2)
                if shares_to_sell > 0:
                    log_event(db, "sell",
                              f"🚀 Take Profit triggered for {ticker} "
                              f"(rose >= 10%). Selling half: {shares_to_sell} shares.")
                    result = client.place_sell_order(ticker, shares_to_sell)
                    if result["success"]:
                        sell_price = result["price"]

                        # Bank this partial gain — never written to trade.pnl
                        partial_gain = (sell_price - buy_price) * shares_to_sell
                        sell_fees = result.get("fees", 0.0)

                        trade.status = "sold_half"
                        trade.realised_partial_pnl = round(
                            (trade.realised_partial_pnl or 0.0) + partial_gain, 2
                        )
                        trade.fees = round((trade.fees or 0.0) + sell_fees, 4)
                        db.commit()

                        log_event(db, "sell",
                                  f"🚀 Take-profit: sold {shares_to_sell} shares of {ticker} "
                                  f"@ ${sell_price:.2f} | Partial gain banked: "
                                  f"+${partial_gain:.2f} | Status: sold_half")

        client.disconnect()
    except Exception as e:
        logger.exception(f"Swing trade monitor crashed: {e}")
    finally:
        db.close()
