'use client';

import { useEffect, useState, useCallback } from 'react';

interface AIPick {
  rank: number;
  ticker: string;
  reason: string;
  confidence: number;
  position_size_pct: number;
  created_at: string | null;
}

interface AIPicksData {
  scan_date: string | null;
  total: number;
  picks: AIPick[];
}

type AuthFetch = (url: string, init?: RequestInit) => Promise<Response>;

function ConfidenceBadge({ confidence }: { confidence: number }) {
  const pct = Math.round(confidence * 100);
  let bg = 'rgba(59,130,246,0.15)';
  let color = '#3b82f6';
  let border = 'rgba(59,130,246,0.3)';
  if (pct >= 80) { bg = 'rgba(34,197,94,0.15)'; color = '#22c55e'; border = 'rgba(34,197,94,0.3)'; }
  else if (pct >= 65) { bg = 'rgba(34,197,94,0.1)'; color = '#86efac'; border = 'rgba(34,197,94,0.2)'; }
  else if (pct < 55) { bg = 'rgba(234,179,8,0.12)'; color = '#eab308'; border = 'rgba(234,179,8,0.25)'; }

  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4,
      padding: '3px 10px', borderRadius: 20,
      fontSize: 11, fontWeight: 700, letterSpacing: '0.3px',
      background: bg, color, border: `1px solid ${border}`,
      fontFamily: "'JetBrains Mono', monospace",
    }}>
      {pct}%
    </span>
  );
}

function PositionSizePill({ pct }: { pct: number }) {
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center',
      padding: '2px 10px', borderRadius: 20,
      fontSize: 11, fontWeight: 600,
      background: 'rgba(168,85,247,0.12)',
      color: '#a855f7',
      border: '1px solid rgba(168,85,247,0.25)',
      fontFamily: "'JetBrains Mono', monospace",
    }}>
      {pct.toFixed(0)}% capital
    </span>
  );
}

function RankBadge({ rank }: { rank: number }) {
  const colors: Record<number, { bg: string; color: string }> = {
    1: { bg: 'rgba(234,179,8,0.2)',  color: '#eab308' },
    2: { bg: 'rgba(148,163,184,0.15)', color: '#94a3b8' },
    3: { bg: 'rgba(180,83,9,0.18)',  color: '#f97316' },
  };
  const style = colors[rank] || { bg: 'rgba(255,255,255,0.05)', color: '#475569' };
  return (
    <div style={{
      width: 28, height: 28,
      borderRadius: '50%',
      background: style.bg,
      color: style.color,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontSize: 12, fontWeight: 800,
      flexShrink: 0,
      fontFamily: "'JetBrains Mono', monospace",
    }}>
      {rank}
    </div>
  );
}

function formatScanDate(dateStr: string | null): string {
  if (!dateStr) return '—';
  const d = new Date(dateStr + 'T00:00:00');
  return d.toLocaleDateString('en-AU', {
    weekday: 'long', year: 'numeric', month: 'long', day: 'numeric',
  });
}

