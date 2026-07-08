# Systematic Equity Trading Bot — Full Design Blueprint
### IBKR · NASDAQ/NYSE · ~USD $5,400 Starting Capital

> **This is a design document, not financial advice.** I'm not a licensed financial advisor. Every number, threshold, and rule below is a defensible starting point grounded in market structure and risk-management principles — not a guarantee of profit. No systematic strategy removes risk; it only controls it. You are responsible for backtesting, paper trading, and validating everything here before risking real capital.

---

## The One Constraint That Shapes Everything: Account Size

Before any strategy discussion, three structural facts about a $5,400 USD account must be confronted, because they eliminate entire categories of "obvious" strategies:

1. **Pattern Day Trader (PDT) Rule.** FINRA requires a minimum of $25,000 equity to day-trade (open and close the same position same-day) more than 3 times in a rolling 5-business-day window in a margin account. At $5,400 you are **not eligible to day trade** in a margin account without tripping a trading restriction. Two ways around this: (a) use an **IBKR cash account** (no PDT rule, but trades must settle — T+1 for US equities — before proceeds are reusable), or (b) simply **don't day-trade** — hold positions overnight. This blueprint assumes a cash account and a **swing-trading** holding period (1–10 trading days) specifically to make PDT and settlement irrelevant.
2. **Diversification is mathematically limited.** With $5,400 and a 1–2% risk-per-trade rule, you can realistically hold 2–4 positions at once, not 15–20. This means idiosyncratic (single-stock) risk cannot be diversified away the way a $500k portfolio could. The strategy must therefore lean harder on liquidity, quality, and stop discipline per trade rather than on diversification.
3. **Commissions and slippage are a bigger percentage drag on a small account.** A $10 fill slippage on a $1,000 position is 1% — the same slippage on a $50,000 position is 0.02%. This pushes the design toward IBKR's **Lite** commission-free US stock tier (or Pro's tiered pricing if you value better execution/routing — see Section 14) and toward stocks with tight bid/ask spreads only.

Everything downstream is built around these three facts.

---

## Section 1 — Overall Strategy: Swing-Trading Momentum with Trend and Mean-Reversion Filters

### Options considered

| Style | Fit for $5.4k account | Why / why not |
|---|---|---|
| Day trading / gap-and-go | Poor | PDT rule blocks it in a margin account; a cash account can't recycle capital fast enough for true intraday systems |
| Pure mean reversion (buy dips) | Moderate | Works but needs strong regime filters or it becomes "catching falling knives"; higher win rate but fat left tail |
| Pure breakout trading | Moderate | High reward when right, but false-breakout rate on small/mid caps is high without volume confirmation |
| Long-only trend following (position trading, weeks–months) | Good | Robust, low turnover, historically the most researched "edge that persists" in equities, but slow capital compounding on a small account |
| **Momentum swing trading (relative strength + pullback entries), trend-filtered** | **Best fit** | Matches account size (few concentrated, high-quality trades), avoids PDT, has decades of academic support (Jegadeesh & Titman cross-sectional momentum; also documented time-series/trend-following premium), and is compatible with a once-daily automated scan |

### Recommendation

**A hybrid system: cross-sectional relative-strength momentum for candidate selection, combined with a mean-reversion pullback trigger for entry timing, gated by a trend/regime filter.**

- **Selection layer (momentum):** Every morning, rank the tradable universe by relative strength — stocks outperforming the S&P 500/sector over 1, 3, and 6 months, in confirmed uptrends. This is the "what to buy" layer. Momentum is one of the most persistent, out-of-sample-replicated anomalies in equity research.
- **Timing layer (mean reversion within the trend):** Don't buy strength at the top. Wait for a short-term pullback to a moving average or prior support **within** the larger uptrend (a "buy the dip in an uptrend" trigger). This improves entry price, tightens the stop distance (better risk:reward), and reduces the odds of buying an exhaustion spike.
- **Regime gate (trend filter):** The whole system is switched on/off by the broader market's trend (Section 6, Section 10). In a confirmed downtrend or high-volatility regime, the system reduces size or goes to cash rather than fighting the tape.

**Why not combine more styles?** Every additional strategy sleeve (e.g., adding earnings continuation, sector rotation, gap trading) multiplies code complexity, multiplies failure surface, and dilutes the few positions you can hold. For a $5.4k account, **one well-executed strategy beats three mediocre ones.** Sector rotation and earnings-continuation concepts are folded in as *filters* (avoid stocks in weak sectors; avoid holding through earnings — Section 10) rather than as separate standalone strategies.

**ETFs:** Not recommended as core holdings. ETFs dilute the relative-strength edge (a basket average has less momentum dispersion than its best constituent) and most sector/leveraged ETFs have wider spreads or decay characteristics (leveraged ETFs) unsuitable for this account. The one justified use of an ETF is as **the benchmark/regime filter** (SPY or QQQ) — not as a tradable position.

---

## Section 2 — Daily Market Scan

Runs once, pre-market (e.g., 8:00–9:15am ET / after-hours the prior evening as a first pass, refreshed pre-open).

### Data required
- Daily OHLCV history (2+ years) for the full universe
- Real-time/pre-market quote snapshot (last price, pre-market volume, pre-market % change)
- Fundamentals snapshot (market cap, float, shares outstanding, sector/industry, next earnings date)
- Index/benchmark data (SPY, QQQ, sector ETFs) for relative strength and regime detection
- News/headline feed (for exclusion filtering, not signal generation)

### Universe
Start broad, narrow fast:
1. **Raw universe:** All common stocks listed on NYSE and NASDAQ (~6,000–7,000 tickers). Exclude OTC, ADRs of non-reporting foreign issuers, SPACs pre-merger, and any security not tagged as a common share (no preferred shares, warrants, rights, units).
2. **Hard liquidity/quality pre-filter** (before any scoring — this is a *universe reduction* step, not the ranking):
   - Price ≥ $5 (sub-$5 stocks have wider relative spreads, higher manipulation risk, and many brokers/exchanges treat them differently)
   - Average dollar volume (20-day) ≥ $10,000,000/day (ensures your ~$1,000–2,000 position can enter/exit without moving the market)
   - Market cap ≥ $500M (removes the thinnest, most manipulable micro-caps)
   - Not currently halted, not on any regulatory short-sale restriction list you can't handle, not in the 3 trading days before/after a confirmed earnings release (see Section 10)

This typically prunes ~7,000 tickers down to **~800–1,500 candidates**.

