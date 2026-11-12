'use client';

import { useEffect, useState, useCallback, useMemo } from 'react';
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
} from 'recharts';

// ─── Interfaces ───────────────────────────────────────────────────────────────

interface Position {
  ticker: string;
  shares: number;
  avg_cost: number;
  current_price: number;
  market_value: number;
  pnl: number;
  pnl_pct: number;
  realised_partial_pnl: number;
  trade_status: 'open' | 'sold_half' | 'closed';
}

interface Account {
  TotalCashValue?: number;
  NetLiquidation?: number;
  AvailableFunds?: number;
  BuyingPower?: number;
  TotalCashValue_AUD?: number;
  NetLiquidation_AUD?: number;
  AvailableFunds_AUD?: number;
  BuyingPower_AUD?: number;
  ExchangeRate_USD?: number;
  ExchangeRate_AUD?: number;
}

interface PortfolioData {
  connected: boolean;
  mode: string;
  account_type?: string;
  paper_strategy?: string;
  positions: Position[];
  account: Account;
  strategy_alert?: {
    type: string;
    threshold?: number;
    message: string;
  } | null;
  error?: string;
}

interface DailyPnlPoint {
  date: string;
  daily_pnl: number;
  cumulative_pnl: number;
  daily_pnl_aud?: number;
  cumulative_pnl_aud?: number;
  net_liq_usd?: number | null;
  daily_pct?: number;
  cumulative_pct?: number;
  daily_fees?: number;
  daily_fees_aud?: number;
  cumulative_fees?: number;
  source?: string;
}

interface PnlHistory {
  chart_data: DailyPnlPoint[];
  all_time_realized_pnl: number;
  total_closed_trades: number;
  winning_trades: number;
  losing_trades: number;
  all_time_fees?: number;
}

interface ExchangeRateData {
  rate: number;
  fetched_at: string | null;
  stale: boolean;
  age_minutes: number | null;
}

type AuthFetch = (url: string, init?: RequestInit) => Promise<Response>;

// ─── Helpers ──────────────────────────────────────────────────────────────────

