"""
jobs.py — Systematic Swing Trading Strategy Jobs
=================================================
Implements the three scheduled jobs per blueprint Section 2/18:

  job_pre_market_scan  : 07:30 ET Mon-Fri
    Full pipeline: universe fetch → filter → score → AI → candidate list persisted.
    No orders placed here — candidates are staged for intraday entry confirmation.

  job_entry_monitor    : 09:45–15:30 ET, every 5 min, Mon-Fri
    Checks pending candidates for intraday entry confirmation (Section 8).
    Places limit orders via IBKR when all entry conditions are met.
    Respects all risk engine gates before any order placement.

  job_exit_monitor     : 09:30–16:00 ET, every 5 min, Mon-Fri
    Checks all open positions against all exit rules (Section 9):
    stop-loss, 1.5R partial, Chandelier trail, MA break, time exits, ATR expansion.

  job_eod_snapshot     : 15:45 ET Mon-Fri
    Captures daily NetLiquidation snapshot (unchanged from previous system).

DESIGN PRINCIPLES:
  - "Fail-safe, not fail-guess": every data failure is logged and halts that job step
  - "No forced trades": system correctly outputs "no trade today" when appropriate
  - Paper trading is the default — live trading requires explicit DB setting
  - Stop-loss orders are placed with IBKR at time of entry as native stop orders
  - The software monitor is a belt-and-suspenders fallback
"""

import logging
import threading
import time
import json
from datetime import datetime, timezone, timedelta, date

from database import SessionLocal, get_setting, log_event
from models import Trade, AIPick, AccountSnapshot, ScanResult
from trader import IBKRClient, safe_float

import pytz

logger = logging.getLogger(__name__)

_ET = pytz.timezone("America/New_York")
_MARKET_OPEN_HOUR = 9
_MARKET_OPEN_MINUTE = 30
_MARKET_CLOSE_HOUR = 16

# Module-level storage for today's scan candidates
# (shared between pre_market_scan and entry_monitor jobs)
_pending_candidates: list[dict] = []
_pending_candidates_lock = threading.Lock()
_scan_date_today: date | None = None


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
# Market-hours helpers (NYSE / ET)
# ---------------------------------------------------------------------------

def is_market_open() -> bool:
    """Return True if NYSE is currently open (Mon–Fri, 09:30–16:00 ET)."""
    now_et = datetime.now(_ET)
    if now_et.weekday() >= 5:
        return False
    open_time  = now_et.replace(hour=_MARKET_OPEN_HOUR, minute=_MARKET_OPEN_MINUTE, second=0, microsecond=0)
    close_time = now_et.replace(hour=_MARKET_CLOSE_HOUR, minute=0, second=0, microsecond=0)
    return open_time <= now_et < close_time


def seconds_until_market_open() -> float:
    if is_market_open():
        return 0
    now_et = datetime.now(_ET)
    candidate = now_et.replace(hour=_MARKET_OPEN_HOUR, minute=_MARKET_OPEN_MINUTE, second=0, microsecond=0)
    if candidate <= now_et:
        candidate += timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return max((candidate - now_et).total_seconds(), 0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# log_event is imported from database — see database.py for the canonical definition.
# It is re-exported here so legacy call-sites within this module continue to work.

def _count_open_positions(db) -> int:
    return db.query(Trade).filter(Trade.status.in_(["open", "sold_half", "closing"])).count()


def _get_open_positions_with_sectors(db) -> list[dict]:
    """Return open trades as list of dicts including sector for risk engine."""
    trades = db.query(Trade).filter(Trade.status.in_(["open", "sold_half"])).all()
    result = []
    for t in trades:
        result.append({
            "ticker": t.ticker,
            "shares": t.shares,
            "buy_price": t.buy_price,
            "stop_price": t.stop_price,
            "sector": getattr(t, "sector", "Unknown") or "Unknown",
            "status": t.status,
        })
    return result


def _reconcile_stale_db_trades(db, live_tickers: set[str]) -> None:
    """Close any DB trades for tickers no longer held in IBKR."""
    open_trades = db.query(Trade).filter(Trade.status.in_(["open", "sold_half"])).all()
    for trade in open_trades:
        if trade.ticker not in live_tickers:
            trade.status = "closed"
            trade.sell_time = datetime.now(timezone.utc)
            db.commit()
            log_event(db, "sell",
                      f"⚠️ Reconciled stale DB record for {trade.ticker} "
                      f"(marked closed — not found in live IBKR positions).")


def _sync_untracked_ibkr_positions(db, live_positions: list[dict], trading_mode: str) -> None:
    """Ensure every live IBKR position has a matching DB trade record."""
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
            # Conservative safety stop at 5% below avg cost
            stop_price=round(avg_cost * 0.95, 4) if avg_cost else None,
        )
        db.add(ghost_trade)
        db.commit()
        log_event(db, "system",
                  f"⚠️ Untracked IBKR position detected: {ticker} "
                  f"({shares} shares @ avg ${avg_cost:.2f}). DB record created.")