### Scan order (why this order matters — cheap filters first, expensive analysis last)
1. **Liquidity/price/cap filter** (above) — cheapest, eliminates ~80% of the universe instantly.
2. **Trend/regime pre-check** — is the *stock itself* above its 50-day and 200-day moving average, and is the *broader market* in an uptrend? If the market regime is "risk-off" (Section 6/10), skip straight to a reduced or cash-only candidate list.
3. **Relative strength ranking** — rank remaining ~800–1,500 names by 63-day (3-month) and 126-day (6-month) return relative to SPY. Keep top ~10% (roughly 80–150 names).
4. **Technical/volume scoring** (Section 4/5 metrics) applied to this shortlist only — this is the computationally heavier stage (ATR, RSI, MACD, ADX, Bollinger position, pullback-to-MA proximity, volume pattern).
5. **Fundamental/quality overlay** — filter out names with deteriorating fundamentals (negative revenue growth, high net debt/EBITDA, recent negative EPS surprise) even if technically strong; momentum + quality outperforms momentum alone and has a shallower drawdown profile.
6. **News/event exclusion pass** — remove anything with pending FDA decisions, litigation headlines, ongoing SEC investigation, unresolved M&A rumor, or earnings inside the exclusion window.
7. **Final ranking and top-N candidate list** — score everything that survives (Section 5), output top 5–10 ranked candidates to the AI analysis layer (Section 3/12).

### Filtering vs. ranking — the distinction
*Filters* are binary pass/fail gates (liquidity, price, halts, earnings blackout). *Ranking* is the continuous weighted score applied only to what survives the filters. Never let a high rank override a failed mandatory filter — mandatory filters are non-negotiable circuit breakers, not scoring inputs (Section 5 details this).

---

## Section 3 — Best Free AI Model for the Analysis Layer

The AI's job here (Section 12) is **not** to predict prices — it's to do structured qualitative reasoning over an already-quantified shortlist: synthesizing news/catalyst context, flagging hidden risks a pure numeric filter would miss, and producing a calibrated confidence/probability estimate and written rationale. That's a reasoning + instruction-following + moderate-context task, not a raw-intelligence-ceiling task, so a frontier free-tier model is more than sufficient — you don't need (and shouldn't pay for) top-tier frontier pricing for this step.

### Comparison (current as of mid-2026)

| Model | Financial reasoning | Speed | Free-tier cost | Context | Reliability/structured output | Notes |
|---|---|---|---|---|---|---|
| **Gemini (via Google AI Studio free tier)** | Strong | Fast | Free, generous daily quota | 1M tokens | Very reliable JSON mode, native function calling | Best "no self-hosting needed" option; Google's free API tier is the most production-friendly free option available |
| **DeepSeek (V3/V4 family, chat or via free-tier routers)** | Strong, particularly good at quantitative/structured reasoning | Fast (V4 Flash) / slower (reasoning mode) | Free via chat; very cheap via API even outside free tiers | 128K–1M depending on variant | Good, though verbosity in reasoning mode needs prompt constraints | Excellent value; a strong secondary/cross-check model |
| **Llama 4 (via Groq's free API tier)** | Good | Extremely fast (Groq's inference hardware) | Free tier with rate limits | Long (Scout variant reaches multi-million token context) | Reliable, good tool-calling | Groq's free tier is the best way to get very low-latency automated morning runs |
| **Qwen (3.x family, via free routers/Groq/OpenRouter free tier)** | Good, strong multilingual/quant background | Fast | Free tier available on several routers | Long | Reliable | Good backup; particularly solid at numeric/tabular reasoning |
| **Mistral (Small/Medium, free tier via La Plateforme)** | Adequate | Fast | Free tier available | Moderate | Reliable but less nuanced financial reasoning than the above | Fine as a tertiary fallback |
| **Phi (Microsoft, small models)** | Weaker on nuanced reasoning | Very fast, can run locally | Free/local | Short | Best for simple, low-stakes local tasks | Use only for lightweight local pre-filtering, not the main analysis |

### Recommendation
- **Primary: Gemini via Google AI Studio's free tier.** Best combination of financial/general reasoning quality, reliable structured JSON output (critical for a bot parsing responses automatically), a genuinely free and generous quota, and long context (fits the full candidate shortlist + recent news in one call).
- **Backup #1: DeepSeek** (chat/API) — use as a **second opinion**: run the same structured prompt through both models and only act on a candidate if the two models substantially agree on direction and confidence. Disagreement is itself a signal to skip or downsize the trade (Section 6).
- **Backup #2: Llama 4 via Groq's free tier** — use as the failover if both Gemini and DeepSeek are unavailable/erroring, valued for its speed in a time-sensitive pre-market window.
- **Do not** rely on a single AI call as the sole trade trigger. The AI augments the quantitative score; it never overrides a failed mandatory filter (Section 6/12).

---

## Section 4 — Stock Selection Metrics (Detailed)

Format for each: **Why it matters | Threshold | Direction | Weight in score (of 100) | Mandatory or optional**

### Liquidity & tradability (mandatory gates — pass/fail, not weighted)
- **Average dollar volume (20-day):** Ensures you can enter/exit without excessive slippage. ≥ $10M/day. Higher = better. **Mandatory.**
- **Relative volume (today vs 20-day avg):** Confirms genuine interest, not a data glitch or thin print. ≥ 1.2× normal on breakout/entry day. Higher = better, up to a point (>5× can signal news-driven volatility to be cautious of). Weight: 8. **Semi-mandatory** (required at entry, not at scan time).
- **Market capitalization:** Larger caps have deeper order books and more stable price discovery, reducing manipulation and gap risk. ≥ $500M mandatory floor; $2B–$50B "sweet spot" preferred for balancing liquidity with room to run (mega-caps move too slowly for swing-trade R:R). Weight: 5. **Mandatory floor + optional preference band.**
- **Float:** Low float stocks move further on given volume, which cuts both ways — great for reward, brutal for slippage/gap risk in a small account. Prefer float ≥ 20M shares to avoid the most explosive low-float names. Weight: 4. **Optional but strongly weighted.**
- **Bid/ask spread:** Direct cost measure. ≤ 0.2% of price. Weight: included in liquidity mandatory gate.

### Volatility (mandatory band, not "more is better")
- **ATR (Average True Range, 14-day):** Sets stop distance and position size — the single most important volatility input. No universal threshold; used in position sizing math (Section 7), not as a filter itself.
- **ATR % (ATR/price):** Normalizes volatility across price levels. Target band: 2%–6% of price. Below 2% = too little movement to hit profit targets efficiently; above 6% = stop distances too wide for account-size risk budgeting. Weight: 7. **Mandatory band.**
- **Beta (vs S&P 500):** Contextualizes systemic risk exposure. Prefer 0.8–1.8; extreme betas (>2.5) usually indicate speculative/thin names. Weight: 3. **Optional.**

### Trend & price structure
- **Price vs 50-day and 200-day SMA:** The most robust, simplest trend filter in the literature. Require price > 50-day SMA > 200-day SMA (or price > 200-day SMA at minimum) — this is the single highest-value mandatory filter in the whole system, because trading with the primary trend materially improves the odds of momentum continuation and avoids "catching a falling knife." **Mandatory.**
- **Relative strength vs SPY/sector (3-month, 6-month return percentile):** This *is* the momentum signal — the core edge. Top decile preferred. Weight: 15 (highest single weight in the score). **Mandatory: must be top 30% of universe; Weight applies within that band.**
- **52-week high proximity:** Stocks near highs have no overhead supply (no trapped sellers wanting to "get back to even"), a well-documented feature of strong continuation moves. Within 10% of 52-week high preferred. Weight: 8. **Optional.**
- **Support/resistance & breakout quality:** Clean prior consolidation (tight range, low volatility) breaking to new highs on volume is higher-quality than a breakout from a chaotic, choppy base. Assessed qualitatively by the AI layer + quantitatively via Bollinger Band width contraction before the move. Weight: 6. **Optional.**
- **ADX (Average Directional Index, 14-day):** Confirms a *trending* (not choppy) market — momentum strategies underperform badly in range-bound conditions, so this is a quality-of-trend filter. ≥ 20 preferred (≥25 stronger). Weight: 6. **Optional but recommended mandatory-lite (soft mandatory: score = 0 below 15).**

### Entry-timing / oscillator metrics (used mainly at Section 8 entry, lightly at scan)
- **RSI (14-day):** Identifies the pullback entry zone within an uptrend — buying RSI 40–55 (a mild pullback, not oversold-from-weakness and not overbought-chasing) has better historical risk/reward than buying RSI > 70. Weight: 8. **Optional, timing-relevant.**
- **MACD (12,26,9):** Confirms momentum is turning back up after the pullback (MACD histogram troughing/turning positive) rather than still falling. Weight: 5. **Optional, timing-relevant.**
- **VWAP (intraday):** At entry, price reclaiming/holding above VWAP on the entry day is a same-day confirmation of buyer control. Weight: used in entry rules (Section 8), not the daily score.
- **Bollinger Bands (20,2):** Band-width contraction flags "coiled spring" setups; price walking the upper band flags strong-trend continuation vs. price sitting mid-band after a pullback (preferred entry zone). Weight: 4. **Optional.**
- **Candlestick/price-action confirmation:** Simple, objective patterns only (e.g., bullish engulfing, higher-low reversal bar) as a final entry-day trigger, not a scan-level ranking input.

### Fundamental / quality overlay (reduces the "value trap"/"junk momentum" failure mode)
- **Revenue growth (YoY, most recent quarter):** Momentum backed by real business growth is more durable. > 0% mandatory-lite; > 10% preferred. Weight: 6.
- **EPS growth (YoY):** Same rationale. Positive/accelerating preferred. Weight: 5.
- **Free cash flow (positive, trailing 12mo):** Filters out cash-burning speculative names — critical risk reducer for a small account that can't absorb a binary blow-up. Weight: 5. **Semi-mandatory** (penalize heavily if negative, don't auto-reject unless combined with weak balance sheet).
- **Debt (net debt/EBITDA or debt/equity):** High leverage names are more fragile in a drawdown/rate-shock scenario. Prefer net debt/EBITDA < 3x. Weight: 4.
- **Profit margins / ROE:** Quality proxy; higher and stable preferred over volatile/negative. Weight: 3.
- **Institutional ownership:** A rough proxy for scrutiny/quality (very low institutional ownership can indicate a name too small/obscure for reliable info flow). Prefer 20%–90% (not 0%, not near-100% which can indicate crowding/limited float for retail). Weight: 2. **Optional.**

