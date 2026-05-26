import logging
import threading
import time
from datetime import datetime, timezone, timedelta
from database import SessionLocal, get_setting
from models import Trade, SystemLog, AIPick
from ai_analyst import run_daily_scan, verify_ticker_momentum
from trader import IBKRClient

import pytz

# Minimum number of stocks to buy each week.
# If AI returns fewer picks, we fill the gap with the top screener candidates.
MIN_WEEKLY_BUYS = 3

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Market-hours helpers (NYSE / ET)
# ---------------------------------------------------------------------------
_ET = pytz.timezone("America/New_York")
_MARKET_OPEN_HOUR = 9
_MARKET_OPEN_MINUTE = 30
_MARKET_CLOSE_HOUR = 16  # 4 PM ET


def is_market_open() -> bool:
    """Return True if NYSE is currently open (Mon–Fri, 09:30–16:00 ET)."""
    now_et = datetime.now(_ET)
    if now_et.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    open_time = now_et.replace(hour=_MARKET_OPEN_HOUR, minute=_MARKET_OPEN_MINUTE, second=0, microsecond=0)
    close_time = now_et.replace(hour=_MARKET_CLOSE_HOUR, minute=0, second=0, microsecond=0)
    return open_time <= now_et < close_time


def seconds_until_market_open() -> float:
    """
    Return the number of seconds until the next NYSE open (09:30 ET Mon–Fri).
    Returns 0 if the market is currently open.
    """
    if is_market_open():
        return 0
    now_et = datetime.now(_ET)
    # Find the next market-open datetime
    candidate = now_et.replace(hour=_MARKET_OPEN_HOUR, minute=_MARKET_OPEN_MINUTE, second=0, microsecond=0)
    if candidate <= now_et:
        # Already past today's open — move to the next calendar day
        candidate += timedelta(days=1)
    # Skip weekends
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    delta = (candidate - now_et).total_seconds()
    return max(delta, 0)


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

# ---------------------------------------------------------------------------
# Internal helper — reusable scan phase
# ---------------------------------------------------------------------------

def _run_scan_phase(db, log_prefix: str = "morning") -> tuple[list[dict], list[float], dict] | None:
    """
    Runs the AI scan + screener fallback and computes per-pick budgets.
    Returns (picks, budgets, meta) where meta contains mode/strategy info,
    or None if the scan should be aborted (disabled, no funds, no picks).

    Does NOT connect to IBKR itself — the caller is responsible for the
    client lifecycle when they are ready to place orders.
    """
    trader_enabled = get_setting(db, "trader_enabled", "true")
    if trader_enabled.lower() != "true":
        log_event(db, "system", "Trader is globally disabled. Skipping scan.")
        return None

    scan_enabled = get_setting(db, "scan_enabled", "true")
    if scan_enabled.lower() != "true":
        log_event(db, "system", "Auto-scan is disabled. Skipping scan.")
        return None

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

    # Connect briefly to IBKR only to check available funds
    client = IBKRClient(trading_mode=trading_mode)
    connected = client.connect()
    if not connected:
        log_event(db, "ibkr", "Failed to connect to IB Gateway. Aborting scan.", "ERROR")
        return None

    client.start_keepalive(interval=30)
    account = client.get_account_summary()
    available_cash = account.get("AvailableFunds", 0)
    net_liq = account.get("NetLiquidation", 0)
    client.disconnect()

    if available_cash <= 0:
        log_event(db, "ibkr", f"No available funds (${available_cash:.2f}). Aborting.", "ERROR")
        return None

    daily_budget, max_positions, strategy_label = _build_strategy_plan(
        trading_mode, paper_strategy, available_cash, net_liq, budget_pct, max_positions_setting
    )

    log_event(db, "scan", f"Starting {log_prefix} scan. Mode: {trading_mode}, "
                          f"Account: {account_type}, Strategy: {strategy_label}, "
                          f"Budget: ${daily_budget:,.2f}")

    # AI Scan — returns (ai_picks, screener_fallback_candidates)
    recommendations, screened_candidates = run_daily_scan()

    # Sort AI picks by confidence (highest first)
    recommendations.sort(key=lambda r: r.get("confidence", 0), reverse=True)

    if recommendations:
        tickers_str = ", ".join(
            f"{r['ticker']}({r.get('confidence', 0):.0%})" for r in recommendations
        )
        log_event(db, "scan", f"AI recommended {len(recommendations)} stock(s): {tickers_str}")
    else:
        log_event(db, "scan",
                  "⚠️ AI returned no recommendations. Will use top screener candidates "
                  f"to guarantee {MIN_WEEKLY_BUYS} buy(s).")

    # Persist all AI picks to DB for the UI to display
    today_date = datetime.now(timezone.utc).date()
    if recommendations:
        _persist_ai_picks(db, recommendations, today_date)

    # ── Guarantee minimum buys ────────────────────────────────────────────
    pick_limit = min(max_positions, len(recommendations))
    picks = list(recommendations[:pick_limit])

    ai_ticker_set = {r["ticker"] for r in picks}
    fallback_used: list[dict] = []
    if len(picks) < MIN_WEEKLY_BUYS and screened_candidates:
        needed = MIN_WEEKLY_BUYS - len(picks)
        for candidate in screened_candidates:
            if len(fallback_used) >= needed:
                break
            if candidate["ticker"] not in ai_ticker_set:
                fallback_used.append(candidate)
                ai_ticker_set.add(candidate["ticker"])

        if fallback_used:
            fallback_str = ", ".join(c["ticker"] for c in fallback_used)
            log_event(db, "scan",
                      f"📊 Screener fallback: adding {len(fallback_used)} top-scored "
                      f"candidate(s) to reach minimum {MIN_WEEKLY_BUYS} buys: {fallback_str}")
            picks.extend(fallback_used)

    if not picks:
        log_event(db, "scan",
                  "❌ No picks from AI or screener. Market data may be unavailable. "
                  "No trades will be placed.")
        return None

    # Distribute budget according to position_size_pct if available, otherwise split evenly
    total_pct = sum(r.get("position_size_pct", 0) for r in picks)
    budgets: list[float] = []
    if total_pct > 0:
        for r in picks:
            weight = r.get("position_size_pct", 0) / total_pct
            budgets.append(daily_budget * weight)
    else:
        budgets = [daily_budget / len(picks)] * len(picks)

    meta = {
        "trading_mode": trading_mode,
        "net_liq": net_liq,
        "available_cash": available_cash,
        "daily_budget": daily_budget,
    }

    log_event(db, "system",
              f"Net Liq: ${net_liq:,.2f} | Available cash: ${available_cash:,.2f} | "
              f"Today's budget: ${daily_budget:,.2f} | "
              f"Buying {len(picks)} stock(s)")

    return picks, budgets, meta


