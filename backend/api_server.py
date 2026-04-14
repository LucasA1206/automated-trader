import os
import logging
import logging.config
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db, init_db, get_setting, set_setting, SessionLocal
from models import Trade, SystemLog, Setting
from scheduler import create_scheduler, get_next_job_times
from trader import IBKRClient
from auth import require_auth, validate_credentials, create_access_token
from jobs import start_persistent_keepalive, stop_persistent_keepalive

# ─── Logging ───────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

MARGIN_UPGRADE_THRESHOLD = 25_000.0

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

    # Start a persistent IBKR connection that keeps the gateway alive between jobs.
    # Run in a regular thread since IBKRClient is synchronous.
    import threading
    db = SessionLocal()
    trading_mode = get_setting(db, "trading_mode", "paper")
    db.close()
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
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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


def _sync_strategy_settings(db: Session, account_type: str) -> None:
    """Keep derived strategy settings aligned with the selected strategy preset."""
    if account_type == "margin":
        set_setting(db, "daily_budget_pct", "100")
        set_setting(db, "max_positions", "5")
    else:
        set_setting(db, "daily_budget_pct", "50")
        set_setting(db, "max_positions", "3")


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


# ─── Portfolio ─────────────────────────────────────────────────────────────
@app.get("/api/portfolio", dependencies=[Depends(require_auth)])
def get_portfolio(db: Session = Depends(get_db)):
    """Returns IBKR account summary + open positions."""
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
    """Returns trade history, optionally filtered by status (open/closed/error)."""
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
                "ai_reason": t.ai_reason,
            }
            for t in trades
        ],
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
        settings["daily_budget_pct"] = "50" if settings["paper_strategy"] == "cash" else "100"
    if "max_positions" not in settings:
        settings["max_positions"] = "3" if settings["paper_strategy"] == "cash" else "5"
    return settings


@app.put("/api/settings", dependencies=[Depends(require_auth)])
def update_settings(body: SettingsBulkUpdate, db: Session = Depends(get_db)):
    """Updates one or more settings."""
    updates = body.dict(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No settings provided")

    # Validation
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
            # Reset the one-time live upgrade alert so it can fire again if the
            # user switches to a different cash account type later.
            set_setting(db, "margin_upgrade_alerted", "false")

    # Log trading mode change and restart the persistent keepalive on the new port
    if "trading_mode" in updates:
        new_mode = updates["trading_mode"]
        db.add(SystemLog(
            timestamp=datetime.now(timezone.utc),
            level="INFO",
            category="system",
            message=f"Trading mode changed to: {new_mode.upper()} — restarting IBKR keepalive.",
        ))
        db.commit()

        # Restart the persistent keepalive so it connects to the correct IB Gateway port.
        # paper → port 4004 | live → port 4003
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
    """Manually triggers the morning scan & buy job in the background."""
    from jobs import job_morning_scan_and_buy
    background_tasks.add_task(job_morning_scan_and_buy)
    return {"status": "triggered", "message": "Market scan started in background"}


@app.post("/api/sell-all", dependencies=[Depends(require_auth)])
def trigger_sell(background_tasks: BackgroundTasks):
    """Manually triggers the sell-all job in the background."""
    from jobs import job_afternoon_sell
    background_tasks.add_task(job_afternoon_sell)
    return {"status": "triggered", "message": "Sell-all job started in background"}


@app.post("/api/sell-all-ibkr", dependencies=[Depends(require_auth)])
def sell_all_ibkr(db: Session = Depends(get_db)):
    """
    Immediately sells ALL open positions in the IBKR account (synchronous).
    This uses the live portfolio from IB Gateway — not just DB-tracked trades.
    Returns per-ticker results.
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
            shares = pos["shares"]
            logger.info(f"[SELL-ALL] Placing sell order for {shares} shares of {ticker}...")
            result = client.place_sell_order(ticker, shares)
            results.append(result)

            # Update DB trade record if one exists
            if result.get("success"):
                trade = (
                    db.query(Trade)
                    .filter(Trade.ticker == ticker, Trade.status == "open")
                    .order_by(Trade.buy_time.desc())
                    .first()
                )
                if trade:
                    sell_price = result["price"]
                    pnl = (sell_price - trade.buy_price) * trade.shares
                    pnl_pct = ((sell_price - trade.buy_price) / trade.buy_price * 100) if trade.buy_price else 0
                    trade.sell_price = sell_price
                    trade.sell_time = datetime.now(timezone.utc)
                    trade.status = "closed"
                    trade.pnl = round(pnl, 2)
                    trade.pnl_pct = round(pnl_pct, 2)
                    db.commit()

            from models import SystemLog
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


# ─── P&L History ───────────────────────────────────────────────────────────
@app.get("/api/pnl-history", dependencies=[Depends(require_auth)])
def get_pnl_history(db: Session = Depends(get_db)):
    """
    Returns daily realized P&L from closed trades, cumulative P&L over time,
    and the all-time realized P&L total.
    """
    from sqlalchemy import func, cast, Date as SQLDate

    trading_mode = get_setting(db, "trading_mode", "paper")

    # All closed trades with a sell_time and pnl in current mode
    closed_trades = (
        db.query(Trade)
        .filter(Trade.status == "closed", Trade.sell_time.isnot(None), Trade.pnl.isnot(None), Trade.mode == trading_mode)
        .order_by(Trade.sell_time.asc())
        .all()
    )

    # Group by calendar date (UTC)
    from collections import defaultdict
    daily: dict[str, float] = defaultdict(float)
    daily_cost: dict[str, float] = defaultdict(float)
    daily_fees: dict[str, float] = defaultdict(float)
    for t in closed_trades:
        day = t.sell_time.strftime("%Y-%m-%d")
        daily[day] += t.pnl
        daily_fees[day] += (t.fees or 0.0)
        if t.buy_price is not None and t.shares is not None:
            daily_cost[day] += (t.buy_price * t.shares)

    # Build sorted list with cumulative running total
    sorted_days = sorted(daily.keys())
    cumulative = 0.0
    cumulative_cost = 0.0
    cumulative_fees = 0.0
    chart_data = []
    for day in sorted_days:
        cumulative += daily[day]
        cumulative_cost += daily_cost[day]
        cumulative_fees += daily_fees[day]
        
        day_pnl = daily[day]
        day_fees = daily_fees[day]
        day_cost = daily_cost[day]
        daily_pct = (day_pnl / day_cost * 100) if day_cost > 0 else 0.0
        cumulative_pct = (cumulative / cumulative_cost * 100) if cumulative_cost > 0 else 0.0

        chart_data.append({
            "date": day,
            "daily_pnl": round(day_pnl, 2),
            "cumulative_pnl": round(cumulative, 2),
            "daily_pct": round(daily_pct, 2),
            "cumulative_pct": round(cumulative_pct, 2),
            "daily_fees": round(day_fees, 2),
            "cumulative_fees": round(cumulative_fees, 2),
        })

    # All-time realized P&L
    all_time_realized = round(sum(t.pnl for t in closed_trades), 2)
    all_time_fees = round(sum((t.fees or 0.0) for t in closed_trades), 2)

    # Count of winning vs losing closed trades
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
    }


# ─── Entrypoint ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api_server:app", host="0.0.0.0", port=8000, reload=False)
