import os
import logging
import logging.config
import threading
import requests
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db, init_db, get_setting, set_setting, SessionLocal
from models import Trade, SystemLog, Setting, AIPick, AccountSnapshot, ScanResult, TradeJournalEntry
from scheduler import create_scheduler, get_next_job_times
from trader import IBKRClient
from auth import require_auth, validate_credentials, create_access_token
from jobs import start_persistent_keepalive, stop_persistent_keepalive, job_manual_scan

# ─── Logging ───────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

MARGIN_UPGRADE_THRESHOLD = 25_000.0

# ─── USD/AUD Exchange Rate Cache ───────────────────────────────────────────
_fx_lock = threading.Lock()
_fx_rate: float = 1.55          # sensible fallback (approx AUD/USD mid-2025)
_fx_fetched_at: datetime | None = None
_fx_stale: bool = True
_FX_CACHE_TTL = timedelta(hours=1)
_FX_API_URL = "https://api.frankfurter.app/latest?from=USD&to=AUD"


def _refresh_fx_rate() -> None:
    """
    Fetch the latest USD→AUD rate from Frankfurter (free, no API key).
    Updates the module-level cache in place. Thread-safe.
    Falls back gracefully — the last successful rate is kept if the fetch fails.
    """
    global _fx_rate, _fx_fetched_at, _fx_stale
    try:
        resp = requests.get(_FX_API_URL, timeout=8)
        resp.raise_for_status()
        data = resp.json()
        rate = float(data["rates"]["AUD"])
        with _fx_lock:
            _fx_rate = rate
            _fx_fetched_at = datetime.now(timezone.utc)
            _fx_stale = False
        logger.info(f"USD/AUD exchange rate updated: {rate:.4f}")
    except Exception as e:
        with _fx_lock:
            _fx_stale = True
        logger.warning(f"Failed to fetch USD/AUD rate: {e}. Using last cached value {_fx_rate:.4f}.")


def get_fx_rate() -> dict:
    """
    Return the current exchange rate info, refreshing if the cache is > 1 hour old.
    Returns { rate, fetched_at (ISO string or None), stale, age_minutes }.
    """
    global _fx_rate, _fx_fetched_at, _fx_stale

    with _fx_lock:
        needs_refresh = (
            _fx_fetched_at is None
            or (datetime.now(timezone.utc) - _fx_fetched_at) > _FX_CACHE_TTL
        )

    if needs_refresh:
        _refresh_fx_rate()

    with _fx_lock:
        rate = _fx_rate
        fetched_at = _fx_fetched_at
        stale = _fx_stale

    age_minutes: float | None = None
    if fetched_at:
        age_seconds = (datetime.now(timezone.utc) - fetched_at).total_seconds()
        age_minutes = round(age_seconds / 60, 1)

    return {
        "rate": round(rate, 4),
        "fetched_at": fetched_at.isoformat() if fetched_at else None,
        "stale": stale,
        "age_minutes": age_minutes,
    }


# ─── Scheduler (global) ───────────────────────────────────────────────────
scheduler = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global scheduler
    logger.info("🚀 Blitz Trader API starting up...")
    init_db()
    scheduler = create_scheduler()
    scheduler.start()
    logger.info("✅ Scheduler started.")

    # Warm up the exchange rate cache at startup
    import threading as _threading
    _threading.Thread(target=_refresh_fx_rate, daemon=True, name="fx-warmup").start()

    # Start a persistent IBKR connection that keeps the gateway alive between jobs.
    db = SessionLocal()
    trading_mode = get_setting(db, "trading_mode", "paper")
    db.close()
    import threading
    threading.Thread(
        target=start_persistent_keepalive,
        args=(trading_mode,),
        daemon=True,
        name="ibkr-startup-keepalive",
    ).start()

    yield

    stop_persistent_keepalive()
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
    logger.info("🛑 Blitz Trader API shut down.")


# ─── App ───────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Blitz Trader API",
    version="2.0.0",
    lifespan=lifespan,
)

