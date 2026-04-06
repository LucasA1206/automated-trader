import logging
from datetime import datetime, timezone
from database import SessionLocal, get_setting
from models import Trade, SystemLog
from ai_analyst import run_daily_scan
from trader import IBKRClient

logger = logging.getLogger(__name__)


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


def job_morning_scan_and_buy():
    """
    Runs at 09:20 ET weekdays:
    1. Checks if scan is enabled
    2. Runs AI stock scan
    3. Buys top picks using configured budget %
    """
    db = SessionLocal()
    try:
        scan_enabled = get_setting(db, "scan_enabled", "true")
        if scan_enabled.lower() != "true":
            log_event(db, "system", "Auto-scan is disabled. Skipping morning job.")
            return

        trading_mode = get_setting(db, "trading_mode", "paper")
        daily_budget_pct = float(get_setting(db, "daily_budget_pct", "100")) / 100
        max_positions = int(get_setting(db, "max_positions", "5"))

        log_event(db, "scan", f"Starting morning scan. Mode: {trading_mode}, "
                              f"Budget: {daily_budget_pct*100:.0f}%")

        # Step 1: AI Scan
        recommendations = run_daily_scan()
        if not recommendations:
            log_event(db, "scan", "No stocks recommended by AI today. No trades placed.")
            return

        tickers_str = ", ".join(r["ticker"] for r in recommendations)
        log_event(db, "scan", f"AI recommended {len(recommendations)} stock(s): {tickers_str}")

        # Step 2: Connect to IBKR
        client = IBKRClient(trading_mode=trading_mode)
        connected = client.connect()
        if not connected:
            log_event(db, "ibkr", "Failed to connect to IB Gateway. Aborting trades.", "ERROR")
            return

        # Step 3: Get available cash
        account = client.get_account_summary()
        available_cash = account.get("AvailableFunds", 0)
        if available_cash <= 0:
            log_event(db, "ibkr", "No available funds. Aborting.", "ERROR")
            client.disconnect()
            return

        daily_budget = available_cash * daily_budget_pct
        # Cap to max_positions stocks
        picks = recommendations[:max_positions]
        budget_per_trade = daily_budget / len(picks)

        log_event(db, "system",
                  f"Available cash: ${available_cash:,.2f} | "
                  f"Daily budget: ${daily_budget:,.2f} | "
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
    Runs at 15:50 ET weekdays:
    Sells ALL open positions held in the IBKR account — not just the ones
    bought by this morning's job.  Any position found live in the broker
    account will be sold, regardless of whether it exists in the local DB.
    """
    db = SessionLocal()
    try:
        trading_mode = get_setting(db, "trading_mode", "paper")
        log_event(db, "sell", "Starting afternoon sell-all job.")

        client = IBKRClient(trading_mode=trading_mode)
        connected = client.connect()
        if not connected:
            log_event(db, "ibkr",
                      "Failed to connect to IB Gateway for sell job.", "ERROR")
            return

        # Fetch live positions directly from IBKR — this captures everything
        # in the account, including positions not bought by today's morning job.
        live_positions = client.get_positions()
        if not live_positions:
            log_event(db, "sell", "No live positions found in IBKR account. Nothing to sell.")
            client.disconnect()
            return

        log_event(db, "sell",
                  f"Found {len(live_positions)} live position(s) in IBKR: "
                  f"{', '.join(p['ticker'] for p in live_positions)}")

        # Build a lookup of DB open trades by ticker for P&L tracking
        open_trades = db.query(Trade).filter(Trade.status == "open").all()
        db_trades_by_ticker = {t.ticker: t for t in open_trades}

        for position in live_positions:
            ticker = position["ticker"]
            shares = position["shares"]

            log_event(db, "sell",
                      f"Placing SELL order for {shares} shares of {ticker}...")
            result = client.place_sell_order(ticker, shares)

            if result["success"]:
                sell_price = result["price"]

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
                    db.commit()

                    emoji = "🟢" if pnl >= 0 else "🔴"
                    log_event(db, "sell",
                              f"{emoji} Sold {trade.shares} shares of {ticker} "
                              f"@ ${sell_price:.2f} | P&L: ${pnl:+.2f} ({pnl_pct:+.2f}%)")
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

        client.disconnect()
        log_event(db, "sell", "Afternoon sell job complete.")

    except Exception as e:
        logger.exception(f"Afternoon sell job crashed: {e}")
        log_event(db, "system", f"Afternoon sell job crashed: {e}", "ERROR")
    finally:
        db.close()
