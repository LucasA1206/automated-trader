'use client';

import { useEffect, useState, useCallback } from 'react';
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
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
}

interface Account {
  TotalCashValue?: number;
  NetLiquidation?: number;
  AvailableFunds?: number;
  BuyingPower?: number;
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
  daily_pct?: number;
  cumulative_pct?: number;
}

interface PnlHistory {
  chart_data: DailyPnlPoint[];
  all_time_realized_pnl: number;
  total_closed_trades: number;
  winning_trades: number;
  losing_trades: number;
}

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

function fmtDate(dateStr: string): string {
  const d = new Date(dateStr + 'T00:00:00');
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

// ─── P&L Cell (table) ─────────────────────────────────────────────────────────

function PnlCell({ val, pct }: { val: number; pct: number }) {
  const cls = val >= 0 ? 'positive' : 'negative';
  const sign = val >= 0 ? '+' : '-';
  return (
    <td className="mono">
      <span className={cls}>
        {sign}{fmt(val)} ({sign}{Math.abs(pct).toFixed(2)}%)
      </span>
    </td>
  );
}

// ─── Custom Chart Tooltip ─────────────────────────────────────────────────────

function ChartTooltip({ active, payload, label }: {
  active?: boolean;
  payload?: { value: number; name: string; color: string; payload: DailyPnlPoint }[];
  label?: string;
}) {
  if (!active || !payload || !payload.length) return null;
  return (
    <div style={{
      background: 'rgba(13,20,32,0.95)',
      border: '1px solid rgba(255,255,255,0.12)',
      borderRadius: 10,
      padding: '10px 14px',
      backdropFilter: 'blur(12px)',
      boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
    }}>
      <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 6 }}>
        {label ? fmtDate(label) : ''}
      </div>
      {payload.map((p, i) => {
        const isPos = p.value >= 0;
        const isDaily = p.name === 'daily_pnl';
        const pct = isDaily ? p.payload.daily_pct : p.payload.cumulative_pct;
        const pctStr = pct !== undefined ? ` (${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%)` : '';
        return (
          <div key={i} style={{
            fontSize: 13,
            fontWeight: 600,
            color: isPos ? 'var(--accent-green)' : 'var(--accent-red)',
            fontFamily: "'JetBrains Mono', monospace",
          }}>
            {isDaily ? 'Day' : 'Total'}: {fmtSigned(p.value)}{pctStr}
          </div>
        );
      })}
    </div>
  );
}

// ─── Chart Mode Toggle ────────────────────────────────────────────────────────

type ChartMode = 'cumulative' | 'daily';

// ─── Main Component ───────────────────────────────────────────────────────────

type AuthFetch = (url: string, init?: RequestInit) => Promise<Response>;