# ── CORS ── Read ALLOWED_ORIGINS from env var for production security.
# Set ALLOWED_ORIGINS=https://your-frontend.vercel.app in Railway env vars.
# Falls back to wildcard "*" in dev/local when the env var is not set.
_raw_origins = os.getenv("ALLOWED_ORIGINS", "")
ALLOWED_ORIGINS: list[str] = (
    [o.strip() for o in _raw_origins.split(",") if o.strip()]
    if _raw_origins else ["*"]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Pydantic schemas ──────────────────────────────────────────────────────
class LoginRequest(BaseModel):
    username: str
    password: str


class SettingUpdate(BaseModel):
    value: str


class SettingsBulkUpdate(BaseModel):
    trading_mode: Optional[str] = None
    paper_strategy: Optional[str] = None
    daily_budget_pct: Optional[str] = None
    max_positions: Optional[str] = None
    scan_enabled: Optional[str] = None
    account_type: Optional[str] = None
    trader_enabled: Optional[str] = None


def _sync_strategy_settings(db: Session, account_type: str) -> None:
    """Keep derived strategy settings aligned with the selected strategy preset."""
    set_setting(db, "daily_budget_pct", "100")
    set_setting(db, "max_positions", "5")


def _normalize_account_type(value: str | None) -> str:
    if value in ("trading_cash", "investment_cash"):
        return value
    return "trading_cash"


def _normalize_paper_strategy(value: str | None, legacy_account_type: str | None = None) -> str:
    if value in ("cash", "margin"):
        return value
    if legacy_account_type == "margin":
        return "margin"
    return "cash"


def _build_margin_upgrade_alert(db: Session, trading_mode: str, account_type: str, net_liq: float) -> dict | None:
    """Return a one-time alert when a live cash account crosses $25k."""
    if trading_mode != "live" or account_type not in ("trading_cash", "investment_cash") or net_liq < MARGIN_UPGRADE_THRESHOLD:
        return None

    alerted = get_setting(db, "margin_upgrade_alerted", "false").lower() == "true"
    if alerted:
        return None

    set_setting(db, "margin_upgrade_alerted", "true")
    return {
        "type": "margin_upgrade",
        "threshold": MARGIN_UPGRADE_THRESHOLD,
        "message": (
            f"Net liquidation is now ${net_liq:,.2f}. "
            f"This IBKR account is cash-only, so the live bot stays on the Cash strategy. "
            f"Use Paper Mode to compare Cash vs Margin setups."
        ),
    }


# ─── Auth ─────────────────────────────────────────────────────────────────
@app.post("/api/auth/login")
def login(body: LoginRequest):
    """Validates IBKR credentials and returns a JWT access token."""
    if not validate_credentials(body.username, body.password):
        raise HTTPException(
            status_code=401,
            detail="Invalid username or password",
        )
    token = create_access_token(body.username)
    return {"access_token": token, "token_type": "bearer"}


# ─── Health (public — Railway health checks) ────────────────────────────────
@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "time": datetime.now(timezone.utc).isoformat(),
        "scheduler_running": scheduler.running if scheduler else False,
        "scheduled_jobs": get_next_job_times(scheduler) if scheduler else [],
    }


# ─── Exchange Rate ──────────────────────────────────────────────────────────
@app.get("/api/exchange-rate", dependencies=[Depends(require_auth)])
def exchange_rate():
    """
    Returns the current USD→AUD exchange rate.
    Fetches from Frankfurter API (free, no API key) and caches for up to 1 hour.
    If the API call fails, returns the last successful rate with stale=true.
    """
    return get_fx_rate()


