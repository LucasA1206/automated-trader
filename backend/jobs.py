import logging
import threading
import time
from datetime import datetime, timezone, timedelta
from database import SessionLocal, get_setting
from models import Trade, SystemLog, AIPick, AccountSnapshot
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


def _count_open_positions(db) -> int:
    """Return the number of currently open/sold_half/closing trades in the DB."""
    return db.query(Trade).filter(Trade.status.in_(["open", "sold_half", "closing"])).count()

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
    """Close any DB trades marked 'open'/'sold_half' for tickers no longer held in IBKR.

    Trades with status 'closing' are excluded — they have a sell order in-flight
    and will be finalised by the monitor that initiated the sell.
    """
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


def _sync_untracked_ibkr_positions(db, live_positions: list[dict], trading_mode: str, log_fn) -> None:
    """Ensure every live IBKR position has a matching open Trade in the DB.

    If a position exists in IBKR but not the DB (e.g. the buy order was marked
    'cancelled' due to a timeout but actually filled — a known IBKR paper bug),
    a synthetic Trade record is inserted so that the monitor and sell jobs can
    apply take-profit / stop-loss and properly record P&L.
    """
    open_tickers = set(
        t.ticker for t in db.query(Trade).filter(
            Trade.status.in_(["open", "sold_half", "closing"]),
            Trade.mode == trading_mode,
        ).all()
    )
    for pos in live_positions:
        ticker = pos["ticker"]
        if ticker in open_tickers:
            continue
        # This position is live in IBKR but has no DB record — create one.
        avg_cost = pos.get("avg_cost") or pos.get("current_price", 0)
        shares = pos.get("shares", 0)
        if shares == 0:
            continue
        ghost_trade = Trade(
            ticker=ticker,
            shares=shares,
            buy_price=avg_cost,
            buy_time=datetime.now(timezone.utc),
            status="open",
            mode=trading_mode,
            fees=0.0,
            realised_partial_pnl=0.0,
            ai_reason="[Auto-registered: position found in IBKR but missing from DB]",
        )
        db.add(ghost_trade)
        db.commit()
        log_fn(db, "system",
               f"⚠️ Untracked IBKR position detected: {ticker} "
               f"({shares} shares @ avg ${avg_cost:.2f}). "
               f"Created synthetic DB record so monitoring/take-profit can track it.",
               "WARNING")


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

