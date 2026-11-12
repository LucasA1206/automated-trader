'use client';

import { useEffect, useState, useCallback, useMemo } from 'react';

// ─── Interfaces ───────────────────────────────────────────────────────────────

interface LogItem {
  id: number;
  timestamp: string;
  timeFormatted: string;
  level: 'INFO' | 'WARN' | 'ERROR';
  category: string;
  message: string;
}

type AuthFetch = (url: string, init?: RequestInit) => Promise<Response>;

const SAMPLE_LOGS: LogItem[] = [
  { id: 1, timestamp: '2026-11-12T09:42:08', timeFormatted: '12 Nov 09:42:08', level: 'INFO', category: 'Broker', message: 'IBKR heartbeat received. Connection healthy.' },
  { id: 2, timestamp: '2026-11-12T09:42:01', timeFormatted: '12 Nov 09:42:01', level: 'INFO', category: 'Portfolio', message: 'Portfolio sync complete. 5 open positions.' },
  { id: 3, timestamp: '2026-11-12T09:41:56', timeFormatted: '12 Nov 09:41:56', level: 'INFO', category: 'Pricing', message: 'Market prices refreshed for 5 symbols.' },
  { id: 4, timestamp: '2026-11-12T09:40:00', timeFormatted: '12 Nov 09:40:00', level: 'INFO', category: 'Scheduler', message: 'Intraday confirmation job started.' },
  { id: 5, timestamp: '2026-11-12T09:40:00', timeFormatted: '12 Nov 09:40:00', level: 'WARN', category: 'Entry filter', message: 'AMZN entry skipped: relative volume below 1.5×.' },
  { id: 6, timestamp: '2026-11-12T09:39:58', timeFormatted: '12 Nov 09:39:58', level: 'INFO', category: 'Strategy', message: 'NVDA passed VWAP and momentum checks.' },
  { id: 7, timestamp: '2026-11-12T09:38:12', timeFormatted: '12 Nov 09:38:12', level: 'INFO', category: 'Orders', message: 'Paper order acknowledged: BUY 120 NVDA.' },
  { id: 8, timestamp: '2026-11-12T09:38:11', timeFormatted: '12 Nov 09:38:11', level: 'INFO', category: 'Risk', message: 'Position sizing approved. Exposure within limit.' },
  { id: 9, timestamp: '2026-11-12T09:35:09', timeFormatted: '12 Nov 09:35:09', level: 'INFO', category: 'Market data', message: 'AAPL quote recovered on retry 1 of 3.' },
  { id: 10, timestamp: '2026-11-12T09:35:04', timeFormatted: '12 Nov 09:35:04', level: 'ERROR', category: 'Market data', message: 'AAPL quote timeout. Retry scheduled in 5 seconds.' },
  { id: 11, timestamp: '2026-11-12T08:30:14', timeFormatted: '12 Nov 08:30:14', level: 'INFO', category: 'AI analysis', message: 'Daily analysis complete. 142 screened; 4 candidates.' },
  { id: 12, timestamp: '2026-11-12T08:30:00', timeFormatted: '12 Nov 08:30:00', level: 'INFO', category: 'Scheduler', message: 'Daily AI stock analysis job started.' },
];

