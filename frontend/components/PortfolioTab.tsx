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
  net_liq_usd?: number | null;
  daily_pct?: number;
  cumulative_pct?: number;
  daily_fees?: number;
  cumulative_fees?: number;
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

  const realizedPnlUsd = pnlHistory?.all_time_realized_pnl ?? 0;
  const realizedPnlAud = realizedPnlUsd * usdToAud;
  const allTimeFeesUsd = pnlHistory?.all_time_fees ?? 0;
  const allTimeFeesAud = allTimeFeesUsd * usdToAud;

  // Open P&L = unrealised P&L + banked partials
  const openPnlUsd = unrealisedPnl + openPartialPnl;
  const openPnlAud = openPnlUsd * usdToAud;

  // Net Liquidation
  const netLiqUsd = account.NetLiquidation ?? 0;
  const netLiqAud = account.NetLiquidation_AUD ?? (netLiqUsd * usdToAud);
  const availableCashUsd = account.AvailableFunds ?? account.TotalCashValue ?? 0;
  const availableCashAud = account.AvailableFunds_AUD ?? (availableCashUsd * usdToAud);

  // All-time P&L calculation based on Net Liquidation vs starting capital
  const STARTING_CAPITAL_AUD = 7900;
  const allTimePnlAud = netLiqAud > 0 ? netLiqAud - STARTING_CAPITAL_AUD : (realizedPnlAud + openPnlAud);
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

  const chartData = pnlHistory?.chart_data ?? [];

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
                {loading ? '—' : fmtSigned(allTimePnlAud)}
              </span>
              <span className="hero-pnl-usd" style={{ color: allTimePnlPositive ? '#34d399' : '#f87171' }}>
                {loading ? '—' : `${fmtSigned(allTimePnlUsd)} USD`}
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
            <div className="value">{loading ? '—' : fmt(netLiqAud)}</div>
          </div>
          <div className="hero-metric-item">
            <div className="label">Open P&amp;L</div>
            <div className="value" style={{ color: openPnlAud >= 0 ? '#34d399' : '#f87171' }}>
              {loading ? '—' : fmtSigned(openPnlAud)}
            </div>
          </div>
          <div className="hero-metric-item">
            <div className="label">All Time Realised</div>
            <div className="value" style={{ color: realizedPnlAud >= 0 ? '#34d399' : '#f87171' }}>
              {loading ? '—' : fmtSigned(realizedPnlAud)}
            </div>
          </div>
          <div className="hero-metric-item">
            <div className="label">Fees Paid</div>
            <div className="value">{loading ? '—' : fmt(allTimeFeesAud)}</div>
          </div>
        </div>
      </div>

      {/* ── P&L Over Time Chart Card ────────────────────────────── */}
      <div className="theme-card" style={{ marginBottom: 24 }}>
        <div className="table-header-flex">
          <div>
            <h3 className="table-title-bold">P&amp;L Over Time</h3>
            <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>
              {allTimePnlPositive ? `+${fmt(allTimePnlAud)}` : `-${fmt(allTimePnlAud)}`} · live portfolio tracking
            </div>
          </div>
          {/* Timeframe selector (Desktop) */}
          <div style={{ display: 'flex', gap: 6 }}>
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
          {chartData.length === 0 ? (
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
              <AreaChart data={chartData} margin={{ top: 10, right: 10, left: -10, bottom: 0 }}>
                <defs>
                  <linearGradient id="chartGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#059669" stopOpacity={0.2} />
                    <stop offset="100%" stopColor="#059669" stopOpacity={0.0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f3" vertical={false} />
                <XAxis
                  dataKey="date"
                  tickFormatter={(d: string) => {
                    try {
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
                  tickFormatter={(val: number) => `$${Math.round(val / 1000)}k`}
                  tick={{ fill: '#94a3b8', fontSize: 11 }}
                  axisLine={false}
                  tickLine={false}
                />
                <Tooltip
                  content={({ active, payload }) => {
                    if (!active || !payload || !payload.length) return null;
                    const item = payload[0].payload as DailyPnlPoint;
                    return (
                      <div style={{
                        background: '#ffffff',
                        border: '1px solid #e2e8e5',
                        borderRadius: 8,
                        padding: '8px 12px',
                        boxShadow: '0 4px 12px rgba(0,0,0,0.08)',
                        fontSize: 12,
                      }}>
                        <div style={{ color: '#64748b', fontSize: 11 }}>{item.date}</div>
                        <div style={{ color: '#059669', fontWeight: 700, marginTop: 2 }}>
                          {fmtSigned(item.cumulative_pnl || 0)}
                        </div>
                      </div>
                    );
                  }}
                />
                <Area
                  type="monotone"
                  dataKey="cumulative_pnl"
                  stroke="#059669"
                  strokeWidth={2.5}
                  fill="url(#chartGradient)"
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
          <div className="stat-metric-val">{loading ? '—' : fmt(netLiqAud)}</div>
          <div className="stat-metric-subtext">Total account equity</div>
        </div>
        <div className="stat-metric-card">
          <div className="stat-metric-label">Available Cash</div>
          <div className="stat-metric-val">{loading ? '—' : fmt(availableCashAud)}</div>
          <div className="stat-metric-subtext">{buyingPowerPct}% buying power</div>
        </div>
        <div className="stat-metric-card">
          <div className="stat-metric-label">Open Pos Value</div>
          <div className="stat-metric-val">{loading ? '—' : fmt(totalPosValueAud)}</div>
          <div className="stat-metric-subtext">{positions.length} active positions</div>
        </div>
        <div className="stat-metric-card">
          <div className="stat-metric-label">Unrealised P&amp;L</div>
          <div className="stat-metric-val" style={{ color: unrealisedPnl >= 0 ? '#059669' : '#dc2626' }}>
            {loading ? '—' : fmtSigned(unrealisedPnl * usdToAud)}
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
                      <td>{fmt(marketValAud)}</td>
                      <td style={{ color: pnlPos ? '#059669' : '#dc2626', fontWeight: 600 }}>
                        {fmtSigned(pnlAud)}
                      </td>
                      <td>
                        {partialAud > 0 ? (
                          <span style={{ color: '#059669', fontWeight: 600 }}>
                            {fmtSigned(partialAud)}
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
        Paper trading · Simulated funds. No real orders are placed.
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
                  {fmt(managedPosition.market_value * usdToAud)}
                </div>
              </div>
              <div>
                <span style={{ color: '#64748b' }}>Unrealised P&amp;L:</span>
                <div style={{ fontWeight: 600, color: managedPosition.pnl >= 0 ? '#059669' : '#dc2626' }}>
                  {fmtSigned(managedPosition.pnl * usdToAud)}
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