export default function AIPicksTab({ authFetch }: { authFetch: AuthFetch }) {
  const [data, setData] = useState<AIPicksData | null>(null);
  const [loading, setLoading] = useState(true);
  const [expandedRank, setExpandedRank] = useState<number | null>(null);
  const [lastRefreshed, setLastRefreshed] = useState<Date | null>(null);

  const fetchPicks = useCallback(async () => {
    try {
      const res = await authFetch('/api/ai-picks');
      const json: AIPicksData = await res.json();
      setData(json);
      setLastRefreshed(new Date());
    } catch {
      /* silently fail */
    } finally {
      setLoading(false);
    }
  }, [authFetch]);

  useEffect(() => {
    fetchPicks();
  }, [fetchPicks]);

  const totalAlloc = data?.picks.reduce((s, p) => s + p.position_size_pct, 0) ?? 0;

  return (
    <div>
      {/* ── Header ───────────────────────────────────────────────── */}
      <div className="page-header">
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div>
            <h2>AI Picks</h2>
            <p>
              This week&apos;s Gemini-ranked stock recommendations
              {lastRefreshed && ` · Refreshed ${lastRefreshed.toLocaleTimeString()}`}
            </p>
          </div>
          <button
            className="btn btn-outline btn-icon"
            onClick={fetchPicks}
            title="Refresh picks"
            id="btn-refresh-picks"
          >
            🔄
          </button>
        </div>
      </div>

      {/* ── Scan date banner ─────────────────────────────────────── */}
      {data?.scan_date && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 12,
          padding: '12px 20px', borderRadius: 12, marginBottom: 24,
          background: 'linear-gradient(135deg, rgba(59,130,246,0.12) 0%, rgba(99,102,241,0.06) 100%)',
          border: '1px solid rgba(59,130,246,0.22)',
        }}>
          <span style={{ fontSize: 18 }}>🤖</span>
          <div>
            <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--accent-blue)', marginBottom: 1 }}>
              Latest Scan — {formatScanDate(data.scan_date)}
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
              {data.total} stock{data.total !== 1 ? 's' : ''} selected ·{' '}
              Total allocation: {totalAlloc.toFixed(0)}%
            </div>
          </div>
        </div>
      )}

      {/* ── Loading / Empty states ───────────────────────────────── */}
      {loading && (
        <div className="table-container">
          <div className="empty-state">
            <div className="skeleton" style={{ width: '100%', height: 200, borderRadius: 8 }} />
          </div>
        </div>
      )}

      {!loading && (!data || data.picks.length === 0) && (
        <div className="table-container">
          <div className="empty-state">
            <div className="icon">🔍</div>
            <p>No AI picks yet</p>
            <p style={{ fontSize: 12 }}>
              Picks will appear here after the next scan. You can trigger a manual scan in Settings.
            </p>
          </div>
        </div>
      )}

      {/* ── Picks list ───────────────────────────────────────────── */}
      {!loading && data && data.picks.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {data.picks.map((pick) => {
            const isExpanded = expandedRank === pick.rank;
            const confPct = Math.round(pick.confidence * 100);

            // Bar width for the confidence visualiser
            const barColor =
              confPct >= 80 ? '#22c55e'
              : confPct >= 65 ? '#86efac'
              : confPct >= 55 ? '#3b82f6'
              : '#eab308';

            return (
              <div
                key={pick.rank}
                style={{
                  background: 'var(--bg-card)',
                  border: '1px solid var(--border)',
                  borderRadius: 14,
                  overflow: 'hidden',
                  transition: 'border-color 0.15s, box-shadow 0.15s',
                  boxShadow: isExpanded ? '0 4px 24px rgba(0,0,0,0.2)' : 'none',
                  borderColor: isExpanded ? 'var(--border-bright)' : 'var(--border)',
                }}
              >
                {/* ── Pick header row ─────────────────────────── */}
                <div
                  onClick={() => setExpandedRank(isExpanded ? null : pick.rank)}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 16,
                    padding: '18px 20px',
                    cursor: 'pointer',
                    userSelect: 'none',
                  }}
                >
                  <RankBadge rank={pick.rank} />

                  <div style={{ fontWeight: 800, fontSize: 17, color: 'var(--text-primary)', letterSpacing: '0.5px', minWidth: 60 }}>
                    {pick.ticker}
                  </div>

                  {/* Confidence bar */}
                  <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 4 }}>
                    <div style={{ height: 5, background: 'rgba(255,255,255,0.06)', borderRadius: 3, overflow: 'hidden' }}>
                      <div style={{
                        height: '100%',
                        width: `${confPct}%`,
                        background: barColor,
                        borderRadius: 3,
                        transition: 'width 0.4s ease',
                        boxShadow: `0 0 6px ${barColor}80`,
                      }} />
                    </div>
                    <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>
                      {pick.reason.split('.')[0].slice(0, 80)}{pick.reason.length > 80 ? '…' : ''}
                    </div>
                  </div>

                  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 6, flexShrink: 0 }}>
                    <ConfidenceBadge confidence={pick.confidence} />
                    <PositionSizePill pct={pick.position_size_pct} />
                  </div>

                  <div style={{
                    color: 'var(--text-muted)', fontSize: 14,
                    transition: 'transform 0.2s', transform: isExpanded ? 'rotate(180deg)' : 'rotate(0deg)',
                    flexShrink: 0, marginLeft: 4,
                  }}>
                    ▾
                  </div>
                </div>

                {/* ── Expanded rationale ──────────────────────── */}
                {isExpanded && (
                  <div style={{
                    borderTop: '1px solid var(--border)',
                    padding: '18px 20px',
                    background: 'rgba(59,130,246,0.03)',
                  }}>
                    <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--accent-blue)', marginBottom: 10, letterSpacing: '0.5px', textTransform: 'uppercase' }}>
                      AI Rationale
                    </div>
                    <div style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.7 }}>
                      {pick.reason}
                    </div>
                    <div style={{ display: 'flex', gap: 16, marginTop: 14, flexWrap: 'wrap' }}>
                      <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                        <span style={{ color: 'var(--text-secondary)', fontWeight: 500 }}>Confidence: </span>
                        <span style={{ fontFamily: "'JetBrains Mono', monospace", color: barColor, fontWeight: 700 }}>
                          {confPct}%
                        </span>
                      </div>
                      <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                        <span style={{ color: 'var(--text-secondary)', fontWeight: 500 }}>Suggested Allocation: </span>
                        <span style={{ fontFamily: "'JetBrains Mono', monospace", color: '#a855f7', fontWeight: 700 }}>
                          {pick.position_size_pct.toFixed(0)}% of capital
                        </span>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* ── Info footer ─────────────────────────────────────────── */}
      {!loading && data && data.picks.length > 0 && (
        <div style={{ marginTop: 20, padding: '12px 16px', borderRadius: 10, background: 'rgba(255,255,255,0.02)', border: '1px solid var(--border)', fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.6 }}>
          <strong style={{ color: 'var(--text-secondary)' }}>How picks are generated: </strong>
          The AI scans the full NASDAQ universe every Monday morning, screens the top 75 momentum candidates,
          and uses Gemini to rank them by expected weekly performance. Stocks with earnings this week,
          average volume under 50k, or a 5-day gain over 20% are automatically excluded.
          Confidence scores reflect multi-factor analysis of technicals, news catalysts, and sector trends.
        </div>
      )}
    </div>
  );
}