def _get_peak_equity(db) -> float:
    """Return peak NetLiquidation from account_snapshots for drawdown tracking."""
    snapshots = db.query(AccountSnapshot).order_by(AccountSnapshot.date.desc()).limit(90).all()
    if not snapshots:
        return 0.0
    return max((s.net_liq_usd for s in snapshots), default=0.0)


def _compute_weekly_pnl_pct(db, account_equity: float) -> float:
    """Estimate weekly P&L % from account snapshots."""
    from sqlalchemy import func
    now_et = datetime.now(_ET)
    # Monday of this week
    days_since_monday = now_et.weekday()
    week_start = (now_et - timedelta(days=days_since_monday)).date()
    snap = (
        db.query(AccountSnapshot)
        .filter(AccountSnapshot.date >= week_start)
        .order_by(AccountSnapshot.date.asc())
        .first()
    )
    if snap and snap.net_liq_usd and account_equity:
        return round((account_equity - snap.net_liq_usd) / snap.net_liq_usd * 100, 3)
    return 0.0


# ---------------------------------------------------------------------------
# Fetch the universe of tickers from the existing NASDAQ source
# ---------------------------------------------------------------------------

def _fetch_ticker_universe() -> list[str]:
    """
    Fetch the full universe of tradeable tickers using the NASDAQ FTP source.
    Reuses the parsing logic from the old ai_analyst.py via direct HTTP fetch.
    Falls back to a compact curated list if fetch fails.
    """
    import csv
    import requests

    FALLBACK = [
        "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AVGO",
        "AMD", "PLTR", "CRM", "NFLX", "CRWD", "PANW", "ADBE", "NOW", "WDAY",
        "DDOG", "NET", "SNOW", "SHOP", "COIN", "MELI", "UBER", "ABNB",
        "DKNG", "RBLX", "PYPL", "SQ", "SOFI", "HOOD", "MU", "INTC", "QCOM",
        "SMCI", "ARM", "AMAT", "LRCX", "KLAC", "ANET", "CSCO", "FTNT",
        "ISRG", "IDXX", "DXCM", "REGN", "VRTX", "MRNA", "CRSP", "RXRX",
        "COST", "LULU", "ORLY", "ROST", "ULTA", "DECK", "ONON",
        "AXON", "KTOS", "RKLB", "TMUS",
    ]

    _SPECIAL_SUFFIX = set("WRUPQZ")

    def _fetch_screener() -> list[str]:
        import requests
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            'Accept': 'application/json',
            'Origin': 'https://www.nasdaq.com',
            'Referer': 'https://www.nasdaq.com/'
        }
        url = "https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=15000&offset=0"
        
        tickers = []
        try:
            resp = requests.get(url, headers=headers, timeout=20)
            resp.raise_for_status()
            data = resp.json()
            rows = data.get('data', {}).get('table', {}).get('rows', [])
            
            filtered_special = 0
            candidates = []
            for row in rows:
                if not row or 'symbol' not in row:
                    continue
                    
                symbol = row['symbol'].strip().upper()
                if not symbol or any(c in symbol for c in (".", "+", "-", "^", "=", "/")):
                    continue
                if symbol.startswith("$") or " " in symbol:
                    continue
                if len(symbol) > 4 and symbol[-1] in _SPECIAL_SUFFIX and len(symbol[:-1]) >= 4:
                    filtered_special += 1
                    continue
                if len(symbol) == 5 and symbol[-1] in ("P", "R"):
                    filtered_special += 1
                    continue
                if symbol.lower().endswith("test"):
                    continue
                    
                # ── Pre-filter 1: price ≥ $3 ────────────────────────────────────────
                try:
                    price_str = row.get('lastsale', '').replace('$', '').replace(',', '').strip()
                    price = float(price_str) if price_str else 0.0
                    if price < 3.0:
                        continue
                except (ValueError, TypeError):
                    price = 0.0

                # ── Pre-filter 2: market cap ≥ $150M ────────────────────────────────
                try:
                    mcap_str = row.get('marketCap', '').replace(',', '').strip()
                    mcap = float(mcap_str) if mcap_str else 0.0
                    if mcap < 150_000_000.0:
                        continue
                except (ValueError, TypeError):
                    mcap = 0.0

                # Collect volume for the second pass
                try:
                    vol_str = row.get('volume', '').replace(',', '').strip()
                    vol = float(vol_str) if vol_str else 0.0
                except (ValueError, TypeError):
                    vol = 0.0

                candidates.append((symbol, price, vol, mcap))

            # ── Pre-filter 3: single-day dollar volume ≥ $500K ──────────────────
            # Only apply this filter if the screener is returning real volume data.
            # After market close, Nasdaq resets volume to 0 for all tickers, which
            # would incorrectly eliminate everything. We check: if fewer than 20% of
            # candidates have vol > 0, the screener is returning stale/zeroed data,
            # and we skip this filter to avoid eliminating the entire universe.
            # At 07:30 ET (scan time), prior-session volume is still populated.
            with_vol = sum(1 for _, _, v, _ in candidates if v > 0)
            vol_filter_active = with_vol >= len(candidates) * 0.20
            if vol_filter_active:
                logger.info(
                    "[Jobs] Volume pre-filter active: %d/%d candidates have vol data.",
                    with_vol, len(candidates),
                )
            else:
                logger.info(
                    "[Jobs] Volume pre-filter SKIPPED (only %d/%d have vol data — screener may be post-market).",
                    with_vol, len(candidates),
                )

            # Sort by market cap descending so the most liquid stocks process first
            candidates.sort(key=lambda x: x[3], reverse=True)
            for symbol, price, vol, mcap in candidates:
                if vol_filter_active:
                    dollar_vol_1d = vol * price
                    if dollar_vol_1d < 500_000.0:
                        continue
                tickers.append(symbol)


            if filtered_special:
                logger.debug("[Jobs] Universe parse: filtered %d special-suffix symbols.", filtered_special)
                
        except Exception as exc:
            logger.warning("[Jobs] Ticker universe fetch failed via screener: %s", exc)
            
        return tickers

    deduped = _fetch_screener()

    if len(deduped) < 100:
        logger.warning("[Jobs] Universe too small (%d) — using fallback.", len(deduped))
        return FALLBACK

    logger.info("[Jobs] Ticker universe loaded: %d symbols.", len(deduped))
    return deduped


