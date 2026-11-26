'use client';

import React, { useEffect, useState, useCallback } from 'react';

type AuthFetch = (url: string, options?: RequestInit) => Promise<Response>;

interface HealthCheckItem {
  check_name: string;
  status: 'ok' | 'warning' | 'critical' | 'unknown';
  summary: string;
  details: Record<string, unknown>;
  checked_at: string | null;
}

interface AlertItem {
  id: number;
  alert_key: string;
  severity: 'info' | 'warning' | 'critical';
  category: string;
  title: string;
  message: string;
  acknowledged: boolean;
  resolved: boolean;
  created_at: string | null;
}

interface HistoryItem {
  id: number;
  check_name: string;
  status: string;
  summary: string;
  checked_at: string | null;
}

interface DataHealthResponse {
  dq_critical_paused: boolean;
  dq_pause_reason: string | null;
  latest_checks: Record<string, HealthCheckItem>;
  api_stats: Record<
    string,
    {
      calls: number;
      errors: number;
      error_rate_pct: number;
      rate_limits: number;
      avg_latency_ms: number;
      last_error: string | null;
      last_call_at: string | null;
    }
  >;
  active_alerts: AlertItem[];
  history: HistoryItem[];
}

interface DeRiskStatusResponse {
  state: {
    level: number;
    label: string;
    size_multiplier: number;
    score_bump: number;
    entries_allowed: boolean;
    reason: string;
    escalated_at: string | null;
    deescalated_at: string | null;
    deescalated_by: string | null;
  };
  baseline: {
    source: string;
    date: string;
    has_backtest_file: boolean;
    max_drawdown_pct: number;
    hard_stop_drawdown_pct: number;
    longest_losing_streak_p90: number;
    win_rate_min_pct: number;
  };
  live_metrics: {
    drawdown_pct: number;
    losing_streak: number;
    total_closed_trades: number;
    min_sample_trades: number;
    sample_ready: boolean;
    rolling_win_rate_pct: number | null;
    rolling_avg_return_pct: number | null;
  };
}

interface ShadowRuleSummary {
  gate_name: string;
  total_decisions: number;
  open_count: number;
  resolved_count: number;
  would_have_blocked_count: number;
  blocked_stats: { resolved: number; avg_return_pct: number | null; win_rate_pct: number | null };
  allowed_stats: { resolved: number; avg_return_pct: number | null; win_rate_pct: number | null };
  evidence: { label: string; recommend_promotion: boolean; reason: string };
}

interface ShadowReportResponse {
  shadow_tracker?: {
    min_sample_size: number;
    rules: Record<string, ShadowRuleSummary>;
    near_misses: {
      total: number;
      open: number;
      resolved: number;
      avg_return_pct: number | null;
      win_rate_pct: number | null;
      label: string;
    };
  };
}

const CHECK_LABELS: Record<string, string> = {
  metric_coverage: 'Scoring Metric Coverage',
  score_distribution: 'Score Distribution',
  regime_inputs: 'Regime Inputs & Freshness',
  price_sanity: 'Price & Bar Sanity',
  api_health: 'API Health & Error Rates',
  cross_source_spot_check: 'Cross-Source Spot Check',
  position_reconciliation: 'Position & Stop Reconciliation',
};

function statusColor(status: string): string {
  if (status === 'ok') return '#10b981';
  if (status === 'warning') return '#f59e0b';
  if (status === 'critical') return '#ef4444';
  return '#6b7280';
}

function statusBg(status: string): string {
  if (status === 'ok') return 'rgba(16, 185, 129, 0.12)';
  if (status === 'warning') return 'rgba(245, 158, 11, 0.14)';
  if (status === 'critical') return 'rgba(239, 68, 68, 0.15)';
  return 'rgba(107, 114, 128, 0.12)';
}

