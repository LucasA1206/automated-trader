# Graph Report - automated-trader  (2026-11-26)

## Corpus Check
- 79 files · ~101,224 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 10 file(s) not represented in the graph (top: (none) 6, .toml 1, .ico 1)

## Summary
- 1225 nodes · 2724 edges · 77 communities (45 shown, 32 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 165 edges (avg confidence: 0.89)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `b27837f9`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- scoring_engine.py
- Next.js Dashboard Views
- Multi-Factor Scoring Engine
- jobs.py
- data_layer.py
- post
- Batch OHLCV Downloader & Cache
- exit_engine.py
- Docker Infrastructure & Compose
- api_server.py
- Job Execution & System Logging
- Trade Exits & Earnings Defense
- universe_filter.py
- RiskEngine
- Market Breadth & Sector Leadership
- FastAPI Routing & FX Conversion
- test_e2e_self_monitoring_dry_run.py
- API Alpha & System Logs Endpoints
- os
- Backtest Engine & Historical Simulation
- Intraday VWAP & Pullback Timing
- get_setting
- Scan Automation & Ticker Screener
- Trailing Breakeven Stop Tests
- trader.py
- typing
- IBKR Liquidation & Order Execution
- Base
- TestPhase2MarketState
- data_providers.py
- Manual Scan & Snapshot Triggers
- compute_composite_score
- test_phase2_market_state.py
- entry_engine.py
- page.tsx
- _retry
- Portfolio Metrics & Settings API
- job_data_quality_monitor
- react
- Historical AI Analysis Records
- fetch_fundamentals
- Candidate Ranking & Tiebreaking
- check_market_linked_exit_trigger
- HTTP Resiliency & Retries
- Next.js Environment Declarations
- Vercel Routing & Edge Proxy
- Strategy Package Metadata
- Railway & Gateway Deployment Docs
- _stage2_check_single
- Position Sizing & Risk Docs
- AuthContext.tsx
- _percentile_rank
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
- logging
- TestFeature1DeRiskLadder
- TestIBKROrderCleanup
- score_all_candidates
- _compute_gap_history_penalty
- compute_confidence_score

## God Nodes (most connected - your core abstractions)
1. `Trade` - 50 edges
2. `IBKRClient` - 45 edges
3. `job_pre_market_scan()` - 37 edges
4. `get_system_config()` - 33 edges
5. `generate_weekly_report()` - 32 edges
6. `job_exit_monitor()` - 30 edges
7. `fetch_ohlcv()` - 30 edges
8. `compute_composite_score()` - 30 edges
9. `compute_regime_status()` - 29 edges
10. `job_entry_monitor()` - 28 edges

## Surprising Connections (you probably didn't know these)
- `get_portfolio()` --uses--> `Trade`  [INFERRED]
  backend/api_server.py → backend/models.py
- `get_trades()` --uses--> `Trade`  [INFERRED]
  backend/api_server.py → backend/models.py
- `get_ai_picks()` --uses--> `AIPick`  [INFERRED]
  backend/api_server.py → backend/models.py
- `get_scan_history()` --uses--> `ScanResult`  [INFERRED]
  backend/api_server.py → backend/models.py
- `get_ai_analysis()` --uses--> `ScanResult`  [INFERRED]
  backend/api_server.py → backend/models.py

## Import Cycles
- 2-file cycle: `frontend/app/page.tsx -> frontend/components/Sidebar.tsx -> frontend/app/page.tsx`

## Hyperedges (group relationships)
- **Systematic Trading Bot Core Strategy Pipeline** — systematic_trading_bot_blueprint_momentum_swing_trading, systematic_trading_bot_blueprint_market_regime_filter, systematic_trading_bot_blueprint_gap_down_veto, systematic_trading_bot_blueprint_position_sizing_risk, systematic_trading_bot_blueprint_atr_exit_engine [EXTRACTED 0.95]

## Communities (77 total, 32 thin omitted)

### Community 0 - "scoring_engine.py"
Cohesion: 0.12
Nodes (10): score_52w_high_proximity(), score_adx(), score_beta(), score_debt(), score_eps_growth(), score_float(), score_profit_margins(), score_relative_volume() (+2 more)

### Community 1 - "Next.js Dashboard Views"
Cohesion: 0.07
Nodes (7): sell_all_ibkr(), sell_single_stock(), job_deferred_sell_single(), SystemLog, IBKRClient, round_to_tick(), safe_float()

### Community 2 - "Multi-Factor Scoring Engine"
Cohesion: 0.05
Nodes (22): analyse_with_gemini(), check_market_regime(), _compute_rsi(), fetch_full_nasdaq_tickers(), fetch_news_for_ticker(), fetch_technicals_batch(), _fetch_technicals_for_ticker(), fetch_top_movers_news() (+14 more)

### Community 3 - "jobs.py"
Cohesion: 0.08
Nodes (21): log_event(), _count_open_positions(), ensure_pending_candidates_loaded(), _get_open_positions_with_sectors(), is_market_open(), job_entry_monitor(), job_eod_snapshot(), job_exit_monitor() (+13 more)

### Community 4 - "data_layer.py"
Cohesion: 0.13
Nodes (7): clear_all_caches(), fetch_economic_calendar(), fetch_next_earnings_date(), fetch_vix(), get_cache_stats(), _is_cache_fresh(), is_economic_blackout_day()

### Community 5 - "post"
Cohesion: 0.11
Nodes (10): ack_monitoring_alert(), reset_pnl_history(), stop_scan(), trigger_entry_monitor(), trigger_health_check(), trigger_scan(), trigger_sell(), trigger_snapshot() (+2 more)

### Community 6 - "Batch OHLCV Downloader & Cache"
Cohesion: 0.07
Nodes (36): eslintConfig, dependencies, next@^16.4.6, react@19.2.4, react-dom@19.2.4, recharts@^3.8.1, devDependencies, babel-plugin-react-compiler@1.0.0 (+28 more)

### Community 7 - "exit_engine.py"
Cohesion: 0.13
Nodes (7): is_near_earnings(), check_exit_conditions(), compute_chandelier_trail(), compute_partial_target(), ExitSignal, _get_trading_days_since(), _compute_atr()

### Community 8 - "Docker Infrastructure & Compose"
Cohesion: 0.07
Nodes (4): compute_regime_status(), _is_valid_spy_dict(), _is_valid_vix_dict(), TestRegimeFailSafe

### Community 9 - "api_server.py"
Cohesion: 0.06
Nodes (30): _build_margin_upgrade_alert(), DeEscalateRequest, exchange_rate(), get_ai_picks(), get_alpha_analysis(), get_data_health(), get_fx_rate(), get_logs() (+22 more)

### Community 10 - "Job Execution & System Logging"
Cohesion: 0.06
Nodes (12): login(), logout(), clear_auth_cookie(), create_access_token(), decode_token(), hash_password(), require_admin(), require_auth() (+4 more)

### Community 11 - "Trade Exits & Earnings Defense"
Cohesion: 0.11
Nodes (9): _fetch_ticker_universe(), job_pre_market_scan(), calculate_beta_scalar(), check_sector_leadership(), check_spy_intraday_confirmation(), compute_empirical_beta(), get_latest_breadth(), rank_sectors_by_leadership() (+1 more)

### Community 12 - "universe_filter.py"
Cohesion: 0.16
Nodes (7): reset_yfinance_block(), apply_fcf_compound_filter(), apply_relative_strength_threshold(), run_universe_filter(), stage1_price_volume_filter(), stage2_technical_filter(), stage3_event_filter()

### Community 14 - "Market Breadth & Sector Leadership"
Cohesion: 0.06
Nodes (33): build, command, depends_on, environment, ports, restart, volumes, context (+25 more)

### Community 15 - "FastAPI Routing & FX Conversion"
Cohesion: 0.11
Nodes (9): ShadowEvaluation, classify_evidence_strength(), compute_shadow_summary(), _default_price_fetcher(), _get_cfg(), record_shadow_decision(), update_open_shadow_outcomes(), TestFeature4ShadowTracking (+1 more)

### Community 16 - "test_e2e_self_monitoring_dry_run.py"
Cohesion: 0.07
Nodes (18): DataHealthCheck, PendingExitIntent, SystemAlert, emit_alert(), resolve_alert_by_key(), ApiHealthTracker, check_api_health(), check_metric_coverage() (+10 more)

### Community 17 - "API Alpha & System Logs Endpoints"
Cohesion: 0.10
Nodes (5): get_client_ip(), rate_limit_endpoint(), dependency(), RateLimiter, SecurityHeadersMiddleware

### Community 18 - "os"
Cohesion: 0.13
Nodes (3): check_mean_reversion_exit(), compute_rsi2(), scan_mean_reversion_candidates()

### Community 19 - "Backtest Engine & Historical Simulation"
Cohesion: 0.12
Nodes (11): ScanResult, WeeklyReport, _bucket_stats(), _confidence_bucket(), _entry_time_bucket(), _fetch_spy_period_return(), generate_weekly_report(), _group() (+3 more)

### Community 20 - "Intraday VWAP & Pullback Timing"
Cohesion: 0.17
Nodes (9): DeRiskEvent, DeRiskState, compute_live_performance_metrics(), _ensure_state_row(), evaluate_derisk_ladder(), _get_cfg(), get_derisk_modifiers(), get_derisk_state() (+1 more)

### Community 21 - "get_setting"
Cohesion: 0.10
Nodes (11): lifespan(), _sync_strategy_settings(), update_settings(), get_db(), get_setting(), init_db(), set_setting(), start_persistent_keepalive() (+3 more)

### Community 22 - "Scan Automation & Ticker Screener"
Cohesion: 0.21
Nodes (6): fetch_ohlcv(), fetch_ohlcv_batch(), _download_chunk(), _fetch_ohlcv_ibkr(), prime_ohlcv_cache(), _sanity_check_ohlcv()

### Community 23 - "Trailing Breakeven Stop Tests"
Cohesion: 0.11
Nodes (18): compilerOptions, allowJs, esModuleInterop, incremental, isolatedModules, jsx, lib, module (+10 more)

### Community 25 - "typing"
Cohesion: 0.18
Nodes (4): get_active_baseline(), log_circuit_breaker(), log_no_trade_day(), log_scan_result()

### Community 27 - "Base"
Cohesion: 0.20
Nodes (3): get_ai_analysis(), AIPick, TradeJournalEntry

### Community 28 - "TestPhase2MarketState"
Cohesion: 0.06
Nodes (3): check_gap_down_veto(), classify_market_tier(), TestPhase2MarketState

### Community 29 - "data_providers.py"
Cohesion: 0.05
Nodes (21): AlpacaProvider, EODHDProvider, FinnhubProvider, FMPProvider, get_provider_chain(), MarketDataProvider, MassivePolygonProvider, ProviderChain (+13 more)

### Community 30 - "Manual Scan & Snapshot Triggers"
Cohesion: 0.18
Nodes (12): AlertItem, AuthFetch, CHECK_LABELS, DataHealthResponse, DataHealthTab(), DeRiskStatusResponse, HealthCheckItem, HistoryItem (+4 more)

### Community 31 - "compute_composite_score"
Cohesion: 0.11
Nodes (9): _compute_bollinger(), compute_composite_score(), score_bollinger_position(), score_fcf(), score_institutional_ownership(), score_macd_histogram(), score_market_cap_band(), score_rsi_zone() (+1 more)

### Community 32 - "test_phase2_market_state.py"
Cohesion: 0.10
Nodes (4): compute_market_breadth(), set_latest_breadth(), get_risk_engine(), _create_mock_df()

### Community 33 - "entry_engine.py"
Cohesion: 0.16
Nodes (8): check_entry_confirmation(), is_within_entry_window(), prepare_entry_order(), compute_initial_stop(), _compute_adx(), _compute_macd_histogram(), _compute_rsi(), _compute_sma()

### Community 34 - "page.tsx"
Cohesion: 0.20
Nodes (12): Home(), tabTitles, useAuth(), LoginPage(), AuthFetch, Props, SettingsTab(), Sidebar() (+4 more)

### Community 35 - "_retry"
Cohesion: 0.16
Nodes (6): estimate_vwap(), _fetch(), fetch_spy_regime(), fetch_spy_returns(), _retry(), _rotate_yf_session()

### Community 36 - "Portfolio Metrics & Settings API"
Cohesion: 0.22
Nodes (10): Account, AuthFetch, DailyPnlPoint, ExchangeRateData, fmt(), fmtSigned(), PnlHistory, PortfolioData (+2 more)

### Community 37 - "job_data_quality_monitor"
Cohesion: 0.22
Nodes (6): get_derisk_status(), get_risk_state(), _compute_weekly_pnl_pct(), _get_peak_equity(), job_data_quality_monitor(), AccountSnapshot

### Community 38 - "react"
Cohesion: 0.40
Nodes (4): AuthFetch, BucketStat, WeeklyReportItem, react

### Community 39 - "Historical AI Analysis Records"
Cohesion: 0.28
Nodes (8): AIAnalysisData, AIAnalysisTab(), AuthFetch, Candidate, DayAnalysis, fmt(), fmtMktCap(), TechnicalIndicators

### Community 40 - "fetch_fundamentals"
Cohesion: 0.18
Nodes (7): fetch_fundamentals(), fetch_fundamentals_batch(), _fetch(), _fetch(), _finnhub_get(), _finnhub_rate_check(), _get_finnhub_api_key()

### Community 42 - "check_market_linked_exit_trigger"
Cohesion: 0.27
Nodes (3): check_market_linked_exit_trigger(), compute_earnings_season_density(), TestPhase4ExitsEarnings

### Community 43 - "HTTP Resiliency & Retries"
Cohesion: 0.47
Nodes (5): AuthFetch, fmt(), fmtSigned(), TradeHistoryTab(), TradeItem

### Community 44 - "Next.js Environment Declarations"
Cohesion: 0.33
Nodes (6): ATR-Based Trailing Stop & Profit Targets, Dual-Model AI Review Layer (Gemini & DeepSeek), Gap-Down Veto Circuit Breaker, Market Regime Filter (SPY 200 SMA & VIX), Momentum Swing Trading Strategy, Sector Relative Strength Filter

### Community 45 - "Vercel Routing & Edge Proxy"
Cohesion: 0.60
Nodes (4): Tab, NavItemDef, navItems, Props

### Community 48 - "_stage2_check_single"
Cohesion: 0.28
Nodes (4): _compute_52w_high_proximity(), _compute_atr_pct(), _compute_relative_strength(), _stage2_check_single()

### Community 52 - "AuthContext.tsx"
Cohesion: 0.28
Nodes (6): metadata, RootLayout(), viewport, AuthContext, AuthContextValue, AuthProvider()

### Community 53 - "_percentile_rank"
Cohesion: 0.25
Nodes (4): _percentile_rank(), score_breakout_quality(), score_relative_strength(), score_sector_rs()

## Knowledge Gaps
- **22 isolated node(s):** `ATR-Based Trailing Stop & Profit Targets`, `Dual-Model AI Review Layer (Gemini & DeepSeek)`, `Gap-Down Veto Circuit Breaker`, `Sector Relative Strength Filter`, `IB Gateway Headless Docker` (+17 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 586 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **32 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `compute_regime_status()` connect `Docker Infrastructure & Compose` to `entry_engine.py`, `jobs.py`, `data_layer.py`, `job_data_quality_monitor`, `_retry`, `api_server.py`, `Trade Exits & Earnings Defense`, `test_e2e_self_monitoring_dry_run.py`, `os`?**
  _High betweenness centrality (0.050) - this node is a cross-community bridge._
- **Are the 25 inferred relationships involving `Trade` (e.g. with `get_alpha_analysis()` and `get_pnl_history()`) actually correct?**
  _`Trade` has 25 INFERRED edges - model-reasoned connections that need verification._
- **What connects `ATR-Based Trailing Stop & Profit Targets`, `Dual-Model AI Review Layer (Gemini & DeepSeek)`, `Gap-Down Veto Circuit Breaker` to the rest of the system?**
  _22 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `scoring_engine.py` be split into smaller, more focused modules?**
  _Cohesion score 0.1225296442687747 - nodes in this community are weakly interconnected._
- **Why does `Trade` connect `jobs.py` to `Next.js Dashboard Views`, `job_data_quality_monitor`, `TestFeature1DeRiskLadder`, `api_server.py`, `FastAPI Routing & FX Conversion`, `test_e2e_self_monitoring_dry_run.py`, `os`, `Backtest Engine & Historical Simulation`, `Intraday VWAP & Pullback Timing`, `Base`, `data_providers.py`?**
  _High betweenness centrality (0.046) - this node is a cross-community bridge._
- **Are the 2 inferred relationships involving `IBKRClient` (e.g. with `TestIBKROrderCleanup` and `TestPhaseAlignmentAndCalendar`) actually correct?**
  _`IBKRClient` has 2 INFERRED edges - model-reasoned connections that need verification._
- **Should `Next.js Dashboard Views` be split into smaller, more focused modules?**
  _Cohesion score 0.06988120195667366 - nodes in this community are weakly interconnected._