def _place_buy_orders(db, client: IBKRClient, picks: list[dict], budgets: list[float], trading_mode: str) -> None:
    """Place buy orders for all picks. Expects an already-connected IBKRClient."""
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


# ---------------------------------------------------------------------------
# Deferred buy — waits for market open, then places queued orders
# ---------------------------------------------------------------------------

def job_deferred_buy(picks: list[dict], budgets: list[float], trading_mode: str) -> None:
    """
    Called in a background thread when a manual scan is triggered outside market hours.
    Sleeps until NYSE opens (09:30 ET, next weekday), then places the pre-computed
    buy orders. A fresh DB session and IBKR connection are opened at that point.
    """
    wait_secs = seconds_until_market_open()
    if wait_secs > 0:
        open_et = datetime.now(_ET) + timedelta(seconds=wait_secs)
        logger.info(
            "Deferred buy: market is closed. Sleeping %.0f s until %s ET.",
            wait_secs,
            open_et.strftime("%Y-%m-%d %H:%M"),
        )
        db_notify = SessionLocal()
        try:
            log_event(
                db_notify, "scan",
                f"⏳ Buy orders deferred — market is closed. "
                f"Will execute at {open_et.strftime('%Y-%m-%d %H:%M ET')} "
                f"for {len(picks)} stock(s): "
                + ", ".join(r['ticker'] for r in picks)
            )
        finally:
            db_notify.close()

        time.sleep(wait_secs)

    db = SessionLocal()
    try:
        # Re-check settings haven't been changed while we waited
        trader_enabled = get_setting(db, "trader_enabled", "true")
        if trader_enabled.lower() != "true":
            log_event(db, "system", "Trader disabled — cancelling deferred buy orders.")
            return

        log_event(db, "scan",
                  f"🔔 Market opened — placing {len(picks)} deferred buy order(s): "
                  + ", ".join(r['ticker'] for r in picks))

        client = IBKRClient(trading_mode=trading_mode)
        if not client.connect():
            log_event(db, "ibkr",
                      "Deferred buy: failed to connect to IB Gateway at market open.", "ERROR")
            return

        client.start_keepalive(interval=30)
        _place_buy_orders(db, client, picks, budgets, trading_mode)
        client.disconnect()
    except Exception as e:
        logger.exception("Deferred buy job crashed: %s", e)
        try:
            log_event(db, "system", f"Deferred buy crashed: {e}", "ERROR")
        except Exception:
            pass
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Public job entry points
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
        result = _run_scan_phase(db, log_prefix="morning")
        if result is None:
            return
        picks, budgets, meta = result
        trading_mode = meta["trading_mode"]

        client = IBKRClient(trading_mode=trading_mode)
        if not client.connect():
            log_event(db, "ibkr", "Failed to connect to IB Gateway. Aborting trades.", "ERROR")
            return

        client.start_keepalive(interval=30)
        _place_buy_orders(db, client, picks, budgets, trading_mode)
        client.disconnect()

    except Exception as e:
        logger.exception(f"Morning scan job crashed: {e}")
        log_event(db, "system", f"Morning scan crashed: {e}", "ERROR")
    finally:
        db.close()


def job_manual_scan_with_deferred_buy():
    """
    Entry point for manual scans triggered via the API.
    - Runs the AI scan immediately (any time of day).
    - If the market is currently open: places buy orders immediately.
    - If the market is closed: persists the AI picks and queues a background
      thread that will place orders when NYSE opens next.
    """
    db = SessionLocal()
    try:
        result = _run_scan_phase(db, log_prefix="manual")
        if result is None:
            return
        picks, budgets, meta = result
        trading_mode = meta["trading_mode"]

        if is_market_open():
            # Market is open — place orders right now
            log_event(db, "scan", "Market is open — placing buy orders immediately.")
            client = IBKRClient(trading_mode=trading_mode)
            if not client.connect():
                log_event(db, "ibkr", "Failed to connect to IB Gateway. Aborting trades.", "ERROR")
                return
            client.start_keepalive(interval=30)
            _place_buy_orders(db, client, picks, budgets, trading_mode)
            client.disconnect()
        else:
            # Market is closed — hand off to the deferred-buy thread
            t = threading.Thread(
                target=job_deferred_buy,
                args=(picks, budgets, trading_mode),
                daemon=True,
                name="deferred-buy",
            )
            t.start()

    except Exception as e:
        logger.exception(f"Manual scan job crashed: {e}")
        log_event(db, "system", f"Manual scan crashed: {e}", "ERROR")
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
