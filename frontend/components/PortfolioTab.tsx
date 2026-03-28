'use client';

import { useEffect, useState, useCallback } from 'react';

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
  positions: Position[];
  account: Account;
  error?: string;
}

function fmt(val: number, prefix = '$'): string {
  return `${prefix}${Math.abs(val).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

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

export default function PortfolioTab() {
  const [data, setData] = useState<PortfolioData | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const fetchPortfolio = useCallback(async () => {
    try {
      const res = await fetch('/api/portfolio');
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

  useEffect(() => {
    fetchPortfolio();
    const interval = setInterval(fetchPortfolio, 30_000);
    return () => clearInterval(interval);
  }, [fetchPortfolio]);

  const account = data?.account ?? {};
  const positions = data?.positions ?? [];
  const totalPnl = positions.reduce((sum, p) => sum + p.pnl, 0);
  const totalValue = positions.reduce((sum, p) => sum + p.market_value, 0);

  return (
    <div>
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
            onClick={fetchPortfolio}
            title="Refresh"
            id="btn-refresh-portfolio"
          >
            🔄
          </button>
        </div>
      </div>

      {/* Connection status banner */}
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

      {/* Stat cards */}
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
              <span className={totalPnl >= 0 ? 'positive' : 'negative'}>
                {totalPnl >= 0 ? '+' : '-'}{fmt(totalPnl)}
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Positions table */}
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
