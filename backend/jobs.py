import logging
import threading
from datetime import datetime, timezone
from database import SessionLocal, get_setting
from models import Trade, SystemLog
from ai_analyst import run_daily_scan
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
# so the gateway never idles out.  Managed by start_persistent_keepalive() /
# stop_persistent_keepalive() which are called from api_server.py on startup /
# shutdown.
# ---------------------------------------------------------------------------
_persistent_client: IBKRClient | None = None
_persistent_client_lock = threading.Lock()


def start_persistent_keepalive(trading_mode: str = "paper") -> None:
    """Connect a long-lived IBKRClient and keep it alive in the background.

    This prevents the IB Gateway from dropping the connection during the quiet
    periods between the morning buy and afternoon sell jobs.
    """
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
    """Close any DB trades marked 'open' for tickers no longer held in IBKR.

    This fixes the discrepancy between the portfolio count and trade history count
    caused by trades that failed to sell (or were sold manually / outside the system).
    """
    open_trades = db.query(Trade).filter(Trade.status == "open").all()
    for trade in open_trades:
        if trade.ticker not in live_tickers:
            trade.status = "closed"
            trade.sell_time = datetime.now(timezone.utc)
            # sell_price/pnl left as None — we don't know the actual exit price
            db.commit()
            log_fn(db, "sell",
                   f"⚠️ Reconciled stale DB record for {trade.ticker} "
                   f"(marked closed — not found in live IBKR positions).")


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

def job_morning_scan_and_buy():
    """
    Runs at 09:20 ET weekdays:
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
            budget_pct = float(get_setting(db, "daily_budget_pct", "50" if paper_strategy == "cash" else "100"))
        except ValueError:
            budget_pct = 50.0
            
        try:
            max_positions_setting = int(get_setting(db, "max_positions", "3" if paper_strategy == "cash" else "5"))
        except ValueError:
            max_positions_setting = 3

        # Connect to IBKR to get account balance
        client = IBKRClient(trading_mode=trading_mode)
        connected = client.connect()
        if not connected:
            log_event(db, "ibkr", "Failed to connect to IB Gateway. Aborting trades.", "ERROR")
            return

        # Keep the connection alive while we iterate through buy orders
        client.start_keepalive(interval=30)

        # Get available cash and net liquidation
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

        tickers_str = ", ".join(r["ticker"] for r in recommendations)
        log_event(db, "scan", f"AI recommended {len(recommendations)} stock(s): {tickers_str}")

        # Step 2: Cap to max_positions stocks
        picks = recommendations[:max_positions]
        budget_per_trade = daily_budget / len(picks)

        log_event(db, "system",
              f"Net Liq: ${net_liq:,.2f} | Available cash: ${available_cash:,.2f} | "
              f"Today's budget: ${daily_budget:,.2f} | "
              f"Per trade: ${budget_per_trade:,.2f}")

        # Step 4: Place buy orders
        for rec in picks:
            ticker = rec["ticker"]
            reason = rec.get("reason", "")
            confidence = rec.get("confidence", 0)

            log_event(db, "buy",
                      f"Placing BUY order for {ticker} "
                      f"(confidence={confidence:.0%}): {reason}")

            result = client.place_buy_order(ticker, budget_per_trade)

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
    Sells ALL open positions held in the IBKR account — not just the ones
    bought by this morning's job.  Any position found live in the broker
    account will be sold, regardless of whether it exists in the local DB.

    After selling, any DB trades still marked 'open' for tickers that are no
    longer in IBKR are reconciled (marked closed) to keep the trade history
    count consistent with the portfolio count.
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

        # Keep the connection alive while we iterate through sell orders
        client.start_keepalive(interval=30)

        # Fetch live positions directly from IBKR — this captures EVERYTHING
        # in the account, including positions not bought by today's morning job.
        # get_positions() now waits up to 8 s for the portfolio snapshot so we
        # are guaranteed to see all holdings after a fresh connect.
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

        # Build a lookup of DB open trades by ticker for P&L tracking
        open_trades = db.query(Trade).filter(Trade.status == "open").all()
        db_trades_by_ticker = {t.ticker: t for t in open_trades}

        sold_tickers: set[str] = set()

        for position in live_positions:
            ticker = position["ticker"]
            shares = position["shares"]

            log_event(db, "sell",
                      f"Placing SELL order for {shares} shares of {ticker}...")
            result = client.place_sell_order(ticker, shares)

            if result["success"]:
                sell_price = result["price"]
                sold_tickers.add(ticker)

                # Update the DB trade record if one exists
                trade = db_trades_by_ticker.get(ticker)
                if trade:
                    pnl = (sell_price - trade.buy_price) * trade.shares
                    pnl_pct = ((sell_price - trade.buy_price) / trade.buy_price * 100) if trade.buy_price else 0

                    trade.sell_price = sell_price
                    trade.sell_time = datetime.now(timezone.utc)
                    trade.status = "closed"
                    trade.pnl = round(pnl, 2)
                    trade.pnl_pct = round(pnl_pct, 2)
                    
                    sell_fees = result.get("fees", 0.0)
                    trade.fees = round((trade.fees or 0.0) + sell_fees, 4)
                    db.commit()

                    emoji = "🟢" if pnl >= 0 else "🔴"
                    log_event(db, "sell",
                              f"{emoji} Sold {trade.shares} shares of {ticker} "
                              f"@ ${sell_price:.2f} | P&L: ${pnl:+.2f} ({pnl_pct:+.2f}%) | Fees: ${sell_fees:.2f}")
                else:
                    # Position existed in IBKR but not in our DB (e.g. held overnight,
                    # bought manually, or carried over from a previous session).
                    log_event(db, "sell",
                              f"✅ Sold {shares} shares of {ticker} @ ${sell_price:.2f} "
                              f"(untracked position — no matching DB record)")
            else:
                # Mark any matching DB trade as errored
                trade = db_trades_by_ticker.get(ticker)
                if trade:
                    trade.status = "error"
                    db.commit()
                log_event(db, "sell",
                          f"❌ Sell failed for {ticker}: {result.get('error')}", "ERROR")

        # Reconcile any DB open records for tickers that weren't in IBKR at all —
        # these are "ghost" records from previous sessions that were never closed.
        _reconcile_stale_db_trades(db, live_tickers, log_event)

        client.disconnect()
        log_event(db, "sell", "Afternoon sell job complete.")

    except Exception as e:
        logger.exception(f"Afternoon sell job crashed: {e}")
        log_event(db, "system", f"Afternoon sell job crashed: {e}", "ERROR")
    finally:
        db.close()