# ---------------------------------------------------------------------------
# Job 1: Pre-market scan (07:30 ET Mon-Fri)
# ---------------------------------------------------------------------------

def job_pre_market_scan():
    """
    Full systematic pipeline:
      1. Fetch market regime (SPY + VIX)
      2. Fetch ticker universe
      3. Apply mandatory filters (price, vol, market cap, 200SMA, ATR, earnings)
      4. Score surviving candidates (0–100 composite)
      5. Run AI analysis (Gemini + DeepSeek cross-check)
      6. Persist candidates to DB for entry monitor
      7. Log scan result

    NO orders are placed here. This job only STAGES candidates.
    The entry monitor job places orders after intraday confirmation.
    """
    global _pending_candidates, _scan_date_today

    db = SessionLocal()
    try:
        trader_enabled = get_setting(db, "trader_enabled", "true")
        if trader_enabled.lower() != "true":
            log_event(db, "scan", "Trader globally disabled — skipping pre-market scan.")
            return

        trading_mode = get_setting(db, "trading_mode", "paper")
        scan_date = datetime.now(timezone.utc).date()

        log_event(db, "scan", "🔍 Pre-market scan starting…")

        # ── Step 1: Market regime ────────────────────────────────────────────
        from strategy.data_layer import compute_regime_status, clear_all_caches
        clear_all_caches()
        regime_data = compute_regime_status()

        if regime_data is None:
            log_event(db, "scan",
                      "❌ Regime data unavailable — cannot proceed safely. No trade today. "
                      "(fail-safe: never proceed on stale/missing regime data)", "WARNING")
            from strategy.journal import log_no_trade_day, log_scan_result
            log_no_trade_day(db, "regime_data_unavailable",
                             "SPY or VIX fetch failed — fail-safe halt.")
            log_scan_result(db, scan_date, "unknown", "Data unavailable", 0, 0, 0,
                            "no_trade", [], {})
            return

        regime = regime_data["regime"]
        log_event(db, "scan",
                  f"📊 Regime: {regime.upper()} | {regime_data['details']}")

        if regime == "risk_off":
            log_event(db, "scan",
                      f"🛑 Market is RISK_OFF — no new entries today. "
                      f"({regime_data['details']})")
            from strategy.journal import log_no_trade_day, log_scan_result
            log_no_trade_day(db, "risk_off", regime_data["details"])
            log_scan_result(db, scan_date, regime, regime_data["details"], 0, 0, 0,
                            "regime_off", [], {})
            return

        # ── Step 2: Universe ─────────────────────────────────────────────────
        log_event(db, "scan", "📋 Fetching ticker universe…")
        tickers = _fetch_ticker_universe()
        log_event(db, "scan", f"Universe: {len(tickers)} tickers loaded.")

        # ── Step 3: Mandatory filters ─────────────────────────────────────────
        from strategy.universe_filter import run_universe_filter
        log_event(db, "scan", f"🔬 Applying mandatory filters…")
        shortlist, rejections = run_universe_filter(tickers)

        log_event(db, "scan",
                  f"Filters complete: {len(shortlist)} candidates survived / "
                  f"{len(rejections)} rejected from {len(tickers)} universe.")

        # ── Per-stage breakdown for diagnostics ───────────────────────────────
        from collections import Counter
        rejection_buckets = Counter()
        for reason in rejections.values():
            # Normalise reason to a short label
            if reason.startswith("no_price_data") or reason.startswith("price_parse") or reason.startswith("volume_parse"):
                rejection_buckets["no_data"] += 1
            elif reason.startswith("price_too_low"):
                rejection_buckets["price<$3"] += 1
            elif reason.startswith("avg_dollar_vol_too_low"):
                rejection_buckets["dollar_vol<$3M"] += 1
            elif reason.startswith("insufficient_history"):
                rejection_buckets["insufficient_history"] += 1
            elif reason.startswith("market_cap_too_low"):
                rejection_buckets["mkt_cap<$150M"] += 1
            elif reason.startswith("price_below_200sma"):
                rejection_buckets["below_200sma"] += 1
            elif reason.startswith("atr_pct_too_low"):
                rejection_buckets["atr<1.5%"] += 1
            elif reason.startswith("atr_pct_too_high"):
                rejection_buckets["atr>12%"] += 1
            elif reason.startswith("rs_below_top50pct"):
                rejection_buckets["rs_bottom50%"] += 1
            elif reason.startswith("earnings_within"):
                rejection_buckets["earnings_blackout"] += 1
            elif reason.startswith("economic_blackout"):
                rejection_buckets["econ_blackout"] += 1
            elif reason.startswith("fcf_negative"):
                rejection_buckets["fcf+debt"] += 1
            else:
                rejection_buckets["other"] += 1
        breakdown_str = " | ".join(
            f"{label}:{count}" for label, count in rejection_buckets.most_common()
        )
        log_event(db, "scan", f"🔎 Rejection breakdown: {breakdown_str}")

        # ── Diagnostic: sample no_data tickers for operator inspection ──────────
        no_data_tickers = [
            t for t, r in rejections.items()
            if r.startswith("no_price_data") or r.startswith("price_parse") or r.startswith("volume_parse")
        ]
        if no_data_tickers:
            sample = no_data_tickers[:10]
            log_event(
                db, "scan",
                f"🔍 no_data sample ({len(no_data_tickers)} total): {', '.join(sample)}"
                + (" …" if len(no_data_tickers) > 10 else "")
            )


        if not shortlist:
            log_event(db, "scan",
                      "✅ No candidates passed all mandatory filters — no trade today. "
                      "This is a valid system output.")
            from strategy.journal import log_no_trade_day, log_scan_result
            log_no_trade_day(db, "no_filter_survivors",
                             "All tickers failed mandatory filter gates.")
            log_scan_result(db, scan_date, regime, regime_data["details"], 0, 0, 0,
                            "no_trade", [], dict(list(rejections.items())[:50]))
            return

        # ── Step 4: Score ─────────────────────────────────────────────────────
        from strategy.data_layer import fetch_sector_etf_returns
        from strategy.scoring_engine import score_all_candidates, compute_confidence_score, SCORE_HIGH_CONVICTION, SCORE_MARGINAL, WEIGHTS, MAX_POSITIVE_WEIGHT
        sector_returns = fetch_sector_etf_returns()
        open_positions = _get_open_positions_with_sectors(db)

        log_event(db, "scan", f"📈 Scoring {len(shortlist)} candidates…")
        high_conviction, marginal, no_trade_list = score_all_candidates(
            shortlist, sector_returns, regime, open_positions
        )

        all_scored = high_conviction + marginal + no_trade_list
        log_event(db, "scan",
                  f"Scoring done: {len(high_conviction)} high-conviction (≥{SCORE_HIGH_CONVICTION}), "
                  f"{len(marginal)} marginal ({SCORE_MARGINAL}-{SCORE_HIGH_CONVICTION-0.1}), {len(no_trade_list)} no-trade (<{SCORE_MARGINAL}).")

        # ── Diagnostic: full per-metric breakdown for every scored candidate ─────────
        for c in all_scored[:20]:
            sub     = c.get("sub_scores", {})
            gaps    = set(c.get("data_gaps", []))
            eff_w   = c.get("effective_max_weight", MAX_POSITIVE_WEIGHT)
            pens    = c.get("penalties", {})

            # Line 1: summary — score, effective denominator, data gaps
            gap_str = ", ".join(sorted(gaps)) if gaps else "none"
            log_event(db, "scan", (
                f"📊 {c['ticker']}: {c['composite_score']}/100 "
                f"[eff_denom={eff_w}/{MAX_POSITIVE_WEIGHT}] "
                f"| data_gaps: {gap_str}"
            ))

            # Line 2: all metric sub-scores and weighted contributions
            parts = []
            for k in sorted(WEIGHTS.keys()):
                s  = sub.get(k, 0.0)
                ws = round(s * WEIGHTS[k], 2)
                flag = "⚫" if k in gaps else ""
                parts.append(f"{k}={s:.2f}×{WEIGHTS[k]}={ws:.2f}{flag}")
            pen_str = (f"si_pen={pens.get('short_interest', 0):.2f} "
                      f"gap_hist_pen={pens.get('gap_history', 0):.2f}")
            log_event(db, "scan", f"   ↳ {'  |  '.join(parts)}  |  {pen_str}")

        if not high_conviction and not marginal:
            log_event(db, "scan",
                      f"✅ No candidates scored above {SCORE_MARGINAL} — no trade today. "
                      "This is a valid system output.")
            from strategy.journal import log_no_trade_day, log_scan_result
            log_no_trade_day(db, "no_scoring_threshold", f"All candidates scored below {SCORE_MARGINAL}.")
            log_scan_result(db, scan_date, regime, regime_data["details"],
                            len(shortlist), 0, 0, "no_trade",
                            [_strip_df(c) for c in all_scored[:20]], {})
            return

        # ── Step 5: AI analysis ───────────────────────────────────────────────
        candidates_for_ai = high_conviction[:10] + marginal[:5]  # Top 15 max
        log_event(db, "scan", f"🤖 Running AI analysis on {len(candidates_for_ai)} top candidates…")

        from strategy.ai_layer import analyze_candidates_batch
        verdicts = analyze_candidates_batch(
            candidates_for_ai, regime_data["details"], max_candidates=10
        )

        approved_verdicts = [v for v in verdicts if v.get("proceed")]
        log_event(db, "scan",
                  f"AI result: {len(approved_verdicts)}/{len(verdicts)} candidates approved.")

        if not approved_verdicts:
            log_event(db, "scan",
                      "✅ AI rejected all candidates — no trade today. "
                      "This is a valid system output.")
            from strategy.journal import log_no_trade_day, log_scan_result
            log_no_trade_day(db, "ai_rejected_all",
                             f"AI analyzed {len(verdicts)} candidates, approved 0.")
            log_scan_result(db, scan_date, regime, regime_data["details"],
                            len(shortlist), len(high_conviction), len(marginal),
                            "ai_rejected", [_strip_df(c) for c in all_scored[:20]], {})
            return

        # ── Step 6: Merge AI verdicts with scored metrics ─────────────────────
        # Build lookup for score data
        score_by_ticker = {c["ticker"]: c for c in all_scored}
        staged_candidates = []
        for verdict in approved_verdicts:
            ticker = verdict["ticker"]
            scored = score_by_ticker.get(ticker, {})
            staged = {**scored, **verdict}  # scored metrics + AI verdict
            # Compute final confidence score
            staged["confidence_score"] = compute_confidence_score(
                composite_score=scored.get("composite_score", 0),
                ai_gemini_score=verdict.get("gemini_raw", {}).get("conviction") if verdict.get("gemini_raw") else None,
                ai_deepseek_score=verdict.get("crosscheck_raw", {}).get("conviction") if verdict.get("crosscheck_raw") else None,
                regime=regime,
                filter_margin=0.5,
            )
            staged_candidates.append(staged)

        # ── Step 7: Persist AIPick records for UI ─────────────────────────────
        for rank, candidate in enumerate(staged_candidates, 1):
            pick = AIPick(
                scan_date=scan_date,
                ticker=candidate["ticker"],
                reason=candidate.get("entry_notes", ""),
                confidence=round(candidate.get("confidence_score", 0) / 100, 2),
                position_size_pct=None,
                rank=rank,
            )
            db.add(pick)
        db.commit()

        # ── Step 8: Store staged candidates for entry monitor ─────────────────
        with _pending_candidates_lock:
            _pending_candidates = staged_candidates
            _scan_date_today = scan_date

        log_event(db, "scan",
                  f"✅ Pre-market scan complete: {len(staged_candidates)} candidate(s) staged for entry. "
                  f"Intraday entry monitor will place orders when conditions are met.")

        # ── Persist scan result ───────────────────────────────────────────────
        from strategy.journal import log_scan_result
        log_scan_result(
            db, scan_date, regime, regime_data["details"],
            len(shortlist), len(high_conviction), len(marginal),
            "trade",
            [_strip_df(c) for c in staged_candidates],
            dict(list(rejections.items())[:50]),
        )

    except Exception as exc:
        logger.exception("Pre-market scan crashed: %s", exc)
        try:
            log_event(db, "system", f"Pre-market scan crashed: {exc}", "ERROR")
        except Exception:
            pass
    finally:
        db.close()