function fmt(val: number | null | undefined, prefix = '$'): string {
  if (val == null || isNaN(val)) return '—';
  return `${prefix}${Math.abs(val).toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function fmtSigned(val: number | null | undefined, prefix = '$'): string {
  if (val == null || isNaN(val)) return '—';
  const sign = val >= 0 ? '+' : '-';
  return `${sign}${prefix}${Math.abs(val).toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

const STARTING_CAPITAL_AUD = 7900;

export default function PortfolioTab({
  authFetch,
  tradingMode = 'paper',
}: {
  authFetch: AuthFetch;
  tradingMode?: 'paper' | 'live';
}) {
  const [data, setData] = useState<PortfolioData | null>(null);
  const [pnlHistory, setPnlHistory] = useState<PnlHistory | null>(null);
  const [fxData, setFxData] = useState<ExchangeRateData | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [timeframe, setTimeframe] = useState<'1W' | '1M' | '3M' | '1Y' | 'All time'>('All time');

  // Manage modal states
  const [managedPosition, setManagedPosition] = useState<Position | null>(null);
  const [actionInProgress, setActionInProgress] = useState(false);
  const [actionMessage, setActionMessage] = useState<string | null>(null);

  // Fetch live portfolio from IBKR
  const fetchPortfolio = useCallback(async () => {
    try {
      const res = await authFetch('/api/portfolio');
      if (res.ok) {
        const json: PortfolioData = await res.json();
        setData(json);
        setLastUpdated(new Date());
      }
    } catch {
      // Failed to reach API
    } finally {
      setLoading(false);
    }
  }, [authFetch]);

  // Fetch real P&L history
  const fetchPnlHistory = useCallback(async () => {
    try {
      const res = await authFetch('/api/pnl-history');
      if (res.ok) {
        const json: PnlHistory = await res.json();
        setPnlHistory(json);
      }
    } catch {
      // Fail silently
    }
  }, [authFetch]);

  // Fetch real FX rate
  const fetchFxRate = useCallback(async () => {
    try {
      const res = await authFetch('/api/exchange-rate');
      if (res.ok) {
        const json: ExchangeRateData = await res.json();
        setFxData(json);
      }
    } catch {
      // Fail silently
    }
  }, [authFetch]);

  useEffect(() => {
    fetchPortfolio();
    fetchPnlHistory();
    fetchFxRate();

    const interval = setInterval(fetchPortfolio, 30_000);
    const pnlInterval = setInterval(fetchPnlHistory, 60_000);
    return () => {
      clearInterval(interval);
      clearInterval(pnlInterval);
    };
  }, [fetchPortfolio, fetchPnlHistory, fetchFxRate]);

  // Execute sell via manage modal
  const handleExecuteSell = async (ticker: string) => {
    setActionInProgress(true);
    setActionMessage(null);
    try {
      const res = await authFetch('/api/sell-stock', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ticker }),
      });
      const json = await res.json();
      if (json.status === 'ok' || json.deferred) {
        setActionMessage(`Order placed: ${json.message || `Sold ${ticker}`}`);
        setTimeout(() => {
          setManagedPosition(null);
          setActionMessage(null);
          fetchPortfolio();
          fetchPnlHistory();
        }, 1800);
      } else {
        setActionMessage(`Failed: ${json.detail || json.result?.error || 'Execution error'}`);
      }
    } catch (err) {
      setActionMessage(`Error: ${err instanceof Error ? err.message : 'Network error'}`);
    } finally {
      setActionInProgress(false);
    }
  };

  // Live account values from IBKR
  const account = data?.account ?? {};
  const positions = data?.positions ?? [];

  // Live FX rate
  const usdToAud = fxData?.rate ?? account.ExchangeRate_USD ?? 1.55;
  const audToUsd = 1 / usdToAud;

  // Real position metrics
  const unrealisedPnl = positions.reduce((sum, p) => sum + (p.pnl || 0), 0);
  const openPartialPnl = positions.reduce((sum, p) => sum + (p.realised_partial_pnl || 0), 0);
  const totalPosValueUsd = positions.reduce((sum, p) => sum + (p.market_value || 0), 0);
  const totalPosValueAud = totalPosValueUsd * usdToAud;

  const allTimeFeesUsd = pnlHistory?.all_time_fees ?? 0;
  const allTimeFeesAud = allTimeFeesUsd * usdToAud;

  // Open P&L = unrealised P&L + banked partials
  const openPnlUsd = unrealisedPnl + openPartialPnl;
  const openPnlAud = openPnlUsd * usdToAud;

  // Net Liquidation & Available Cash from IBKR
  // Handle per-currency balances safely, falling back to USD * FX if AUD is 0 or absent
  const netLiqRawAud = Number(account.NetLiquidation_AUD || 0);
  const netLiqRawUsd = Number(account.NetLiquidation || 0);
  const netLiqAud = netLiqRawAud > 0
    ? netLiqRawAud
    : (netLiqRawUsd > 0 ? netLiqRawUsd * usdToAud : 0);
  const netLiqUsd = netLiqRawUsd > 0
    ? netLiqRawUsd
    : (netLiqRawAud > 0 ? netLiqRawAud * audToUsd : 0);

  const availRawAud = Number(account.AvailableFunds_AUD || account.TotalCashValue_AUD || 0);
  const availRawUsd = Number(account.AvailableFunds || account.TotalCashValue || 0);
  const availableCashAud = availRawAud > 0
    ? availRawAud
    : (availRawUsd > 0 ? availRawUsd * usdToAud : 0);
  const availableCashUsd = availRawUsd > 0
    ? availRawUsd
    : (availRawAud > 0 ? availRawAud * audToUsd : 0);

  // All-time Realised / All-Time P&L: calculated directly from $7,900 starting capital vs current Net Liq in AUD
  // If netLiqAud is $7,500, user is down $400 (-A$400.00). If $8,100, user is up $200 (+A$200.00).
  const allTimePnlAud = netLiqAud > 0 ? (netLiqAud - STARTING_CAPITAL_AUD) : 0;
  const allTimePnlUsd = allTimePnlAud * audToUsd;
  const allTimePnlPositive = allTimePnlAud >= 0;

  // All-time return percentage
  const allTimeReturnPct = STARTING_CAPITAL_AUD > 0 && netLiqAud > 0
    ? ((allTimePnlAud / STARTING_CAPITAL_AUD) * 100)
    : 0;

  // Win/Loss metrics
  const winningTrades = pnlHistory?.winning_trades ?? 0;
  const losingTrades = pnlHistory?.losing_trades ?? 0;
  const totalTrades = pnlHistory?.total_closed_trades ?? 0;
  const winRateStr = totalTrades > 0 ? `${((winningTrades / totalTrades) * 100).toFixed(1)}%` : '—';

  // Buying power percentage
  const buyingPowerPct = netLiqAud > 0 ? ((availableCashAud / netLiqAud) * 100).toFixed(1) : '0.0';

  // Unrealised P&L on open cost percentage
  const openCostAud = totalPosValueAud - (unrealisedPnl * usdToAud);
  const unrealisedPctOnCost = openCostAud > 0 ? ((unrealisedPnl * usdToAud / openCostAud) * 100).toFixed(2) : '0.00';

  // Sync date string
  const syncDateString = useMemo(() => {
    if (!lastUpdated) return 'CONNECTING TO IBKR…';
    const dateFormatted = lastUpdated.toLocaleDateString('en-AU', { day: '2-digit', month: 'short', year: 'numeric' }).toUpperCase();
    const timeFormatted = lastUpdated.toLocaleTimeString('en-AU', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    return `${dateFormatted} · LAST SYNC ${timeFormatted} AEDT`;
  }, [lastUpdated]);

  // Construct chart dataset enriched with AUD values and today's live point
  const rawChartData = useMemo(() => {
    const list = pnlHistory?.chart_data ?? [];
    const todayStr = new Date().toISOString().split('T')[0];

    const liveCumulativeAud = netLiqAud > 0 ? (netLiqAud - STARTING_CAPITAL_AUD) : openPnlAud;
    const liveCumulativeUsd = liveCumulativeAud * audToUsd;
    const liveDailyAud = openPnlAud;
    const liveDailyUsd = openPnlUsd;

    const livePoint: DailyPnlPoint = {
      date: todayStr,
      daily_pnl: liveDailyUsd,
      cumulative_pnl: liveCumulativeUsd,
      daily_pnl_aud: liveDailyAud,
      cumulative_pnl_aud: liveCumulativeAud,
      daily_fees: 0,
      daily_fees_aud: 0,
      net_liq_usd: netLiqUsd,
    };

    if (list.length === 0) {
      if (netLiqAud > 0) {
        // If no snapshots captured yet, create baseline starting capital (7 days ago) + today's live point
        const dBaseline = new Date(Date.now() - 7 * 86400000).toISOString().split('T')[0];
        return [
          {
            date: dBaseline,
            daily_pnl: 0,
            cumulative_pnl: 0,
            daily_pnl_aud: 0,
            cumulative_pnl_aud: 0,
            daily_fees: 0,
            daily_fees_aud: 0,
            net_liq_usd: STARTING_CAPITAL_AUD * audToUsd,
          },
          livePoint,
        ];
      }
      return [];
    }

    const enriched: DailyPnlPoint[] = list.map((item) => ({
      ...item,
      daily_pnl_aud: (item.daily_pnl || 0) * usdToAud,
      cumulative_pnl_aud: (item.cumulative_pnl || 0) * usdToAud,
      daily_fees_aud: (item.daily_fees || 0) * usdToAud,
    }));

    const last = enriched[enriched.length - 1];
    if (last.date === todayStr) {
      return [...enriched.slice(0, -1), { ...last, ...livePoint }];
    }
    return [...enriched, livePoint];
  }, [pnlHistory?.chart_data, netLiqAud, netLiqUsd, openPnlAud, openPnlUsd, usdToAud, audToUsd]);

  // Filter chart data by timeframe
  const filteredChartData = useMemo(() => {
    if (rawChartData.length === 0) return [];
    if (timeframe === 'All time') return rawChartData;

    const daysMap: Record<'1W' | '1M' | '3M' | '1Y', number> = {
      '1W': 7,
      '1M': 30,
      '3M': 90,
      '1Y': 365,
    };
    const days = daysMap[timeframe] || 7;
    const now = Date.now();
    const cutoff = now - days * 86400000;

    const subset = rawChartData.filter((pt) => {
      const t = new Date(pt.date).getTime();
      return !isNaN(t) && t >= cutoff;
    });

    // Ensure at least 2 points render if available in the dataset
    if (subset.length < 2 && rawChartData.length >= 2) {
      const count = timeframe === '1W' ? 7 : timeframe === '1M' ? 30 : timeframe === '3M' ? 90 : 365;
      return rawChartData.slice(-Math.min(count, rawChartData.length));
    }

    return subset.length > 0 ? subset : rawChartData;
  }, [rawChartData, timeframe]);

  // Calculate P&L over the selected timeframe for the banner and color
  const { periodPnlAud, periodPnlIsPositive } = useMemo(() => {
    if (timeframe === 'All time') {
      const pnl = netLiqAud > 0 ? (netLiqAud - STARTING_CAPITAL_AUD) : allTimePnlAud;
      return { periodPnlAud: pnl, periodPnlIsPositive: pnl >= 0 };
    }

    if (filteredChartData.length >= 2) {
      const first = filteredChartData[0];
      const last = filteredChartData[filteredChartData.length - 1];
      const delta = (last.cumulative_pnl_aud ?? 0) - (first.cumulative_pnl_aud ?? 0);
      return { periodPnlAud: delta, periodPnlIsPositive: delta >= 0 };
    } else if (filteredChartData.length === 1) {
      const dayPnl = filteredChartData[0].daily_pnl_aud ?? 0;
      return { periodPnlAud: dayPnl, periodPnlIsPositive: dayPnl >= 0 };
    }

    return { periodPnlAud: 0, periodPnlIsPositive: true };
  }, [timeframe, netLiqAud, allTimePnlAud, filteredChartData]);

  // Dynamic chart colors: emerald green if positive, vibrant red if negative
  const chartStrokeColor = periodPnlIsPositive ? '#059669' : '#ef4444';
  const chartGradientId = periodPnlIsPositive ? 'chartGradGreen' : 'chartGradRed';

  return (
    <div>
      {/* ── Page Header ────────────────────────────────────────── */}
      <div className="page-title-block">
        <h1 className="page-title-heading">Portfolio</h1>
        <p className="page-title-subtitle">Your capital, working smarter.</p>
        <p className="page-title-meta">{syncDateString}</p>
      </div>

      {/* ── All Time P&L Hero Card (Dark Spruce) ────────────────── */}
      <div className="hero-pnl-card">
        <div className="hero-pnl-top-row">
          <div>
            <div className="hero-pnl-label">ALL TIME P&amp;L</div>
            <div className="hero-pnl-amounts">
              <span className="hero-pnl-main" style={{ color: allTimePnlPositive ? '#ffffff' : '#f87171' }}>
                {loading ? '—' : (
                  allTimePnlPositive
                    ? `+${fmt(allTimePnlAud, 'A$')}`
                    : `-${fmt(Math.abs(allTimePnlAud), 'A$')}`
                )}
              </span>
              <span className="hero-pnl-usd" style={{ color: allTimePnlPositive ? '#34d399' : '#f87171' }}>
                {loading ? '—' : `${fmtSigned(allTimePnlUsd, '$')} USD`}
              </span>
            </div>
          </div>
          <div className="hero-stats-right-col">
            <span
              className="hero-badge-trend"
              style={{
                color: allTimeReturnPct >= 0 ? '#34d399' : '#f87171',
                background: allTimeReturnPct >= 0 ? 'rgba(52, 211, 153, 0.12)' : 'rgba(239, 68, 68, 0.12)',
                borderColor: allTimeReturnPct >= 0 ? 'rgba(52, 211, 153, 0.25)' : 'rgba(239, 68, 68, 0.25)',
              }}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <line x1="7" y1={allTimeReturnPct >= 0 ? "17" : "7"} x2="17" y2={allTimeReturnPct >= 0 ? "7" : "17"} />
                <polyline points={allTimeReturnPct >= 0 ? "7 7 17 7 17 17" : "7 17 17 17 17 7"} />
              </svg>
              {allTimeReturnPct >= 0 ? `+${allTimeReturnPct.toFixed(2)}%` : `${allTimeReturnPct.toFixed(2)}%`}
            </span>
            <div className="hero-win-loss-grid">
              <div className="hero-win-loss-item">
                <span className="hero-win-loss-num">{winningTrades}</span>
                <span className="hero-win-loss-lbl">Wins</span>
              </div>
              <div className="hero-win-loss-item">
                <span className="hero-win-loss-num">{losingTrades}</span>
                <span className="hero-win-loss-lbl">Losses</span>
              </div>
              <div className="hero-win-loss-item">
                <span className="hero-win-loss-num">{winRateStr}</span>
                <span className="hero-win-loss-lbl">Win rate</span>
              </div>
            </div>
          </div>
        </div>

        <div className="hero-pnl-metrics-row">
          <div className="hero-metric-item">
            <div className="label">Net Liq</div>
            <div className="value">{loading ? '—' : fmt(netLiqAud, 'A$')}</div>
          </div>
          <div className="hero-metric-item">
            <div className="label">Open P&amp;L</div>
            <div className="value" style={{ color: openPnlAud >= 0 ? '#34d399' : '#f87171' }}>
              {loading ? '—' : fmtSigned(openPnlAud, 'A$')}
            </div>
          </div>
          <div className="hero-metric-item">
            <div className="label">All Time Realised</div>
            <div className="value" style={{ color: allTimePnlPositive ? '#34d399' : '#f87171' }}>
              {loading ? '—' : (
                allTimePnlPositive
                  ? `+${fmt(allTimePnlAud, 'A$')}`
                  : `-${fmt(Math.abs(allTimePnlAud), 'A$')}`
              )}
            </div>
          </div>
          <div className="hero-metric-item">
            <div className="label">Fees Paid</div>
            <div className="value">{loading ? '—' : fmt(allTimeFeesAud, 'A$')}</div>
          </div>
        </div>
      </div>

      {/* ── P&L Over Time Chart Card ────────────────────────────── */}
      <div className="theme-card" style={{ marginBottom: 24 }}>
        <div className="table-header-flex">
          <div>
            <h3 className="table-title-bold">P&amp;L Over Time</h3>
            {/* Banner above graph: updates dynamically with timeframe P&L and status */}
            <div style={{
              fontSize: 13,
              fontWeight: 700,
              color: periodPnlIsPositive ? '#059669' : '#ef4444',
              marginTop: 2,
              display: 'flex',
              alignItems: 'center',
              gap: 6,
            }}>
              <span>
                {periodPnlIsPositive
                  ? `+${fmt(periodPnlAud, 'A$')}`
                  : `-${fmt(Math.abs(periodPnlAud), 'A$')}`}
              </span>
              <span style={{ color: '#64748b', fontWeight: 500, fontSize: 12 }}>
                · {timeframe === 'All time' ? 'all time' : `past ${timeframe}`}
              </span>
            </div>
          </div>
          {/* Timeframe selector */}
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {(['1W', '1M', '3M', '1Y', 'All time'] as const).map((tf) => (
              <button
                key={tf}
                onClick={() => setTimeframe(tf)}
                style={{
                  background: timeframe === tf ? '#0d2523' : '#f8faf9',
                  color: timeframe === tf ? '#ffffff' : '#64748b',
                  border: '1px solid',
                  borderColor: timeframe === tf ? '#0d2523' : '#e6ece9',
                  borderRadius: 6,
                  padding: '4px 10px',
                  fontSize: 12,
                  fontWeight: 600,
                  cursor: 'pointer',
                  transition: 'all 0.15s ease',
                }}
              >
                {tf}
              </button>
            ))}
          </div>
        </div>

        {/* Recharts Area Curve */}
        <div style={{ height: 260, width: '100%', marginTop: 12 }}>
          {filteredChartData.length === 0 ? (
            <div style={{
              height: '100%',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              color: '#94a3b8',
              fontSize: 13,
            }}>
              <span style={{ fontSize: 24, marginBottom: 6 }}>📈</span>
              <p>No P&amp;L chart history yet</p>
              <span style={{ fontSize: 11.5, color: '#94a3b8', marginTop: 4 }}>
                Daily snapshots record after US market close to plot the performance curve.
              </span>
            </div>
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={filteredChartData} margin={{ top: 10, right: 10, left: -10, bottom: 0 }}>
                <defs>
                  <linearGradient id="chartGradGreen" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#059669" stopOpacity={0.25} />
                    <stop offset="100%" stopColor="#059669" stopOpacity={0.0} />
                  </linearGradient>
                  <linearGradient id="chartGradRed" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#ef4444" stopOpacity={0.25} />
                    <stop offset="100%" stopColor="#ef4444" stopOpacity={0.0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f3" vertical={false} />
                <XAxis
                  dataKey="date"
                  tickFormatter={(d: string) => {
                    try {
                      const parts = d.split('-');
                      if (parts.length === 3) {
                        const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
                        return `${parseInt(parts[2], 10)} ${months[parseInt(parts[1], 10) - 1]}`;
                      }
                      const dateObj = new Date(d);
                      return dateObj.toLocaleDateString('en-US', { day: '2-digit', month: 'short' });
                    } catch {
                      return d;
                    }
                  }}
                  tick={{ fill: '#94a3b8', fontSize: 11 }}
                  axisLine={false}
                  tickLine={false}
                />
                <YAxis
                  tickFormatter={(val: number) => {
                    if (Math.abs(val) >= 1000) {
                      return `${val >= 0 ? '' : '-'}$${(Math.abs(val) / 1000).toFixed(1)}k`;
                    }
                    return `${val >= 0 ? '' : '-'}$${Math.abs(Math.round(val))}`;
                  }}
                  tick={{ fill: '#94a3b8', fontSize: 11 }}
                  axisLine={false}
                  tickLine={false}
                />
                <Tooltip
                  content={({ active, payload }) => {
                    if (!active || !payload || !payload.length) return null;
                    const pt = payload[0].payload as DailyPnlPoint;
                    const dayMade = Number(pt.daily_pnl_aud ?? ((pt.daily_pnl || 0) * usdToAud));
                    const allTimeOnDay = Number(pt.cumulative_pnl_aud ?? ((pt.cumulative_pnl || 0) * usdToAud));
                    const feesPaid = Number(pt.daily_fees_aud ?? ((pt.daily_fees || 0) * usdToAud));

                    let formattedDate = pt.date;
                    try {
                      const d = new Date(pt.date);
                      if (!isNaN(d.getTime())) {
                        formattedDate = d.toLocaleDateString('en-AU', {
                          day: '2-digit',
                          month: 'short',
                          year: 'numeric',
                        });
                      }
                    } catch {}

                    const isDownAllTime = allTimeOnDay < 0;

                    return (
                      <div style={{
                        background: '#ffffff',
                        border: '1px solid #e2e8e5',
                        borderRadius: 8,
                        padding: '10px 14px',
                        boxShadow: '0 6px 20px rgba(0,0,0,0.12)',
                        fontSize: 12,
                        minWidth: 200,
                      }}>
                        <div style={{
                          fontWeight: 700,
                          color: '#0f172a',
                          marginBottom: 8,
                          borderBottom: '1px solid #f1f5f3',
                          paddingBottom: 4,
                          fontSize: 12,
                        }}>
                          {formattedDate}
                        </div>

                        {/* 1. How much made that day */}
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 5 }}>
                          <span style={{ color: '#64748b' }}>Made that day:</span>
                          <span style={{ fontWeight: 700, color: dayMade >= 0 ? '#059669' : '#ef4444' }}>
                            {dayMade >= 0 ? `+${fmt(dayMade, 'A$')}` : `-${fmt(Math.abs(dayMade), 'A$')}`}
                          </span>
                        </div>

                        {/* 2. How much down all time on that day */}
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 5 }}>
                          <span style={{ color: '#64748b' }}>
                            {isDownAllTime ? 'Down all time:' : 'Up all time:'}
                          </span>
                          <span style={{ fontWeight: 700, color: isDownAllTime ? '#ef4444' : '#059669' }}>
                            {isDownAllTime ? `-${fmt(Math.abs(allTimeOnDay), 'A$')}` : `+${fmt(allTimeOnDay, 'A$')}`}
                          </span>
                        </div>

                        {/* 3. Fees paid that day */}
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                          <span style={{ color: '#64748b' }}>Fees paid that day:</span>
                          <span style={{ fontWeight: 600, color: '#0f172a' }}>
                            {fmt(feesPaid, 'A$')}
                          </span>
                        </div>
                      </div>
                    );
                  }}
                />
                <Area
                  type="monotone"
                  dataKey="cumulative_pnl_aud"
                  stroke={chartStrokeColor}
                  strokeWidth={2.5}
                  fill={`url(#${chartGradientId})`}
                />
              </AreaChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      {/* ── 4 Stat Cards Grid ───────────────────────────────────── */}
      <div className="stats-cards-grid">
        <div className="stat-metric-card">
          <div className="stat-metric-label">Net Liq</div>
          <div className="stat-metric-val">{loading ? '—' : fmt(netLiqAud, 'A$')}</div>
          <div className="stat-metric-subtext">Total account equity</div>
        </div>
        <div className="stat-metric-card">
          <div className="stat-metric-label">Available Cash</div>
          <div className="stat-metric-val">{loading ? '—' : fmt(availableCashAud, 'A$')}</div>
          <div className="stat-metric-subtext">{buyingPowerPct}% buying power</div>
        </div>
        <div className="stat-metric-card">
          <div className="stat-metric-label">Open Pos Value</div>
          <div className="stat-metric-val">{loading ? '—' : fmt(totalPosValueAud, 'A$')}</div>
          <div className="stat-metric-subtext">{positions.length} active positions</div>
        </div>
        <div className="stat-metric-card">
          <div className="stat-metric-label">Unrealised P&amp;L</div>
          <div className="stat-metric-val" style={{ color: unrealisedPnl >= 0 ? '#059669' : '#dc2626' }}>
            {loading ? '—' : fmtSigned(unrealisedPnl * usdToAud, 'A$')}
          </div>
          <div className="stat-metric-subtext">
            {unrealisedPnl >= 0 ? `+${unrealisedPctOnCost}%` : `${unrealisedPctOnCost}%`} on open cost
          </div>
        </div>
      </div>

      {/* ── Open Positions Table (Sideways Scrollable) ──────────── */}
      <div className="theme-card">
        <div className="table-header-flex">
          <div>
            <h3 className="table-title-bold">Open Positions</h3>
            <span className="table-mobile-hint">Swipe to see all columns →</span>
          </div>
          <div className="badge-green-pill">
            <span>{positions.length} active</span>
          </div>
        </div>

        {/* Scrollable table container */}
        <div className="scrollable-table-wrapper" id="open-positions-scroll-container">
          {positions.length === 0 ? (
            <div style={{
              padding: '36px 20px',
              textAlign: 'center',
              color: '#94a3b8',
              fontSize: 13,
            }}>
              <span style={{ fontSize: 26, display: 'block', marginBottom: 6 }}>📭</span>
              <p style={{ fontWeight: 600, color: '#475569', marginBottom: 4 }}>No open positions</p>
              <p style={{ fontSize: 12 }}>Positions will appear here when the bot buys stocks during US market hours.</p>
            </div>
          ) : (
            <table className="custom-data-table" id="table-open-positions">
              <thead>
                <tr>
                  <th>Ticker</th>
                  <th>Status</th>
                  <th>Shares</th>
                  <th>Avg Cost</th>
                  <th>Current Price</th>
                  <th>Market Value (AUD)</th>
                  <th>Unrealised P&amp;L</th>
                  <th>Partial Gain</th>
                  <th style={{ textAlign: 'right' }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((pos) => {
                  const isPartial = pos.trade_status === 'sold_half';
                  const pnlPos = pos.pnl >= 0;
                  const marketValAud = pos.market_value * usdToAud;
                  const pnlAud = pos.pnl * usdToAud;
                  const partialAud = (pos.realised_partial_pnl || 0) * usdToAud;

                  return (
                    <tr key={pos.ticker}>
                      <td style={{ fontWeight: 700, color: '#0f172a' }}>{pos.ticker}</td>
                      <td>
                        <span className={isPartial ? 'badge-status-partial' : 'badge-status-open'}>
                          {isPartial ? '½ Sold' : 'Open'}
                        </span>
                      </td>
                      <td>{pos.shares.toLocaleString()}</td>
                      <td>{fmt(pos.avg_cost)}</td>
                      <td>{fmt(pos.current_price)}</td>
                      <td>{fmt(marketValAud, 'A$')}</td>
                      <td style={{ color: pnlPos ? '#059669' : '#dc2626', fontWeight: 600 }}>
                        {fmtSigned(pnlAud, 'A$')}
                      </td>
                      <td>
                        {partialAud > 0 ? (
                          <span style={{ color: '#059669', fontWeight: 600 }}>
                            {fmtSigned(partialAud, 'A$')}
                          </span>
                        ) : (
                          <span style={{ color: '#94a3b8' }}>—</span>
                        )}
                      </td>
                      <td style={{ textAlign: 'right' }}>
                        <button
                          className="btn-manage-link"
                          onClick={() => setManagedPosition(pos)}
                          id={`btn-manage-${pos.ticker}`}
                        >
                          Manage
                          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
                            <line x1="7" y1="17" x2="17" y2="7" />
                            <polyline points="7 7 17 7 17 17" />
                          </svg>
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>

        {/* Footer Subtext */}
        <div style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginTop: 14,
          fontSize: 12,
          color: '#94a3b8',
          flexWrap: 'wrap',
          gap: 8,
        }}>
          <div>{positions.length} positions · Prices in USD</div>
          <div>Values in AUD · FX 1 USD = {usdToAud.toFixed(2)} AUD</div>
        </div>
      </div>

      {/* Bottom disclaimer */}
      <div style={{ textAlign: 'center', fontSize: 12, color: '#94a3b8', marginTop: 24 }}>
        {tradingMode === 'live' ? 'Live trading mode · Real orders are active.' : 'Paper trading · Simulated funds. No real orders are placed.'}
      </div>

      {/* ── Manage Position Modal ───────────────────────────────── */}
      {managedPosition && (
        <div className="modal-backdrop-blur" onClick={() => setManagedPosition(null)}>
          <div className="modal-content-white" onClick={(e) => e.stopPropagation()}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
              <div>
                <h3 style={{ fontSize: 18, fontWeight: 700, color: '#0f172a' }}>
                  Manage {managedPosition.ticker}
                </h3>
                <p style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>
                  {managedPosition.shares} shares @ avg {fmt(managedPosition.avg_cost)}
                </p>
              </div>
              <button
                onClick={() => setManagedPosition(null)}
                style={{ background: 'none', border: 'none', fontSize: 18, cursor: 'pointer', color: '#94a3b8' }}
              >
                ✕
              </button>
            </div>

            {actionMessage && (
              <div style={{
                padding: '10px 14px',
                borderRadius: 8,
                background: '#ecfdf5',
                color: '#047857',
                fontSize: 12,
                fontWeight: 600,
                marginBottom: 16,
              }}>
                {actionMessage}
              </div>
            )}

            <div style={{
              background: '#f8faf9',
              borderRadius: 10,
              padding: 16,
              display: 'grid',
              gridTemplateColumns: 'repeat(2, 1fr)',
              gap: 12,
              marginBottom: 20,
              fontSize: 13,
            }}>
              <div>
                <span style={{ color: '#64748b' }}>Current Price:</span>
                <div style={{ fontWeight: 600, color: '#0f172a' }}>{fmt(managedPosition.current_price)}</div>
              </div>
              <div>
                <span style={{ color: '#64748b' }}>Market Value (AUD):</span>
                <div style={{ fontWeight: 600, color: '#0f172a' }}>
                  {fmt(managedPosition.market_value * usdToAud, 'A$')}
                </div>
              </div>
              <div>
                <span style={{ color: '#64748b' }}>Unrealised P&amp;L:</span>
                <div style={{ fontWeight: 600, color: managedPosition.pnl >= 0 ? '#059669' : '#dc2626' }}>
                  {fmtSigned(managedPosition.pnl * usdToAud, 'A$')}
                </div>
              </div>
              <div>
                <span style={{ color: '#64748b' }}>Status:</span>
                <div style={{ fontWeight: 600, color: '#0f172a' }}>
                  {managedPosition.trade_status === 'sold_half' ? '½ Sold' : 'Open'}
                </div>
              </div>
            </div>

            <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
              <button
                className="btn-outline-subtle"
                onClick={() => setManagedPosition(null)}
              >
                Cancel
              </button>
              <button
                className="btn-primary-dark"
                style={{ background: '#dc2626' }}
                disabled={actionInProgress}
                onClick={() => handleExecuteSell(managedPosition.ticker)}
              >
                {actionInProgress ? 'Executing…' : 'Sell / Close Position'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
