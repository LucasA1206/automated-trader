'use client';

import { useEffect, useState, useCallback } from 'react';

interface Trade {
  id: number;
  ticker: string;
  shares: number;
  buy_price: number | null;
  sell_price: number | null;
  buy_time: string | null;
  sell_time: string | null;
  status: 'open' | 'closed' | 'error';
  pnl: number | null;
  pnl_pct: number | null;
  ai_reason: string | null;
}

function fmt(val: number): string {
  return `$${Math.abs(val).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function formatDate(iso: string | null): string {
  if (!iso) return '—';
  return new Date(iso).toLocaleString('en-AU', {
    month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}

type Filter = 'all' | 'open' | 'closed' | 'error';

type AuthFetch = (url: string, init?: RequestInit) => Promise<Response>;

export default function TradeHistoryTab({ authFetch }: { authFetch: AuthFetch }) {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<Filter>('all');
  const [expandedId, setExpandedId] = useState<number | null>(null);

  const fetchTrades = useCallback(async () => {
    const params = filter !== 'all' ? `&status=${filter}` : '';
    try {
      const res = await authFetch(`/api/trades?limit=100${params}`);
      const json = await res.json();
      setTrades(json.trades ?? []);
      setTotal(json.total ?? 0);
    } catch {
      setTrades([]);
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    setLoading(true);
    fetchTrades();
  }, [fetchTrades]);

  // Summary stats
  const closed = trades.filter((t) => t.status === 'closed');
  const totalPnl = closed.reduce((sum, t) => sum + (t.pnl ?? 0), 0);
  const winCount = closed.filter((t) => (t.pnl ?? 0) >= 0).length;
  const winRate = closed.length > 0 ? (winCount / closed.length) * 100 : 0;

  return (
    <div>
      <div className="page-header">
        <h2>Trade History</h2>
        <p>All buy &amp; sell orders placed by the bot</p>
      </div>

      {/* Summary stats */}
      <div className="stat-grid" style={{ marginBottom: 24 }}>
        <div className="card">
          <div className="card-label">Total Trades</div>
          <div className="card-value">{total}</div>
        </div>
        <div className="card">
          <div className="card-label">Realised P&amp;L</div>
          <div className="card-value">
            <span className={totalPnl >= 0 ? 'positive' : 'negative'}>
              {totalPnl >= 0 ? '+' : '-'}{fmt(totalPnl)}
            </span>
          </div>
        </div>
        <div className="card">
          <div className="card-label">Win Rate</div>
          <div className="card-value">{winRate.toFixed(0)}%</div>
        </div>
        <div className="card">
          <div className="card-label">Open Positions</div>
          <div className="card-value">{trades.filter((t) => t.status === 'open').length}</div>
        </div>
      </div>

      <div className="table-container">
        <div className="table-header-bar">
          <h3>Trades</h3>
          <div className="filter-bar">
            {(['all', 'open', 'closed', 'error'] as Filter[]).map((f) => (
              <button
                key={f}
                id={`filter-${f}`}
                className={`filter-btn ${filter === f ? 'active' : ''}`}
                onClick={() => setFilter(f)}
              >
                {f.charAt(0).toUpperCase() + f.slice(1)}
              </button>
            ))}
          </div>
        </div>

        {loading ? (
          <div className="empty-state">
            <div className="skeleton" style={{ width: '100%', height: 120 }} />
          </div>
        ) : trades.length === 0 ? (
          <div className="empty-state">
            <div className="icon">📭</div>
            <p>No trades found</p>
            <p style={{ fontSize: 12 }}>Trades will appear here once the bot starts trading.</p>
          </div>
        ) : (
          <table id="trade-history-table">
            <thead>
              <tr>
                <th>Ticker</th>
                <th>Shares</th>
                <th>Buy Price</th>
                <th>Sell Price</th>
                <th>Buy Time</th>
                <th>Sell Time</th>
                <th>P&amp;L</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {trades.map((trade) => {
                const pnlPos = (trade.pnl ?? 0) >= 0;
                const statusClass =
                  trade.status === 'open'
                    ? 'open'
                    : trade.status === 'error'
                    ? 'error'
                    : pnlPos
                    ? 'closed-win'
                    : 'closed-lose';

                return (
                  <>
                    <tr
                      key={trade.id}
                      onClick={() => setExpandedId(expandedId === trade.id ? null : trade.id)}
                      style={{ cursor: 'pointer' }}
                    >
                      <td className="ticker">{trade.ticker}</td>
                      <td className="mono">{trade.shares}</td>
                      <td className="mono">{trade.buy_price ? fmt(trade.buy_price) : '—'}</td>
                      <td className="mono">{trade.sell_price ? fmt(trade.sell_price) : '—'}</td>
                      <td>{formatDate(trade.buy_time)}</td>
                      <td>{formatDate(trade.sell_time)}</td>
                      <td className="mono">
                        {trade.pnl !== null ? (
                          <span className={pnlPos ? 'positive' : 'negative'}>
                            {pnlPos ? '+' : '-'}{fmt(trade.pnl)}
                            {trade.pnl_pct !== null && ` (${trade.pnl_pct > 0 ? '+' : ''}${trade.pnl_pct.toFixed(2)}%)`}
                          </span>
                        ) : '—'}
                      </td>
                      <td>
                        <span className={`badge ${statusClass}`}>
                          {trade.status === 'open' ? '● Open' : trade.status === 'error' ? '✕ Error' : `${pnlPos ? '▲' : '▼'} Closed`}
                        </span>
                      </td>
                    </tr>
                    {expandedId === trade.id && trade.ai_reason && (
                      <tr key={`${trade.id}-detail`} style={{ background: 'rgba(59,130,246,0.04)' }}>
                        <td colSpan={8} style={{ padding: '12px 20px' }}>
                          <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                            <strong style={{ color: 'var(--accent-blue)' }}>AI Reason: </strong>
                            {trade.ai_reason}
                          </div>
                        </td>
                      </tr>
                    )}
                  </>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
