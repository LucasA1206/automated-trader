# Graph Report - automated-trader  (2026-11-23)

## Corpus Check
- 68 files · ~81,448 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 10 file(s) not represented in the graph (top: (none) 6, .toml 1, .ico 1)

## Summary
- 947 nodes · 1863 edges · 63 communities (31 shown, 32 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 104 edges (avg confidence: 0.88)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- AI Analyst & Gemini Insights
- Next.js Dashboard Views
- Multi-Factor Scoring Engine
- Frontend App Shell & Auth Context
- Financial Data & Fundamentals Ingestion
- Market Regime & VIX Verification
- Batch OHLCV Downloader & Cache
- Market Tiers & Gap-Down Veto
- Docker Infrastructure & Compose
- Cryptographic Auth & JWT RBAC
- Job Execution & System Logging
- Trade Exits & Earnings Defense
- Database Models & Settings Store
- Risk Management & Beta Sizing
- Market Breadth & Sector Leadership
- FastAPI Routing & FX Conversion
- Security Headers & Rate Limiting
- API Alpha & System Logs Endpoints
- TypeScript Configuration & Types
- Backtest Engine & Historical Simulation
- Intraday VWAP & Pullback Timing
- Background Task Scheduler
- Scan Automation & Ticker Screener
- Trailing Breakeven Stop Tests
- Portfolio Risk State Monitor
- Authentication Endpoints & Sessions
- IBKR Liquidation & Order Execution
- IBKR Gateway Keepalive Service
- Universe Breadth Calculations
- Market Hours & PnL Metrics
- Manual Scan & Snapshot Triggers
- Strategy Configuration Store
- Market-Linked Exit Triggers
- Settings API & PnL Reset
- Stop-Loss Order Modifications
- Limit & Cover Order Execution
- Portfolio Metrics & Settings API
- Shadow Gate Trade Evaluations
- Zero Look-Ahead Backtest Core
- Historical AI Analysis Records
- Trading Blueprint Strategy Core
- Candidate Ranking & Tiebreaking
- Next.js Build Configuration
- HTTP Resiliency & Retries
- Vercel Routing & Edge Proxy
- Railway & Gateway Deployment Docs
- Tailwind & PostCSS Styling Config
- Live Trading Checklist & Killswitch
- Position Sizing & Risk Docs
- Backend Dependency Manifest
- Python Runtime Version Spec
- Frontend Agent Guidelines
- Claude Assistant Prompt Spec
- File SVG Icon Asset
- Globe SVG Icon Asset
- Next.js SVG Logo Asset
- Vercel SVG Logo Asset
- Window SVG Icon Asset
- Frontend Dashboard Documentation
- Blitz Trader Repository Overview

## God Nodes (most connected - your core abstractions)
1. `IBKRClient` - 35 edges
2. `compute_composite_score()` - 30 edges
3. `job_pre_market_scan()` - 29 edges
4. `job_exit_monitor()` - 27 edges
5. `compute_regime_status()` - 26 edges
6. `job_entry_monitor()` - 25 edges
7. `Trade` - 24 edges
8. `TestPhase2MarketState` - 24 edges
9. `get_setting()` - 22 edges
10. `fetch_ohlcv()` - 22 edges

## Surprising Connections (you probably didn't know these)
- `lifespan()` --indirect_call--> `start_persistent_keepalive()`  [INFERRED]
  backend/api_server.py → backend/jobs.py
- `get_portfolio()` --uses--> `Trade`  [INFERRED]
  backend/api_server.py → backend/models.py
- `get_trades()` --uses--> `Trade`  [INFERRED]
  backend/api_server.py → backend/models.py
- `get_ai_picks()` --uses--> `AIPick`  [INFERRED]
  backend/api_server.py → backend/models.py
- `get_scan_history()` --uses--> `ScanResult`  [INFERRED]
  backend/api_server.py → backend/models.py

## Import Cycles
- 2-file cycle: `frontend/app/page.tsx -> frontend/components/Sidebar.tsx -> frontend/app/page.tsx`

## Hyperedges (group relationships)
- **Systematic Trading Bot Core Strategy Pipeline** — systematic_trading_bot_blueprint_momentum_swing_trading, systematic_trading_bot_blueprint_market_regime_filter, systematic_trading_bot_blueprint_gap_down_veto, systematic_trading_bot_blueprint_position_sizing_risk, systematic_trading_bot_blueprint_atr_exit_engine [EXTRACTED 0.95]

## Communities (63 total, 32 thin omitted)

### Community 0 - "AI Analyst & Gemini Insights"
Cohesion: 0.06
Nodes (21): analyse_with_gemini(), check_market_regime(), _compute_rsi(), fetch_full_nasdaq_tickers(), fetch_news_for_ticker(), fetch_technicals_batch(), _fetch_technicals_for_ticker(), fetch_top_movers_news() (+13 more)

### Community 1 - "Next.js Dashboard Views"
Cohesion: 0.07
Nodes (41): Home(), Tab, tabTitles, AIAnalysisData, AIAnalysisTab(), AuthFetch, Candidate, DayAnalysis (+33 more)

### Community 2 - "Multi-Factor Scoring Engine"
Cohesion: 0.07
Nodes (23): _compute_bollinger(), compute_composite_score(), _percentile_rank(), score_52w_high_proximity(), score_adx(), score_beta(), score_bollinger_position(), score_breakout_quality() (+15 more)

### Community 3 - "Frontend App Shell & Auth Context"
Cohesion: 0.06
Nodes (40): metadata, RootLayout(), viewport, AuthProvider(), eslintConfig, dependencies, next@^16.4.6, react@19.2.4 (+32 more)

### Community 4 - "Financial Data & Fundamentals Ingestion"
Cohesion: 0.08
Nodes (17): fetch_economic_calendar(), fetch_fundamentals(), fetch_fundamentals_batch(), _fetch(), fetch_next_earnings_date(), _fetch(), _fetch(), fetch_sector_etf_returns() (+9 more)

### Community 5 - "Market Regime & VIX Verification"
Cohesion: 0.07
Nodes (4): compute_regime_status(), _is_valid_spy_dict(), _is_valid_vix_dict(), TestRegimeFailSafe

### Community 6 - "Batch OHLCV Downloader & Cache"
Cohesion: 0.07
Nodes (18): fetch_ohlcv_batch(), _download_chunk(), is_economic_blackout_day(), prime_ohlcv_cache(), reset_yfinance_block(), _sanity_check_ohlcv(), apply_fcf_compound_filter(), apply_relative_strength_threshold() (+10 more)

### Community 7 - "Market Tiers & Gap-Down Veto"
Cohesion: 0.07
Nodes (3): check_gap_down_veto(), classify_market_tier(), TestPhase2MarketState

### Community 8 - "Docker Infrastructure & Compose"
Cohesion: 0.06
Nodes (33): build, command, depends_on, environment, ports, restart, volumes, context (+25 more)

### Community 9 - "Cryptographic Auth & JWT RBAC"
Cohesion: 0.08
Nodes (8): create_access_token(), decode_token(), hash_password(), require_admin(), require_auth(), validate_credentials(), verify_password(), TestSecurityHardening

### Community 10 - "Job Execution & System Logging"
Cohesion: 0.11
Nodes (14): log_event(), _count_open_positions(), ensure_pending_candidates_loaded(), _get_open_positions_with_sectors(), job_manual_entry_monitor(), _reconcile_stale_db_trades(), _sync_untracked_ibkr_positions(), ScanResult (+6 more)

### Community 11 - "Trade Exits & Earnings Defense"
Cohesion: 0.11
Nodes (9): fetch_ohlcv(), is_near_earnings(), check_exit_conditions(), compute_chandelier_trail(), ExitSignal, _get_trading_days_since(), check_mean_reversion_exit(), compute_rsi2() (+1 more)

### Community 12 - "Database Models & Settings Store"
Cohesion: 0.11
Nodes (5): init_db(), set_setting(), AccountSnapshot, Setting, TradeJournalEntry

### Community 13 - "Risk Management & Beta Sizing"
Cohesion: 0.09
Nodes (4): compute_empirical_beta(), get_risk_engine(), RiskEngine, TestPhase3IntradaySectorBeta

### Community 14 - "Market Breadth & Sector Leadership"
Cohesion: 0.13
Nodes (6): calculate_beta_scalar(), check_sector_leadership(), check_spy_intraday_confirmation(), get_latest_breadth(), rank_sectors_by_leadership(), set_latest_breadth()

### Community 15 - "FastAPI Routing & FX Conversion"
Cohesion: 0.11
Nodes (10): exchange_rate(), get_fx_rate(), lifespan(), _refresh_fx_rate(), SellStockRequest, SettingsBulkUpdate, SettingUpdate, stop_scan() (+2 more)

### Community 16 - "Security Headers & Rate Limiting"
Cohesion: 0.10
Nodes (5): get_client_ip(), rate_limit_endpoint(), dependency(), RateLimiter, SecurityHeadersMiddleware

### Community 17 - "API Alpha & System Logs Endpoints"
Cohesion: 0.13
Nodes (10): get_ai_picks(), get_alpha_analysis(), get_logs(), get_pending_candidates(), get_pnl_history(), get_scan_history(), get_scan_status(), get_shadow_report() (+2 more)

### Community 18 - "TypeScript Configuration & Types"
Cohesion: 0.11
Nodes (18): compilerOptions, allowJs, esModuleInterop, incremental, isolatedModules, jsx, lib, module (+10 more)

### Community 20 - "Intraday VWAP & Pullback Timing"
Cohesion: 0.16
Nodes (8): estimate_vwap(), check_entry_confirmation(), is_within_entry_window(), prepare_entry_order(), compute_initial_stop(), compute_partial_target(), _compute_macd_histogram(), _compute_rsi()

### Community 21 - "Background Task Scheduler"
Cohesion: 0.15
Nodes (4): job_eod_snapshot(), job_exit_monitor(), create_scheduler(), get_next_job_times()

### Community 22 - "Scan Automation & Ticker Screener"
Cohesion: 0.12
Nodes (7): _fetch_ticker_universe(), job_manual_scan(), job_pre_market_scan(), _strip_df(), analyze_candidates_batch(), clear_all_caches(), compute_confidence_score()

### Community 24 - "Portfolio Risk State Monitor"
Cohesion: 0.17
Nodes (4): get_risk_state(), _fetch_ohlcv_ibkr(), get_ib_port(), IBKRClient

### Community 25 - "Authentication Endpoints & Sessions"
Cohesion: 0.18
Nodes (5): login(), LoginRequest, logout(), clear_auth_cookie(), set_auth_cookie()

### Community 26 - "IBKR Liquidation & Order Execution"
Cohesion: 0.21
Nodes (4): sell_all_ibkr(), sell_single_stock(), get_setting(), job_deferred_sell_single()

### Community 29 - "Market Hours & PnL Metrics"
Cohesion: 0.20
Nodes (6): _compute_weekly_pnl_pct(), _get_peak_equity(), is_market_open(), job_entry_monitor(), job_manual_scan_with_deferred_buy(), seconds_until_market_open()

### Community 30 - "Manual Scan & Snapshot Triggers"
Cohesion: 0.24
Nodes (4): trigger_entry_monitor(), trigger_scan(), trigger_sell(), trigger_snapshot()

### Community 32 - "Market-Linked Exit Triggers"
Cohesion: 0.27
Nodes (3): check_market_linked_exit_trigger(), compute_earnings_season_density(), TestPhase4ExitsEarnings

### Community 33 - "Settings API & PnL Reset"
Cohesion: 0.22
Nodes (4): reset_pnl_history(), _sync_strategy_settings(), update_settings(), SystemLog

### Community 36 - "Portfolio Metrics & Settings API"
Cohesion: 0.29
Nodes (5): _build_margin_upgrade_alert(), get_portfolio(), get_settings(), _normalize_account_type(), _normalize_paper_strategy()

### Community 40 - "Trading Blueprint Strategy Core"
Cohesion: 0.33
Nodes (6): ATR-Based Trailing Stop & Profit Targets, Dual-Model AI Review Layer (Gemini & DeepSeek), Gap-Down Veto Circuit Breaker, Market Regime Filter (SPY 200 SMA & VIX), Momentum Swing Trading Strategy, Sector Relative Strength Filter

## Knowledge Gaps
- **21 isolated node(s):** `Gap-Down Veto Circuit Breaker`, `Dual-Model AI Review Layer (Gemini & DeepSeek)`, `ATR-Based Trailing Stop & Profit Targets`, `Risk Engine & Dynamic Position Sizing`, `Market Breadth Sizing Tiers (A/B/C)` (+16 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 471 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **32 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `compute_regime_status()` connect `Market Regime & VIX Verification` to `Financial Data & Fundamentals Ingestion`, `Job Execution & System Logging`, `FastAPI Routing & FX Conversion`, `Intraday VWAP & Pullback Timing`, `Scan Automation & Ticker Screener`, `Portfolio Risk State Monitor`?**
  _High betweenness centrality (0.055) - this node is a cross-community bridge._
- **Are the 11 inferred relationships involving `job_exit_monitor()` (e.g. with `trigger_sell()` and `Trade`) actually correct?**
  _`job_exit_monitor()` has 11 INFERRED edges - model-reasoned connections that need verification._
- **What connects `Gap-Down Veto Circuit Breaker`, `Dual-Model AI Review Layer (Gemini & DeepSeek)`, `ATR-Based Trailing Stop & Profit Targets` to the rest of the system?**
  _21 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `AI Analyst & Gemini Insights` be split into smaller, more focused modules?**
  _Cohesion score 0.05647058823529412 - nodes in this community are weakly interconnected._
- **Why does `IBKRClient` connect `Portfolio Risk State Monitor` to `Stop-Loss Order Modifications`, `Limit & Cover Order Execution`, `Portfolio Metrics & Settings API`, `Financial Data & Fundamentals Ingestion`, `Job Execution & System Logging`, `FastAPI Routing & FX Conversion`, `Backtest Engine & Historical Simulation`, `Background Task Scheduler`, `IBKR Liquidation & Order Execution`, `IBKR Gateway Keepalive Service`, `Market Hours & PnL Metrics`?**
  _High betweenness centrality (0.040) - this node is a cross-community bridge._
- **Should `Next.js Dashboard Views` be split into smaller, more focused modules?**
  _Cohesion score 0.06745098039215686 - nodes in this community are weakly interconnected._
- **Why does `classify_market_tier()` connect `Market Tiers & Gap-Down Veto` to `Job Execution & System Logging`, `Strategy Configuration Store`, `Scan Automation & Ticker Screener`, `Market Breadth & Sector Leadership`?**
  _High betweenness centrality (0.027) - this node is a cross-community bridge._