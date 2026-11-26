# Graph Report - automated-trader  (2026-11-26)

## Corpus Check
- 27 files · ~97,528 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1136 nodes · 2420 edges · 71 communities (34 shown, 37 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 151 edges (avg confidence: 0.89)
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
- Next.js Environment Declarations
- Vercel Routing & Edge Proxy
- Strategy Package Metadata
- Railway & Gateway Deployment Docs
- Tailwind & PostCSS Styling Config
- Position Sizing & Risk Docs
- Frontend Agent Guidelines
- Claude Assistant Prompt Spec
- File SVG Icon Asset
- Globe SVG Icon Asset
- Next.js SVG Logo Asset
- Vercel SVG Logo Asset
- Window SVG Icon Asset
- Blitz Trader Repository Overview
- Claude Module
- File Module
- Globe Module
- Next Module
- Vercel Module
- Window Module
- Readme Module
- Readme Module

## God Nodes (most connected - your core abstractions)
1. `Trade` - 46 edges
2. `IBKRClient` - 37 edges
3. `get_system_config()` - 33 edges
4. `generate_weekly_report()` - 32 edges
5. `compute_composite_score()` - 30 edges
6. `fetch_ohlcv()` - 28 edges
7. `compute_regime_status()` - 27 edges
8. `job_entry_monitor()` - 25 edges
9. `job_data_quality_monitor()` - 25 edges
10. `TestPhase2MarketState` - 24 edges

## Surprising Connections (you probably didn't know these)
- `_count_open_positions()` --uses--> `Trade`  [INFERRED]
  backend/jobs.py → backend/models.py
- `TestPhase3IntradaySectorBeta` --uses--> `RiskEngine`  [INFERRED]
  backend/tests/test_phase3_intraday_sector_beta.py → backend/strategy/risk_engine.py
- `TestPhase5AlphaJournal` --uses--> `Trade`  [INFERRED]
  backend/tests/test_phase5_alpha_journal.py → backend/models.py
- `get_portfolio()` --uses--> `Trade`  [INFERRED]
  backend/api_server.py → backend/models.py
- `get_trades()` --uses--> `Trade`  [INFERRED]
  backend/api_server.py → backend/models.py

## Import Cycles
- 2-file cycle: `frontend/app/page.tsx -> frontend/components/Sidebar.tsx -> frontend/app/page.tsx`

## Hyperedges (group relationships)
- **Systematic Trading Bot Core Strategy Pipeline** — systematic_trading_bot_blueprint_momentum_swing_trading, systematic_trading_bot_blueprint_market_regime_filter, systematic_trading_bot_blueprint_gap_down_veto, systematic_trading_bot_blueprint_position_sizing_risk, systematic_trading_bot_blueprint_atr_exit_engine [EXTRACTED 0.95]

## Communities (71 total, 37 thin omitted)

### Community 0 - "AI Analyst & Gemini Insights"
Cohesion: 0.05
Nodes (30): apply_tiebreaking(), _compute_adx(), _compute_bollinger(), compute_composite_score(), compute_confidence_score(), _compute_gap_history_penalty(), _compute_macd_histogram(), _compute_rsi() (+22 more)

### Community 1 - "Next.js Dashboard Views"
Cohesion: 0.08
Nodes (12): get_risk_state(), sell_all_ibkr(), sell_single_stock(), get_setting(), job_deferred_sell_single(), job_eod_snapshot(), job_exit_monitor(), job_manual_entry_monitor() (+4 more)

### Community 2 - "Multi-Factor Scoring Engine"
Cohesion: 0.05
Nodes (22): analyse_with_gemini(), check_market_regime(), _compute_rsi(), fetch_full_nasdaq_tickers(), fetch_news_for_ticker(), fetch_technicals_batch(), _fetch_technicals_for_ticker(), fetch_top_movers_news() (+14 more)

### Community 3 - "Frontend App Shell & Auth Context"
Cohesion: 0.07
Nodes (22): log_event(), _compute_weekly_pnl_pct(), _count_open_positions(), ensure_pending_candidates_loaded(), _fetch_ticker_universe(), _get_open_positions_with_sectors(), _get_peak_equity(), is_market_open() (+14 more)

### Community 4 - "Financial Data & Fundamentals Ingestion"
Cohesion: 0.07
Nodes (18): estimate_vwap(), fetch_economic_calendar(), fetch_fundamentals(), fetch_fundamentals_batch(), _fetch(), fetch_next_earnings_date(), _fetch(), _fetch() (+10 more)

### Community 5 - "Market Regime & VIX Verification"
Cohesion: 0.07
Nodes (20): ack_monitoring_alert(), DeEscalateRequest, health(), login(), LoginRequest, logout(), post_derisk_deescalate(), reset_pnl_history() (+12 more)

### Community 6 - "Batch OHLCV Downloader & Cache"
Cohesion: 0.06
Nodes (40): metadata, RootLayout(), viewport, AuthProvider(), eslintConfig, dependencies, next@^16.4.6, react@19.2.4 (+32 more)

### Community 7 - "Market Tiers & Gap-Down Veto"
Cohesion: 0.08
Nodes (10): _load_from_db(), check_exit_conditions(), compute_chandelier_trail(), compute_initial_stop(), compute_partial_target(), ExitSignal, _get_trading_days_since(), check_mean_reversion_exit() (+2 more)

### Community 8 - "Docker Infrastructure & Compose"
Cohesion: 0.07
Nodes (4): compute_regime_status(), _is_valid_spy_dict(), _is_valid_vix_dict(), TestRegimeFailSafe

### Community 9 - "Cryptographic Auth & JWT RBAC"
Cohesion: 0.07
Nodes (19): _build_margin_upgrade_alert(), get_ai_analysis(), get_ai_picks(), get_alpha_analysis(), get_data_health(), get_logs(), get_monitoring_alerts(), get_pending_candidates() (+11 more)

### Community 10 - "Job Execution & System Logging"
Cohesion: 0.07
Nodes (10): clear_auth_cookie(), create_access_token(), decode_token(), hash_password(), require_admin(), require_auth(), set_auth_cookie(), validate_credentials() (+2 more)

### Community 11 - "Trade Exits & Earnings Defense"
Cohesion: 0.09
Nodes (11): calculate_beta_scalar(), check_market_linked_exit_trigger(), check_sector_leadership(), check_spy_intraday_confirmation(), compute_earnings_season_density(), compute_empirical_beta(), get_latest_breadth(), rank_sectors_by_leadership() (+3 more)

### Community 12 - "Database Models & Settings Store"
Cohesion: 0.09
Nodes (15): is_economic_blackout_day(), is_near_earnings(), reset_yfinance_block(), apply_fcf_compound_filter(), apply_relative_strength_threshold(), _compute_52w_high_proximity(), _compute_atr(), _compute_atr_pct() (+7 more)

### Community 13 - "Risk Management & Beta Sizing"
Cohesion: 0.08
Nodes (4): get_derisk_modifiers(), RiskEngine, TestFeature1DeRiskLadder, TestFeature3DataQuality

### Community 14 - "Market Breadth & Sector Leadership"
Cohesion: 0.06
Nodes (33): build, command, depends_on, environment, ports, restart, volumes, context (+25 more)

### Community 15 - "FastAPI Routing & FX Conversion"
Cohesion: 0.12
Nodes (8): get_system_config(), classify_evidence_strength(), compute_shadow_summary(), _get_cfg(), record_shadow_decision(), update_open_shadow_outcomes(), TestEndToEndSelfMonitoringDryRun, TestFeature4ShadowTracking

### Community 16 - "Security Headers & Rate Limiting"
Cohesion: 0.17
Nodes (10): resolve_alert_by_key(), check_api_health(), check_metric_coverage(), check_price_sanity(), check_regime_inputs(), check_score_distribution(), _get_cfg(), reconcile_positions_and_stops() (+2 more)

### Community 17 - "API Alpha & System Logs Endpoints"
Cohesion: 0.10
Nodes (5): get_client_ip(), rate_limit_endpoint(), dependency(), RateLimiter, SecurityHeadersMiddleware

### Community 19 - "Backtest Engine & Historical Simulation"
Cohesion: 0.15
Nodes (10): AIPick, Trade, _bucket_stats(), _confidence_bucket(), _entry_time_bucket(), _fetch_spy_period_return(), generate_weekly_report(), _group() (+2 more)

### Community 20 - "Intraday VWAP & Pullback Timing"
Cohesion: 0.19
Nodes (9): get_derisk_status(), emit_alert(), get_active_baseline(), compute_live_performance_metrics(), _ensure_state_row(), evaluate_derisk_ladder(), _get_cfg(), get_derisk_state() (+1 more)

### Community 21 - "Background Task Scheduler"
Cohesion: 0.12
Nodes (9): exchange_rate(), get_fx_rate(), lifespan(), _refresh_fx_rate(), _sync_strategy_settings(), update_settings(), set_setting(), start_persistent_keepalive() (+1 more)

### Community 22 - "Scan Automation & Ticker Screener"
Cohesion: 0.13
Nodes (9): fetch_ohlcv(), fetch_ohlcv_batch(), _download_chunk(), _fetch_ohlcv_ibkr(), prime_ohlcv_cache(), _sanity_check_ohlcv(), check_entry_confirmation(), is_within_entry_window() (+1 more)

### Community 23 - "Trailing Breakeven Stop Tests"
Cohesion: 0.11
Nodes (18): compilerOptions, allowJs, esModuleInterop, incremental, isolatedModules, jsx, lib, module (+10 more)

### Community 25 - "Authentication Endpoints & Sessions"
Cohesion: 0.14
Nodes (6): ScanResult, TradeJournalEntry, log_circuit_breaker(), log_no_trade_day(), log_scan_result(), log_trade_event()

### Community 27 - "IBKR Gateway Keepalive Service"
Cohesion: 0.16
Nodes (4): DataHealthCheck, DeRiskEvent, DeRiskState, Setting

### Community 29 - "Market Hours & PnL Metrics"
Cohesion: 0.27
Nodes (3): SystemAlert, acknowledge_alert(), is_dq_critical_paused()

### Community 30 - "Manual Scan & Snapshot Triggers"
Cohesion: 0.18
Nodes (12): AlertItem, AuthFetch, CHECK_LABELS, DataHealthResponse, DataHealthTab(), DeRiskStatusResponse, HealthCheckItem, HistoryItem (+4 more)

### Community 34 - "Stop-Loss Order Modifications"
Cohesion: 0.21
Nodes (7): AuthContext, AuthContextValue, useAuth(), LoginPage(), AuthFetch, Props, react

### Community 36 - "Portfolio Metrics & Settings API"
Cohesion: 0.22
Nodes (10): Account, AuthFetch, DailyPnlPoint, ExchangeRateData, fmt(), fmtSigned(), PnlHistory, PortfolioData (+2 more)

### Community 38 - "Zero Look-Ahead Backtest Core"
Cohesion: 0.31
Nodes (7): Home(), tabTitles, Sidebar(), AuthFetch, BucketStat, WeeklyReportItem, WeeklyReportsTab()

### Community 39 - "Historical AI Analysis Records"
Cohesion: 0.28
Nodes (8): AIAnalysisData, AIAnalysisTab(), AuthFetch, Candidate, DayAnalysis, fmt(), fmtMktCap(), TechnicalIndicators

### Community 43 - "HTTP Resiliency & Retries"
Cohesion: 0.47
Nodes (5): AuthFetch, fmt(), fmtSigned(), TradeHistoryTab(), TradeItem

### Community 44 - "Next.js Environment Declarations"
Cohesion: 0.33
Nodes (6): ATR-Based Trailing Stop & Profit Targets, Dual-Model AI Review Layer (Gemini & DeepSeek), Gap-Down Veto Circuit Breaker, Market Regime Filter (SPY 200 SMA & VIX), Momentum Swing Trading Strategy, Sector Relative Strength Filter

### Community 45 - "Vercel Routing & Edge Proxy"
Cohesion: 0.60
Nodes (4): Tab, NavItemDef, navItems, Props

## Knowledge Gaps
- **22 isolated node(s):** `ATR-Based Trailing Stop & Profit Targets`, `Dual-Model AI Review Layer (Gemini & DeepSeek)`, `Gap-Down Veto Circuit Breaker`, `Sector Relative Strength Filter`, `IB Gateway Headless Docker` (+17 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 554 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **37 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `get_system_config()` connect `FastAPI Routing & FX Conversion` to `Next.js Dashboard Views`, `Settings API & PnL Reset`, `Frontend App Shell & Auth Context`, `Market Regime & VIX Verification`, `Market Tiers & Gap-Down Veto`, `Cryptographic Auth & JWT RBAC`, `Trade Exits & Earnings Defense`, `Database Models & Settings Store`, `Security Headers & Rate Limiting`, `TypeScript Configuration & Types`, `Backtest Engine & Historical Simulation`, `Intraday VWAP & Pullback Timing`, `Universe Breadth Calculations`, `Market Hours & PnL Metrics`?**
  _High betweenness centrality (0.070) - this node is a cross-community bridge._
- **Are the 23 inferred relationships involving `Trade` (e.g. with `get_alpha_analysis()` and `get_pnl_history()`) actually correct?**
  _`Trade` has 23 INFERRED edges - model-reasoned connections that need verification._
- **What connects `ATR-Based Trailing Stop & Profit Targets`, `Dual-Model AI Review Layer (Gemini & DeepSeek)`, `Gap-Down Veto Circuit Breaker` to the rest of the system?**
  _22 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `AI Analyst & Gemini Insights` be split into smaller, more focused modules?**
  _Cohesion score 0.049883449883449886 - nodes in this community are weakly interconnected._
- **Why does `compute_regime_status()` connect `Docker Infrastructure & Compose` to `Next.js Dashboard Views`, `Frontend App Shell & Auth Context`, `Financial Data & Fundamentals Ingestion`, `Market Regime & VIX Verification`, `Market Tiers & Gap-Down Veto`, `TypeScript Configuration & Types`?**
  _High betweenness centrality (0.050) - this node is a cross-community bridge._
- **Are the 7 inferred relationships involving `generate_weekly_report()` (e.g. with `AccountSnapshot` and `AIPick`) actually correct?**
  _`generate_weekly_report()` has 7 INFERRED edges - model-reasoned connections that need verification._
- **Should `Next.js Dashboard Views` be split into smaller, more focused modules?**
  _Cohesion score 0.07966457023060797 - nodes in this community are weakly interconnected._