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

# ─── Logging ───────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

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
    yield
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
class SettingUpdate(BaseModel):
    value: str


class SettingsBulkUpdate(BaseModel):
    trading_mode: Optional[str] = None
    daily_budget_pct: Optional[str] = None
    max_positions: Optional[str] = None
    scan_enabled: Optional[str] = None


# ─── Health ────────────────────────────────────────────────────────────────
@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "time": datetime.now(timezone.utc).isoformat(),
        "scheduler_running": scheduler.running if scheduler else False,
        "scheduled_jobs": get_next_job_times(scheduler) if scheduler else [],
    }


# ─── Portfolio ─────────────────────────────────────────────────────────────
@app.get("/api/portfolio")
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
        client.disconnect()
        return {
            "connected": True,
            "mode": trading_mode,
            "positions": positions,
            "account": account,
        }
    except Exception as e:
        logger.error(f"Portfolio fetch error: {e}")
        return {"connected": False, "mode": trading_mode, "positions": [], "account": {}, "error": str(e)}


# ─── Trades ────────────────────────────────────────────────────────────────
@app.get("/api/trades")
def get_trades(
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """Returns trade history, optionally filtered by status (open/closed/error)."""
    query = db.query(Trade).order_by(Trade.buy_time.desc())
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
@app.get("/api/logs")
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
@app.get("/api/settings")
def get_settings(db: Session = Depends(get_db)):
    """Returns all user-configurable settings."""
    settings = db.query(Setting).all()
    return {s.key: s.value for s in settings}


@app.put("/api/settings")
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

    for key, value in updates.items():
        set_setting(db, key, str(value))

    # Log trading mode change
    if "trading_mode" in updates:
        from models import SystemLog
        db.add(SystemLog(
            timestamp=datetime.now(timezone.utc),
            level="INFO",
            category="system",
            message=f"Trading mode changed to: {updates['trading_mode'].upper()}",
        ))
        db.commit()

    return {"status": "updated", "settings": updates}


# ─── Manual Triggers ───────────────────────────────────────────────────────
@app.post("/api/scan")
def trigger_scan(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Manually triggers the morning scan & buy job in the background."""
    from jobs import job_morning_scan_and_buy
    background_tasks.add_task(job_morning_scan_and_buy)
    return {"status": "triggered", "message": "Market scan started in background"}


@app.post("/api/sell-all")
def trigger_sell(background_tasks: BackgroundTasks):
    """Manually triggers the sell-all job in the background."""
    from jobs import job_afternoon_sell
    background_tasks.add_task(job_afternoon_sell)
    return {"status": "triggered", "message": "Sell-all job started in background"}


@app.post("/api/sell-all-ibkr")
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


# ─── Entrypoint ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api_server:app", host="0.0.0.0", port=8000, reload=False)