def _run_scan_phase(db, log_prefix: str = "morning", num_picks: int | None = None) -> tuple[list[dict], list[float], dict] | None:
    """
    Runs the AI scan + screener fallback and computes per-pick budgets.
    Returns (picks, budgets, meta) where meta contains mode/strategy info,
    or None if the scan should be aborted (disabled, no funds, no picks).

    If num_picks is provided, limits the number of stocks to buy to that value
    (used for daily replacement scans where only some slots need filling).

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

    # If caller specifies how many picks to buy, use that as the cap
    effective_pick_limit = num_picks if num_picks is not None else max_positions

    log_event(db, "scan", f"Starting {log_prefix} scan. Mode: {trading_mode}, "
                          f"Account: {account_type}, Strategy: {strategy_label}, "
                          f"Budget: ${daily_budget:,.2f}, "
                          f"Slots to fill: {effective_pick_limit}")

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

    # ── Select picks up to the effective limit ────────────────────────────
    pick_limit = min(effective_pick_limit, len(recommendations))
    picks = list(recommendations[:pick_limit])

    # Exclude tickers we already hold open positions for
    open_tickers = set(
        t.ticker for t in db.query(Trade).filter(Trade.status.in_(["open", "sold_half"])).all()
    )
    picks = [p for p in picks if p["ticker"] not in open_tickers]

    ai_ticker_set = {r["ticker"] for r in picks} | open_tickers
    fallback_used: list[dict] = []
    min_buys = min(MIN_WEEKLY_BUYS, effective_pick_limit)
    if len(picks) < min_buys and screened_candidates:
        needed = min_buys - len(picks)
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
                      f"candidate(s) to reach minimum {min_buys} buys: {fallback_str}")
            picks.extend(fallback_used)

    # Final trim to effective limit (fallback may have added extras)
    picks = picks[:effective_pick_limit]

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
    """Place buy orders for all picks. Expects an already-connected IBKRClient.

    Budget redistribution: when a stock is rejected (momentum check failure or
    order error), its budget is redistributed equally across the remaining
    un-attempted picks so the full daily budget is always deployed.
    """
    # Work with a mutable copy so we can adjust future budgets in-place
    budgets = list(budgets)
    remaining_budget = 0.0  # Accumulates budget from rejected/failed stocks

    for i, rec in enumerate(picks):
        ticker = rec["ticker"]
        reason = rec.get("reason", "")
        confidence = rec.get("confidence", 0)
        pos_size = rec.get("position_size_pct", 0)

        budget_for_trade = budgets[i]

        # Redistribute any leftover budget from previously rejected stocks
        if remaining_budget > 0:
            remaining_picks_count = len(picks) - i  # this pick + future picks
            extra_per_pick = remaining_budget / remaining_picks_count
            budget_for_trade += extra_per_pick
            # Also adjust future budgets so the redistribution cascades correctly
            for j in range(i + 1, len(picks)):
                budgets[j] += extra_per_pick
            remaining_budget = 0.0

        log_event(db, "buy",
                  f"Placing BUY order for {ticker} "
                  f"(confidence={confidence:.0%}, size={pos_size:.0f}%, "
                  f"budget=${budget_for_trade:,.2f}): {reason}")

        # Pre-buy momentum gate
        if not verify_ticker_momentum(ticker):
            log_event(db, "buy",
                      f"⚠️ Skipped {ticker} — failed pre-buy momentum check "
                      f"(down >3% over recent sessions despite AI recommendation). "
                      f"Redistributing ${budget_for_trade:,.2f} to remaining picks.")
            remaining_budget += budget_for_trade
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
                      f"❌ Buy failed for {ticker}: {result.get('error')}. "
                      f"Redistributing ${budget_for_trade:,.2f} to remaining picks.", "ERROR")
            remaining_budget += budget_for_trade

    if remaining_budget > 0:
        log_event(db, "buy",
                  f"⚠️ ${remaining_budget:,.2f} of budget could not be deployed "
                  f"(all remaining picks were rejected or failed).")


# ---------------------------------------------------------------------------
# Deferred buy — waits for market open, then places queued orders
# ---------------------------------------------------------------------------

def job_deferred_sell_single(ticker: str, trading_mode: str) -> None:
    """
    Called in a background thread when a manual sell is triggered outside market hours.
    Sleeps until NYSE opens (09:30 ET, next weekday), then sells all shares of the
    given ticker. A fresh DB session and IBKR connection are opened at that point.
    """
    wait_secs = seconds_until_market_open()
    if wait_secs > 0:
        open_et = datetime.now(_ET) + timedelta(seconds=wait_secs)
        logger.info(
            "Deferred sell (%s): market is closed. Sleeping %.0f s until %s ET.",
            ticker, wait_secs, open_et.strftime("%Y-%m-%d %H:%M"),
        )
        db_notify = SessionLocal()
        try:
            log_event(
                db_notify, "sell",
                f"⏳ Sell order for {ticker} deferred — market is closed. "
                f"Will execute at {open_et.strftime('%Y-%m-%d %H:%M ET')}."
            )
        finally:
            db_notify.close()

        time.sleep(wait_secs)

    db = SessionLocal()
    try:
        # Re-check settings haven't been changed while we waited
        trader_enabled = get_setting(db, "trader_enabled", "true")
        if trader_enabled.lower() != "true":
            log_event(db, "system", f"Trader disabled — cancelling deferred sell for {ticker}.")
            return

        log_event(db, "sell",
                  f"🔔 Market opened — placing deferred sell order for {ticker}.")

        client = IBKRClient(trading_mode=trading_mode)
        if not client.connect():
            log_event(db, "ibkr",
                      f"Deferred sell ({ticker}): failed to connect to IB Gateway at market open.", "ERROR")
            return

        client.start_keepalive(interval=30)

        # Find the live position for this ticker
        live_positions = client.get_positions()
        target_pos = None
        for pos in live_positions:
            if pos["ticker"] == ticker:
                target_pos = pos
                break

        if not target_pos or target_pos["shares"] == 0:
            log_event(db, "sell",
                      f"⚠️ Deferred sell ({ticker}): no live position found in IBKR. "
                      f"The position may have already been sold.", "WARNING")
            client.disconnect()
            return

        live_shares = target_pos["shares"]
        # place_sell_order auto-routes to buy-to-cover if live_shares < 0 (short position)
        result = client.place_sell_order(ticker, live_shares)

        if result.get("success"):
            sell_price = result["price"]
            sell_fees = result.get("fees", 0.0)

            trade = (
                db.query(Trade)
                .filter(
                    Trade.ticker == ticker,
                    Trade.status.in_(["open", "sold_half"]),
                    Trade.mode == trading_mode,
                )
                .order_by(Trade.buy_time.desc())
                .first()
            )
            if trade:
                buy_price = trade.buy_price or 0.0
                partial_already_realised = trade.realised_partial_pnl or 0.0
                remaining_pnl = (sell_price - buy_price) * live_shares
                total_pnl = remaining_pnl + partial_already_realised
                original_cost = buy_price * trade.shares if trade.shares else 1
                pnl_pct = (total_pnl / original_cost * 100) if original_cost else 0.0

                trade.sell_price = sell_price
                trade.sell_time = datetime.now(timezone.utc)
                trade.status = "closed"
                trade.pnl = round(total_pnl, 2)
                trade.pnl_pct = round(pnl_pct, 2)
                trade.fees = round((trade.fees or 0.0) + sell_fees, 4)
                db.commit()

            emoji = "🟢" if (trade and (trade.pnl or 0) >= 0) else "🔴"
            log_event(db, "sell",
                      f"{emoji} Deferred sell filled: sold {live_shares} shares of {ticker} "
                      f"@ ${sell_price:.2f} | Fees: ${sell_fees:.2f}")
        else:
            log_event(db, "sell",
                      f"❌ Deferred sell failed for {ticker}: {result.get('error')}", "ERROR")

        client.disconnect()
    except Exception as e:
        logger.exception("Deferred sell job crashed (%s): %s", ticker, e)
        try:
            log_event(db, "system", f"Deferred sell crashed ({ticker}): {e}", "ERROR")
        except Exception:
            pass
    finally:
        db.close()


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
    Runs at 09:30 ET every weekday (Mon–Fri).

    Checks how many position slots are available (max_positions minus current
    open/sold_half trades) and scans for that many replacement stocks.

    If the portfolio is already full, the scan is skipped entirely.
    This means:
    - Monday: typically a full scan for max_positions stocks (portfolio is empty after Friday sell)
    - Tue–Fri: only scans if stocks were sold via take-profit or stop-loss the previous day
    """
    db = SessionLocal()
    try:
        try:
            max_positions = int(get_setting(db, "max_positions", "5"))
        except ValueError:
            max_positions = 5

        current_open = _count_open_positions(db)
        slots_to_fill = max_positions - current_open

        if slots_to_fill <= 0:
            log_event(db, "scan",
                      f"Portfolio is full ({current_open}/{max_positions} positions open). "
                      f"Skipping morning scan.")
            return

        log_event(db, "scan",
                  f"📊 {current_open}/{max_positions} positions open — "
                  f"scanning for {slots_to_fill} replacement stock(s).")

        result = _run_scan_phase(db, log_prefix="morning", num_picks=slots_to_fill)
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

        # Sync any positions held in IBKR that have no DB record before selling.
        _sync_untracked_ibkr_positions(db, live_positions, trading_mode, log_event)

        # Build lookup of DB open trades by ticker
        open_trades = db.query(Trade).filter(Trade.status.in_(["open", "sold_half"])).all()
        db_trades_by_ticker = {t.ticker: t for t in open_trades}

        sold_tickers: set[str] = set()

        for position in live_positions:
            ticker = position["ticker"]
            live_shares = position["shares"]  # may be negative for short positions

            is_short = live_shares < 0
            order_desc = f"BUY-TO-COVER {abs(live_shares)}" if is_short else f"SELL {live_shares}"

            if live_shares == 0:
                log_event(db, "sell",
                          f"⚠️ Skipping {ticker} in afternoon sell — zero share count.")
                continue

            log_event(db, "sell",
                      f"Placing {order_desc} order for {ticker}...")
            # place_sell_order transparently handles short positions (negative shares)
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