def _strip_df(candidate: dict) -> dict:
    """Remove non-serialisable DataFrame objects from a candidate dict."""
    return {k: v for k, v in candidate.items() if k != "ohlcv_df"}


# ---------------------------------------------------------------------------
# Job 2: Entry Monitor (09:45–15:30 ET, every 5 min)
# ---------------------------------------------------------------------------

def job_entry_monitor():
    """
    Checks pending candidates for intraday entry confirmation.
    Places limit orders + ATR-based native stop orders when all Section 8
    conditions are met and all risk engine gates pass.

    Only runs if there are pending candidates from today's pre-market scan.
    """
    global _pending_candidates, _scan_date_today

    db = SessionLocal()
    try:
        trader_enabled = get_setting(db, "trader_enabled", "true")
        if trader_enabled.lower() != "true":
            return

        if not is_market_open():
            return

        with _pending_candidates_lock:
            candidates = list(_pending_candidates)
            scan_date = _scan_date_today

        if not candidates:
            return

        # Only act on today's candidates
        if scan_date != datetime.now(timezone.utc).date():
            logger.info("[EntryMonitor] Candidates are from a previous day — clearing.")
            with _pending_candidates_lock:
                _pending_candidates.clear()
                _scan_date_today = None
            return

        trading_mode = get_setting(db, "trading_mode", "paper")
        client = IBKRClient(trading_mode=trading_mode)
        if not client.connect():
            log_event(db, "ibkr",
                      "Entry monitor: could not connect to IBKR — skipping this cycle.",
                      "WARNING")
            return
        client.start_keepalive(interval=30)

        account = client.get_account_summary()
        account_equity = account.get("NetLiquidation", 0)

        if account_equity <= 0:
            log_event(db, "ibkr",
                      "Entry monitor: account equity is 0 or unavailable — skipping.", "WARNING")
            client.disconnect()
            return

        open_positions = _get_open_positions_with_sectors(db)
        peak_equity = _get_peak_equity(db)
        weekly_pnl_pct = _compute_weekly_pnl_pct(db, account_equity)

        from strategy.risk_engine import get_risk_engine
        from strategy.entry_engine import prepare_entry_order
        risk_engine = get_risk_engine()

        placed_this_cycle = 0

        for candidate in candidates[:]:  # iterate over a copy
            ticker = candidate["ticker"]

            # Skip if already have a trade for this ticker today
            existing = db.query(Trade).filter(
                Trade.ticker == ticker,
                Trade.status.in_(["open", "sold_half", "closing"]),
            ).first()
            if existing:
                continue

            order_info = prepare_entry_order(
                candidate=candidate,
                account_equity=account_equity,
                open_positions=open_positions,
                risk_engine=risk_engine,
            )

            if order_info is None:
                continue

            shares = order_info["shares"]
            limit_price = order_info["limit_price"]
            stop_price  = order_info["stop_price"]
            partial_target = order_info["partial_target_price"]
            atr_abs     = order_info["atr_abs"]
            sector      = order_info["sector"]

            log_event(db, "buy",
                      f"🟢 {ticker}: placing limit order — "
                      f"{shares} shares @ ${limit_price:.4f} (limit) | "
                      f"stop=${stop_price:.4f} | 1.5R=${partial_target:.4f} | "
                      f"score={candidate.get('composite_score', 0):.1f} | "
                      f"confidence={order_info.get('confidence_score', 0)}")

            # Place limit buy order
            result = client.place_limit_buy_order(ticker, shares, limit_price)

            if not result.get("success"):
                log_event(db, "buy",
                          f"❌ {ticker}: limit order failed — {result.get('error')}", "ERROR")
                continue

            fill_price = result.get("price", limit_price)
            order_id   = result.get("order_id", "")

            # Place native stop order at IBKR
            stop_result = client.place_stop_order(ticker, shares, stop_price)
            stop_order_id = stop_result.get("order_id") if stop_result.get("success") else None
            if not stop_result.get("success"):
                log_event(db, "buy",
                          f"⚠️ {ticker}: stop order placement failed — {stop_result.get('error')}. "
                          f"Software monitor will act as fallback.", "WARNING")

            # Record trade in DB
            trade = Trade(
                ticker=ticker,
                shares=shares,
                buy_price=fill_price,
                buy_time=datetime.now(timezone.utc),
                status="open",
                mode=trading_mode,
                order_id=str(order_id),
                ai_reason=candidate.get("entry_notes", ""),
                stop_price=stop_price,
                stop_order_id=str(stop_order_id) if stop_order_id else None,
                partial_target_price=partial_target,
                partial_sold=False,
                atr_at_entry=atr_abs,
                entry_composite_score=candidate.get("composite_score"),
                sector=sector,
            )
            db.add(trade)
            db.commit()

            # Journal the entry event
            from strategy.journal import log_trade_event
            log_trade_event(
                db, trade.id, "entry",
                details=order_info.get("entry_reason", ""),
                composite_score=candidate.get("composite_score"),
                confidence_score=order_info.get("confidence_score"),
                stop_price=stop_price,
                ai_gemini_json=candidate.get("gemini_raw"),
                ai_crosscheck_json=candidate.get("crosscheck_raw"),
                regime_at_event=order_info.get("regime"),
            )

            log_event(db, "buy",
                      f"✅ {ticker}: {shares} shares bought @ ${fill_price:.4f} | "
                      f"stop=${stop_price:.4f} | "
                      f"1.5R target=${partial_target:.4f} | "
                      f"risk=${order_info.get('risk_dollar', 0):.2f}")

            placed_this_cycle += 1
            # Remove candidate from pending list
            with _pending_candidates_lock:
                _pending_candidates = [c for c in _pending_candidates
                                       if c.get("ticker") != ticker]

        client.disconnect()

        if placed_this_cycle:
            log_event(db, "buy",
                      f"Entry monitor cycle complete: {placed_this_cycle} order(s) placed.")

    except Exception as exc:
        logger.exception("Entry monitor crashed: %s", exc)
        try:
            log_event(db, "system", f"Entry monitor crashed: {exc}", "ERROR")
        except Exception:
            pass
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Job 3: Exit Monitor (09:30–16:00 ET, every 5 min)
# ---------------------------------------------------------------------------

