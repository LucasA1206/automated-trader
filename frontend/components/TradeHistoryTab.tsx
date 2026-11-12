'use client';

import { useEffect, useState, useCallback, useMemo } from 'react';

// ─── Interfaces ───────────────────────────────────────────────────────────────

interface TradeItem {
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
  current_price?: number;
  market_value_aud?: number;
  unrealised_pnl?: number;
  ai_reason?: string | null;
  alpha_pct?: number | null;
}

type AuthFetch = (url: string, init?: RequestInit) => Promise<Response>;

function fmt(val: number | null | undefined): string {
  if (val == null || isNaN(val)) return '—';
  return `$${Math.abs(val).toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function fmtSigned(val: number | null | undefined): string {
  if (val == null || isNaN(val)) return '—';
  const sign = val >= 0 ? '+' : '-';
  return `${sign}$${Math.abs(val).toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

export default function TradeHistoryTab({
  authFetch,
  tradingMode = 'paper',
}: {
  authFetch: AuthFetch;
  tradingMode?: 'paper' | 'live';
}) {
  const [trades, setTrades] = useState<TradeItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [searchTicker, setSearchTicker] = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | 'open' | 'sold_half' | 'closed' | 'error'>('all');
  const [selectedTrade, setSelectedTrade] = useState<TradeItem | null>(null);

  const syncDateString = useMemo(() => {
    const now = new Date();
    return `${now.toLocaleDateString('en-AU', { day: '2-digit', month: 'short', year: 'numeric' }).toUpperCase()} · LAST SYNC ${now.toLocaleTimeString('en-AU')} AEDT`;
  }, []);

  const fetchTrades = useCallback(async () => {
    try {
      const params = statusFilter !== 'all' ? `&status=${statusFilter}` : '';
      const res = await authFetch(`/api/trades?limit=200${params}`);
      if (res.ok) {
        const json = await res.json();
        setTrades(json.trades || []);
        setTotal(json.total || (json.trades ? json.trades.length : 0));
      }
    } catch {
      // Fail silently
    } finally {
      setLoading(false);
    }
  }, [authFetch, statusFilter]);

  useEffect(() => {
    fetchTrades();
  }, [fetchTrades]);

  // Summary calculations from real live trades
  const closedTrades = useMemo(() => trades.filter((t) => t.status === 'closed'), [trades]);
  const openTrades = useMemo(() => trades.filter((t) => t.status === 'open'), [trades]);
  const soldHalfTrades = useMemo(() => trades.filter((t) => t.status === 'sold_half'), [trades]);

  const totalRealisedPnl = useMemo(() => {
    return closedTrades.reduce((sum, t) => sum + (t.pnl || 0), 0);
  }, [closedTrades]);

  const totalFees = useMemo(() => {
    return trades.reduce((sum, t) => sum + (t.fees || 0), 0);
  }, [trades]);

  const winningTradesCount = useMemo(() => {
    return closedTrades.filter((t) => (t.pnl || 0) >= 0).length;
  }, [closedTrades]);

  const winRateFormatted = useMemo(() => {
    if (closedTrades.length === 0) return '0.0%';
    return `${((winningTradesCount / closedTrades.length) * 100).toFixed(1)}%`;
  }, [closedTrades.length, winningTradesCount]);

  // Filtered trades by search ticker
  const filteredTrades = useMemo(() => {
    return trades.filter((t) => {
      const matchSearch = !searchTicker || t.ticker.toLowerCase().includes(searchTicker.toLowerCase());
      return matchSearch;
    });
  }, [trades, searchTicker]);

  // Export CSV
  const handleExportCSV = () => {
    const headers = ['Ticker', 'Status', 'Shares', 'Buy Price', 'Sell Price', 'Buy Time', 'Sell Time', 'Partial Gain', 'Final PnL', 'Fees'];
    const rows = filteredTrades.map((t) => [
      t.ticker,
      t.status,
      t.shares,
      t.buy_price ?? '',
      t.sell_price ?? '',
      t.buy_time ?? '',
      t.sell_time ?? '',
      t.realised_partial_pnl ?? '',
      t.pnl ?? '',
      t.fees ?? '',
    ]);
    const csvContent = 'data:text/csv;charset=utf-8,' + [headers.join(','), ...rows.map((e) => e.join(','))].join('\n');
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement('a');
    link.setAttribute('href', encodedUri);
    link.setAttribute('download', `trade_history_${new Date().toISOString().split('T')[0]}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  return (
    <div>
      {/* ── Page Header ────────────────────────────────────────── */}
      <div className="page-title-block">
        <h1 className="page-title-heading">Trade History</h1>
        <p className="page-title-subtitle">Every execution. A complete picture.</p>
        <p className="page-title-meta">{syncDateString}</p>
      </div>

      {/* ── Mobile-Only Realised P&L Hero Card (Page 12) ────────── */}
      <div className="mobile-only-block" style={{ marginBottom: 16 }}>
        <div className="theme-card" style={{ padding: '20px 22px' }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: '#64748b', letterSpacing: '0.8px', textTransform: 'uppercase' }}>
            REALISED P&amp;L
          </div>
          <div style={{
            fontSize: 34,
            fontWeight: 800,
            color: totalRealisedPnl >= 0 ? '#059669' : '#dc2626',
            marginTop: 4,
            letterSpacing: '-0.8px',
          }}>
            {loading ? '—' : fmtSigned(totalRealisedPnl)}
          </div>
        </div>
      </div>

      {/* ── Stat Cards ─────────────────────────────────────────── */}
      <div className="trade-history-stat-grid">
        <div className="stat-metric-card desktop-only-card">
          <div className="stat-metric-label">Total Trades</div>
          <div className="stat-metric-val">{loading ? '—' : total}</div>
        </div>
        <div className="stat-metric-card desktop-only-card">
          <div className="stat-metric-label">Realised P&amp;L</div>
          <div className="stat-metric-val" style={{ color: totalRealisedPnl >= 0 ? '#059669' : '#dc2626' }}>
            {loading ? '—' : fmtSigned(totalRealisedPnl)}
          </div>
        </div>
        <div className="stat-metric-card">
          <div className="stat-metric-label">Win Rate</div>
          <div className="stat-metric-val">{loading ? '—' : winRateFormatted}</div>
        </div>
        <div className="stat-metric-card">
          <div className="stat-metric-label">Open / ½ Sold</div>
          <div className="stat-metric-val">{loading ? '—' : `${openTrades.length} / ${soldHalfTrades.length}`}</div>
        </div>
        <div className="stat-metric-card">
          <div className="stat-metric-label">Total Fees</div>
          <div className="stat-metric-val">{loading ? '—' : fmt(totalFees)}</div>
        </div>
        <div className="stat-metric-card mobile-only-card">
          <div className="stat-metric-label">Total Trades</div>
          <div className="stat-metric-val">{loading ? '—' : total}</div>
        </div>
      </div>

      {/* ── Filter Bar ─────────────────────────────────────────── */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 12,
        marginBottom: 20,
        flexWrap: 'wrap',
      }}>
        <div style={{ display: 'flex', gap: 10, flex: 1, minWidth: 260, maxWidth: 500 }}>
          <div style={{
            flex: 1,
            position: 'relative',
            background: '#ffffff',
            borderRadius: 8,
            border: '1px solid var(--border)',
          }}>
            <input
              type="text"
              placeholder="Search ticker…"
              value={searchTicker}
              onChange={(e) => setSearchTicker(e.target.value)}
              style={{
                width: '100%',
                padding: '9px 14px',
                border: 'none',
                background: 'transparent',
                outline: 'none',
                fontSize: 13,
                color: '#0f172a',
              }}
            />
          </div>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as any)}
            style={{
              padding: '9px 14px',
              borderRadius: 8,
              border: '1px solid var(--border)',
              background: '#ffffff',
              fontSize: 13,
              color: '#334155',
              outline: 'none',
              cursor: 'pointer',
            }}
          >
            <option value="all">All statuses ▾</option>
            <option value="open">Open</option>
            <option value="sold_half">½ Sold</option>
            <option value="closed">Closed</option>
            <option value="error">Error</option>
          </select>
        </div>

        <button
          className="btn-outline-subtle"
          onClick={handleExportCSV}
          id="btn-export-csv"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <line x1="12" y1="5" x2="12" y2="19" />
            <polyline points="19 12 12 19 5 12" />
          </svg>
          Export CSV
        </button>
      </div>

      {/* ── Desktop Trades Table (Page 3) ──────────────────────── */}
      <div className="theme-card desktop-only-table-view">
        <div className="table-header-flex">
          <h3 className="table-title-bold">All trades</h3>
          <span style={{ fontSize: 12, color: '#94a3b8' }}>
            {filteredTrades.length} total · Scroll right for execution details →
          </span>
        </div>

        <div className="scrollable-table-wrapper">
          {filteredTrades.length === 0 ? (
            <div style={{
              padding: '36px 20px',
              textAlign: 'center',
              color: '#94a3b8',
              fontSize: 13,
            }}>
              <span style={{ fontSize: 26, display: 'block', marginBottom: 6 }}>📋</span>
              <p style={{ fontWeight: 600, color: '#475569', marginBottom: 4 }}>No trades found</p>
              <p style={{ fontSize: 12 }}>Trades will appear here as the bot executes buy and sell orders.</p>
            </div>
          ) : (
            <table className="custom-data-table" style={{ minWidth: 1080 }}>
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
                  <th>Buy Price</th>
                  <th>Sell Price</th>
                  <th>Buy Time (AEDT)</th>
                  <th>Sell Time (AEDT)</th>
                  <th>Final P&amp;L (AUD)</th>
                </tr>
              </thead>
              <tbody>
                {filteredTrades.map((t) => {
                  const isClosed = t.status === 'closed';
                  const isPartial = t.status === 'sold_half';
                  return (
                    <tr key={t.id}>
                      <td style={{ fontWeight: 700, color: '#0f172a' }}>{t.ticker}</td>
                      <td>
                        <span className={isClosed ? 'badge-status-closed' : isPartial ? 'badge-status-partial' : 'badge-status-open'}>
                          {isClosed ? 'Closed' : isPartial ? '½ Sold' : 'Open'}
                        </span>
                      </td>
                      <td>{t.shares}</td>
                      <td>{fmt(t.buy_price)}</td>
                      <td>{fmt(t.current_price ?? t.buy_price)}</td>
                      <td>{t.market_value_aud ? fmt(t.market_value_aud) : '—'}</td>
                      <td style={{ color: (t.unrealised_pnl || 0) >= 0 ? '#059669' : '#dc2626', fontWeight: 600 }}>
                        {t.unrealised_pnl ? fmtSigned(t.unrealised_pnl) : '—'}
                      </td>
                      <td style={{ color: (t.realised_partial_pnl || 0) > 0 ? '#059669' : '#94a3b8', fontWeight: 600 }}>
                        {t.realised_partial_pnl ? fmtSigned(t.realised_partial_pnl) : '—'}
                      </td>
                      <td>
                        <button
                          className="btn-manage-link"
                          onClick={() => setSelectedTrade(t)}
                        >
                          {isClosed ? 'View' : 'Manage'} ↗
                        </button>
                      </td>
                      <td>{fmt(t.buy_price)}</td>
                      <td>{fmt(t.sell_price)}</td>
                      <td>{t.buy_time ? new Date(t.buy_time).toLocaleDateString('en-AU', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }) : '—'}</td>
                      <td>{t.sell_time ? new Date(t.sell_time).toLocaleDateString('en-AU', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }) : '—'}</td>
                      <td style={{ color: (t.pnl || 0) >= 0 ? '#059669' : '#dc2626', fontWeight: 700 }}>
                        {isClosed ? fmtSigned(t.pnl) : '—'}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>

        {/* Pagination Bar */}
        <div style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginTop: 16,
          fontSize: 12,
          color: '#64748b',
          flexWrap: 'wrap',
          gap: 10,
        }}>
          <div>Showing 1–{filteredTrades.length} of {total} trades</div>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            <button className="btn-outline-subtle" style={{ padding: '4px 8px', fontSize: 11 }}>← Previous</button>
            <span style={{ fontWeight: 600, padding: '0 6px', color: '#0f172a' }}>1</span>
            <button className="btn-outline-subtle" style={{ padding: '4px 8px', fontSize: 11 }}>Next →</button>
          </div>
        </div>
      </div>

      {/* ── Mobile Phone Cards View (Page 12) ──────────────────── */}
      <div className="mobile-only-cards-list">
        <div style={{ fontSize: 12, color: '#94a3b8', marginBottom: 12 }}>
          All trades · {filteredTrades.length} &nbsp;&nbsp; Prices USD · Returns AUD
        </div>

        {filteredTrades.length === 0 ? (
          <div className="theme-card" style={{ padding: '32px 20px', textAlign: 'center', color: '#94a3b8' }}>
            <span style={{ fontSize: 26, display: 'block', marginBottom: 6 }}>📋</span>
            <p style={{ fontWeight: 600, color: '#475569', marginBottom: 4 }}>No trades found</p>
            <p style={{ fontSize: 12 }}>Trades will appear here as the bot executes buy and sell orders.</p>
          </div>
        ) : (
          filteredTrades.map((t) => {
            const isClosed = t.status === 'closed';
            const isPartial = t.status === 'sold_half';
            const pnlPos = (t.pnl || 0) >= 0;

            return (
              <div
                key={t.id}
                className="theme-card"
                style={{ marginBottom: 14, padding: '18px 20px' }}
              >
                {/* Card Header */}
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                  <span style={{ fontSize: 20, fontWeight: 800, color: '#0f172a' }}>
                    {t.ticker}
                  </span>
                  <span className={isClosed ? 'badge-status-closed' : isPartial ? 'badge-status-partial' : 'badge-status-open'}>
                    {isClosed ? 'Closed' : isPartial ? '½ Sold' : 'Open'}
                  </span>
                </div>

                {/* Metric Rows */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8, fontSize: 13 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                    <span style={{ color: '#64748b' }}>{isClosed ? 'Final P&L' : 'Unrealised P&L'}</span>
                    <span style={{ fontSize: 20, fontWeight: 800, color: pnlPos ? '#059669' : '#dc2626' }}>
                      {fmtSigned(t.pnl || t.unrealised_pnl)}
                    </span>
                  </div>

                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span style={{ color: '#64748b' }}>Shares / Avg Cost</span>
                    <span style={{ color: '#0f172a', fontWeight: 500 }}>
                      {t.shares} / {fmt(t.buy_price)}
                    </span>
                  </div>

                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span style={{ color: '#64748b' }}>Current / Market Value</span>
                    <span style={{ color: '#0f172a', fontWeight: 500 }}>
                      {fmt(t.current_price ?? t.buy_price)} / {t.market_value_aud ? fmt(t.market_value_aud) : '—'}
                    </span>
                  </div>

                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span style={{ color: '#64748b' }}>Buy / Sell Price</span>
                    <span style={{ color: '#0f172a', fontWeight: 500 }}>
                      {fmt(t.buy_price)} / {t.sell_price ? fmt(t.sell_price) : '—'}
                    </span>
                  </div>

                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span style={{ color: '#64748b' }}>Buy Time</span>
                    <span style={{ color: '#0f172a', fontWeight: 500 }}>
                      {t.buy_time ? new Date(t.buy_time).toLocaleDateString('en-AU', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }) + ' AEDT' : '—'}
                    </span>
                  </div>

                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span style={{ color: '#64748b' }}>Sell Time</span>
                    <span style={{ color: '#0f172a', fontWeight: 500 }}>
                      {t.sell_time ? new Date(t.sell_time).toLocaleDateString('en-AU', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }) + ' AEDT' : '—'}
                    </span>
                  </div>

                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span style={{ color: '#64748b' }}>Partial Gain</span>
                    <span style={{ color: (t.realised_partial_pnl || 0) > 0 ? '#059669' : '#94a3b8', fontWeight: 600 }}>
                      {t.realised_partial_pnl ? fmtSigned(t.realised_partial_pnl) : '—'}
                    </span>
                  </div>
                </div>

                {/* Action Link at Bottom */}
                <div style={{ marginTop: 14, paddingTop: 10, borderTop: '1px solid var(--border-subtle)' }}>
                  <button
                    className="btn-manage-link"
                    onClick={() => setSelectedTrade(t)}
                    style={{ fontSize: 13, padding: 0 }}
                  >
                    {isClosed ? 'View ↗' : 'Manage ↗'}
                  </button>
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* ── Trade Detail Modal ─────────────────────────────────── */}
      {selectedTrade && (
        <div className="modal-backdrop-blur" onClick={() => setSelectedTrade(null)}>
          <div className="modal-content-white" onClick={(e) => e.stopPropagation()}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
              <h3 style={{ fontSize: 18, fontWeight: 700, color: '#0f172a' }}>
                {selectedTrade.ticker} Details
              </h3>
              <button
                onClick={() => setSelectedTrade(null)}
                style={{ background: 'none', border: 'none', fontSize: 18, cursor: 'pointer', color: '#94a3b8' }}
              >
                ✕
              </button>
            </div>
            <div style={{ fontSize: 13, color: '#475569', lineHeight: 1.6 }}>
              <p><strong>Status:</strong> {selectedTrade.status}</p>
              <p><strong>Shares:</strong> {selectedTrade.shares}</p>
              <p><strong>Buy Price:</strong> {fmt(selectedTrade.buy_price)}</p>
              <p><strong>Sell Price:</strong> {fmt(selectedTrade.sell_price)}</p>
              <p><strong>Total P&amp;L:</strong> {fmtSigned(selectedTrade.pnl)}</p>
              {selectedTrade.ai_reason && (
                <div style={{ marginTop: 12, padding: 12, background: '#f8faf9', borderRadius: 8 }}>
                  <strong>AI Strategy Note:</strong> {selectedTrade.ai_reason}
                </div>
              )}
            </div>
            <div style={{ marginTop: 20, textAlign: 'right' }}>
              <button className="btn-outline-subtle" onClick={() => setSelectedTrade(null)}>
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Responsive layout styling rules for Trade History */}
      <style jsx>{`
        .trade-history-stat-grid {
          display: grid;
          grid-template-columns: repeat(5, 1fr);
          gap: 14px;
          margin-bottom: 24px;
        }
        .desktop-only-table-view {
          display: block;
        }
        .mobile-only-cards-list {
          display: none;
        }
        .mobile-only-block {
          display: none;
        }
        .mobile-only-card {
          display: none;
        }

        @media (max-width: 900px) {
          .trade-history-stat-grid {
            grid-template-columns: repeat(3, 1fr);
          }
        }

        @media (max-width: 768px) {
          .trade-history-stat-grid {
            grid-template-columns: repeat(2, 1fr);
            gap: 10px;
          }
          .desktop-only-table-view {
            display: none;
          }
          .desktop-only-card {
            display: none;
          }
          .mobile-only-cards-list {
            display: block;
          }
          .mobile-only-block {
            display: block;
          }
          .mobile-only-card {
            display: block;
          }
        }
      `}</style>
    </div>
  );
}