export default function PortfolioTab({ authFetch }: { authFetch: AuthFetch }) {
  const [data, setData] = useState<PortfolioData | null>(null);
  const [pnlHistory, setPnlHistory] = useState<PnlHistory | null>(null);
  const [loading, setLoading] = useState(true);
  const [pnlLoading, setPnlLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [chartMode, setChartMode] = useState<ChartMode>('cumulative');

  // ── Fetch live portfolio ──────────────────────────────────────────────────
  const fetchPortfolio = useCallback(async () => {
    try {
      const res = await authFetch('/api/portfolio');
      const json: PortfolioData = await res.json();
      setData(json);
      setLastUpdated(new Date());
    } catch {
      setData({
        connected: false,
        mode: 'unknown',
        positions: [],
        account: {},
        error: 'Failed to reach API server',
      });
    } finally {
      setLoading(false);
    }
  }, []);

  // ── Fetch P&L history ─────────────────────────────────────────────────────
  const fetchPnlHistory = useCallback(async () => {
    try {
      const res = await authFetch('/api/pnl-history');
      const json: PnlHistory = await res.json();
      setPnlHistory(json);
    } catch {
      /* silently fail */
    } finally {
      setPnlLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchPortfolio();
    fetchPnlHistory();
    const interval = setInterval(fetchPortfolio, 30_000);
    const pnlInterval = setInterval(fetchPnlHistory, 60_000);
    return () => {
      clearInterval(interval);
      clearInterval(pnlInterval);
    };
  }, [fetchPortfolio, fetchPnlHistory]);

  const account = data?.account ?? {};
  const positions = data?.positions ?? [];
  const unrealisedPnl = positions.reduce((sum, p) => sum + p.pnl, 0);
  const totalValue = positions.reduce((sum, p) => sum + p.market_value, 0);

  const realizedPnl = pnlHistory?.all_time_realized_pnl ?? 0;
  const openPnl = realizedPnl + unrealisedPnl;   // All-time Open P&L
  const openPnlPositive = openPnl >= 0;

  const chartData = pnlHistory?.chart_data ?? [];
  const activeKey: 'cumulative_pnl' | 'daily_pnl' =
    chartMode === 'cumulative' ? 'cumulative_pnl' : 'daily_pnl';
  const chartColor =
    chartMode === 'cumulative'
      ? openPnlPositive ? '#22c55e' : '#ef4444'
      : '#3b82f6';

  const winRate =
    pnlHistory && pnlHistory.total_closed_trades > 0
      ? ((pnlHistory.winning_trades / pnlHistory.total_closed_trades) * 100).toFixed(0)
      : '—';

  return (
    <div>
      {/* ── Header ─────────────────────────────────────────────────────── */}
      <div className="page-header">
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div>
            <h2>Portfolio</h2>
            <p>
              Live IBKR positions &amp; account summary
              {lastUpdated && ` · Updated ${lastUpdated.toLocaleTimeString()}`}
            </p>
          </div>
          <button
            className="btn btn-outline btn-icon"
            onClick={() => { fetchPortfolio(); fetchPnlHistory(); }}
            title="Refresh"
            id="btn-refresh-portfolio"
          >
            🔄
          </button>
        </div>
      </div>

      {/* ── Connection status banner ────────────────────────────────────── */}
      {data && !data.connected && (
        <div style={{
          display: 'flex',
          alignItems: 'flex-start',
          gap: 12,
          padding: '12px 16px',
          borderRadius: 10,
          marginBottom: 20,
          background: data.error === 'Failed to reach API server'
            ? 'rgba(239,68,68,0.08)'
            : 'rgba(234,179,8,0.07)',
          border: `1px solid ${data.error === 'Failed to reach API server'
            ? 'rgba(239,68,68,0.2)'
            : 'rgba(234,179,8,0.2)'}`,
        }}>
          <span style={{ fontSize: 16, flexShrink: 0 }}>
            {data.error === 'Failed to reach API server' ? '🔴' : '🟡'}
          </span>
          <div>
            <div style={{ fontSize: 13, fontWeight: 600, color: data.error === 'Failed to reach API server' ? 'var(--accent-red)' : 'var(--accent-yellow)', marginBottom: 2 }}>
              {data.error === 'Failed to reach API server'
                ? 'Backend API unreachable'
                : 'IB Gateway not connected'}
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.5 }}>
              {data.error === 'Failed to reach API server'
                ? 'The backend server is not responding. Check Railway deployment logs.'
                : 'The IB Gateway service is starting up or awaiting IBKR login. Check Railway → ib-gateway service logs. You may need to approve 2FA on your IBKR Mobile app.'}
            </div>
          </div>
        </div>
      )}

      {/* Strategy upgrade alert */}
      {data?.strategy_alert && (
        <div style={{
          display: 'flex',
          alignItems: 'flex-start',
          gap: 12,
          padding: '14px 16px',
          borderRadius: 12,
          marginBottom: 20,
          background: 'linear-gradient(135deg, rgba(59,130,246,0.14) 0%, rgba(59,130,246,0.06) 100%)',
          border: '1px solid rgba(59,130,246,0.24)',
        }}>
          <span style={{ fontSize: 16, flexShrink: 0 }}>ℹ️</span>
          <div>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--accent-blue)', marginBottom: 2 }}>
              Cash account threshold reached
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.5 }}>
              {data.strategy_alert.message}
            </div>
          </div>
        </div>
      )}

      {/* ── OPEN P&L HERO ───────────────────────────────────────────────── */}
      <div style={{
        background: openPnlPositive
          ? 'linear-gradient(135deg, rgba(34,197,94,0.08) 0%, rgba(34,197,94,0.03) 100%)'
          : 'linear-gradient(135deg, rgba(239,68,68,0.08) 0%, rgba(239,68,68,0.03) 100%)',
        border: `1px solid ${openPnlPositive ? 'rgba(34,197,94,0.2)' : 'rgba(239,68,68,0.2)'}`,
        borderRadius: 16,
        padding: '24px 28px',
        marginBottom: 24,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        flexWrap: 'wrap' as const,
        gap: 16,
      }}>
        <div>
          <div style={{
            fontSize: 11,
            fontWeight: 600,
            letterSpacing: '0.8px',
            textTransform: 'uppercase' as const,
            color: 'var(--text-muted)',
            marginBottom: 8,
          }}>
            Open P&amp;L — All Time
          </div>
          {loading && pnlLoading ? (
            <div style={{ fontSize: 42, fontWeight: 800, color: 'var(--text-muted)', fontFamily: "'JetBrains Mono', monospace" }}>—</div>
          ) : (
            <div style={{
              fontSize: 46,
              fontWeight: 800,
              letterSpacing: '-1.5px',
              color: openPnlPositive ? 'var(--accent-green)' : 'var(--accent-red)',
              fontFamily: "'JetBrains Mono', monospace",
              textShadow: openPnlPositive
                ? '0 0 40px rgba(34,197,94,0.35)'
                : '0 0 40px rgba(239,68,68,0.35)',
            }}>
              {fmtSigned(openPnl)}
            </div>
          )}
          <div style={{ display: 'flex', gap: 20, marginTop: 10, flexWrap: 'wrap' as const }}>
            <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
              <span style={{ color: 'var(--text-secondary)', fontWeight: 500 }}>Realized: </span>
              <span style={{ color: realizedPnl >= 0 ? 'var(--accent-green)' : 'var(--accent-red)', fontFamily: "'JetBrains Mono', monospace" }}>
                {fmtSigned(realizedPnl)}
              </span>
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
              <span style={{ color: 'var(--text-secondary)', fontWeight: 500 }}>Unrealised: </span>
              <span style={{ color: unrealisedPnl >= 0 ? 'var(--accent-green)' : 'var(--accent-red)', fontFamily: "'JetBrains Mono', monospace" }}>
                {fmtSigned(unrealisedPnl)}
              </span>
            </div>
          </div>
        </div>

        {/* Win/Loss stats */}
        <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap' as const }}>
          <div style={{ textAlign: 'center' as const }}>
            <div style={{ fontSize: 24, fontWeight: 700, color: 'var(--accent-green)', fontFamily: "'JetBrains Mono', monospace" }}>
              {pnlHistory?.winning_trades ?? '—'}
            </div>
            <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase' as const, letterSpacing: '0.5px', marginTop: 2 }}>Wins</div>
          </div>
          <div style={{ textAlign: 'center' as const }}>
            <div style={{ fontSize: 24, fontWeight: 700, color: 'var(--accent-red)', fontFamily: "'JetBrains Mono', monospace" }}>
              {pnlHistory?.losing_trades ?? '—'}
            </div>
            <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase' as const, letterSpacing: '0.5px', marginTop: 2 }}>Losses</div>
          </div>
          <div style={{ textAlign: 'center' as const }}>
            <div style={{ fontSize: 24, fontWeight: 700, color: 'var(--accent-blue)', fontFamily: "'JetBrains Mono', monospace" }}>
              {winRate}{winRate !== '—' ? '%' : ''}
            </div>
            <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase' as const, letterSpacing: '0.5px', marginTop: 2 }}>Win Rate</div>
          </div>
        </div>
      </div>

      {/* ── P&L Chart ───────────────────────────────────────────────────── */}
      <div className="table-container" style={{ marginBottom: 28 }}>
        <div className="table-header-bar">
          <h3>P&amp;L Over Time</h3>
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              id="chart-mode-cumulative"
              className={`filter-btn ${chartMode === 'cumulative' ? 'active' : ''}`}
              onClick={() => setChartMode('cumulative')}
            >
              Cumulative
            </button>
            <button
              id="chart-mode-daily"
              className={`filter-btn ${chartMode === 'daily' ? 'active' : ''}`}
              onClick={() => setChartMode('daily')}
            >
              Daily
            </button>
          </div>
        </div>

        <div style={{ padding: '24px 8px 16px' }}>
          {pnlLoading ? (
            <div style={{ height: 260, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <div className="skeleton" style={{ width: '100%', height: 260, borderRadius: 8 }} />
            </div>
          ) : chartData.length === 0 ? (
            <div className="empty-state" style={{ height: 260 }}>
              <div className="icon">📈</div>
              <p>No closed trades yet</p>
              <p style={{ fontSize: 12 }}>P&amp;L chart will appear once trades are closed.</p>
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={260}>
              <AreaChart data={chartData} margin={{ top: 4, right: 24, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id="pnlGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor={chartColor} stopOpacity={0.22} />
                    <stop offset="95%" stopColor={chartColor} stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid
                  strokeDasharray="3 3"
                  stroke="rgba(255,255,255,0.04)"
                  vertical={false}
                />
                <XAxis
                  dataKey="date"
                  tickFormatter={fmtDate}
                  tick={{ fill: 'var(--text-muted)', fontSize: 11 }}
                  axisLine={false}
                  tickLine={false}
                  interval="preserveStartEnd"
                />
                <YAxis
                  tickFormatter={(v) => `$${v >= 0 ? '' : '-'}${Math.abs(v).toLocaleString()}`}
                  tick={{ fill: 'var(--text-muted)', fontSize: 11 }}
                  axisLine={false}
                  tickLine={false}
                  width={72}
                />
                <Tooltip content={<ChartTooltip />} />
                <ReferenceLine y={0} stroke="rgba(255,255,255,0.12)" strokeDasharray="4 4" />
                <Area
                  type="monotone"
                  dataKey={activeKey}
                  stroke={chartColor}
                  strokeWidth={2.5}
                  fill="url(#pnlGradient)"
                  dot={chartData.length <= 20 ? { fill: chartColor, r: 3, strokeWidth: 0 } : false}
                  activeDot={{ r: 5, fill: chartColor, strokeWidth: 0 }}
                />
              </AreaChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      {/* ── Stat cards ──────────────────────────────────────────────────── */}
      <div className="stat-grid">
        <div className="card">
          <div className="card-label">Net Liquidation</div>
          <div className="card-value">
            {loading ? '—' : fmt(account.NetLiquidation ?? 0)}
          </div>
        </div>
        <div className="card">
          <div className="card-label">Available Cash</div>
          <div className="card-value">
            {loading ? '—' : fmt(account.AvailableFunds ?? 0)}
          </div>
        </div>
        <div className="card">
          <div className="card-label">Open Positions Value</div>
          <div className="card-value">{loading ? '—' : fmt(totalValue)}</div>
        </div>
        <div className="card">
          <div className="card-label">Unrealised P&amp;L</div>
          <div className="card-value">
            {loading ? '—' : (
              <span className={unrealisedPnl >= 0 ? 'positive' : 'negative'}>
                {unrealisedPnl >= 0 ? '+' : '-'}{fmt(unrealisedPnl)}
              </span>
            )}
          </div>
        </div>
      </div>

      {/* ── Positions table ─────────────────────────────────────────────── */}
      <div className="table-container">
        <div className="table-header-bar">
          <h3>Open Positions ({positions.length})</h3>
          <span
            className={`badge ${data?.mode === 'live' ? 'live' : 'paper'}`}
          >
            {data?.mode === 'live' ? '🔴 LIVE' : '🟡 PAPER'}
          </span>
        </div>
        {loading ? (
          <div className="empty-state">
            <div className="skeleton" style={{ width: '100%', height: 40 }} />
          </div>
        ) : positions.length === 0 ? (
          <div className="empty-state">
            <div className="icon">📭</div>
            <p>No open positions</p>
            <p style={{ fontSize: 12 }}>Positions will appear here after the morning scan buys stocks.</p>
          </div>
        ) : (
          <table id="portfolio-table">
            <thead>
              <tr>
                <th>Ticker</th>
                <th>Shares</th>
                <th>Avg Cost</th>
                <th>Current Price</th>
                <th>Market Value</th>
                <th>P&amp;L</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((pos) => (
                <tr key={pos.ticker}>
                  <td className="ticker">{pos.ticker}</td>
                  <td className="mono">{pos.shares.toLocaleString()}</td>
                  <td className="mono">{fmt(pos.avg_cost)}</td>
                  <td className="mono">{fmt(pos.current_price)}</td>
                  <td className="mono">{fmt(pos.market_value)}</td>
                  <PnlCell val={pos.pnl} pct={pos.pnl_pct} />
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
