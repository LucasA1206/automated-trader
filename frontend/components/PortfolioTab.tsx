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
  source?: 'snapshot' | 'trades';
}

interface PnlHistory {
  chart_data: DailyPnlPoint[];
  all_time_realized_pnl: number;
  total_closed_trades: number;
  winning_trades: number;
  losing_trades: number;
  all_time_fees?: number;
  has_snapshots?: boolean;
}

interface ExchangeRateData {
  rate: number;
  fetched_at: string | null;
  stale: boolean;
  age_minutes: number | null;
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

function ChartTooltip({ active, payload, label, chartMode }: {
  active?: boolean;
  payload?: { value: number; name: string; color: string; payload: DailyPnlPoint }[];
  label?: string;
  chartMode?: ChartMode;
}) {
  if (!active || !payload || !payload.length) return null;
  const p = payload[0];
  const point = p.payload;
  const isSnapshot = point.source === 'snapshot';

  return (
    <div style={{
      background: 'rgba(13,20,32,0.95)',
      border: '1px solid rgba(255,255,255,0.12)',
      borderRadius: 10,
      padding: '10px 14px',
      backdropFilter: 'blur(12px)',
      boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
      minWidth: 180,
    }}>
      <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 6 }}>
        {label ? fmtDate(label) : ''}
        {isSnapshot && (
          <span style={{ marginLeft: 6, fontSize: 10, color: 'var(--accent-blue)', opacity: 0.7 }}>● live</span>
        )}
      </div>

      {chartMode === 'cumulative' ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          {/* Running gain/loss from starting capital */}
          <div style={{ fontSize: 13, fontWeight: 600, color: p.value >= 0 ? 'var(--accent-green)' : 'var(--accent-red)', fontFamily: "'JetBrains Mono', monospace" }}>
            Total Change: {fmtSigned(p.value)}
            {point.cumulative_pct !== undefined && (
              <span style={{ fontSize: 11, opacity: 0.75 }}> ({point.cumulative_pct >= 0 ? '+' : ''}{point.cumulative_pct.toFixed(2)}%)</span>
            )}
          </div>
          {/* Actual portfolio value (snapshot mode only) */}
          {isSnapshot && point.net_liq_usd != null && (
            <div style={{ fontSize: 12, color: 'var(--text-secondary)', fontFamily: "'JetBrains Mono', monospace" }}>
              Portfolio: {fmt(point.net_liq_usd)} USD
            </div>
          )}
          {/* Day's move */}
          <div style={{ fontSize: 12, color: point.daily_pnl >= 0 ? 'var(--accent-green)' : 'var(--accent-red)', opacity: 0.8, fontFamily: "'JetBrains Mono', monospace" }}>
            Day: {fmtSigned(point.daily_pnl)}
            {point.daily_pct !== undefined && (
              <span style={{ fontSize: 11, opacity: 0.75 }}> ({point.daily_pct >= 0 ? '+' : ''}{point.daily_pct.toFixed(2)}%)</span>
            )}
          </div>
          {(point.daily_fees ?? 0) > 0 && (
            <div style={{ fontSize: 11, color: 'var(--accent-red)', opacity: 0.7, fontFamily: "'JetBrains Mono', monospace" }}>
              Fees: {fmt(point.daily_fees ?? 0)}
            </div>
          )}
        </div>
      ) : (
        // Daily mode — just show that day's gain/loss
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: p.value >= 0 ? 'var(--accent-green)' : 'var(--accent-red)', fontFamily: "'JetBrains Mono', monospace" }}>
            Day's Change: {fmtSigned(p.value)}
            {point.daily_pct !== undefined && (
              <span style={{ fontSize: 11, opacity: 0.75 }}> ({point.daily_pct >= 0 ? '+' : ''}{point.daily_pct.toFixed(2)}%)</span>
            )}
          </div>
          {isSnapshot && point.net_liq_usd != null && (
            <div style={{ fontSize: 12, color: 'var(--text-secondary)', fontFamily: "'JetBrains Mono', monospace" }}>
              Portfolio: {fmt(point.net_liq_usd)} USD
            </div>
          )}
          {(point.daily_fees ?? 0) > 0 && (
            <div style={{ fontSize: 11, color: 'var(--accent-red)', opacity: 0.7, fontFamily: "'JetBrains Mono', monospace" }}>
              Fees: {fmt(point.daily_fees ?? 0)}
            </div>
          )}
        </div>
      )}
    </div>
  );
}


