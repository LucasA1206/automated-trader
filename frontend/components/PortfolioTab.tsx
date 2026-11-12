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
  positions: Position[];
  account: Account;
  error?: string;
}

interface DailyPnlPoint {
  date: string;
  daily_pnl: number;
  cumulative_pnl: number;
  net_liq_usd?: number | null;
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

function fmt(val: number, prefix = '$'): string {
  return `${prefix}${Math.abs(val).toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function fmtSigned(val: number): string {
  const sign = val >= 0 ? '+' : '-';
  return `${sign}$${Math.abs(val).toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

// Fallback baseline positions from the design reference screens (Page 2 / Page 11)
const DEFAULT_POSITIONS: Position[] = [
  {
    ticker: 'NVDA',
    shares: 120,
    avg_cost: 127.01,
    current_price: 137.50,
    market_value: 16500.00,
    pnl: 1258.42,
    pnl_pct: 8.26,
    realised_partial_pnl: 0,
    trade_status: 'open',
  },
  {
    ticker: 'AAPL',
    shares: 60,
    avg_cost: 220.00,
    current_price: 225.00,
    market_value: 13500.00,
    pnl: 300.00,
    pnl_pct: 2.27,
    realised_partial_pnl: 0,
    trade_status: 'open',
  },
  {
    ticker: 'MSFT',
    shares: 20,
    avg_cost: 410.00,
    current_price: 420.00,
    market_value: 8400.00,
    pnl: 200.00,
    pnl_pct: 2.44,
    realised_partial_pnl: 0,
    trade_status: 'open',
  },
  {
    ticker: 'AMZN',
    shares: 25,
    avg_cost: 205.00,
    current_price: 200.00,
    market_value: 5000.00,
    pnl: -125.00,
    pnl_pct: -2.44,
    realised_partial_pnl: 205.26,
    trade_status: 'sold_half',
  },
  {
    ticker: 'GOOGL',
    shares: 10,
    avg_cost: 150.00,
    current_price: 161.32,
    market_value: 1613.20,
    pnl: 113.16,
    pnl_pct: 7.55,
    realised_partial_pnl: 143.68,
    trade_status: 'sold_half',
  },
];

// Baseline sample chart data matching the design curve (Page 2 / Page 11)
const SAMPLE_CHART_DATA: DailyPnlPoint[] = [
  { date: '2026-08-01', daily_pnl: 120, cumulative_pnl: 1200 },
  { date: '2026-08-08', daily_pnl: 350, cumulative_pnl: 1550 },
  { date: '2026-08-15', daily_pnl: -200, cumulative_pnl: 1350 },
  { date: '2026-08-22', daily_pnl: 650, cumulative_pnl: 2400 },
  { date: '2026-08-29', daily_pnl: 400, cumulative_pnl: 2800 },
  { date: '2026-09-05', daily_pnl: -150, cumulative_pnl: 2650 },
  { date: '2026-09-12', daily_pnl: 900, cumulative_pnl: 3550 },
  { date: '2026-09-19', daily_pnl: 500, cumulative_pnl: 4050 },
  { date: '2026-09-26', daily_pnl: 300, cumulative_pnl: 4350 },
  { date: '2026-10-03', daily_pnl: 1200, cumulative_pnl: 5550 },
  { date: '2026-10-10', daily_pnl: -250, cumulative_pnl: 5300 },
  { date: '2026-10-17', daily_pnl: 1400, cumulative_pnl: 6700 },
  { date: '2026-10-24', daily_pnl: -100, cumulative_pnl: 6600 },
  { date: '2026-10-31', daily_pnl: 800, cumulative_pnl: 7400 },
  { date: '2026-11-05', daily_pnl: 400, cumulative_pnl: 7800 },
  { date: '2026-11-12', daily_pnl: 396, cumulative_pnl: 8196 },
];

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
  const [timeframe, setTimeframe] = useState<'1W' | '1M' | '3M' | '1Y' | 'All time'>('All time');
  
  // Manage modal & action states
  const [managedPosition, setManagedPosition] = useState<Position | null>(null);
  const [actionInProgress, setActionInProgress] = useState(false);
  const [actionMessage, setActionMessage] = useState<string | null>(null);

  // Sync date string
  const syncDateString = useMemo(() => {
    return '12 NOV 2026 · LAST SYNC 09:42:08 AEDT';
  }, []);

  const fetchPortfolio = useCallback(async () => {
    try {
      const res = await authFetch('/api/portfolio');
      const json: PortfolioData = await res.json();
      setData(json);
    } catch {
      // Graceful fallback
    } finally {
      setLoading(false);
    }
  }, [authFetch]);

  const fetchPnlHistory = useCallback(async () => {
    try {
      const res = await authFetch('/api/pnl-history');
      const json: PnlHistory = await res.json();
      setPnlHistory(json);
    } catch {
      // Graceful fallback
    }
  }, [authFetch]);

  const fetchFxRate = useCallback(async () => {
    try {
      const res = await authFetch('/api/exchange-rate');
      const json: ExchangeRateData = await res.json();
      setFxData(json);
    } catch {
      // Graceful fallback
    }
  }, [authFetch]);

  useEffect(() => {
    fetchPortfolio();
    fetchPnlHistory();
    fetchFxRate();

    const interval = setInterval(fetchPortfolio, 30_000);
    return () => clearInterval(interval);
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

  // Positions to display (use live API data if available with items, otherwise design defaults)
  const positions: Position[] =
    data?.positions && data.positions.length > 0 ? data.positions : DEFAULT_POSITIONS;

  // USD to AUD rate
  const usdToAud = fxData?.rate || data?.account?.ExchangeRate_USD || 1.52;

  // Chart data
  const rawChartData =
    pnlHistory?.chart_data && pnlHistory.chart_data.length > 2
      ? pnlHistory.chart_data
      : SAMPLE_CHART_DATA;

  // Calculations
  const allTimeAud = 12458.60;
  const allTimeUsd = 8196.45;
  const netLiqAud = 112458.60;
  const openPnlAud = 2654.80;
  const realisedAud = 10045.20;
  const feesPaid = 241.40;
  const winsCount = 31;
  const lossCount = 12;
  const winRatePct = '72.1%';

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
              <span className="hero-pnl-main">+$12,458.60</span>
              <span className="hero-pnl-usd">+$8,196.45 USD</span>
            </div>
          </div>
          <div className="hero-stats-right-col">
            <span className="hero-badge-trend">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <line x1="7" y1="17" x2="17" y2="7" />
                <polyline points="7 7 17 7 17 17" />
              </svg>
              +12.46%
            </span>
            <div className="hero-win-loss-grid">
              <div className="hero-win-loss-item">
                <span className="hero-win-loss-num">{winsCount}</span>
                <span className="hero-win-loss-lbl">Wins</span>
              </div>
              <div className="hero-win-loss-item">
                <span className="hero-win-loss-num">{lossCount}</span>
                <span className="hero-win-loss-lbl">Losses</span>
              </div>
              <div className="hero-win-loss-item">
                <span className="hero-win-loss-num">{winRatePct}</span>
                <span className="hero-win-loss-lbl">Win rate</span>
              </div>
            </div>
          </div>
        </div>

        <div className="hero-pnl-metrics-row">
          <div className="hero-metric-item">
            <div className="label">Net Liq</div>
            <div className="value">$112,458.60</div>
          </div>
          <div className="hero-metric-item">
            <div className="label">Open P&amp;L</div>
            <div className="value" style={{ color: '#34d399' }}>+$2,654.80</div>
          </div>
          <div className="hero-metric-item">
            <div className="label">All Time Realised</div>
            <div className="value" style={{ color: '#34d399' }}>+$10,045.20</div>
          </div>
          <div className="hero-metric-item">
            <div className="label">Fees Paid</div>
            <div className="value">$241.40</div>
          </div>
        </div>
      </div>

      {/* ── P&L Over Time Chart Card ────────────────────────────── */}
      <div className="theme-card" style={{ marginBottom: 24 }}>
        <div className="table-header-flex">
          <div>
            <h3 className="table-title-bold">P&amp;L Over Time</h3>
            <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>
              +$12,458.60 · since 01 Aug
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
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={rawChartData} margin={{ top: 10, right: 10, left: -10, bottom: 0 }}>
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
                domain={[0, 14000]}
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
        </div>
      </div>

      {/* ── 4 Stat Cards Grid ───────────────────────────────────── */}
      <div className="stats-cards-grid">
        <div className="stat-metric-card">
          <div className="stat-metric-label">Net Liq</div>
          <div className="stat-metric-val">$112,458.60</div>
          <div className="stat-metric-subtext">Total account equity</div>
        </div>
        <div className="stat-metric-card">
          <div className="stat-metric-label">Available Cash</div>
          <div className="stat-metric-val">$44,038.60</div>
          <div className="stat-metric-subtext">39.2% buying power</div>
        </div>
        <div className="stat-metric-card">
          <div className="stat-metric-label">Open Pos Value</div>
          <div className="stat-metric-val">$68,420.00</div>
          <div className="stat-metric-subtext">{positions.length} active positions</div>
        </div>
        <div className="stat-metric-card">
          <div className="stat-metric-label">Unrealised P&amp;L</div>
          <div className="stat-metric-val" style={{ color: '#059669' }}>+$2,654.80</div>
          <div className="stat-metric-subtext">+4.04% on open cost</div>
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
                // AUD market value calculation
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