# ─── Portfolio ─────────────────────────────────────────────────────────────
@app.get("/api/portfolio", dependencies=[Depends(require_auth)])
def get_portfolio(db: Session = Depends(get_db)):
    """Returns IBKR account summary + open positions + partial P&L data."""
    trading_mode = get_setting(db, "trading_mode", "paper")
    try:
        client = IBKRClient(trading_mode=trading_mode)
        connected = client.connect(retries=2, delay=3)
        if not connected:
            return {
                "connected": False,
                "mode": trading_mode,
                "positions": [],
                "account": {},
                "error": (
                    "Could not connect to IB Gateway. "
                    "If backend logs show 'error 2110', the IB Gateway container has lost "
                    "its upstream connection to IB servers — restart the ib-gateway service on Railway."
                ),
            }
        positions = client.get_positions()
        account = client.get_account_summary()
        raw_account_type = get_setting(db, "account_type", "trading_cash")
        account_type = _normalize_account_type(raw_account_type)
        paper_strategy = _normalize_paper_strategy(get_setting(db, "paper_strategy", None), raw_account_type)
        net_liq = account.get("NetLiquidation", 0)
        strategy_alert = _build_margin_upgrade_alert(db, trading_mode, account_type, net_liq)
        client.disconnect()

        # Enrich positions with realised_partial_pnl from the DB
        open_trades = db.query(Trade).filter(
            Trade.status.in_(["open", "sold_half"]),
            Trade.mode == trading_mode
        ).all()
        partial_by_ticker = {t.ticker: t.realised_partial_pnl or 0.0 for t in open_trades}
        status_by_ticker  = {t.ticker: t.status for t in open_trades}

        for pos in positions:
            ticker = pos["ticker"]
            pos["realised_partial_pnl"] = round(partial_by_ticker.get(ticker, 0.0), 2)
            pos["trade_status"] = status_by_ticker.get(ticker, "open")

        return {
            "connected": True,
            "mode": trading_mode,
            "account_type": account_type,
            "paper_strategy": paper_strategy,
            "positions": positions,
            "account": account,
            "strategy_alert": strategy_alert,
        }
    except Exception as e:
        logger.error(f"Portfolio fetch error: {e}")
        return {"connected": False, "mode": trading_mode, "positions": [], "account": {}, "error": str(e)}


