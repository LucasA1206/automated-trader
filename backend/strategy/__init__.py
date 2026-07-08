"""Systematic Swing-Trading Strategy Package.

Implements the full blueprint from systematic_trading_bot_blueprint.md:
  - data_layer     : OHLCV, fundamentals, earnings, VIX, regime data
  - universe_filter: mandatory pass/fail gates (Section 4/5)
  - scoring_engine : weighted composite 0-100 score (Section 5)
  - backtest       : multi-regime backtester with Monte Carlo (Section 16)
  - risk_engine    : hard-gated circuit breakers (Section 7/10)
  - ai_layer       : dual-model Gemini + DeepSeek qualitative review (Section 3/12)
  - entry_engine   : intraday entry confirmation (Section 8)
  - exit_engine    : ATR stop, 1.5R partial, trailing, time exits (Section 9)
  - journal        : structured trade journaling and scan logging (Section 15)
  - alerting       : push/email notifications on trade events and circuit breakers
"""