// ─── AUD Freshness Label ──────────────────────────────────────────────────────

function AudLabel({ fxData }: { fxData: ExchangeRateData | null }) {
  if (!fxData) return null;
  const mins = fxData.age_minutes;
  const label = mins !== null
    ? mins < 1 ? 'just now' : `${mins} min ago`
    : 'unknown';
  return (
    <span style={{ fontSize: 10, color: fxData.stale ? 'var(--accent-yellow)' : 'var(--text-muted)', marginLeft: 6 }}>
      {fxData.stale ? '⚠ stale · ' : ''}Updated {label}
    </span>
  );
}

// ─── Chart Mode Toggle ────────────────────────────────────────────────────────

type ChartMode = 'cumulative' | 'daily';

// ─── Main Component ───────────────────────────────────────────────────────────

type AuthFetch = (url: string, init?: RequestInit) => Promise<Response>;

export default function PortfolioTab({ authFetch }: { authFetch: AuthFetch }) {
  const [data, setData] = useState<PortfolioData | null>(null);
  const [pnlHistory, setPnlHistory] = useState<PnlHistory | null>(null);
  const [fxData, setFxData] = useState<ExchangeRateData | null>(null);
  const [loading, setLoading] = useState(true);
  const [pnlLoading, setPnlLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [chartMode, setChartMode] = useState<ChartMode>('cumulative');
  const [sellingTicker, setSellingTicker] = useState<string | null>(null);
  const [confirmTicker, setConfirmTicker] = useState<string | null>(null);
  const [sellResult, setSellResult] = useState<{ ticker: string; message: string; success: boolean } | null>(null);
  const [resettingPnl, setResettingPnl] = useState(false);
  const [resetResult, setResetResult] = useState<{ message: string; success: boolean } | null>(null);

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
  }, [authFetch]);

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
  }, [authFetch]);

  // ── Fetch USD/AUD exchange rate ───────────────────────────────────────────
  const fetchFxRate = useCallback(async () => {
    try {
      const res = await authFetch('/api/exchange-rate');
      const json: ExchangeRateData = await res.json();
      setFxData(json);
    } catch {
      /* silently fail */
    }
  }, [authFetch]);

  // ── Sell a single stock ───────────────────────────────────────────────────
  const sellStock = useCallback(async (ticker: string) => {
    setSellingTicker(ticker);
    setConfirmTicker(null);
    setSellResult(null);
    try {
      const res = await authFetch('/api/sell-stock', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ticker }),
      });
      const json = await res.json();
      if (json.deferred) {
        setSellResult({ ticker, message: json.message, success: true });
      } else if (json.status === 'ok') {
        setSellResult({
          ticker,
          message: `Sold ${json.result?.shares ?? ''} shares of ${ticker} @ $${(json.result?.price ?? 0).toFixed(2)}`,
          success: true,
        });
        // Refresh portfolio after a brief delay to let IBKR sync
        setTimeout(() => { fetchPortfolio(); fetchPnlHistory(); }, 2000);
      } else {
        setSellResult({
          ticker,
          message: json.result?.error || json.detail || 'Sell order failed',
          success: false,
        });
      }
    } catch (err) {
      setSellResult({
        ticker,
        message: `Network error: ${err instanceof Error ? err.message : 'unknown'}`,
        success: false,
      });
    } finally {
      setSellingTicker(null);
    }
  }, [authFetch, fetchPortfolio, fetchPnlHistory]);

  // ── Reset P&L history and start fresh ────────────────────────────────────
  const resetPnlHistory = useCallback(async () => {
    if (!window.confirm(
      'This will delete all P&L chart history and start tracking fresh from tonight.\n\nThis cannot be undone. Continue?'
    )) return;

    setResettingPnl(true);
    setResetResult(null);
    try {
      // Step 1: Delete all snapshots
      const resetRes = await authFetch('/api/reset-pnl-history', { method: 'POST' });
      const resetJson = await resetRes.json();
      if (resetJson.status !== 'ok') throw new Error(resetJson.detail || 'Reset failed');

      // Step 2: Take a fresh snapshot immediately so chart has a baseline
      await authFetch('/api/trigger-snapshot', { method: 'POST' });

      setResetResult({ message: 'P&L history reset. Chart will update shortly (allow ~10s for snapshot).', success: true });
      // Refresh chart data after a delay to let the snapshot job complete
      setTimeout(() => fetchPnlHistory(), 10000);
    } catch (err) {
      setResetResult({
        message: `Reset failed: ${err instanceof Error ? err.message : 'unknown error'}`,
        success: false,
      });
    } finally {
      setResettingPnl(false);
    }
  }, [authFetch, fetchPnlHistory]);

  useEffect(() => {
    fetchPortfolio();
    fetchPnlHistory();
    fetchFxRate();

    const interval    = setInterval(fetchPortfolio,  30_000);
    const pnlInterval = setInterval(fetchPnlHistory, 60_000);
    const fxInterval  = setInterval(fetchFxRate,   1_800_000); // every 30 min
    return () => {
      clearInterval(interval);
      clearInterval(pnlInterval);
      clearInterval(fxInterval);
    };
  }, [fetchPortfolio, fetchPnlHistory, fetchFxRate]);

  const account   = data?.account ?? {};
  const positions = data?.positions ?? [];

  // Unrealised P&L = sum of live position P&L from IBKR
  const unrealisedPnl = positions.reduce((sum, p) => sum + p.pnl, 0);
  // Partial gains on still-open positions (banked from take-profit partials)
  const openPartialPnl = positions.reduce((sum, p) => sum + (p.realised_partial_pnl ?? 0), 0);
  const totalValue = positions.reduce((sum, p) => sum + p.market_value, 0);

  const realizedPnl  = pnlHistory?.all_time_realized_pnl ?? 0;
  const allTimeFees  = pnlHistory?.all_time_fees ?? 0;
  // Open P&L = unrealised gains on all held positions + already-realised partials on still-open trades
  const openPnl = unrealisedPnl + openPartialPnl;

  // Live USD→AUD rate from Frankfurter (falls back to IBKR rate or 1.55)
  const usdToAud = fxData?.rate ?? account.ExchangeRate_USD ?? 1.55;
  const audToUsd = 1 / usdToAud;
  const openPnlAud = openPnl * usdToAud;

  // All-Time P&L = NetLiquidation (USD → AUD) - $7900 AUD starting capital
  const STARTING_CAPITAL_AUD = 7900;
  const netLiqAud = (account.NetLiquidation ?? 0) * usdToAud;
  const allTimePnlAud = netLiqAud - STARTING_CAPITAL_AUD;
  const allTimePnlUsd = allTimePnlAud * audToUsd;
  const allTimePnlPositive = allTimePnlAud >= 0;

  const chartData = pnlHistory?.chart_data ?? [];
  const activeKey: 'cumulative_pnl' | 'daily_pnl' =
    chartMode === 'cumulative' ? 'cumulative_pnl' : 'daily_pnl';
  const chartColor =
    chartMode === 'cumulative'
      ? allTimePnlPositive ? '#22c55e' : '#ef4444'
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
            onClick={() => { fetchPortfolio(); fetchPnlHistory(); fetchFxRate(); }}
            title="Refresh"
            id="btn-refresh-portfolio"
          >
            🔄
          </button>
        </div>
      </div>

      {/* ── Sell result banner ─────────────────────────────────────────── */}
      {sellResult && (
        <div style={{
          display: 'flex', alignItems: 'flex-start', gap: 12,
          padding: '12px 16px', borderRadius: 10, marginBottom: 16,
          background: sellResult.success
            ? 'rgba(34,197,94,0.08)' : 'rgba(239,68,68,0.08)',
          border: `1px solid ${sellResult.success
            ? 'rgba(34,197,94,0.2)' : 'rgba(239,68,68,0.2)'}`,
        }}>
          <span style={{ fontSize: 14, flexShrink: 0 }}>
            {sellResult.success ? '✅' : '❌'}
          </span>
          <div style={{ fontSize: 12, color: sellResult.success ? 'var(--accent-green)' : 'var(--accent-red)', flex: 1 }}>
            <strong>{sellResult.ticker}:</strong> {sellResult.message}
          </div>
          <button
            onClick={() => setSellResult(null)}
            style={{
              background: 'none', border: 'none', color: 'var(--text-muted)',
              cursor: 'pointer', fontSize: 14, padding: 0, flexShrink: 0,
            }}
          >
            ✕
          </button>
        </div>
      )}

      {/* ── Stale FX rate warning ─────────────────────────────────────── */}
      {fxData?.stale && (
        <div style={{
          display: 'flex', alignItems: 'flex-start', gap: 12,
          padding: '10px 16px', borderRadius: 10, marginBottom: 16,
          background: 'rgba(234,179,8,0.08)', border: '1px solid rgba(234,179,8,0.2)',
        }}>
          <span style={{ fontSize: 14, flexShrink: 0 }}>⚠️</span>
          <div style={{ fontSize: 12, color: 'var(--accent-yellow)' }}>
            <strong>Stale exchange rate:</strong> The USD/AUD rate could not be refreshed.
            AUD values shown below are based on the last successful rate.
          </div>
        </div>
      )}

      {/* ── Connection status banner ─────────────────────────────────── */}
      {data && !data.connected && (
        <div style={{
          display: 'flex', alignItems: 'flex-start', gap: 12,
          padding: '12px 16px', borderRadius: 10, marginBottom: 20,
          background: data.error === 'Failed to reach API server'
            ? 'rgba(239,68,68,0.08)' : 'rgba(234,179,8,0.07)',
          border: `1px solid ${data.error === 'Failed to reach API server'
            ? 'rgba(239,68,68,0.2)' : 'rgba(234,179,8,0.2)'}`,
        }}>
          <span style={{ fontSize: 16, flexShrink: 0 }}>
            {data.error === 'Failed to reach API server' ? '🔴' : '🟡'}
          </span>
          <div>
            <div style={{ fontSize: 13, fontWeight: 600, color: data.error === 'Failed to reach API server' ? 'var(--accent-red)' : 'var(--accent-yellow)', marginBottom: 2 }}>
              {data.error === 'Failed to reach API server' ? 'Backend API unreachable' : 'IB Gateway not connected'}
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.5 }}>
              {data.error === 'Failed to reach API server'
                ? 'The backend server is not responding. Check Railway deployment logs.'
                : 'The IB Gateway service is starting up or awaiting IBKR login.'}
            </div>
          </div>
        </div>
      )}

      {/* Strategy upgrade alert */}
      {data?.strategy_alert && (
        <div style={{
          display: 'flex', alignItems: 'flex-start', gap: 12,
          padding: '14px 16px', borderRadius: 12, marginBottom: 20,
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

      {/* ── ALL-TIME P&L HERO ────────────────────────────────────────── */}
      <div style={{
        background: allTimePnlPositive
          ? 'linear-gradient(135deg, rgba(34,197,94,0.08) 0%, rgba(34,197,94,0.03) 100%)'
          : 'linear-gradient(135deg, rgba(239,68,68,0.08) 0%, rgba(239,68,68,0.03) 100%)',
        border: `1px solid ${allTimePnlPositive ? 'rgba(34,197,94,0.2)' : 'rgba(239,68,68,0.2)'}`,
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
            fontSize: 11, fontWeight: 600, letterSpacing: '0.8px',
            textTransform: 'uppercase' as const,
            color: 'var(--text-muted)', marginBottom: 8,
          }}>
            All-Time P&amp;L (Net Liq − A$7,900 starting capital)
          </div>
          {loading ? (
            <div style={{ display: 'flex', gap: 24, alignItems: 'baseline' }}>
              <div style={{ fontSize: 42, fontWeight: 800, color: 'var(--text-muted)', fontFamily: "'JetBrains Mono', monospace" }}>—</div>
            </div>
          ) : (
            <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap' as const, alignItems: 'baseline' }}>
              {/* Primary: AUD */}
              <div style={{
                fontSize: 46, fontWeight: 800, letterSpacing: '-1.5px',
                color: allTimePnlPositive ? 'var(--accent-green)' : 'var(--accent-red)',
                fontFamily: "'JetBrains Mono', monospace",
                textShadow: allTimePnlPositive
                  ? '0 0 40px rgba(34,197,94,0.35)'
                  : '0 0 40px rgba(239,68,68,0.35)',
              }}>
                {fmtSigned(allTimePnlAud)}
                <span style={{ fontSize: 16, marginLeft: 8, color: 'var(--text-muted)', fontWeight: 600, textShadow: 'none', letterSpacing: '0' }}>AUD</span>
                <AudLabel fxData={fxData} />
              </div>
              {/* Secondary: USD */}
              <div style={{
                fontSize: 32, fontWeight: 700, letterSpacing: '-1px',
                color: allTimePnlPositive ? 'var(--accent-green)' : 'var(--accent-red)',
                fontFamily: "'JetBrains Mono', monospace",
                opacity: 0.8,
              }}>
                {fmtSigned(allTimePnlUsd)}
                <span style={{ fontSize: 14, marginLeft: 6, color: 'var(--text-muted)', fontWeight: 600, letterSpacing: '0' }}>USD</span>
              </div>
            </div>
          )}
          <div style={{ display: 'flex', gap: 20, marginTop: 10, flexWrap: 'wrap' as const }}>
            <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
              <span style={{ color: 'var(--text-secondary)', fontWeight: 500 }}>Net Liq: </span>
              <span style={{ color: 'var(--text-primary)', fontFamily: "'JetBrains Mono', monospace" }}>
                {fmt(account.NetLiquidation ?? 0)} USD
              </span>
              <span style={{ color: 'var(--text-muted)', marginLeft: 6, fontFamily: "'JetBrains Mono', monospace" }}>
                ({fmt(netLiqAud, 'A$')})
              </span>
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
              <span style={{ color: 'var(--text-secondary)', fontWeight: 500 }}>Open P&amp;L: </span>
              <span style={{ color: openPnl >= 0 ? 'var(--accent-green)' : 'var(--accent-red)', fontFamily: "'JetBrains Mono', monospace" }}>
                {fmtSigned(openPnl)} USD
              </span>
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
              <span style={{ color: 'var(--text-secondary)', fontWeight: 500 }}>All-Time Realised: </span>
              <span style={{ color: realizedPnl >= 0 ? 'var(--accent-green)' : 'var(--accent-red)', fontFamily: "'JetBrains Mono', monospace" }}>
                {fmtSigned(realizedPnl)}
              </span>
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
              <span style={{ color: 'var(--text-secondary)', fontWeight: 500 }}>Fees Paid: </span>
              <span style={{ color: 'var(--accent-red)', fontFamily: "'JetBrains Mono', monospace" }}>
                {fmt(allTimeFees)}
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

      {/* ── P&L Chart ───────────────────────────────────────────── */}
      <div className="table-container" style={{ marginBottom: 28 }}>
        <div className="table-header-bar">
          <h3>P&amp;L Over Time</h3>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
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
            <button
              id="btn-reset-pnl"
              className="btn btn-outline"
              title="Delete all chart history and start tracking from tonight"
              onClick={resetPnlHistory}
              disabled={resettingPnl}
              style={{ fontSize: 11, padding: '4px 10px', color: 'var(--accent-red)', borderColor: 'rgba(239,68,68,0.3)', marginLeft: 4 }}
            >
              {resettingPnl ? '⏳ Resetting…' : '🔄 Reset Chart'}
            </button>
          </div>
        </div>

        {/* Reset result banner */}
        {resetResult && (
          <div style={{
            display: 'flex', alignItems: 'flex-start', gap: 10,
            padding: '10px 16px', margin: '0 0 0 0',
            background: resetResult.success ? 'rgba(34,197,94,0.07)' : 'rgba(239,68,68,0.07)',
            border: `1px solid ${resetResult.success ? 'rgba(34,197,94,0.2)' : 'rgba(239,68,68,0.2)'}`,
            borderTop: 'none',
          }}>
            <span style={{ fontSize: 13, flexShrink: 0 }}>{resetResult.success ? '✅' : '❌'}</span>
            <div style={{ fontSize: 12, color: resetResult.success ? 'var(--accent-green)' : 'var(--accent-red)', flex: 1 }}>
              {resetResult.message}
            </div>
            <button onClick={() => setResetResult(null)} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: 13, padding: 0 }}>✕</button>
          </div>
        )}

        <div style={{ padding: '24px 8px 16px' }}>
          {pnlLoading ? (
            <div style={{ height: 260, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <div className="skeleton" style={{ width: '100%', height: 260, borderRadius: 8 }} />
            </div>
          ) : chartData.length === 0 ? (
            <div className="empty-state" style={{ height: 280 }}>
              <div className="icon">📊</div>
              <p>No P&amp;L history yet</p>
              <p style={{ fontSize: 12, maxWidth: 340, textAlign: 'center', lineHeight: 1.6 }}>
                Click <strong>🔄 Reset Chart</strong> above to start tracking from tonight&apos;s portfolio value.
                The chart updates each weekday at ~15:45 ET after positions are settled.
              </p>
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={260}>
              <AreaChart data={chartData} margin={{ top: 4, right: 24, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id="pnlGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%"  stopColor={chartColor} stopOpacity={0.22} />
                    <stop offset="95%" stopColor={chartColor} stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" vertical={false} />
                <XAxis
                  dataKey="date"
                  tickFormatter={fmtDate}
                  tick={{ fill: 'var(--text-muted)', fontSize: 11 }}
                  axisLine={false} tickLine={false} interval="preserveStartEnd"
                />
                <YAxis
                  tickFormatter={(v) => `$${v >= 0 ? '' : '-'}${Math.abs(v).toLocaleString()}`}
                  tick={{ fill: 'var(--text-muted)', fontSize: 11 }}
                  axisLine={false} tickLine={false} width={72}
                />
                <Tooltip content={<ChartTooltip chartMode={chartMode} />} />
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

      {/* ── Stat cards ──────────────────────────────────────────── */}
      <div className="stat-grid">
        <div className="card">
          <div className="card-label">Net Liquidation</div>
          <div className="card-value">
            {loading ? '—' : fmt(account.NetLiquidation ?? 0)}
          </div>
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>
            {loading ? '' : <>{fmt(account.NetLiquidation_AUD ?? (account.NetLiquidation ?? 0) * usdToAud, 'A$')}<AudLabel fxData={fxData} /></>}
          </div>
        </div>
        <div className="card">
          <div className="card-label">Available Cash</div>
          <div className="card-value">
            {loading ? '—' : fmt(account.AvailableFunds ?? 0)}
          </div>
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>
            {loading ? '' : <>{fmt(account.AvailableFunds_AUD ?? (account.AvailableFunds ?? 0) * usdToAud, 'A$')}<AudLabel fxData={fxData} /></>}
          </div>
        </div>
        <div className="card">
          <div className="card-label">Open Positions Value</div>
          <div className="card-value">{loading ? '—' : fmt(totalValue)}</div>
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>
            {loading ? '' : <>{fmt(totalValue * usdToAud, 'A$')}<AudLabel fxData={fxData} /></>}
          </div>
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
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>
            {loading ? '' : <>{fmtSigned(unrealisedPnl * usdToAud)} AUD<AudLabel fxData={fxData} /></>}
          </div>
        </div>
      </div>

      {/* ── Positions table ─────────────────────────────────────── */}
      <div className="table-container">
        <div className="table-header-bar">
          <h3>Open Positions ({positions.length})</h3>
          <span className={`badge ${data?.mode === 'live' ? 'live' : 'paper'}`}>
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
                <th>Status</th>
                <th>Shares</th>
                <th>Avg Cost</th>
                <th>Current Price</th>
                <th>Market Value (AUD)</th>
                <th>Unrealised P&amp;L</th>
                <th>Partial Gain</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((pos) => {
                const isShort = pos.shares < 0;
                return (
                <tr key={pos.ticker}>
                  <td className="ticker">{pos.ticker}</td>
                  <td>
                    {isShort ? (
                      <span className="badge" style={{
                        background: 'rgba(139,92,246,0.15)',
                        color: '#a78bfa',
                        border: '1px solid rgba(139,92,246,0.3)',
                      }}>
                        ⬇ SHORT
                      </span>
                    ) : (
                      <span className={`badge ${pos.trade_status === 'sold_half' ? 'sold-half' : 'open'}`}>
                        {pos.trade_status === 'sold_half' ? '½ Sold' : '● Open'}
                      </span>
                    )}
                  </td>
                  <td className="mono" style={{ color: isShort ? '#a78bfa' : undefined }}>
                    {isShort ? `${pos.shares.toLocaleString()} (short)` : pos.shares.toLocaleString()}
                  </td>
                  <td className="mono">{fmt(pos.avg_cost)}</td>
                  <td className="mono">{fmt(pos.current_price)}</td>
                  <td className="mono">
                    {fmt(Math.abs(pos.market_value) * usdToAud, isShort ? '-A$' : 'A$')}
                    <AudLabel fxData={fxData} />
                  </td>
                  <PnlCell val={pos.pnl} pct={pos.pnl_pct} />
                  <td className="mono">
                    {pos.realised_partial_pnl !== 0 ? (
                      <span className={pos.realised_partial_pnl >= 0 ? 'positive' : 'negative'}>
                        {fmtSigned(pos.realised_partial_pnl)}
                      </span>
                    ) : (
                      <span style={{ color: 'var(--text-muted)' }}>—</span>
                    )}
                  </td>
                  <td>
                    {confirmTicker === pos.ticker ? (
                      <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                        <button
                          id={`btn-confirm-sell-${pos.ticker}`}
                          className="btn btn-danger"
                          style={{
                            padding: '4px 12px', fontSize: 11, fontWeight: 700,
                            borderRadius: 6, minWidth: 60,
                          }}
                          onClick={() => sellStock(pos.ticker)}
                          disabled={sellingTicker === pos.ticker}
                        >
                          {sellingTicker === pos.ticker ? '…' : 'Confirm'}
                        </button>
                        <button
                          className="btn btn-outline"
                          style={{
                            padding: '4px 8px', fontSize: 11, borderRadius: 6,
                          }}
                          onClick={() => setConfirmTicker(null)}
                        >
                          ✕
                        </button>
                      </div>
                    ) : (
                      <button
                        id={`btn-sell-${pos.ticker}`}
                        className="btn btn-outline"
                        style={{
                          padding: '4px 12px', fontSize: 11, fontWeight: 600,
                          borderRadius: 6,
                          color: isShort ? '#a78bfa' : 'var(--accent-red)',
                          borderColor: isShort ? 'rgba(139,92,246,0.3)' : 'rgba(239,68,68,0.3)',
                        }}
                        onClick={() => setConfirmTicker(pos.ticker)}
                        disabled={sellingTicker !== null}
                      >
                        {isShort ? 'Close Short' : 'Sell'}
                      </button>
                    )}
                  </td>
                </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