# _trigger_rescan_if_all_closed() has been removed.
# Instead of triggering an immediate rescan when positions close, the system
# now waits until the next morning scan (09:30 ET) which checks how many
# position slots need filling and scans for that many replacement stocks.


def job_monitor_swing_trades():
    """
    Runs periodically during market hours.
    Checks all open positions:
    - If price drops >= 5% from buy_price (stop-loss): sell ALL, record final P&L.
    - If price rises >= 10% from buy_price (take-profit): sell ALL shares, record final P&L.

    After any full exit, the system logs how many slots are now open.
    Replacement stocks will be bought at the next morning scan (09:30 ET)
    rather than triggering an immediate rescan.

    P&L rules:
    - Take-profit full sell → final pnl = (sell_price - buy_price) * all_live_shares
    - Stop-loss full sell   → final pnl = (sell_price - buy_price) * all_live_shares
                                         + trade.realised_partial_pnl (if any banked)
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

        # Sync any positions held in IBKR that have no DB record (e.g. buy order
        # was reported as cancelled but actually filled — common IBKR paper bug).
        _sync_untracked_ibkr_positions(db, live_positions, trading_mode, log_event)

        open_trades = db.query(Trade).filter(Trade.status.in_(["open", "sold_half"])).all()

        any_fully_closed = False

        # ── Fetch fresh delayed tick prices for all live tickers ───────────────
        # get_positions() uses IBKR's portfolio snapshot, where marketPrice is
        # frequently NaN/0 (especially at market open or after a stale cache
        # flush). safe_float() silently converts NaN → avg_cost, so
        # current_price ends up equal to buy_price and SL/TP never triggers.
        # We batch-request delayed tick data (type 3) for every ticker now so
        # all threshold comparisons use a real, current market price.
        from ib_insync import Stock as _Stock
        fresh_prices: dict[str, float] = {}
        tick_reqs: dict[str, object] = {}
        try:
            client.ib.reqMarketDataType(3)  # delayed — no live subscription needed
            for _ticker in live_tickers:
                try:
                    _contract = _Stock(_ticker, "SMART", "USD")
                    client.ib.qualifyContracts(_contract)
                    tick_reqs[_ticker] = client.ib.reqMktData(_contract, "", False, False)
                except Exception as _exc:
                    logger.warning("Monitor: could not subscribe to tick data for %s: %s", _ticker, _exc)

            # Wait up to 8 s for all prices to arrive
            for _ in range(16):   # 16 × 0.5 s = 8 s
                client.ib.sleep(0.5)
                if all(
                    safe_float(t.last) > 0 or safe_float(t.close) > 0
                    for t in tick_reqs.values()
                ):
                    break

            for _ticker, _mkt in tick_reqs.items():
                _tick_price = safe_float(_mkt.last) or safe_float(_mkt.close)
                _portfolio_price = live_tickers[_ticker]["current_price"]
                if _tick_price > 0:
                    fresh_prices[_ticker] = _tick_price
                    if _portfolio_price > 0 and abs(_tick_price - _portfolio_price) / _portfolio_price > 0.01:
                        logger.info(
                            "Monitor: %s tick price $%.4f differs from portfolio snapshot $%.4f — "
                            "using fresh tick price for SL/TP evaluation.",
                            _ticker, _tick_price, _portfolio_price,
                        )
                else:
                    # Tick unavailable — fall back to portfolio snapshot
                    fresh_prices[_ticker] = _portfolio_price
                    logger.warning(
                        "Monitor: no fresh tick price for %s (last=%.4f, close=%.4f). "
                        "Falling back to portfolio snapshot $%.4f.",
                        _ticker, safe_float(_mkt.last), safe_float(_mkt.close), _portfolio_price,
                    )

            # Cancel all subscriptions
            for _ticker in list(tick_reqs.keys()):
                try:
                    _contract = _Stock(_ticker, "SMART", "USD")
                    client.ib.cancelMktData(_contract)
                except Exception:
                    pass
        except Exception as _exc:
            logger.warning(
                "Monitor: fresh tick-price batch failed (%s). "
                "Falling back to portfolio snapshot prices for all tickers.", _exc,
            )
            fresh_prices = {_t: _p["current_price"] for _t, _p in live_tickers.items()}

        for trade in open_trades:
            ticker = trade.ticker
            if ticker not in live_tickers:
                continue

            pos = live_tickers[ticker]
            # Use fresh tick price; fall back to portfolio snapshot if unavailable
            current_price = fresh_prices.get(ticker, pos["current_price"])
            live_shares = pos["shares"]
            buy_price = trade.buy_price

            if not buy_price:
                continue

            # Guard: skip zero positions — selling zero is a no-op.
            if live_shares == 0:
                log_event(db, "sell",
                          f"⚠️ Skipping {ticker} — live shares is 0 (nothing to close).")
                continue

            # Guard: re-read the trade from the DB in case a concurrent
            # monitor run already closed it (stale portfolio data can linger
            # for several minutes after a sell fills).
            db.refresh(trade)
            if trade.status not in ("open", "sold_half"):
                logger.info(
                    "Monitor: skipping %s — status changed to '%s' "
                    "(likely closed by a concurrent run).",
                    ticker, trade.status,
                )
                continue

            pct_change = (current_price - buy_price) / buy_price * 100
            logger.info(
                "Monitor: %s — buy=$%.4f  current=$%.4f  change=%.2f%%",
                ticker, buy_price, current_price, pct_change,
            )

            # ── Stop Loss (>= 5% drop from buy price) ──────────────────────────
            if current_price <= buy_price * 0.95:
                # Mark as "closing" BEFORE placing the order so concurrent runs
                # see this and skip the trade (idempotent sell guard).
                previous_status = trade.status
                trade.status = "closing"
                db.commit()

                log_event(db, "sell",
                          f"📉 Stop Loss triggered for {ticker} "
                          f"(buy=${buy_price:.4f}, now=${current_price:.4f}, "
                          f"change={pct_change:.2f}%). Selling all {live_shares} shares.")
                result = client.place_sell_order(ticker, live_shares)
                if result["success"]:
                    sell_price = result["price"]
                    partial_already_realised = trade.realised_partial_pnl or 0.0

                    # Include any already-realised partial gain
                    remaining_pnl = (sell_price - buy_price) * live_shares
                    total_pnl = remaining_pnl + partial_already_realised

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
                    any_fully_closed = True
                else:
                    # Sell failed — revert to previous status so the next run retries
                    trade.status = previous_status
                    db.commit()
                    log_event(db, "sell",
                              f"❌ Stop-loss sell failed for {ticker}: "
                              f"{result.get('error')}. Will retry next cycle.", "ERROR")

            # ── Take Profit (>= 10% rise) — sell ALL shares and close ──────────
            elif current_price >= buy_price * 1.10 and trade.status == "open":
                # Mark as "closing" BEFORE placing the order (idempotent guard).
                trade.status = "closing"
                db.commit()

                log_event(db, "sell",
                          f"🚀 Take Profit triggered for {ticker} "
                          f"(buy=${buy_price:.4f}, now=${current_price:.4f}, "
                          f"change={pct_change:.2f}%). Selling ALL {live_shares} shares.")
                result = client.place_sell_order(ticker, live_shares)
                if result["success"]:
                    sell_price = result["price"]
                    sell_fees = result.get("fees", 0.0)

                    total_pnl = (sell_price - buy_price) * live_shares
                    pnl_pct = ((sell_price - buy_price) / buy_price * 100)

                    trade.sell_price = sell_price
                    trade.sell_time = datetime.now(timezone.utc)
                    trade.status = "closed"
                    trade.pnl = round(total_pnl, 2)
                    trade.pnl_pct = round(pnl_pct, 2)
                    trade.fees = round((trade.fees or 0.0) + sell_fees, 4)
                    db.commit()

                    log_event(db, "sell",
                              f"🚀 Take-profit: sold ALL {live_shares} shares of {ticker} "
                              f"@ ${sell_price:.2f} | P&L: +${total_pnl:.2f} "
                              f"({pnl_pct:+.2f}%) | Fees: ${sell_fees:.2f}")
                    any_fully_closed = True
                else:
                    # Sell failed — revert to "open" so the next run retries
                    trade.status = "open"
                    db.commit()
                    log_event(db, "sell",
                              f"❌ Take-profit sell failed for {ticker}: "
                              f"{result.get('error')}. Will retry next cycle.", "ERROR")

        client.disconnect()

        # Positions sold via take-profit or stop-loss will be replaced at the
        # next morning scan (09:30 ET). The morning job checks how many slots
        # are available and scans for that many replacement stocks.
        if any_fully_closed:
            remaining_open = _count_open_positions(db)
            try:
                max_pos = int(get_setting(db, "max_positions", "5"))
            except ValueError:
                max_pos = 5
            slots_available = max_pos - remaining_open
            log_event(db, "scan",
                      f"📋 {slots_available} position slot(s) now open "
                      f"({remaining_open}/{max_pos} held). "
                      f"Replacement stocks will be bought at next morning scan (09:30 ET).")

    except Exception as e:
        logger.exception(f"Swing trade monitor crashed: {e}")
    finally:
        db.close()


def job_snapshot_net_liq() -> None:
    """
    Runs at 15:45 ET Mon–Fri (15 minutes after the afternoon sell).

    Captures a daily end-of-day NetLiquidation snapshot in the account_snapshots
    table.  This data is used by /api/pnl-history to compute the P&L Over Time
    chart from actual account-value movements rather than DB trade P&L fields.

    If a snapshot for today already exists it is UPDATED (upsert) so re-runs
    (e.g. manual triggers) always reflect the latest value.
    """
    db = SessionLocal()
    try:
        trading_mode = get_setting(db, "trading_mode", "paper")

        client = IBKRClient(trading_mode=trading_mode)
        if not client.connect():
            log_event(db, "ibkr",
                      "Snapshot job: could not connect to IB Gateway — skipping today's snapshot.",
                      "WARNING")
            return

        client.start_keepalive(interval=30)
        account = client.get_account_summary()
        client.disconnect()

        net_liq_usd = account.get("NetLiquidation", 0)
        net_liq_aud = account.get("NetLiquidation_AUD", None)
        # fx_rate: USD→AUD (from IBKR account data)
        fx_rate = account.get("ExchangeRate_USD", None)

        if not net_liq_usd:
            log_event(db, "system",
                      "Snapshot job: NetLiquidation is 0 or missing — skipping snapshot.",
                      "WARNING")
            return

        today = datetime.now(timezone.utc).date()

        # Upsert: update today's record if it already exists
        existing = db.query(AccountSnapshot).filter(AccountSnapshot.date == today).first()
        if existing:
            existing.net_liq_usd = net_liq_usd
            existing.net_liq_aud = net_liq_aud
            existing.fx_rate = fx_rate
        else:
            db.add(AccountSnapshot(
                date=today,
                net_liq_usd=net_liq_usd,
                net_liq_aud=net_liq_aud,
                fx_rate=fx_rate,
            ))
        db.commit()

        log_event(db, "system",
                  f"📸 Daily snapshot saved: Net Liq = ${net_liq_usd:,.2f} USD"
                  + (f" / A${net_liq_aud:,.2f} AUD" if net_liq_aud else ""))

    except Exception as e:
        logger.exception("Snapshot job crashed: %s", e)
        try:
            log_event(db, "system", f"Snapshot job crashed: {e}", "ERROR")
        except Exception:
            pass
    finally:
        db.close()