### Catalyst / sentiment / event overlay
- **Earnings date:** Exclude any stock reporting earnings within the next 3 trading days (gap risk is uncapped and un-hedgeable for a small cash account) and any stock still inside a 1-day post-earnings settling window unless the post-earnings drift is the explicit thesis (advanced/optional module, not in the base system). **Mandatory exclusion.**
- **Economic calendar:** No new entries on FOMC decision days, major CPI/NFP release mornings, or the day before, since baseline volatility/gap risk spikes broadly. **Mandatory scan-level pause, not per-stock.**
- **Analyst revisions (recent upgrades/target raises):** A modest positive-tilt input — real information content, weak solo signal. Weight: 3. **Optional.**
- **Insider buying (recent open-market buys, Form 4):** Meaningful when present, rare in general; treat as a scoring bonus, not a requirement. Weight: 2. **Optional.**
- **Short interest (% of float):** Extreme short interest (>20% float) raises squeeze-driven volatility that's hard to model systematically — treat as a caution flag reducing score rather than an outright exclusion (some of the best momentum moves *are* short squeezes, but they're harder for a rules-based system to size correctly). Weight: -3 penalty above threshold. **Optional/penalty.**
- **News sentiment / social sentiment:** Genuinely useful as a *qualitative check* the AI performs (Section 3/12), not as a standalone numeric score — sentiment data quality/latency from free sources is too noisy to trust as a primary quantitative weight. Weight: folded into AI confidence score, not the pre-AI numeric score.
- **Options activity (unusual call volume):** Optional "nice to have" — most free/cheap data sources have poor options-flow coverage, and this account isn't trading options, so treat as a low-weight bonus only if available. Weight: 2. **Optional.**

### Additional robustness metrics worth adding
- **Sector relative strength:** Rank sectors themselves by relative strength and only allow candidates from the top ~half of sectors — a stock swimming against its sector's tide is fighting a headwind. Weight: 5.
- **Correlation to existing open positions:** Not a per-stock scan metric but a *portfolio-construction* filter (Section 10) — reject a candidate that's too correlated with what you already hold.
- **Historical gap frequency:** Stocks with a history of frequent large overnight gaps (even without pending earnings) carry structurally higher tail risk for a small account holding overnight — penalize in scoring.

---

## Section 5 — Ranking Algorithm

### Step 1 — Mandatory filters (binary, applied first; failing any = excluded entirely, regardless of score)
- Price ≥ $5
- 20-day avg dollar volume ≥ $10M
- Market cap ≥ $500M
- Price > 200-day SMA
- No earnings within next 3 trading days
- Not on any halt/restriction list
- ATR% within 2%–6% band
- Free cash flow not deeply negative *combined with* weak balance sheet (compound condition, not FCF alone)

### Step 2 — Weighted composite score (0–100), applied only to survivors
Sum of the weights listed in Section 4 (they total ~100 across mandatory-lite + optional categories: momentum 15, RS/52wk 8, ADX 6, RSI 8, MACD 5, Bollinger 4, breakout quality 6, liquidity/relvol 8, market cap band 5, float 4, beta 3, revenue growth 6, EPS growth 5, FCF-quality bonus 5, debt 4, margins/ROE 3, institutional own. 2, analyst revisions 3, insider buying 2, sector RS 5, options activity 2, short-interest penalty up to -3, gap-history penalty up to -3).

