'use client';

import { useEffect, useState, useCallback, useRef } from 'react';

interface LogEntry {
  id: number;
  timestamp: string;
  level: 'INFO' | 'ERROR' | 'WARNING';
  category: string;
  message: string;
}

type CategoryFilter = 'all' | 'scan' | 'buy' | 'sell' | 'system' | 'ibkr';

function formatTimestamp(iso: string): string {
  return new Date(iso).toLocaleString('en-AU', {
    month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  });
}

export default function SystemLogsTab() {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [category, setCategory] = useState<CategoryFilter>('all');
  const [autoRefresh, setAutoRefresh] = useState(true);
  const bottomRef = useRef<HTMLDivElement>(null);

  const fetchLogs = useCallback(async () => {
    const params = new URLSearchParams({ limit: '200' });
    if (category !== 'all') params.set('category', category);
    try {
      const res = await fetch(`/api/logs?${params}`);
      const json = await res.json();
      setLogs(json.logs ?? []);
      setTotal(json.total ?? 0);
    } catch {
      setLogs([]);
    } finally {
      setLoading(false);
    }
  }, [category]);

  useEffect(() => {
    setLoading(true);
    fetchLogs();
  }, [fetchLogs]);

  // Auto-refresh every 10s
  useEffect(() => {
    if (!autoRefresh) return;
    const interval = setInterval(fetchLogs, 10_000);
    return () => clearInterval(interval);
  }, [fetchLogs, autoRefresh]);

  const categories: CategoryFilter[] = ['all', 'scan', 'buy', 'sell', 'system', 'ibkr'];

  return (
    <div>
      <div className="page-header">
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div>
            <h2>System Logs</h2>
            <p>{total.toLocaleString()} log entries — showing latest 200</p>
          </div>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: 'var(--text-secondary)', cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={autoRefresh}
                onChange={(e) => setAutoRefresh(e.target.checked)}
                id="auto-refresh-toggle"
              />
              Auto-refresh (10s)
            </label>
            <button
              id="btn-refresh-logs"
              className="btn btn-outline btn-icon"
              onClick={fetchLogs}
              title="Refresh now"
            >
              🔄
            </button>
          </div>
        </div>
      </div>

      {/* Category filters */}
      <div className="filter-bar" style={{ marginBottom: 20 }}>
        {categories.map((cat) => (
          <button
            key={cat}
            id={`log-filter-${cat}`}
            className={`filter-btn ${category === cat ? 'active' : ''}`}
            onClick={() => setCategory(cat)}
          >
            {cat === 'all' ? 'All' : (
              <span className={`log-category ${cat}`} style={{ padding: '1px 6px', borderRadius: 3 }}>
                {cat}
              </span>
            )}
          </button>
        ))}
      </div>

      <div className="table-container">
        {/* Column headers */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: '160px 60px 80px 1fr',
            gap: 12,
            padding: '10px 20px',
            borderBottom: '1px solid var(--border)',
            background: 'rgba(255,255,255,0.02)',
          }}
        >
          {['Timestamp', 'Level', 'Category', 'Message'].map((h) => (
            <div
              key={h}
              style={{
                fontSize: 10,
                fontWeight: 700,
                textTransform: 'uppercase',
                letterSpacing: '0.5px',
                color: 'var(--text-muted)',
              }}
            >
              {h}
            </div>
          ))}
        </div>

        {loading ? (
          <div className="empty-state">
            <div className="skeleton" style={{ width: '100%', height: 200 }} />
          </div>
        ) : logs.length === 0 ? (
          <div className="empty-state">
            <div className="icon">🖥️</div>
            <p>No logs yet</p>
            <p style={{ fontSize: 12 }}>System activity will appear here once the bot starts running.</p>
          </div>
        ) : (
          <div className="log-list" id="log-list">
            {logs.map((log) => (
              <div key={log.id} className="log-entry">
                <div className="log-time">{formatTimestamp(log.timestamp)}</div>
                <div className={`log-level ${log.level}`}>{log.level}</div>
                <div className={`log-category ${log.category.toLowerCase()}`}>
                  {log.category}
                </div>
                <div className="log-message">{log.message}</div>
              </div>
            ))}
            <div ref={bottomRef} />
          </div>
        )}
      </div>
    </div>
  );
}