def job_exit_monitor():
    """
    Checks all open positions against all Section 9 exit rules:
      - Hard stop-loss (software safety net for native IBKR stop)
      - 1.5R partial exit (sell 50% and move stop to breakeven)
      - Chandelier trailing stop
      - MA trend break (20-day SMA)
      - Time exits (10d soft warning, 20d hard exit)
      - ATR expansion exit (volatility regime change)
      - Pre-event exit (earnings within 2 trading days)

    IMPORTANT: Exit checks run regardless of circuit breaker state.
    The risk engine only gates NEW entries — existing positions always
    have their exits monitored.
    """
    db = SessionLocal()
    try:
        trader_enabled = get_setting(db, "trader_enabled", "true")
        if trader_enabled.lower() != "true":
            return

        if not is_market_open():
            return

        trading_mode = get_setting(db, "trading_mode", "paper")
        open_trades = db.query(Trade).filter(Trade.status.in_(["open", "sold_half"])).all()

        if not open_trades:
            return

        client = IBKRClient(trading_mode=trading_mode)
        if not client.connect():
            logger.warning("[ExitMonitor] Could not connect to IBKR — skipping this cycle.")
            return
        client.start_keepalive(interval=30)

        # Fetch fresh prices for all open tickers
        live_positions = client.get_positions()
        live_by_ticker = {p["ticker"]: p for p in live_positions}

        # Sync untracked IBKR positions
        _sync_untracked_ibkr_positions(db, live_positions, trading_mode)

        account = client.get_account_summary()
        account_equity = account.get("NetLiquidation", 0)

        from strategy.exit_engine import check_exit_conditions
        from strategy.journal import log_trade_event

        for trade in open_trades:
            ticker = trade.ticker
            pos = live_by_ticker.get(ticker)
            if pos is None:
                continue

            live_shares = int(pos.get("shares", 0))
            current_price = pos.get("current_price", 0)

            if live_shares == 0 or current_price <= 0:
                continue

            # Re-read trade in case a concurrent run just changed its status
            db.refresh(trade)
            if trade.status not in ("open", "sold_half"):
                continue

            signal = check_exit_conditions(
                trade=trade,
                current_price=current_price,
                live_shares=live_shares,
                account_equity=account_equity,
            )

            # ── Trail update (no sell, just update stop price) ────────────────
            if signal.action == "hold" and signal.reason == "trail_update" and signal.new_stop_price:
                trade.trailing_stop_price = signal.new_stop_price
                db.commit()
                logger.info("[ExitMonitor] %s: trailing stop updated to $%.4f",
                            ticker, signal.new_stop_price)
                log_trade_event(db, trade.id, "trail_update", signal.details,
                                trailing_stop_price=signal.new_stop_price)
                continue

            # ── Soft warning (log only, no action) ───────────────────────────
            if signal.action == "hold":
                if signal.reason == "time_exit_soft_warning":
                    log_event(db, "sell",
                              f"⏳ {ticker}: {signal.details}", "WARNING")
                continue

            # ── Partial exit (1.5R) ───────────────────────────────────────────
            if signal.action == "partial_exit":
                shares_to_sell = signal.shares_to_sell or max(1, live_shares // 2)
                log_event(db, "sell",
                          f"💰 {ticker}: 1.5R partial exit — selling {shares_to_sell}/{live_shares} shares. "
                          f"{signal.details}")

                # Mark as closing to prevent concurrent races
                trade.status = "closing"
                db.commit()

                result = client.place_sell_order(ticker, shares_to_sell)
                if result["success"]:
                    sell_price = result["price"]
                    partial_pnl = (sell_price - (trade.buy_price or 0)) * shares_to_sell
                    trade.realised_partial_pnl = round(partial_pnl, 2)
                    trade.partial_sold = True
                    trade.status = "sold_half"
                    # Move stop to breakeven
                    if signal.new_stop_price:
                        trade.stop_price = signal.new_stop_price
                    db.commit()

                    log_event(db, "sell",
                              f"💰 {ticker}: partial exit filled @ ${sell_price:.4f} | "
                              f"realised +${partial_pnl:.2f} | stop moved to breakeven")
                    log_trade_event(db, trade.id, "partial_exit",
                                    f"1.5R partial: sold {shares_to_sell} @ ${sell_price:.4f}. P&L=${partial_pnl:.2f}",
                                    stop_price=signal.new_stop_price)
                else:
                    trade.status = "open"  # Revert
                    db.commit()
                    log_event(db, "sell",
                              f"❌ {ticker}: partial exit failed — {result.get('error')}. Retrying next cycle.",
                              "ERROR")
                continue

            # ── Full exit (stop, trail, MA, time, ATR expansion, pre-event) ──
            if signal.action == "full_exit":
                log_event(db, "sell",
                          f"🔴 {ticker}: {signal.reason} — {signal.details}")

                prev_status = trade.status
                trade.status = "closing"
                db.commit()

                result = client.place_sell_order(ticker, live_shares)
                if result["success"]:
                    sell_price = result["price"]
                    buy_price  = trade.buy_price or 0
                    partial_already = trade.realised_partial_pnl or 0.0
                    remaining_pnl = (sell_price - buy_price) * live_shares
                    total_pnl = remaining_pnl + partial_already

                    original_cost = buy_price * trade.shares if trade.shares else 1
                    pnl_pct = (total_pnl / original_cost * 100) if original_cost else 0.0

                    trade.sell_price = sell_price
                    trade.sell_time  = datetime.now(timezone.utc)
                    trade.status     = "closed"
                    trade.pnl        = round(total_pnl, 2)
                    trade.pnl_pct    = round(pnl_pct, 2)
                    trade.fees       = round((trade.fees or 0.0) + result.get("fees", 0.0), 4)
                    db.commit()

                    emoji = "🟢" if total_pnl >= 0 else "🔴"
                    log_event(db, "sell",
                              f"{emoji} {ticker} closed ({signal.reason}): "
                              f"sold {live_shares} @ ${sell_price:.4f} | "
                              f"P&L: ${total_pnl:+.2f} ({pnl_pct:+.2f}%)")
                    log_trade_event(db, trade.id, signal.reason,
                                    signal.details, stop_price=trade.stop_price)
                else:
                    trade.status = prev_status  # Revert
                    db.commit()
                    log_event(db, "sell",
                              f"❌ {ticker}: exit order failed ({signal.reason}): "
                              f"{result.get('error')}. Retrying next cycle.", "ERROR")

        # Reconcile any stale DB records
        live_tickers = {p["ticker"] for p in live_positions}
        _reconcile_stale_db_trades(db, live_tickers)

        client.disconnect()

    except Exception as exc:
        logger.exception("Exit monitor crashed: %s", exc)
        try:
            log_event(db, "system", f"Exit monitor crashed: {exc}", "ERROR")
        except Exception:
            pass
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Job 4: EOD Snapshot (15:45 ET Mon-Fri) — unchanged from previous system
# ---------------------------------------------------------------------------

def job_eod_snapshot() -> None:
    """
    Captures a daily end-of-day NetLiquidation snapshot.
    Also used by the risk engine to track peak equity for drawdown circuit breakers.
    """
    db = SessionLocal()
    try:
        trading_mode = get_setting(db, "trading_mode", "paper")
        client = IBKRClient(trading_mode=trading_mode)
        if not client.connect():
            log_event(db, "ibkr",
                      "Snapshot job: could not connect to IB Gateway — skipping.", "WARNING")
            return

        client.start_keepalive(interval=30)
        account = client.get_account_summary()
        client.disconnect()

        net_liq_usd = account.get("NetLiquidation", 0)
        net_liq_aud = account.get("NetLiquidation_AUD", None)
        fx_rate     = account.get("ExchangeRate_USD", None)

        if not net_liq_usd:
            log_event(db, "system",
                      "Snapshot job: NetLiquidation is 0 or missing — skipping.", "WARNING")
            return

        today = datetime.now(timezone.utc).date()
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

    except Exception as exc:
        logger.exception("EOD snapshot crashed: %s", exc)
        try:
            log_event(db, "system", f"EOD snapshot crashed: {exc}", "ERROR")
        except Exception:
            pass
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Manual trigger (called by POST /api/scan)
# ---------------------------------------------------------------------------

def job_manual_scan():
    """
    Trigger a full pre-market scan manually (from the API or dashboard).
    Runs the same pipeline as job_pre_market_scan.
    """
    job_pre_market_scan()

def job_manual_scan_with_deferred_buy():
    """
    Triggered by POST /api/scan.
    Runs the pre-market scan, and if the market is open, immediately runs the entry monitor
    to place orders.
    """
    job_manual_scan()
    if is_market_open():
        job_entry_monitor()