Each metric is normalized to a 0–1 sub-score (e.g., percentile rank within the day's surviving universe) before multiplying by its weight, so the composite is self-scaling regardless of market conditions that day.

### Step 3 — Minimum score threshold
- **Score ≥ 70/100:** High-conviction candidate, eligible for full position size.
- **Score 55–69:** Eligible only at reduced size (half of standard, Section 7), and only if fewer than the target number of full-size positions are already open.
- **Score < 55:** Not tradable, regardless of how few other candidates exist that day (this is the anti-"forcing trades" rule, formalized in Section 6).

### Step 4 — Tie-breaking
When two candidates have scores within 2 points of each other and both compete for the same available slot:
1. Prefer the one with higher liquidity (lower slippage risk on a small account).
2. Then prefer lower correlation to currently-open positions (diversification benefit).
3. Then prefer the one with the tighter ATR-based stop distance (better risk:reward per dollar risked).

### Step 5 — Confidence score
Separate from the numeric rank score: a 0–100 **confidence** estimate combining (a) how far above the minimum mandatory thresholds the stock sits (a stock barely scraping past filters is lower-confidence than one comfortably clear of them), (b) agreement between the two AI models (Section 3/12), and (c) current market regime state (Section 6). Confidence gates *position size*, while the rank score gates *selection* — they are deliberately kept as two separate numbers so the system can, e.g., take a well-ranked trade at reduced size in a shaky regime.

---

## Section 6 — When No Perfect Candidates Exist (Anti-Forcing Logic)

This is the most important governance rule in the whole system: **a systematic bot's biggest real-world failure mode isn't a bad model — it's a bot that trades every single day because it was told to run every single day.**

### Decision tree, run every morning after scoring
1. **Market regime check first, before looking at individual candidates.** Compute the regime filter (Section 10): is SPY above its 200-day SMA? Is realized/implied volatility (VIX) below a stress threshold (e.g., VIX < 30)? Is market breadth (e.g., % of S&P 500 stocks above their own 50-day SMA) healthy (>40%)?
   - **Regime = Risk-off (any of the above fails badly):** Skip the scan's actionable output entirely. Log "no trading today — regime filter." Do not proceed to candidate selection. This alone prevents the majority of catastrophic drawdown days a naive momentum system would otherwise walk into.
   - **Regime = Caution (marginal readings):** Proceed, but cap position count/size to 50% of normal (Section 7) and raise the minimum score threshold from 70 to 80.
   - **Regime = Risk-on:** Proceed normally.
2. **Count candidates clearing the score ≥ 70 bar.**
   - **≥ 1 found:** Trade the top-ranked one(s) up to the max open-position count (Section 7), full size, subject to portfolio heat/correlation limits.
   - **0 found, but ≥ 1 in the 55–69 band:** Trade at most **one** reduced-size position from this band, only if you currently hold zero or one open position (never "top up" marginal setups when you're already near full portfolio heat). Log clearly as a "marginal-conviction" trade with its confidence score.
   - **0 found in either band:** **Stay in cash. This is a valid, expected, and good outcome, not a system failure.** Log the day's best 3 near-misses, their scores, and specifically *which* mandatory or weighted criteria they failed, so you can review over time whether thresholds need recalibration (this becomes input to Section 15's continuous-improvement loop) — but do not trade them.
3. **Existing position review always runs regardless of new-entry outcome** (Section 9 exits are independent of whether a new trade is taken today).

### Explicit rule: never lower thresholds dynamically to "find a trade"
The system must **never** contain logic that says "if zero candidates found, lower the score threshold and re-scan." That's the exact mechanism by which automated systems drift into forced, low-quality trades during exactly the periods (dead/choppy/dangerous markets) when discipline matters most. If you want to loosen criteria, that's a deliberate, offline, backtested parameter change (Section 15) — never a live, same-day adaptive fallback.

---

## Section 7 — Position Sizing

- **Maximum concurrent positions: 4.** With $5,400 capital, this keeps each position large enough to absorb IBKR Lite's zero commission efficiently and small enough that per-position risk stays meaningful without over-concentrating.
- **Ideal simultaneous positions in normal conditions: 2–3.** Running at max capacity constantly is itself a sign the score threshold may be too loose (Section 15 review flag).
- **Risk per trade: 1% of account equity** ($54 at $5,400) — standard conservative risk-of-ruin math: at 1% risk/trade, ~15 consecutive losing trades (a statistically extreme losing streak for a >45% win-rate system) only draws the account down ~14%, which is recoverable. At 2%+ risk/trade, the same streak becomes a ~26%+ drawdown, materially harder to recover from and more likely to trigger emotional/override intervention.
- **Position size formula:**
  ```
  Dollar Risk = Account Equity × 1%
  Stop Distance ($) = Entry Price − Stop Price   (derived from ATR, Section 9)
  Shares = floor( Dollar Risk / Stop Distance )
  Position Value = Shares × Entry Price
  ```
  Example: $5,400 account, 1% risk = $54. ATR-based stop is $1.20 below entry. Shares = floor(54/1.20) = 45 shares. If entry price is $30, position value = $1,350 (~25% of account) — check this against the max single-stock exposure cap below and reduce shares if it's breached.
- **Maximum daily risk (new positions opened same day): 2% of equity.** Caps the worst-case same-day-entry drawdown from a correlated adverse move (e.g., a market-wide gap-down the next morning) at roughly 2×1% stop losses.
- **Maximum portfolio risk (sum of open stop-loss distances, all positions): 4% of equity.** With a 4-position cap at 1% each, this is the natural ceiling — but it's enforced explicitly as its own check in case position sizing math ever produces an outlier.
- **Maximum sector exposure: 40% of equity in any single GICS sector.** Prevents an "all momentum names happen to be in the same hot sector" scenario from becoming a concentrated bet on one macro theme.
- **Maximum single-stock exposure: 35% of equity at entry.** With only 2–4 positions, some concentration is unavoidable, but no single name should be able to sink more than ~35% of the account even in a worst-case (non-stop-triggered, e.g., halt/gap) scenario.
- **Cash reserve floor: keep at least 15% of equity uninvested at all times** as a liquidity buffer for settlement timing (cash account, T+1) and to avoid being fully committed when a high-conviction setup appears.

---

## Section 8 — Entry Rules (fully objective)

All conditions below must be true simultaneously for an entry order to be generated. This runs on the shortlisted, AI-reviewed candidates from Section 12, not the full scan universe.

1. **Technical confirmation:** Price is within 1×ATR of its 20-day or 50-day SMA (the "pullback zone"), RSI(14) between 40–55, MACD histogram has turned upward for at least 1 of the last 2 sessions (troughing/rising), and ADX(14) ≥ 20.
2. **Price confirmation:** Current session's price has reclaimed and is holding above the prior session's VWAP by market open + 30 minutes (avoids buying into a fake reclaim that fails in the first half hour), and the low of the entry day is above the low of the prior 3 days (no fresh breakdown).
3. **Volume confirmation:** Relative volume for the entry session ≥ 1.2× the 20-day average by the time of order placement (extrapolated from opening-range volume) — ensures the pullback is being bought, not abandoned on low interest.
4. **Time confirmation:** No new entries in the first 15 minutes after market open (opening-range noise/wide spreads) and no new entries in the final 15 minutes before close (avoids poor fills into closing auction volatility). Standard entry window: 9:45am–3:45pm ET. Since this is a fully automated pre-market-scanned system, the default execution is a **limit order placed shortly after the open confirms the above conditions**, not a market order at the bell.
5. **Order type:** Limit order at or slightly above last price (e.g., +0.1%) with a defined time-in-force (e.g., day order, cancel if unfilled) — never a market order on an illiquid name, and never chase a name that's already gapped beyond the planned entry zone by more than 1×ATR (skip it; there will be another setup).
6. **AI cross-check gate:** The trade only fires if both AI models (Section 3) agree on a "favorable" or "neutral-favorable" read and neither flags a hidden risk (Section 12) that isn't already captured in the quantitative filters — this is a final qualitative sanity check, not the primary decision driver.

---

## Section 9 — Exit Rules (fully objective)

Every open position has **all** of the following monitored continuously (or at each scheduled check interval — e.g., every 5–15 minutes during market hours), and exits on whichever triggers first:

1. **Initial stop loss:** Set at entry using 1.5×–2×ATR(14) below entry price (wider than a fixed % stop because it adapts to each stock's actual volatility — a tight fixed stop on a naturally volatile name gets stopped out by noise, while the same tight stop is too loose on a calm name). This stop is a **hard stop-loss order placed with the broker immediately on fill**, not a mental stop monitored by a possibly-down bot.
2. **Profit target (partial):** At +1.5× the initial risk (i.e., 1.5R), sell 50% of the position and move the stop on the remainder to breakeven. This locks in a partial win and removes downside risk on the rest of the trade — a well-documented way to improve the psychological and statistical robustness of a trend-following system.
3. **Trailing stop (remaining position):** Once the partial target is hit, trail the stop on the remaining shares using a Chandelier-style trail (e.g., highest high since entry minus 2.5×ATR) — lets winners run within the trend while still protecting accumulated gains.
4. **Moving-average exit:** If price closes below the 20-day SMA on above-average volume (a trend-break signal), exit the full remaining position at the next session's open regardless of where the trailing stop currently sits — this catches trend deterioration that a pure price-stop might not trigger fast enough.
5. **Time exit (maximum holding period):** If neither the stop nor a profit target has been hit within **10 trading days**, close the position at market on the 11th day's open. This is a capital-efficiency rule for a small account: capital stuck in a stagnant trade is capital not available for higher-conviction new setups, and momentum that hasn't continued within 2 weeks is statistically less likely to be "working."
6. **Volatility exit:** If ATR(14) on the position expands to more than 2.5× its value at entry (a volatility regime shock — e.g., an unexpected news event), tighten the stop immediately to 1×ATR from current price rather than waiting for the original stop to be hit, and consider a partial reduction regardless of P&L.
7. **News/event exit:** If a scheduled earnings release, FDA decision, litigation ruling, or similar binary event is now within the next 2 trading days for an open position (something that wasn't scheduled at entry, or the holding period ran into it), close the position before the event — the system never holds through a known binary catalyst, no exceptions, no "conviction override."
8. **Maximum holding time hard cap:** Even in a strong ongoing trend, if a position has been open more than **20 trading days** (roughly a month), force a full exit and treat re-entry as a brand-new scored candidate the next scan — this prevents "it's been a winner so I'll just hold it forever" drift that isn't backed by the system's actual tested holding-period edge.

---

## Section 10 — Risk Management (institutional-grade layer)

- **Maximum drawdown circuit breaker:** If account equity drawdown from its most recent peak reaches **8%**, the system automatically halts all new position entries (existing positions still managed by their normal exit rules) until a manual review is performed. At **15%** drawdown, the system also closes all open positions and goes fully to cash pending manual review and re-authorization (a config flag the bot checks, not something it can silently reset itself).
- **Daily loss limit:** If realized + open unrealized loss for the day exceeds **3% of equity**, no new entries for the remainder of that session.
- **Weekly loss limit:** If the trailing 5-trading-day realized P&L is worse than **-6% of equity**, position sizing is automatically halved for the following week, and the minimum score threshold rises to 80 — a "cooling off" throttle rather than a full stop.
- **Volatility filter (systemic):** No new entries on any day where VIX closes above **30**, or where VIX has risen more than 20% in the prior 3 sessions (a volatility-spike regime, historically correlated with poor risk-adjusted momentum performance and elevated gap risk).
- **Market trend filter (systemic):** No new entries unless SPY is above its 200-day SMA. This single rule, backtested extensively in trend-following literature, has historically avoided a large share of the worst drawdown periods for long-only equity systems, at the cost of missing some V-shaped-recovery entries — an acceptable trade-off for a capital-preservation-first mandate.
- **Portfolio heat:** Sum of all open positions' (entry price − stop price) × shares, expressed as % of equity, capped at 4% (ties back to Section 7).
- **Correlation limits:** Before adding a new position, compute its 60-day daily-return correlation to each currently-open position. If correlation > 0.7 with any existing holding, either skip the new candidate or reduce its size by 50% — prevents four "different" stocks from actually being one concentrated bet (e.g., four semiconductor names that all move together).
- **Black swan protection:** A standing rule that on any day the bot detects a single-session S&P 500 move beyond ±3% intraday, it (a) does not open new positions that day regardless of other signals, and (b) tightens all open-position stops to breakeven-or-better where currently profitable. This doesn't prevent losses from a genuine crash but prevents the system from mechanically "buying the dip" into an unfolding crisis before the regime filters have caught up.
- **Market halt handling:** If a held position is halted (LULD halt, regulatory halt, news pending), the bot cancels any working orders on that symbol, logs the halt, and does **not** attempt to place new orders on it until trading resumes and at least one clean quote has been observed (avoids firing a stop or limit order into a reopen auction print that's wildly away from fair value).
- **Trading suspension conditions (bot fully stands down, all symbols):** IBKR API disconnection lasting >5 minutes during market hours; broker account margin/cash discrepancy detected; AI analysis layer (both primary and backup) unreachable/erroring for the pre-market scan; any unhandled exception in the scoring or order-placement pipeline (fail-safe default is always "do nothing," never "guess and trade").

---

## Section 11 — Trade Frequency

- **Ideal trades per week: 2–4 new entries.** Consistent with 2–4 max concurrent positions and a 5–20 day average holding period — this isn't a high-frequency system, and shouldn't be.
- **Ideal trades per month: 8–15 new entries.**
- **Maximum trades per week (hard cap): 6.** If the scan is generating more "qualified" candidates than this consistently, treat it as a signal the score threshold is miscalibrated (too loose) rather than a green light to trade all of them — revisit in the Section 15 review cycle.
- **Minimum trades: none enforced.** There is deliberately no minimum-trade-frequency requirement anywhere in this system. A week or even a month of zero new entries during a hostile regime is a correct outcome, not underperformance (Section 6).
- **Avoiding overtrading — structural safeguards already built in above:** the max-4-position cap, the 1% risk/trade sizing, the score ≥ 70 bar, the regime gate, and the explicit "never lower the bar to find a trade" rule (Section 6) all mechanically throttle frequency without needing a separate arbitrary "don't trade too much" rule bolted on top.

---

## Section 12 — AI Prompt Design (production-ready)

Send this as a **system + user message pair** to each AI model (Gemini primary, DeepSeek cross-check), with the day's quantitatively-scored shortlist (typically 5–10 names) injected as structured JSON. Require **strict JSON-only output** so the bot can parse it programmatically without brittle text parsing.

**System prompt:**
```
You are a risk-focused equity research assistant supporting a fully automated,
rules-based swing-trading system. Your role is NOT to invent a trading signal —
the quantitative filters and score have already been applied. Your role is to:
(1) sanity-check each candidate against current news/context for hidden risks
    the numeric filters would not catch (pending litigation, regulatory action,
    management turnover, accounting concerns, sector-wide bad news, competitive
    threats, dilution risk, upcoming binary catalysts not already excluded),
(2) identify the specific catalyst(s), if any, behind the stock's relative
    strength, (3) provide a calibrated 0-100 confidence score for continuation
    over the next 5-10 trading days, (4) flag anything that should downgrade or
    disqualify the candidate despite its numeric score.
You must default to caution: capital preservation is the priority, and a
"pass"/no-trade recommendation is a valid and often correct output. Do not
recommend a stock you would not be comfortable explaining to a risk committee.
Respond ONLY with valid JSON matching the schema provided. No prose outside
the JSON. No markdown code fences.
```

**User message (templated, injected daily):**
```
Today's date: {DATE}
Market regime: {REGIME_STATUS}  (e.g., "risk-on: SPY > 200SMA, VIX 14.2, breadth 62%")

Candidates (already passed mandatory quantitative filters and are ranked by a
0-100 composite score):

{JSON_ARRAY_OF_CANDIDATES}
  // each item: { ticker, composite_score, sector, price, atr14, rsi14,
  //   macd_hist, adx14, pct_from_52wk_high, rel_strength_3m, rel_strength_6m,
  //   rev_growth_yoy, eps_growth_yoy, fcf_positive, net_debt_ebitda,
  //   days_to_next_earnings, short_interest_pct_float, sector_rel_strength }

For EACH candidate, return an object with this exact schema:
{
  "ticker": string,
  "recommendation": "trade" | "trade_reduced_size" | "pass",
  "confidence_score": integer 0-100,
  "estimated_continuation_probability_5_10d": integer 0-100,
  "downside_risk_notes": string (max 3 sentences, specific, no filler),
  "identified_catalyst": string (max 2 sentences),
  "hidden_risks_flagged": array of strings (empty array if none found),
  "suggested_stop_adjustment": "none" | "tighten" | "widen",
  "rationale": string (max 3 sentences)
}

Return a JSON array of these objects, one per candidate, ordered by
confidence_score descending. Respond with ONLY the JSON array.
```

**Bot-side handling of the response:**
- Parse JSON; if parsing fails or schema validation fails, treat as "AI unavailable" for that model (Section 10 fallback logic), do NOT retry with a looser parser that guesses at malformed output.
- A candidate only proceeds to order placement if **both** models return `"trade"` (full size) or at least one returns `"trade"` and neither returns a `hidden_risks_flagged` entry that maps to a known disqualifying category (litigation, accounting, regulatory) — in which case it downgrades to `"trade_reduced_size"` or is dropped, per Section 6/8.
- If the two models materially disagree (one "trade," one "pass," or confidence scores differ by >30 points), default to **no trade** on that name — disagreement is treated as elevated uncertainty, not resolved by picking the more optimistic model.

---

## Section 13 — System Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│  SCHEDULER (cron / APScheduler, runs on a small always-on VM)      │
└───────────────┬──────────────────────────────────────────────────┘
                │ 07:30 ET daily
                ▼
┌────────────────────────┐
│ 1. DATA COLLECTION      │  Pull OHLCV, fundamentals, calendar, news
│    (Section 14 APIs)    │  for full universe; cache to local DB
└───────────┬──────────────┘
            ▼
┌────────────────────────┐
│ 2. REGIME CHECK          │  SPY/200SMA, VIX, breadth → risk-on/off/caution
└───────────┬──────────────┘
     risk-off?──yes──▶ log "no trade day" → END
            │no/caution
            ▼
┌────────────────────────┐
│ 3. UNIVERSE FILTER +     │  Mandatory gates → shortlist (~80-150)
│    RELATIVE STRENGTH     │
└───────────┬──────────────┘
            ▼
┌────────────────────────┐
│ 4. SCORING ENGINE        │  Weighted composite score (Section 5)
│    (RISK ENGINE reads     │  → top 5-10 candidates
│    portfolio state here) │
└───────────┬──────────────┘
            ▼
┌────────────────────────┐
│ 5. AI ANALYSIS LAYER     │  Gemini + DeepSeek cross-check (Section 12)
└───────────┬──────────────┘
            ▼
┌────────────────────────┐
│ 6. FINAL CANDIDATE LIST  │  Merge quant score + AI confidence + regime
│    + RISK ENGINE SIZING  │  → position size per Section 7
└───────────┬──────────────┘
            ▼
┌────────────────────────┐      ┌──────────────────────────┐
│ 7. ENTRY MONITOR         │◀────▶│  IBKR TWS/Gateway API     │
│    (waits for Section 8  │      │  (order placement,        │
│    confirmation intraday)│      │   fills, account state)   │
└───────────┬──────────────┘      └──────────────────────────┘
            ▼
┌────────────────────────┐
│ 8. POSITION MONITOR /    │  Runs continuously during market hours;
│    EXIT ENGINE            │  Section 9 rules; independent of daily scan
└───────────┬──────────────┘
            ▼
┌────────────────────────┐
│ 9. LOGGING & JOURNAL     │  Every decision, score, AI response, fill,
│    (Section 15/16 input) │  and rejection reason persisted to DB
└───────────┬──────────────┘
            ▼
┌────────────────────────┐
│ 10. ALERTING              │  Push notification / email on: trade opened,
│                            │  trade closed, circuit breaker triggered,
│                            │  system error, AI/data outage
└────────────────────────┘

RISK ENGINE: a standing module (not a pipeline stage) consulted by steps
4, 6, 7, and 8 — enforces Section 7/10 limits (max positions, portfolio
heat, correlation, drawdown circuit breakers) as hard gates that can veto
any order regardless of what upstream stages recommend.

ERROR HANDLING / FALLBACK: every external call (data API, AI API, broker
API) wrapped with retry (max 3, exponential backoff) → on final failure,
log + alert + fail safe to "no action" for that component. The system
never falls back to a "best guess" trade when a dependency is degraded.
```

---

## Section 14 — Recommended APIs (free/low-cost)

| Purpose | Recommended | Why |
|---|---|---|
| **Broker/execution/account data** | IBKR TWS API / Client Portal API (via `ib_insync` or `ib_async` Python wrapper) | Required since IBKR is the broker; also provides real-time quotes, historical bars, and account/margin state in one integration |
| **Market data (EOD OHLCV, broad universe)** | IBKR historical data endpoints (primary, since you're already connected) + free fallback via a provider like Stooq or Yahoo-Finance-style endpoints for backup/cross-check | Avoids paying for a second full market-data subscription; IBKR data is sufficient for daily-bar scanning |
| **Fundamentals** | Financial Modeling Prep (free tier) or SEC EDGAR full-text/XBRL API (fully free, official source, no key limits beyond fair-use) | EDGAR is free and authoritative for the "quality overlay" (revenue growth, FCF, debt) but requires more parsing work; FMP's free tier trades parsing effort for a modest rate limit |
| **Economic calendar** | Free tier of a provider such as Trading Economics or FRED (Federal Reserve Economic Data, fully free, official) for macro release dates | FRED is free, reliable, and sufficient for flagging FOMC/CPI/NFP dates |
| **Earnings calendar** | IBKR contract details / a free earnings-calendar endpoint (e.g., Financial Modeling Prep free tier) | Needed for the mandatory earnings-blackout exclusion filter |
| **News** | Free tier of a news API (e.g., NewsAPI free tier for headline-level scanning) feeding into the AI layer's context, not used for standalone signal generation | Keeps this to the "hidden risk / catalyst context" role the AI needs, per Section 12 |
| **Sentiment** | Skip a dedicated paid sentiment API; let the AI layer infer qualitative sentiment from the news headlines already pulled | Free sentiment APIs are generally low-quality; better to spend the "budget" on a capable LLM read of raw headlines |
| **VIX / regime data** | IBKR (VIX index data) or CBOE's free public VIX data | Needed for Section 10's volatility filter |

**General principle:** IBKR itself covers most of the core data needs (quotes, historical bars, account state) since you're already paying for/using the platform — minimize the number of *additional* third-party subscriptions to reduce both cost and the number of external failure points the error-handling layer has to account for.

---

## Section 15 — Continuous Improvement

- **Backtesting** (Section 16 detail): run before any live capital, and re-run any time a rule changes.
- **Forward testing (paper trading):** minimum **3 months** of IBKR paper-trading the exact live pipeline (same code path, simulated fills) before committing real capital, specifically to catch execution/API/data issues that a backtest can't reveal.
- **Walk-forward optimization:** re-optimize scoring weights and thresholds on a rolling basis (e.g., every 6 months) using only data up to that point, then validate on the next out-of-sample period — never optimize on the full dataset and deploy those same parameters.
- **Performance metrics tracked continuously:** win rate, average win/average loss (payoff ratio), profit factor, Sharpe ratio, Sortino ratio, max drawdown, average holding period, correlation of returns to SPY, and — critically for a small account — post-commission/slippage net return vs. gross return.
- **Model evaluation:** periodically log how often the AI layer's confidence scores actually correlated with trade outcomes; if confidence scores show no predictive value over time, that's a signal to simplify (or replace) the AI layer rather than keep trusting it by default.
- **Parameter optimization:** treat every threshold in Sections 4–10 as a hypothesis, not a fixed truth — but change parameters slowly, one at a time, with a documented reason and a subsequent walk-forward validation, never several at once (you lose the ability to attribute performance changes to a specific fix).
- **Trade journaling:** every trade logs entry/exit reason, all scores at time of entry, AI responses, regime state, and a post-hoc note — this is the raw material for Section 15/16's iteration loop, and its absence is one of the most common reasons retail systematic traders never actually improve their system over time.

---

## Section 16 — Backtesting

- **Minimum historical period: 10+ years**, explicitly spanning:
  - **A bull market** (e.g., 2013–2019 pre-COVID, or 2023–2025)
  - **A bear market** (e.g., 2022, or 2008–2009 if data/liquidity comparability allows)
  - **A sideways/choppy market** (e.g., 2015–2016, or 2011)
  - **A volatility shock** (e.g., COVID crash March 2020, or the 2018 Q4 selloff) — specifically to validate the regime filters and circuit breakers actually behave as designed under stress, not just that the strategy is profitable in calm periods.
- **Performance metrics to compute:** CAGR, max drawdown, Sharpe, Sortino, Calmar ratio, win rate, payoff ratio, profit factor, average trade duration, exposure (% of time invested vs. cash), and worst single-month/single-week loss.
- **Monte Carlo analysis:** resample the historical trade sequence (block bootstrap, preserving some autocorrelation) thousands of times to build a distribution of possible equity curves — report the 5th-percentile (worst-case-ish) outcome, not just the single historical average path, since a single backtest path is one realization among many possible orderings of the same trades.
- **Stress testing:** explicitly simulate degraded conditions — 2× normal slippage, 1-day-delayed data, an AI-layer outage forcing fallback to quant-only scoring, and a simulated broker API disconnection during an open position — to verify the system fails safely (Section 10/13) rather than catastrophically under each.
- **Out-of-sample validation:** hold back the most recent 12–18 months of data entirely from any parameter tuning; only test the final, locked parameter set against this holdout once, at the end, as the closest available proxy for genuine forward performance.
- **Realistic cost modeling:** backtest must include commissions (or confirm $0 under IBKR Lite), a conservative slippage assumption (e.g., 0.1%–0.3% per side on the position sizes this account actually trades), and the actual bid/ask spread cost, not just theoretical close-to-close returns — small-account backtests that ignore these costs are systematically overoptimistic.

---

## Section 17 — Failure Modes and Mitigations

| Failure mode | Mitigation |
|---|---|
| **Market crash / correlated drawdown** | Regime filter (SPY < 200SMA → no new entries), VIX filter, drawdown circuit breakers (Section 10), max portfolio heat cap |
| **AI hallucination / fabricated rationale** | AI never overrides mandatory quantitative filters; dual-model cross-check with disagreement = no-trade; AI output is schema-validated, and any hallucinated ticker/field mismatch is auto-rejected |
| **Bad/stale data (wrong price, missing bar, corporate action not applied)** | Cross-check primary data source against a secondary free source before scoring; sanity-check bounds (e.g., reject any single-bar move >50% without a matched corporate-action flag as likely a data error, not a real gap) |
| **False breakouts** | ADX trend-quality filter, volume-confirmation requirement at entry, pullback-based entry (not chasing raw breakouts), partial profit-taking at 1.5R to reduce exposure to reversal |
| **Low liquidity / can't exit at expected price** | Hard liquidity mandatory filter (Section 4/5), position sizing capped relative to average daily dollar volume (never size a position above ~1% of 20-day average dollar volume) |
| **Gap risk (earnings, overnight news)** | Mandatory earnings-blackout exclusion, news-event exit rule (Section 9), diversification/correlation caps limit worst-case single-name gap impact to the single-stock exposure ceiling (35%) |
| **Slippage** | Limit orders only (never market orders except in the black-swan/emergency full-liquidation case), realistic slippage assumptions baked into backtesting (Section 16), liquidity filters |
| **API outages (data or AI)** | Retry-with-backoff, then fail-safe to "no action" (never guess); dual AI providers with automatic failover; cached previous-day data as a last-resort reference only, never used to place new orders blind |
| **Broker outages / connectivity loss** | Standing stop-loss orders are placed *with the broker* at entry (not held in bot memory), so a bot/connectivity outage does not remove existing downside protection on open positions; trading-suspension condition (Section 10) halts new activity until reconnection is verified |
| **Overfitting during backtesting/optimization** | Walk-forward validation, held-out out-of-sample period, conservative parameter-change process (Section 15), Monte Carlo distribution review rather than trusting a single equity curve |
| **Small-account-specific: concentration risk** | Max single-stock (35%) and sector (40%) exposure caps, correlation limits, 4-position cap balanced against the account's actual capacity to diversify |
| **Regulatory/account-structure risk (PDT)** | Cash account structure and swing-trade holding periods (Section 1) architecturally avoid the PDT rule rather than trying to manage around it |
| **Model/strategy decay over time** | Continuous performance tracking (Section 15), scheduled walk-forward re-optimization, explicit trigger to pause and review if trailing performance metrics deviate materially from backtested expectations |

---

## Section 18 — Final Recommended Strategy (Consolidated Blueprint)

**Structure:** IBKR cash account (PDT-exempt), IBKR Lite commission-free U.S. equities, fully automated Python pipeline.

**Strategy:** Cross-sectional relative-strength momentum for *what* to buy, mean-reversion pullback timing for *when* to buy, gated by a market-regime trend/volatility filter that can shut the whole system down to cash during hostile conditions.

**Scanning:** Daily pre-market run — liquidity/price/cap gates → trend + relative-strength shortlist → weighted technical/fundamental/catalyst scoring → mandatory-filter survivors only.

**AI role:** Gemini (primary, free tier) + DeepSeek (cross-check, free/cheap) perform structured qualitative risk review and confidence scoring on the top 5–10 quant-ranked candidates — never the primary signal generator, always a secondary gate that can only *downgrade or veto*, never *upgrade a rejected candidate*.

**Trade execution:** Only on candidates scoring ≥70 (full size) or 55–69 (half size, capacity-limited), only in risk-on or cautious-but-tolerable regimes, only via limit orders with objective entry confirmation (Section 8) — no forced trades, ever, on a day with no qualifying setup.

**Risk management:** 1% risk per trade, max 4 concurrent positions, max 4% total portfolio heat, hard stop-loss orders placed at the broker at time of entry, 8%/15% drawdown circuit breakers, sector/single-stock exposure caps, correlation limits, and a market-trend/VIX gate on all new entries.

**Exits:** ATR-based hard stop, 1.5R partial profit-take with breakeven stop move, trailing stop on the remainder, moving-average trend-break exit, 10-day soft time exit / 20-day hard time exit, mandatory pre-earnings and pre-binary-event exit.

**Frequency:** 2–4 trades/week target, 6/week hard cap, no minimum — weeks or months of inactivity in poor regimes are expected and correct.

**Validation before going live:** 10+ years multi-regime backtest with realistic cost modeling → Monte Carlo and stress testing → minimum 3 months of paper trading on the exact live code path → only then, deploy with real capital, starting deliberately undersized (e.g., trade at 50% of the calculated position sizes for the first month) before scaling to full sizing.

### Expected strengths
- Structurally avoids the PDT trap and matches trade frequency/position count to what a $5,400 account can actually support.
- Momentum + trend + quality overlay is one of the more evidence-backed combinations in the systematic equity literature, rather than a speculative pattern.
- Multiple independent circuit breakers (regime, drawdown, daily/weekly loss limits, correlation) mean no single failure point can blow up the account.
- "Never force a trade" is enforced architecturally (hard score threshold, no dynamic loosening), not left to willpower.

### Expected weaknesses (see Section 17 for full detail)
- Small account size caps diversification — idiosyncratic single-stock risk is real and only partially mitigated by exposure caps.
- Momentum strategies underperform in prolonged sideways/choppy markets — the regime filter reduces but doesn't eliminate this drag.
- Free-tier data/AI APIs carry rate limits and occasional reliability gaps that a paid institutional feed wouldn't have — the fail-safe architecture (Section 10/13/17) is what makes this acceptable rather than a hidden landmine.
- Backtested edges can decay; this system requires ongoing monitoring and periodic re-validation, not "set and forget."

### Implementation priority (build order)
1. IBKR API connectivity + paper account + basic order placement/monitoring (Section 13 skeleton).
2. Data pipeline: historical bars, fundamentals, calendar (Section 14).
3. Universe filter + scoring engine (Sections 4–5), fully testable offline against historical data.
4. Backtesting engine (Section 16) — validate the quant-only system (no AI layer yet) across multiple regimes first.
5. Risk engine (Sections 7/10) as a standalone, hard-gated module — test it can veto trades correctly before wiring it into the live pipeline.
6. AI analysis layer (Sections 3/12) — add as a secondary gate once the quant system is already backtested and validated on its own.
7. Entry/exit execution logic (Sections 8–9) against the paper account.
8. Logging, alerting, and journaling (Section 15) — required infrastructure before any live capital, not an afterthought.
9. 3-month minimum paper-trading run of the complete pipeline.
10. Live deployment at reduced size, scaling to full sizing only after the live results are consistent with backtested/paper-traded expectations.