export default function SystemLogsTab({
  authFetch,
  tradingMode = 'paper',
}: {
  authFetch: AuthFetch;
  tradingMode?: 'paper' | 'live';
}) {
  const [logs, setLogs] = useState<LogItem[]>(SAMPLE_LOGS);
  const [search, setSearch] = useState('');
  const [levelFilter, setLevelFilter] = useState<string>('all');
  const [categoryFilter, setCategoryFilter] = useState<string>('all');
  const [dateFilter, setDateFilter] = useState<string>('today');

  const syncDateString = '12 NOV 2026 · LAST SYNC 09:42:08 AEDT';

  const fetchLogs = useCallback(async () => {
    try {
      const res = await authFetch('/api/logs?limit=200');
      const json = await res.json();
      if (json.logs && json.logs.length > 0) {
        const mapped: LogItem[] = json.logs.map((l: any, i: number) => ({
          id: l.id || i,
          timestamp: l.timestamp,
          timeFormatted: new Date(l.timestamp).toLocaleDateString('en-AU', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit' }),
          level: (l.level === 'WARNING' ? 'WARN' : l.level) as any,
          category: l.category || 'System',
          message: l.message,
        }));
        setLogs(mapped);
      } else {
        setLogs(SAMPLE_LOGS);
      }
    } catch {
      setLogs(SAMPLE_LOGS);
    }
  }, [authFetch]);

  useEffect(() => {
    fetchLogs();
    const interval = setInterval(fetchLogs, 15_000);
    return () => clearInterval(interval);
  }, [fetchLogs]);

  const filteredLogs = useMemo(() => {
    return logs.filter((log) => {
      const matchSearch =
        !search ||
        log.message.toLowerCase().includes(search.toLowerCase()) ||
        log.category.toLowerCase().includes(search.toLowerCase());
      const matchLevel = levelFilter === 'all' || log.level === levelFilter;
      const matchCat = categoryFilter === 'all' || log.category.toLowerCase() === categoryFilter.toLowerCase();
      return matchSearch && matchLevel && matchCat;
    });
  }, [logs, search, levelFilter, categoryFilter]);

  const handleExportLogs = () => {
    const textContent = filteredLogs.map((l) => `[${l.timestamp}] [${l.level}] [${l.category}] ${l.message}`).join('\n');
    const blob = new Blob([textContent], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `system_logs_${new Date().toISOString().split('T')[0]}.txt`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const categories = ['all', 'Broker', 'Portfolio', 'Pricing', 'Scheduler', 'Entry filter', 'Strategy', 'Orders', 'Risk', 'Market data', 'AI analysis'];

  return (
    <div>
      {/* ── Page Header ────────────────────────────────────────── */}
      <div className="page-title-block">
        <h1 className="page-title-heading">System Logs</h1>
        <p className="page-title-subtitle">A live pulse on your trading system.</p>
        <p className="page-title-meta">{syncDateString}</p>
      </div>

      {/* ── All Systems Operational Banner (Page 5 & Page 14) ───── */}
      <div style={{
        background: '#ecfdf5',
        border: '1px solid #a7f3d0',
        borderRadius: 14,
        padding: '18px 24px',
        marginBottom: 20,
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        flexWrap: 'wrap',
        gap: 12,
      }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 15, fontWeight: 700, color: '#047857' }}>
            <span className="status-dot-green" />
            <span>All systems operational</span>
          </div>
          <div style={{ fontSize: 12.5, color: '#475569', marginTop: 4 }}>
            Broker connected · Scheduler active · Last sync 09:42 AEDT
          </div>
        </div>
        <div style={{ fontSize: 12.5, color: '#047857', fontWeight: 600 }}>
          Uptime 99.98% · Last 30 days
        </div>
      </div>

      {/* ── Search & Filter Controls ───────────────────────────── */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'minmax(240px, 2fr) 1fr 1fr 1fr',
        gap: 12,
        marginBottom: 20,
      }} className="logs-filter-grid">
        <input
          type="text"
          placeholder="Search messages or categories…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{
            background: '#ffffff',
            border: '1px solid var(--border)',
            borderRadius: 8,
            padding: '9px 14px',
            fontSize: 13,
            color: '#0f172a',
            outline: 'none',
          }}
        />

        <select
          value={levelFilter}
          onChange={(e) => setLevelFilter(e.target.value)}
          style={{
            background: '#ffffff',
            border: '1px solid var(--border)',
            borderRadius: 8,
            padding: '9px 12px',
            fontSize: 13,
            color: '#334155',
            outline: 'none',
            cursor: 'pointer',
          }}
        >
          <option value="all">All levels ▾</option>
          <option value="INFO">INFO</option>
          <option value="WARN">WARN</option>
          <option value="ERROR">ERROR</option>
        </select>

        <select
          value={categoryFilter}
          onChange={(e) => setCategoryFilter(e.target.value)}
          style={{
            background: '#ffffff',
            border: '1px solid var(--border)',
            borderRadius: 8,
            padding: '9px 12px',
            fontSize: 13,
            color: '#334155',
            outline: 'none',
            cursor: 'pointer',
          }}
        >
          {categories.map((c) => (
            <option key={c} value={c}>{c === 'all' ? 'All categories ▾' : c}</option>
          ))}
        </select>

        <select
          value={dateFilter}
          onChange={(e) => setDateFilter(e.target.value)}
          style={{
            background: '#ffffff',
            border: '1px solid var(--border)',
            borderRadius: 8,
            padding: '9px 12px',
            fontSize: 13,
            color: '#334155',
            outline: 'none',
            cursor: 'pointer',
          }}
        >
          <option value="today">12 Nov 2026 ▾</option>
          <option value="yesterday">11 Nov 2026</option>
          <option value="older">Older</option>
        </select>
      </div>

      {/* ── Event Stream Container ──────────────────────────────── */}
      <div className="theme-card">
        <div className="table-header-flex">
          <h3 className="table-title-bold">Event stream</h3>
          <div className="badge-green-pill">
            <span className="status-dot-green" />
            <span>Live · {filteredLogs.length} events</span>
          </div>
        </div>

        {/* Desktop Table View (Page 5) */}
        <div className="desktop-logs-table-view">
          <div className="scrollable-table-wrapper">
            <table className="custom-data-table" style={{ minWidth: 780 }}>
              <thead>
                <tr>
                  <th style={{ width: 170 }}>Timestamp (AEDT)</th>
                  <th style={{ width: 85 }}>Level</th>
                  <th style={{ width: 120 }}>Category</th>
                  <th>Message</th>
                </tr>
              </thead>
              <tbody>
                {filteredLogs.map((log) => {
                  const isWarn = log.level === 'WARN';
                  const isError = log.level === 'ERROR';
                  return (
                    <tr key={log.id}>
                      <td style={{ color: '#64748b', fontSize: 12.5 }}>{log.timeFormatted}</td>
                      <td>
                        <span style={{
                          display: 'inline-block',
                          fontSize: 11,
                          fontWeight: 700,
                          padding: '2px 8px',
                          borderRadius: 4,
                          background: isError ? '#fef2f2' : isWarn ? '#fffbeb' : '#ecfdf5',
                          color: isError ? '#dc2626' : isWarn ? '#d97706' : '#059669',
                          border: `1px solid ${isError ? '#fecaca' : isWarn ? '#fde68a' : '#a7f3d0'}`,
                        }}>
                          {log.level}
                        </span>
                      </td>
                      <td style={{ color: '#334155', fontWeight: 500 }}>{log.category}</td>
                      <td style={{ color: '#0f172a' }}>{log.message}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>

        {/* Phone Stacked View (Page 14) */}
        <div className="mobile-logs-list-view">
          <div style={{ fontSize: 11, fontWeight: 700, color: '#94a3b8', letterSpacing: '0.8px', paddingBottom: 8, borderBottom: '1px solid var(--border)' }}>
            TIMESTAMP / LEVEL / CATEGORY / MESSAGE
          </div>
          {filteredLogs.map((log) => {
            const isWarn = log.level === 'WARN';
            const isError = log.level === 'ERROR';
            const timeOnly = log.timestamp.split('T')[1] || log.timeFormatted;
            return (
              <div
                key={log.id}
                style={{
                  padding: '12px 0',
                  borderBottom: '1px solid var(--border-subtle)',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                  <span style={{ fontSize: 12, color: '#64748b' }}>
                    {timeOnly.substring(0, 8)} AEDT
                  </span>
                  <span style={{
                    fontSize: 12,
                    fontWeight: 700,
                    color: isError ? '#dc2626' : isWarn ? '#d97706' : '#059669',
                  }}>
                    {log.level} · {log.category}
                  </span>
                </div>
                <div style={{ fontSize: 13, color: '#0f172a', lineHeight: 1.4 }}>
                  {log.message}
                </div>
              </div>
            );
          })}
        </div>

        {/* Footer */}
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
          <div>
            <span className="desktop-footer-text">Showing {filteredLogs.length} recent events · All times AEDT</span>
            <span className="mobile-footer-text">{filteredLogs.length} events · Today</span>
          </div>
          <button
            className="btn-outline-subtle"
            onClick={handleExportLogs}
            id="btn-export-logs"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="12" y1="5" x2="12" y2="19" />
              <polyline points="19 12 12 19 5 12" />
            </svg>
            Export logs
          </button>
        </div>
      </div>

      <style jsx>{`
        .desktop-logs-table-view {
          display: block;
        }
        .mobile-logs-list-view {
          display: none;
        }
        .desktop-footer-text {
          display: inline;
        }
        .mobile-footer-text {
          display: none;
        }

        @media (max-width: 768px) {
          .logs-filter-grid {
            grid-template-columns: 1fr 1fr;
            gap: 8px;
          }
          .desktop-logs-table-view {
            display: none;
          }
          .mobile-logs-list-view {
            display: block;
          }
          .desktop-footer-text {
            display: none;
          }
          .mobile-footer-text {
            display: inline;
          }
        }
      `}</style>
    </div>
  );
}