# ─── Trades ────────────────────────────────────────────────────────────────
@app.get("/api/trades", dependencies=[Depends(require_auth)])
def get_trades(
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """Returns trade history, optionally filtered by status (open/closed/sold_half/error)."""
    trading_mode = get_setting(db, "trading_mode", "paper")
    query = db.query(Trade).filter(Trade.mode == trading_mode).order_by(Trade.buy_time.desc())
    if status:
        query = query.filter(Trade.status == status)
    total = query.count()
    trades = query.offset(offset).limit(limit).all()

    return {
        "total": total,
        "trades": [
            {
                "id": t.id,
                "ticker": t.ticker,
                "shares": t.shares,
                "buy_price": t.buy_price,
                "sell_price": t.sell_price,
                "buy_time": t.buy_time.isoformat() if t.buy_time else None,
                "sell_time": t.sell_time.isoformat() if t.sell_time else None,
                "status": t.status,
                "pnl": t.pnl,
                "pnl_pct": t.pnl_pct,
                "realised_partial_pnl": t.realised_partial_pnl or 0.0,
                "fees": t.fees or 0.0,
                "ai_reason": t.ai_reason,
            }
            for t in trades
        ],
    }


# ─── AI Picks ──────────────────────────────────────────────────────────────
@app.get("/api/ai-picks", dependencies=[Depends(require_auth)])
def get_ai_picks(db: Session = Depends(get_db)):
    """
    Returns AI stock picks grouped by scan date, most recent first (up to 30 days).
    Each day entry contains the scan_date, total picks for that day, and the picks list.
    """
    from sqlalchemy import func

    # Get up to 30 distinct scan dates, most recent first
    scan_dates = (
        db.query(AIPick.scan_date)
        .distinct()
        .order_by(AIPick.scan_date.desc())
        .limit(30)
        .all()
    )

    if not scan_dates:
        return {"days": [], "total_days": 0}

    days = []
    for (scan_date,) in scan_dates:
        picks = (
            db.query(AIPick)
            .filter(AIPick.scan_date == scan_date)
            .order_by(AIPick.rank.asc())
            .all()
        )
        days.append({
            "scan_date": scan_date.isoformat() if scan_date else None,
            "total": len(picks),
            "picks": [
                {
                    "rank": p.rank,
                    "ticker": p.ticker,
                    "reason": p.reason,
                    "confidence": p.confidence,
                    "position_size_pct": p.position_size_pct,
                    "created_at": p.created_at.isoformat() if p.created_at else None,
                }
                for p in picks
            ],
        })

    return {"days": days, "total_days": len(days)}


# ─── Strategy: Scan History ────────────────────────────────────────────────
@app.get("/api/scan-history", dependencies=[Depends(require_auth)])
def get_scan_history(limit: int = 10, db: Session = Depends(get_db)):
    """
    Returns the most recent daily scan results including regime, candidate counts,
    and the action taken. Used by the frontend to display scan outcomes.
    """
    import json as _json
    results = (
        db.query(ScanResult)
        .order_by(ScanResult.scan_date.desc())
        .limit(limit)
        .all()
    )
    return {
        "scans": [
            {
                "scan_date": r.scan_date.isoformat() if r.scan_date else None,
                "regime_status": r.regime_status,
                "regime_details": r.regime_details,
                "candidates_count": r.candidates_count,
                "high_conviction_count": r.high_conviction_count,
                "marginal_count": r.marginal_count,
                "action_taken": r.action_taken,
                "candidates": _json.loads(r.candidates_json) if r.candidates_json else [],
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in results
        ]
    }


# ─── Strategy: Risk State ──────────────────────────────────────────────────
@app.get("/api/risk-state", dependencies=[Depends(require_auth)])
def get_risk_state(db: Session = Depends(get_db)):
    """
    Returns the current portfolio risk state: heat, drawdown, circuit breaker status.
    """
    trading_mode = get_setting(db, "trading_mode", "paper")
    try:
        client = IBKRClient(trading_mode=trading_mode)
        connected = client.connect(retries=2, delay=3)
        if not connected:
            return {"error": "Cannot connect to IB Gateway", "available": False}
        account = client.get_account_summary()
        client.disconnect()
        equity = account.get("NetLiquidation", 0)
    except Exception as exc:
        return {"error": str(exc), "available": False}

    from strategy.risk_engine import get_risk_engine
    open_trades = db.query(Trade).filter(Trade.status.in_(["open", "sold_half"])).all()
    open_positions = [
        {"buy_price": t.buy_price, "stop_price": t.stop_price, "shares": t.shares,
         "status": t.status, "sector": getattr(t, "sector", "Unknown") or "Unknown"}
        for t in open_trades
    ]
    from jobs import _get_peak_equity, _compute_weekly_pnl_pct
    peak_equity = _get_peak_equity(db)
    weekly_pnl = _compute_weekly_pnl_pct(db, equity)

    from strategy.data_layer import compute_regime_status
    regime_data = compute_regime_status()
    regime = regime_data["regime"] if regime_data else "unknown"

    risk_engine = get_risk_engine()
    state = risk_engine.get_state_summary(
        account_equity=equity,
        peak_equity=peak_equity,
        open_positions=open_positions,
        daily_pnl_pct=0.0,
        weekly_pnl_pct=weekly_pnl,
        regime=regime,
    )
    return {"available": True, **state}


# ─── Strategy: Pending Candidates ─────────────────────────────────────────
@app.get("/api/candidates", dependencies=[Depends(require_auth)])
def get_pending_candidates():
    """Returns the candidates staged by today's scan, awaiting intraday entry confirmation."""
    from jobs import _pending_candidates, _scan_date_today
    from jobs import _strip_df
    candidates = [_strip_df(c) for c in _pending_candidates]
    return {
        "scan_date": _scan_date_today.isoformat() if _scan_date_today else None,
        "count": len(candidates),
        "candidates": candidates,
    }



# ─── System Logs ───────────────────────────────────────────────────────────
@app.get("/api/logs", dependencies=[Depends(require_auth)])
def get_logs(
    category: Optional[str] = None,
    level: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """Returns system logs, newest first."""
    query = db.query(SystemLog).order_by(SystemLog.timestamp.desc())
    if category:
        query = query.filter(SystemLog.category == category)
    if level:
        query = query.filter(SystemLog.level == level)
    total = query.count()
    logs = query.offset(offset).limit(limit).all()

    return {
        "total": total,
        "logs": [
            {
                "id": l.id,
                "timestamp": l.timestamp.isoformat(),
                "level": l.level,
                "category": l.category,
                "message": l.message,
            }
            for l in logs
        ],
    }


# ─── Settings ──────────────────────────────────────────────────────────────
@app.get("/api/settings", dependencies=[Depends(require_auth)])
def get_settings(db: Session = Depends(get_db)):
    """Returns all user-configurable settings."""
    settings = {s.key: s.value for s in db.query(Setting).all()}
    settings["account_type"] = _normalize_account_type(settings.get("account_type"))
    settings["paper_strategy"] = _normalize_paper_strategy(settings.get("paper_strategy"), settings.get("account_type"))
    if "daily_budget_pct" not in settings:
        settings["daily_budget_pct"] = "100"
    if "max_positions" not in settings:
        settings["max_positions"] = "5"
    return settings


@app.put("/api/settings", dependencies=[Depends(require_auth)])
def update_settings(body: SettingsBulkUpdate, db: Session = Depends(get_db)):
    """Updates one or more settings."""
    updates = body.dict(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No settings provided")

    if "trading_mode" in updates and updates["trading_mode"] not in ("paper", "live"):
        raise HTTPException(status_code=400, detail="trading_mode must be 'paper' or 'live'")
    if "daily_budget_pct" in updates:
        pct = float(updates["daily_budget_pct"])
        if not (1 <= pct <= 100):
            raise HTTPException(status_code=400, detail="daily_budget_pct must be 1-100")
    if "account_type" in updates and updates["account_type"] not in ("trading_cash", "investment_cash", "cash"):
        raise HTTPException(status_code=400, detail="account_type must be 'trading_cash' or 'investment_cash'")
    if "paper_strategy" in updates and updates["paper_strategy"] not in ("cash", "margin"):
        raise HTTPException(status_code=400, detail="paper_strategy must be 'cash' or 'margin'")

    for key, value in updates.items():
        set_setting(db, key, str(value))

    if "paper_strategy" in updates:
        _sync_strategy_settings(db, updates["paper_strategy"])

    if "account_type" in updates:
        account_type = _normalize_account_type(updates["account_type"])
        if account_type == "trading_cash":
            set_setting(db, "margin_upgrade_alerted", "false")

    if "trading_mode" in updates:
        new_mode = updates["trading_mode"]
        db.add(SystemLog(
            timestamp=datetime.now(timezone.utc),
            level="INFO",
            category="system",
            message=f"Trading mode changed to: {new_mode.upper()} — restarting IBKR keepalive.",
        ))
        db.commit()

        import threading
        stop_persistent_keepalive()
        threading.Thread(
            target=start_persistent_keepalive,
            args=(new_mode,),
            daemon=True,
            name="ibkr-mode-switch-keepalive",
        ).start()
        logger.info("IBKR keepalive restarted for mode: %s", new_mode)

    return {"status": "updated", "settings": updates}


# ─── Manual Triggers ───────────────────────────────────────────────────────
@app.post("/api/scan", dependencies=[Depends(require_auth)])
def trigger_scan(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Manually triggers the morning scan & buy job in the background.

    The AI scan runs immediately regardless of the time of day.
    If the market is currently open, buy orders are placed right away.
    If the market is closed, buy orders are queued and will be placed
    automatically when NYSE opens next (09:30 ET, next weekday).
    """
    from jobs import job_manual_scan_with_deferred_buy, is_market_open
    market_open = is_market_open()
    background_tasks.add_task(job_manual_scan_with_deferred_buy)
    if market_open:
        return {
            "status": "triggered",
            "message": "Market scan started — buy orders will be placed immediately (market is open).",
            "deferred": False,
        }
    return {
        "status": "triggered",
        "message": (
            "Market scan started — the AI scan will run now, but buy orders are deferred "
            "until market open (09:30 ET next weekday)."
        ),
        "deferred": True,
    }


@app.post("/api/sell-all", dependencies=[Depends(require_auth)])
def trigger_sell(background_tasks: BackgroundTasks):
    """Manually trigger the exit monitor immediately (checks all exit conditions)."""
    from jobs import job_exit_monitor
    background_tasks.add_task(job_exit_monitor)
    return {"status": "triggered", "message": "Exit monitor job started in background"}



@app.post("/api/sell-all-ibkr", dependencies=[Depends(require_auth)])
def sell_all_ibkr(db: Session = Depends(get_db)):
    """
    Immediately sells ALL open positions in the IBKR account (synchronous).
    P&L calculation correctly includes realised_partial_pnl for sold_half trades.
    """
    trading_mode = get_setting(db, "trading_mode", "paper")
    try:
        client = IBKRClient(trading_mode=trading_mode)
        connected = client.connect(retries=2, delay=3)
        if not connected:
            raise HTTPException(status_code=503, detail="Could not connect to IB Gateway")

        positions = client.get_positions()
        if not positions:
            client.disconnect()
            return {"status": "ok", "message": "No open positions to sell.", "results": []}

        results = []
        for pos in positions:
            ticker = pos["ticker"]
            live_shares = pos["shares"]

            # Skip zero positions — nothing to do.
            if live_shares == 0:
                logger.warning(
                    "[SELL-ALL] Skipping %s — zero share count.", ticker)
                results.append({
                    "success": False, "ticker": ticker,
                    "error": "Skipped: zero share count"
                })
                continue

            action = "BUY-TO-COVER" if live_shares < 0 else "SELL"
            logger.info(f"[SELL-ALL] Placing {action} order for {abs(live_shares)} shares of {ticker}...")
            # place_sell_order handles negative shares (short positions) transparently
            result = client.place_sell_order(ticker, live_shares)
            results.append(result)

            if result.get("success"):
                sell_price = result["price"]
                # Match on open OR sold_half trades
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

                    # Correct P&L: use live shares (actual remaining), add banked partials
                    remaining_pnl = (sell_price - buy_price) * live_shares
                    total_pnl = remaining_pnl + partial_already_realised

                    original_cost = buy_price * trade.shares if trade.shares else 1
                    pnl_pct = (total_pnl / original_cost * 100) if original_cost else 0.0

                    trade.sell_price = sell_price
                    trade.sell_time = datetime.now(timezone.utc)
                    trade.status = "closed"
                    trade.pnl = round(total_pnl, 2)
                    trade.pnl_pct = round(pnl_pct, 2)
                    db.commit()

            level = "INFO" if result.get("success") else "ERROR"
            msg = (
                f"✅ Sold {result.get('shares')} shares of {ticker} @ ${result.get('price', 0):.2f}"
                if result.get("success")
                else f"❌ Sell failed for {ticker}: {result.get('error')}"
            )
            db.add(SystemLog(
                timestamp=datetime.now(timezone.utc),
                level=level,
                category="sell",
                message=msg,
            ))
            db.commit()

        client.disconnect()
        return {"status": "ok", "results": results}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"sell-all-ibkr error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class SellStockRequest(BaseModel):
    ticker: str


@app.post("/api/sell-stock", dependencies=[Depends(require_auth)])
def sell_single_stock(body: SellStockRequest, db: Session = Depends(get_db)):
    """
    Sells all shares of a single stock position.

    - If the market is currently open: executes immediately (synchronous).
    - If the market is closed: queues a deferred sell that will fire at NYSE open
      (09:30 ET next weekday). Returns immediately with deferred=true.
    """
    from jobs import is_market_open, job_deferred_sell_single

    ticker = body.ticker.upper().strip()
    if not ticker:
        raise HTTPException(status_code=400, detail="Ticker is required")

    trading_mode = get_setting(db, "trading_mode", "paper")

    if not is_market_open():
        # Defer the sell until market opens
        import threading
        t = threading.Thread(
            target=job_deferred_sell_single,
            args=(ticker, trading_mode),
            daemon=True,
            name=f"deferred-sell-{ticker}",
        )
        t.start()

        db.add(SystemLog(
            timestamp=datetime.now(timezone.utc),
            level="INFO",
            category="sell",
            message=f"📋 Manual sell for {ticker} queued — will execute at market open.",
        ))
        db.commit()

        return {
            "status": "deferred",
            "ticker": ticker,
            "deferred": True,
            "message": (
                f"Market is closed. Sell order for {ticker} has been queued and "
                f"will execute automatically when NYSE opens (09:30 ET next weekday)."
            ),
        }

    # Market is open — sell immediately
    try:
        client = IBKRClient(trading_mode=trading_mode)
        connected = client.connect(retries=2, delay=3)
        if not connected:
            raise HTTPException(status_code=503, detail="Could not connect to IB Gateway")

        positions = client.get_positions()
        target_pos = None
        for pos in positions:
            if pos["ticker"] == ticker:
                target_pos = pos
                break

        if not target_pos:
            client.disconnect()
            raise HTTPException(status_code=404, detail=f"No open position found for {ticker}")

        live_shares = target_pos["shares"]
        # Zero means nothing to close
        if live_shares == 0:
            client.disconnect()
            raise HTTPException(
                status_code=400,
                detail=f"Cannot close {ticker}: zero share count"
            )
        # Negative shares = short position — place_sell_order routes to buy-to-cover automatically

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

        level = "INFO" if result.get("success") else "ERROR"
        msg = (
            f"✅ Manual sell: sold {result.get('shares')} shares of {ticker} @ ${result.get('price', 0):.2f}"
            if result.get("success")
            else f"❌ Manual sell failed for {ticker}: {result.get('error')}"
        )
        db.add(SystemLog(
            timestamp=datetime.now(timezone.utc),
            level=level,
            category="sell",
            message=msg,
        ))
        db.commit()

        client.disconnect()
        return {
            "status": "ok" if result.get("success") else "error",
            "ticker": ticker,
            "deferred": False,
            "result": result,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"sell-stock error ({ticker}): {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─── P&L History ───────────────────────────────────────────────────────────

# Starting capital in AUD (A$7,900 deposited at account open)
STARTING_CAPITAL_AUD = 7_900.0


@app.get("/api/pnl-history", dependencies=[Depends(require_auth)])
def get_pnl_history(db: Session = Depends(get_db)):
    """
    Returns daily and cumulative P&L from either:
      1. AccountSnapshot records (preferred) — computes P&L from actual daily
         NetLiquidation movements, so the chart truly reflects account performance.
      2. DB closed-trade records (fallback) — used for days before snapshots
         started being collected.

    Cumulative P&L is always relative to the A$7,900 starting capital.
    The 'daily_pnl' field is that day's gain/loss only (not running total).
    The 'cumulative_pnl' field is the running sum from starting capital.
    """
    trading_mode = get_setting(db, "trading_mode", "paper")

    # ── 1. Snapshot-based data (preferred) ────────────────────────────────────
    snapshots = (
        db.query(AccountSnapshot)
        .order_by(AccountSnapshot.date.asc())
        .all()
    )

    # ── 2. Fallback: trade-based data for days without snapshots ───────────────
    closed_trades = (
        db.query(Trade)
        .filter(
            Trade.status == "closed",
            Trade.sell_time.isnot(None),
            Trade.pnl.isnot(None),
            Trade.mode == trading_mode,
        )
        .order_by(Trade.sell_time.asc())
        .all()
    )

    from collections import defaultdict
    daily_trade: dict[str, float] = defaultdict(float)
    daily_trade_cost: dict[str, float] = defaultdict(float)
    daily_trade_fees: dict[str, float] = defaultdict(float)
    for t in closed_trades:
        day = t.sell_time.strftime("%Y-%m-%d")
        daily_trade[day] += t.pnl
        daily_trade_fees[day] += (t.fees or 0.0)
        if t.buy_price is not None and t.shares is not None:
            daily_trade_cost[day] += (t.buy_price * t.shares)

    # Days covered by snapshots
    snapshot_dates = {str(s.date) for s in snapshots}

    # ── Build the chart data ───────────────────────────────────────────────────
    chart_data = []

    # --- Snapshot-based segment ---
    if snapshots:
        # The first snapshot IS the baseline — it represents the account value
        # at the start of tracking. Day-1 daily_pnl = 0 (no change yet).
        # Subsequent days show the delta vs the previous day's snapshot.
        # This avoids the phantom loss/gain from the AUD→USD conversion.
        first_net_liq = snapshots[0].net_liq_usd
        starting_capital_usd = first_net_liq  # Actual account value at tracking start

        prev_net_liq = first_net_liq
        cumulative = 0.0

        for snap in snapshots:
            day = str(snap.date)
            daily_pnl = snap.net_liq_usd - prev_net_liq
            cumulative += daily_pnl

            # Percentage calculations
            daily_pct = (daily_pnl / prev_net_liq * 100) if prev_net_liq > 0 else 0.0
            cumulative_pct = (cumulative / starting_capital_usd * 100) if starting_capital_usd > 0 else 0.0

            # Include fees from trade records for this day (if any)
            day_fees = daily_trade_fees.get(day, 0.0)

            chart_data.append({
                "date": day,
                "daily_pnl": round(daily_pnl, 2),
                "cumulative_pnl": round(cumulative, 2),
                "net_liq_usd": round(snap.net_liq_usd, 2),
                "daily_pct": round(daily_pct, 2),
                "cumulative_pct": round(cumulative_pct, 2),
                "daily_fees": round(day_fees, 2),
                "cumulative_fees": 0.0,  # not tracked cumulatively in snapshot mode
                "source": "snapshot",
            })

            prev_net_liq = snap.net_liq_usd

    # --- Trade-based fallback for days NOT covered by snapshots ---
    fallback_days = sorted(d for d in daily_trade.keys() if d not in snapshot_dates)
    if fallback_days:
        # Cumulative offset: if we have snapshot data, the fallback days are
        # all in the past (before snapshots started), so prepend them.
        # Compute their own running cumulative from zero (relative to position cost).
        fallback_cumulative = 0.0
        fallback_cumulative_cost = 0.0
        fallback_points = []
        for day in fallback_days:
            day_pnl = daily_trade[day]
            day_fees = daily_trade_fees[day]
            day_cost = daily_trade_cost[day]
            fallback_cumulative += day_pnl
            fallback_cumulative_cost += day_cost
            daily_pct = (day_pnl / day_cost * 100) if day_cost > 0 else 0.0
            cumulative_pct = (fallback_cumulative / fallback_cumulative_cost * 100) if fallback_cumulative_cost > 0 else 0.0
            fallback_points.append({
                "date": day,
                "daily_pnl": round(day_pnl, 2),
                "cumulative_pnl": round(fallback_cumulative, 2),
                "net_liq_usd": None,
                "daily_pct": round(daily_pct, 2),
                "cumulative_pct": round(cumulative_pct, 2),
                "daily_fees": round(day_fees, 2),
                "cumulative_fees": round(sum(daily_trade_fees[d] for d in fallback_days if d <= day), 2),
                "source": "trades",
            })

        # Prepend fallback points before snapshot points (they're older dates)
        chart_data = fallback_points + chart_data

    all_time_realized = round(sum(t.pnl for t in closed_trades), 2)
    all_time_fees = round(sum((t.fees or 0.0) for t in closed_trades), 2)

    winners = sum(1 for t in closed_trades if t.pnl and t.pnl > 0)
    losers  = sum(1 for t in closed_trades if t.pnl and t.pnl < 0)
    total_closed = len(closed_trades)

    return {
        "chart_data": chart_data,
        "all_time_realized_pnl": all_time_realized,
        "total_closed_trades": total_closed,
        "winning_trades": winners,
        "losing_trades": losers,
        "all_time_fees": all_time_fees,
        "has_snapshots": len(snapshots) > 0,
    }


@app.post("/api/trigger-snapshot", dependencies=[Depends(require_auth)])
def trigger_snapshot(background_tasks: BackgroundTasks):
    """Manually triggers a NetLiquidation snapshot (useful for testing or if the
    scheduled job was missed). Runs in the background."""
    from jobs import job_snapshot_net_liq
    background_tasks.add_task(job_snapshot_net_liq)
    return {"status": "triggered", "message": "NetLiq snapshot job started in background."}


@app.post("/api/reset-pnl-history", dependencies=[Depends(require_auth)])
def reset_pnl_history(db: Session = Depends(get_db), confirm: bool = False):
    """
    Deletes ALL AccountSnapshot records so the P&L chart can start fresh.

    Requires ?confirm=true as a query parameter to prevent accidental deletions.

    Use this when the existing snapshot history is incorrect or stale.
    After calling this endpoint, trigger a new snapshot via /api/trigger-snapshot
    to start tracking from the current account value.

    WARNING: This is irreversible. Old chart data will be lost.
    """
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="Pass ?confirm=true to confirm deletion of all P&L history. This is irreversible."
        )
    try:
        deleted_count = db.query(AccountSnapshot).delete()
        db.commit()
        db.add(SystemLog(
            timestamp=datetime.now(timezone.utc),
            level="INFO",
            category="system",
            message=f"🗑️ P&L history reset: deleted {deleted_count} account snapshot(s). "
                    f"Chart will start fresh from the next snapshot.",
        ))
        db.commit()
        logger.info("P&L history reset: deleted %d snapshots.", deleted_count)
        return {
            "status": "ok",
            "deleted_snapshots": deleted_count,
            "message": (
                f"Deleted {deleted_count} snapshot(s). "
                "Trigger a new snapshot via /api/trigger-snapshot to begin fresh tracking."
            ),
        }
    except Exception as e:
        logger.error("reset-pnl-history error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ─── Entrypoint ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api_server:app", host="0.0.0.0", port=8000, reload=False)