export default function DataHealthTab({ authFetch }: { authFetch: AuthFetch }) {
  const [data, setData] = useState<DataHealthResponse | null>(null);
  const [derisk, setDerisk] = useState<DeRiskStatusResponse | null>(null);
  const [shadowReport, setShadowReport] = useState<ShadowReportResponse | null>(null);
  const [deescalateLoading, setDeescalateLoading] = useState(false);
  const [loading, setLoading] = useState(true);
  const [runningCheck, setRunningCheck] = useState(false);
  const [ackLoadingId, setAckLoadingId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadHealth = useCallback(async () => {
    try {
      const [res, drRes, shRes] = await Promise.all([
        authFetch('/api/monitoring/data-health'),
        authFetch('/api/risk/derisk-status'),
        authFetch('/api/performance/shadow-report'),
      ]);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json: DataHealthResponse = await res.json();
      setData(json);
      if (drRes.ok) {
        setDerisk(await drRes.json());
      }
      if (shRes.ok) {
        setShadowReport(await shRes.json());
      }
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load data health');
    } finally {
      setLoading(false);
    }
  }, [authFetch]);

  const handleDeescalate = async (targetLevel: number) => {
    setDeescalateLoading(true);
    try {
      const res = await authFetch('/api/risk/de-escalate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          target_level: targetLevel,
          reason: 'Manual confirmation via Data Health & Risk UI',
        }),
      });
      if (res.ok) {
        await loadHealth();
      }
    } finally {
      setDeescalateLoading(false);
    }
  };

  useEffect(() => {
    loadHealth();
    const interval = setInterval(loadHealth, 15000);
    return () => clearInterval(interval);
  }, [loadHealth]);

  const handleRunCheck = async () => {
    setRunningCheck(true);
    try {
      await authFetch('/api/monitoring/run-health-check', { method: 'POST' });
      setTimeout(loadHealth, 1500);
    } catch {
      // handled by next poll
    } finally {
      setRunningCheck(false);
    }
  };

  const handleAcknowledge = async (alertId: number) => {
    setAckLoadingId(alertId);
    try {
      const res = await authFetch(`/api/monitoring/alerts/${alertId}/acknowledge`, {
        method: 'POST',
      });
      if (res.ok) {
        await loadHealth();
      }
    } finally {
      setAckLoadingId(null);
    }
  };

  if (loading && !data) {
    return <div className="card" style={{ padding: 24 }}>Loading data-quality health monitor...</div>;
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      {/* Header & Actions */}
      <div
        className="card"
        style={{
          padding: '18px 22px',
          display: 'flex',
          flexWrap: 'wrap',
          justifyContent: 'space-between',
          alignItems: 'center',
          gap: 12,
        }}
      >
        <div>
          <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700 }}>
            Data-Quality Monitor &amp; Broker Reconciliation
          </h2>
          <p style={{ margin: '4px 0 0', fontSize: 13, opacity: 0.75 }}>
            Tracks metric coverage, regime validity, price sanity, API health, and IBKR stop-loss protection.
          </p>
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <button
            className="btn-secondary"
            onClick={loadHealth}
            style={{ padding: '8px 14px', borderRadius: 8, cursor: 'pointer' }}
          >
            Refresh
          </button>
          <button
            className="btn-primary"
            onClick={handleRunCheck}
            disabled={runningCheck}
            style={{ padding: '8px 16px', borderRadius: 8, cursor: 'pointer' }}
          >
            {runningCheck ? 'Running Check...' : 'Run Health & Stop Check'}
          </button>
        </div>
      </div>

      {error && (
        <div className="card" style={{ padding: 14, borderLeft: '4px solid #ef4444', color: '#ef4444' }}>
          Error loading data health: {error}
        </div>
      )}

      {/* Critical Pause Banner */}
      {data?.dq_critical_paused && (
        <div
          className="card"
          style={{
            padding: '16px 20px',
            border: '1px solid rgba(239, 68, 68, 0.5)',
            background: 'rgba(239, 68, 68, 0.1)',
          }}
        >
          <div style={{ fontWeight: 700, color: '#ef4444', fontSize: 15 }}>
            NEW ENTRIES PAUSED BY CRITICAL DATA-QUALITY ALERT
          </div>
          <div style={{ marginTop: 4, fontSize: 13 }}>
            Reason: <code>{data.dq_pause_reason}</code> — RiskEngine is blocking all new entries until resolved or acknowledged below.
          </div>
        </div>
      )}

      {/* De-Risking Ladder Status Card */}
      {derisk && (
        <div
          className="card"
          style={{
            padding: '18px 22px',
            borderLeft: `4px solid ${
              derisk.state.level === 0 ? '#10b981' : derisk.state.level === 1 ? '#f59e0b' : '#ef4444'
            }`,
            display: 'flex',
            flexWrap: 'wrap',
            justifyContent: 'space-between',
            alignItems: 'center',
            gap: 16,
          }}
        >
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>
                De-Risking Ladder: Level {derisk.state.level} ({derisk.state.label})
              </h3>
              <span style={{ fontSize: 12, opacity: 0.75 }}>
                Size: {derisk.state.size_multiplier}x | Score Bump: +{derisk.state.score_bump} | Entries:{' '}
                {derisk.state.entries_allowed ? 'Allowed' : 'Blocked'}
              </span>
            </div>
            <div style={{ marginTop: 6, fontSize: 13, opacity: 0.85 }}>
              Status: {derisk.state.reason}
            </div>
            <div style={{ marginTop: 4, fontSize: 12, opacity: 0.65 }}>
              Live DD: {derisk.live_metrics.drawdown_pct}% (Warn {derisk.baseline.max_drawdown_pct}% / Hard{' '}
              {derisk.baseline.hard_stop_drawdown_pct}%) | Losing Streak: {derisk.live_metrics.losing_streak}/
              {derisk.baseline.longest_losing_streak_p90} | Sample: {derisk.live_metrics.total_closed_trades}/
              {derisk.live_metrics.min_sample_trades} trades | Baseline: {derisk.baseline.source} ({derisk.baseline.date})
            </div>
          </div>
          {derisk.state.level > 0 && (
            <div style={{ display: 'flex', gap: 8 }}>
              <button
                className="btn-secondary"
                disabled={deescalateLoading}
                onClick={() => handleDeescalate(derisk.state.level - 1)}
                style={{ padding: '8px 14px', borderRadius: 8, cursor: 'pointer', fontWeight: 600 }}
              >
                {deescalateLoading ? 'Updating...' : `Confirm De-Escalate to Level ${derisk.state.level - 1}`}
              </button>
            </div>
          )}
        </div>
      )}

      {/* 7 Monitor Status Cards */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
          gap: 14,
        }}
      >
        {Object.entries(CHECK_LABELS).map(([key, label]) => {
          const item = data?.latest_checks?.[key];
          const st = item?.status ?? 'unknown';
          return (
            <div
              key={key}
              className="card"
              style={{
                padding: '16px 18px',
                borderTop: `3px solid ${statusColor(st)}`,
                display: 'flex',
                flexDirection: 'column',
                gap: 8,
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontWeight: 600, fontSize: 14 }}>{label}</span>
                <span
                  style={{
                    fontSize: 11,
                    fontWeight: 700,
                    textTransform: 'uppercase',
                    padding: '2px 8px',
                    borderRadius: 999,
                    color: statusColor(st),
                    background: statusBg(st),
                  }}
                >
                  {st}
                </span>
              </div>
              <div style={{ fontSize: 12.5, opacity: 0.85, lineHeight: 1.45 }}>
                {item?.summary || 'Not yet run.'}
              </div>
              <div style={{ fontSize: 11, opacity: 0.55, marginTop: 'auto' }}>
                {item?.checked_at ? `Last checked: ${new Date(item.checked_at).toLocaleString()}` : 'Never checked'}
              </div>
            </div>
          );
        })}
      </div>

      {/* Active Alerts */}
      <div className="card" style={{ padding: '18px 22px' }}>
        <h3 style={{ margin: '0 0 12px', fontSize: 16, fontWeight: 700 }}>
          Active Unacknowledged Alerts ({data?.active_alerts?.length ?? 0})
        </h3>
        {!data?.active_alerts?.length ? (
          <div style={{ fontSize: 13, opacity: 0.7 }}>No active unacknowledged alerts.</div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr style={{ textAlign: 'left', borderBottom: '1px solid rgba(255,255,255,0.1)' }}>
                  <th style={{ padding: '8px 6px' }}>Severity</th>
                  <th style={{ padding: '8px 6px' }}>Title</th>
                  <th style={{ padding: '8px 6px' }}>Message</th>
                  <th style={{ padding: '8px 6px' }}>Time</th>
                  <th style={{ padding: '8px 6px' }}>Action</th>
                </tr>
              </thead>
              <tbody>
                {data.active_alerts.map((a) => (
                  <tr key={a.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
                    <td style={{ padding: '10px 6px' }}>
                      <span
                        style={{
                          fontSize: 11,
                          fontWeight: 700,
                          textTransform: 'uppercase',
                          padding: '2px 8px',
                          borderRadius: 999,
                          color: statusColor(a.severity),
                          background: statusBg(a.severity),
                        }}
                      >
                        {a.severity}
                      </span>
                    </td>
                    <td style={{ padding: '10px 6px', fontWeight: 600 }}>{a.title}</td>
                    <td style={{ padding: '10px 6px', opacity: 0.85 }}>{a.message}</td>
                    <td style={{ padding: '10px 6px', opacity: 0.65, whiteSpace: 'nowrap' }}>
                      {a.created_at ? new Date(a.created_at).toLocaleString() : '-'}
                    </td>
                    <td style={{ padding: '10px 6px' }}>
                      <button
                        className="btn-secondary"
                        onClick={() => handleAcknowledge(a.id)}
                        disabled={ackLoadingId === a.id}
                        style={{ padding: '4px 10px', fontSize: 12, borderRadius: 6, cursor: 'pointer' }}
                      >
                        {ackLoadingId === a.id ? '...' : 'Acknowledge'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* API Health Stats */}
      {data?.api_stats && Object.keys(data.api_stats).length > 0 && (
        <div className="card" style={{ padding: '18px 22px' }}>
          <h3 style={{ margin: '0 0 12px', fontSize: 16, fontWeight: 700 }}>API Telemetry (Since Restart)</h3>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16 }}>
            {Object.entries(data.api_stats).map(([provider, st]) => (
              <div
                key={provider}
                style={{
                  padding: '12px 16px',
                  borderRadius: 8,
                  background: 'rgba(255,255,255,0.04)',
                  minWidth: 220,
                }}
              >
                <div style={{ fontWeight: 700, textTransform: 'uppercase', fontSize: 13 }}>{provider}</div>
                <div style={{ fontSize: 12.5, marginTop: 6, opacity: 0.85 }}>
                  Calls: {st.calls} | Errors: {st.errors} ({st.error_rate_pct}%)
                </div>
                <div style={{ fontSize: 12.5, opacity: 0.85 }}>
                  Rate Limits: {st.rate_limits} | Avg Latency: {st.avg_latency_ms}ms
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Shadow-Mode & Near-Miss Tracking */}
      {shadowReport?.shadow_tracker && (
        <div className="card" style={{ padding: '18px 22px' }}>
          <h3 style={{ margin: '0 0 8px', fontSize: 16, fontWeight: 700 }}>
            Shadow-Mode &amp; Near-Miss Tracking (Observational Only)
          </h3>
          <div style={{ fontSize: 12.5, opacity: 0.75, marginBottom: 12 }}>
            Hypothetical forward outcomes using live ATR exit rules. Minimum sample size for evidence evaluation:{' '}
            {shadowReport.shadow_tracker.min_sample_size} resolved decisions.
          </div>
          {Object.keys(shadowReport.shadow_tracker.rules).length === 0 ? (
            <div style={{ fontSize: 13, opacity: 0.7 }}>No shadow-mode gate evaluations recorded yet.</div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5 }}>
                <thead>
                  <tr style={{ textAlign: 'left', borderBottom: '1px solid rgba(255,255,255,0.1)' }}>
                    <th style={{ padding: '8px 6px' }}>Gate</th>
                    <th style={{ padding: '8px 6px' }}>Decisions (Open/Resolved)</th>
                    <th style={{ padding: '8px 6px' }}>Would-Block Avg / WR</th>
                    <th style={{ padding: '8px 6px' }}>Allowed Avg / WR</th>
                    <th style={{ padding: '8px 6px' }}>Evidence</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.values(shadowReport.shadow_tracker.rules).map((r) => (
                    <tr key={r.gate_name} style={{ borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
                      <td style={{ padding: '8px 6px', fontWeight: 600 }}>{r.gate_name}</td>
                      <td style={{ padding: '8px 6px' }}>
                        {r.total_decisions} ({r.open_count} open / {r.resolved_count} resolved)
                      </td>
                      <td style={{ padding: '8px 6px' }}>
                        {r.blocked_stats.resolved > 0
                          ? `${r.blocked_stats.avg_return_pct}% / ${r.blocked_stats.win_rate_pct}% (n=${r.blocked_stats.resolved})`
                          : `n=${r.blocked_stats.resolved}`}
                      </td>
                      <td style={{ padding: '8px 6px' }}>
                        {r.allowed_stats.resolved > 0
                          ? `${r.allowed_stats.avg_return_pct}% / ${r.allowed_stats.win_rate_pct}% (n=${r.allowed_stats.resolved})`
                          : `n=${r.allowed_stats.resolved}`}
                      </td>
                      <td style={{ padding: '8px 6px' }}>
                        <span style={{ fontWeight: 700, textTransform: 'uppercase' }}>{r.evidence.label}</span>
                        <div style={{ fontSize: 11, opacity: 0.7 }}>{r.evidence.reason}</div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div style={{ marginTop: 12, fontSize: 12.5, opacity: 0.85 }}>
            <strong>{shadowReport.shadow_tracker.near_misses.label}:</strong> Total{' '}
            {shadowReport.shadow_tracker.near_misses.total} ({shadowReport.shadow_tracker.near_misses.open} open,{' '}
            {shadowReport.shadow_tracker.near_misses.resolved} resolved
            {shadowReport.shadow_tracker.near_misses.resolved > 0
              ? `, avg ${shadowReport.shadow_tracker.near_misses.avg_return_pct}%, WR ${shadowReport.shadow_tracker.near_misses.win_rate_pct}%`
              : ''}
            )
          </div>
        </div>
      )}

      {/* Recent Check History */}
      <div className="card" style={{ padding: '18px 22px' }}>
        <h3 style={{ margin: '0 0 12px', fontSize: 16, fontWeight: 700 }}>Recent Check History</h3>
        {!data?.history?.length ? (
          <div style={{ fontSize: 13, opacity: 0.7 }}>No check history recorded yet.</div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5 }}>
              <thead>
                <tr style={{ textAlign: 'left', borderBottom: '1px solid rgba(255,255,255,0.1)' }}>
                  <th style={{ padding: '8px 6px' }}>Check</th>
                  <th style={{ padding: '8px 6px' }}>Status</th>
                  <th style={{ padding: '8px 6px' }}>Summary</th>
                  <th style={{ padding: '8px 6px' }}>Time</th>
                </tr>
              </thead>
              <tbody>
                {data.history.map((h) => (
                  <tr key={h.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
                    <td style={{ padding: '8px 6px', fontWeight: 600 }}>
                      {CHECK_LABELS[h.check_name] || h.check_name}
                    </td>
                    <td style={{ padding: '8px 6px', color: statusColor(h.status), fontWeight: 700, textTransform: 'uppercase' }}>
                      {h.status}
                    </td>
                    <td style={{ padding: '8px 6px', opacity: 0.85 }}>{h.summary}</td>
                    <td style={{ padding: '8px 6px', opacity: 0.65, whiteSpace: 'nowrap' }}>
                      {h.checked_at ? new Date(h.checked_at).toLocaleString() : '-'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
