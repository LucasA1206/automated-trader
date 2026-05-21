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
  status: 'open' | 'sold_half' | 'closed' | 'error';
  pnl: number | null;
  pnl_pct: number | null;
  realised_partial_pnl: number;
  fees: number;
  ai_reason: string | null;
}

function fmt(val: number): string {
  return `$${Math.abs(val).toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function fmtSigned(val: number): string {
  const sign = val >= 0 ? '+' : '-';
  return `${sign}${fmt(val)}`;
}

function formatDate(iso: string | null): string {
  if (!iso) return '—';
  return new Date(iso).toLocaleString('en-AU', {
    month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}

type Filter = 'all' | 'open' | 'sold_half' | 'closed' | 'error';

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
  }, [filter, authFetch]);

  useEffect(() => {
    setLoading(true);
    fetchTrades();
  }, [fetchTrades]);

  // Summary stats
  const closed = trades.filter((t) => t.status === 'closed');
  const open   = trades.filter((t) => t.status === 'open' || t.status === 'sold_half');

  // All-time realised P&L from closed trades (pnl already includes partial gains — fixed in backend)
  const totalPnl   = closed.reduce((sum, t) => sum + (t.pnl ?? 0), 0);
  const totalFees  = trades.reduce((sum, t) => sum + (t.fees ?? 0), 0);
  const winCount   = closed.filter((t) => (t.pnl ?? 0) >= 0).length;
  const winRate    = closed.length > 0 ? (winCount / closed.length) * 100 : 0;

  // For sold_half open trades: show the banked partial gain in the running total
  const runningPartials = open.reduce((sum, t) => sum + (t.realised_partial_pnl ?? 0), 0);

  const filterButtons: { key: Filter; label: string }[] = [
    { key: 'all', label: 'All' },
    { key: 'open', label: 'Open' },
    { key: 'sold_half', label: '½ Sold' },
    { key: 'closed', label: 'Closed' },
    { key: 'error', label: 'Error' },
  ];

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
          <div className="card-label">Realised P&amp;L (Closed)</div>
          <div className="card-value">
            <span className={totalPnl >= 0 ? 'positive' : 'negative'}>
              {totalPnl >= 0 ? '+' : '-'}{fmt(totalPnl)}
            </span>
          </div>
        </div>
        {runningPartials !== 0 && (
          <div className="card">
            <div className="card-label">Banked Partials (Open)</div>
            <div className="card-value">
              <span className={runningPartials >= 0 ? 'positive' : 'negative'}>
                {fmtSigned(runningPartials)}
              </span>
            </div>
          </div>
        )}
        <div className="card">
          <div className="card-label">Win Rate</div>
          <div className="card-value">{winRate.toFixed(0)}%</div>
        </div>
        <div className="card">
          <div className="card-label">Open / ½ Sold</div>
          <div className="card-value">{open.length}</div>
        </div>
        <div className="card">
          <div className="card-label">Total Fees</div>
          <div className="card-value">
            <span className="negative">{fmt(totalFees)}</span>
          </div>
        </div>
      </div>

      <div className="table-container">
        <div className="table-header-bar">
          <h3>Trades</h3>
          <div className="filter-bar">
            {filterButtons.map(({ key, label }) => (
              <button
                key={key}
                id={`filter-${key}`}
                className={`filter-btn ${filter === key ? 'active' : ''}`}
                onClick={() => setFilter(key)}
              >
                {label}
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
                <th>Status</th>
                <th>Shares</th>
                <th>Buy Price</th>
                <th>Sell Price</th>
                <th>Buy Time</th>
                <th>Sell Time</th>
                <th>Partial Gain</th>
                <th>Final P&amp;L</th>
              </tr>
            </thead>
            <tbody>
              {trades.map((trade) => {
                const finalPnl    = trade.pnl ?? 0;
                const partialPnl  = trade.realised_partial_pnl ?? 0;
                const pnlPos      = finalPnl >= 0;
                const partialPos  = partialPnl >= 0;
                const isExpanded  = expandedId === trade.id;

                const statusClass =
                  trade.status === 'open'      ? 'open'
                  : trade.status === 'sold_half' ? 'sold-half'
                  : trade.status === 'error'     ? 'error'
                  : pnlPos                      ? 'closed-win'
                  : 'closed-lose';

                const statusLabel =
                  trade.status === 'open'       ? '● Open'
                  : trade.status === 'sold_half' ? '½ Sold'
                  : trade.status === 'error'     ? '✕ Error'
                  : `${pnlPos ? '▲' : '▼'} Closed`;

                return (
                  <>
                    <tr
                      key={trade.id}
                      onClick={() => setExpandedId(isExpanded ? null : trade.id)}
                      style={{ cursor: 'pointer' }}
                    >
                      <td className="ticker">{trade.ticker}</td>
                      <td>
                        <span className={`badge ${statusClass}`}>
                          {statusLabel}
                        </span>
                      </td>
                      <td className="mono">{trade.shares.toLocaleString()}</td>
                      <td className="mono">{trade.buy_price ? fmt(trade.buy_price) : '—'}</td>
                      <td className="mono">{trade.sell_price ? fmt(trade.sell_price) : '—'}</td>
                      <td>{formatDate(trade.buy_time)}</td>
                      <td>{formatDate(trade.sell_time)}</td>
                      <td className="mono">
                        {partialPnl !== 0 ? (
                          <span className={partialPos ? 'positive' : 'negative'}>
                            {fmtSigned(partialPnl)}
                          </span>
                        ) : (
                          <span style={{ color: 'var(--text-muted)' }}>—</span>
                        )}
                      </td>
                      <td className="mono">
                        {trade.status === 'closed' && trade.pnl !== null ? (
                          <span className={pnlPos ? 'positive' : 'negative'}>
                            {pnlPos ? '+' : '-'}{fmt(finalPnl)}
                            {trade.pnl_pct !== null && ` (${trade.pnl_pct > 0 ? '+' : ''}${trade.pnl_pct.toFixed(2)}%)`}
                          </span>
                        ) : (
                          <span style={{ color: 'var(--text-muted)' }}>—</span>
                        )}
                      </td>
                    </tr>

                    {/* Expanded detail row */}
                    {isExpanded && (
                      <tr key={`${trade.id}-detail`} style={{ background: 'rgba(59,130,246,0.04)' }}>
                        <td colSpan={9} style={{ padding: '12px 20px' }}>
                          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                            {trade.ai_reason && (
                              <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                                <strong style={{ color: 'var(--accent-blue)' }}>AI Reason: </strong>
                                {trade.ai_reason}
                              </div>
                            )}
                            {partialPnl !== 0 && (
                              <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                                <strong style={{ color: 'var(--accent-green)' }}>Partial Gain: </strong>
                                {fmtSigned(partialPnl)} banked from +10% take-profit half-sell.
                                {trade.status === 'closed' && ' Included in Final P&L above.'}
                              </div>
                            )}
                            {trade.fees > 0 && (
                              <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                                <strong style={{ color: 'var(--text-muted)' }}>Fees: </strong>
                                {fmt(trade.fees)}
                              </div>
                            )}
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
