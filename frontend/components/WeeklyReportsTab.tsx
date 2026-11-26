'use client';

import React, { useEffect, useState, useCallback } from 'react';

type AuthFetch = (url: string, options?: RequestInit) => Promise<Response>;

interface BucketStat {
  sample_size: number;
  status: string;
  win_rate_pct: number | null;
  avg_return_pct: number | null;
  avg_alpha_pct: number | null;
}

interface WeeklyReportItem {
  id: number;
  period_start: string;
  period_end: string;
  total_trades: number;
  strategy_return_pct: number;
  spy_return_pct: number;
  alpha_pct: number;
  derisk_level: number;
  summary_text: string;
  created_at: string | null;
  report: {
    period_returns?: {
      sample_size: number;
      strategy_return_pct: number;
      spy_return_pct: number;
      alpha_pct: number;
      avg_beta: number;
      win_rate_pct: number | null;
      drawdown_pct: number;
      derisk_level: number;
      derisk_label: string;
    };
    trades?: Array<{
      id: number;
      ticker: string;
      entry_reason: string | null;
      exit_reason: string | null;
      holding_days: number | null;
      r_multiple: number | null;
      return_pct: number;
      spy_return_pct: number | null;
      alpha_pct: number | null;
    }>;
    breakdowns?: {
      min_bucket_trades: number;
      by_market_tier?: Record<string, BucketStat>;
      by_sector?: Record<string, BucketStat>;
      by_score_bucket?: Record<string, BucketStat>;
      by_ai_confidence_bucket?: Record<string, BucketStat>;
      by_entry_time?: Record<string, BucketStat>;
      by_intraday_confirmation?: Record<string, BucketStat>;
    };
    scan_statistics?: {
      total_scans: number;
      regime_distribution: Record<string, number>;
      no_trade_days_count: number;
      no_trade_reasons: Record<string, number>;
      ai_approval_rate_pct: number | null;
    };
    baseline_comparison?: {
      baseline_source: string;
      sample_size: number;
      return_within_expected_range: boolean;
      win_rate_status: string;
      expected_weekly_return_range_pct: [number, number];
      expected_win_rate_range_pct: [number, number];
    };
    data_quality_summary?: {
      total_checks: number;
      status_counts: Record<string, number>;
      total_alerts: number;
      alert_severity_counts: Record<string, number>;
    };
    what_to_look_at?: string[];
  };
}

export default function WeeklyReportsTab({ authFetch }: { authFetch: AuthFetch }) {
  const [reports, setReports] = useState<WeeklyReportItem[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);

  const loadReports = useCallback(async () => {
    try {
      const res = await authFetch('/api/monitoring/weekly-reports');
      if (res.ok) {
        const json = await res.json();
        const list: WeeklyReportItem[] = json.reports || [];
        setReports(list);
        if (list.length > 0 && selectedId === null) {
          setSelectedId(list[0].id);
        }
      }
    } finally {
      setLoading(false);
    }
  }, [authFetch, selectedId]);

  useEffect(() => {
    loadReports();
  }, [loadReports]);

  const handleGenerate = async () => {
    setGenerating(true);
    try {
      const res = await authFetch('/api/monitoring/weekly-reports/generate', { method: 'POST' });
      if (res.ok) {
        const json = await res.json();
        await loadReports();
        if (json?.report?.id) {
          setSelectedId(json.report.id);
        }
      }
    } finally {
      setGenerating(false);
    }
  };

  const selected = reports.find((r) => r.id === selectedId) || reports[0] || null;

  if (loading && reports.length === 0) {
    return <div className="card" style={{ padding: 24 }}>Loading weekly performance reports...</div>;
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
      {/* Header */}
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
            Weekly Performance Reports (Observational Only)
          </h2>
          <p style={{ margin: '4px 0 0', fontSize: 13, opacity: 0.75 }}>
            Scheduled Saturday 09:00 ET. Every statistic reports sample size (n); buckets below minimum show &ldquo;insufficient data&rdquo;.
          </p>
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          {reports.length > 0 && (
            <select
              value={selected?.id ?? ''}
              onChange={(e) => setSelectedId(Number(e.target.value))}
              style={{ padding: '8px 12px', borderRadius: 8 }}
            >
              {reports.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.period_start} to {r.period_end} (n={r.total_trades})
                </option>
              ))}
            </select>
          )}
          <button
            className="btn-primary"
            onClick={handleGenerate}
            disabled={generating}
            style={{ padding: '8px 16px', borderRadius: 8, cursor: 'pointer' }}
          >
            {generating ? 'Generating...' : 'Generate Report Now'}
          </button>
        </div>
      </div>

      {!selected ? (
        <div className="card" style={{ padding: 24, opacity: 0.75 }}>
          No weekly reports generated yet. Click &ldquo;Generate Report Now&rdquo; to create the first report.
        </div>
      ) : (
        <>
          {/* Period Return Summary */}
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(210px, 1fr))',
              gap: 12,
            }}
          >
            <div className="card" style={{ padding: 16 }}>
              <div style={{ fontSize: 12, opacity: 0.7 }}>Strategy Return (n={selected.total_trades})</div>
              <div style={{ fontSize: 22, fontWeight: 700, marginTop: 4 }}>
                {selected.strategy_return_pct >= 0 ? '+' : ''}
                {selected.strategy_return_pct}%
              </div>
            </div>
            <div className="card" style={{ padding: 16 }}>
              <div style={{ fontSize: 12, opacity: 0.7 }}>SPY Return</div>
              <div style={{ fontSize: 22, fontWeight: 700, marginTop: 4 }}>
                {selected.spy_return_pct >= 0 ? '+' : ''}
                {selected.spy_return_pct}%
              </div>
            </div>
            <div className="card" style={{ padding: 16 }}>
              <div style={{ fontSize: 12, opacity: 0.7 }}>Net Alpha (n={selected.total_trades})</div>
              <div style={{ fontSize: 22, fontWeight: 700, marginTop: 4 }}>
                {selected.alpha_pct >= 0 ? '+' : ''}
                {selected.alpha_pct}%
              </div>
            </div>
            <div className="card" style={{ padding: 16 }}>
              <div style={{ fontSize: 12, opacity: 0.7 }}>Drawdown / De-Risk</div>
              <div style={{ fontSize: 18, fontWeight: 700, marginTop: 6 }}>
                {selected.report.period_returns?.drawdown_pct ?? 0}% | L{selected.derisk_level}
              </div>
            </div>
          </div>

          {/* What to Look At */}
          {selected.report.what_to_look_at && (
            <div className="card" style={{ padding: '16px 20px' }}>
              <h3 style={{ margin: '0 0 8px', fontSize: 15, fontWeight: 700 }}>What to Look At</h3>
              <ul style={{ margin: 0, paddingLeft: 20, fontSize: 13, lineHeight: 1.6 }}>
                {selected.report.what_to_look_at.map((line, i) => (
                  <li key={i}>{line}</li>
                ))}
              </ul>
            </div>
          )}

          {/* Breakdowns */}
          {selected.report.breakdowns && (
            <div className="card" style={{ padding: '18px 22px' }}>
              <h3 style={{ margin: '0 0 12px', fontSize: 15, fontWeight: 700 }}>
                Breakdowns (Min Sample: {selected.report.breakdowns.min_bucket_trades} trades)
              </h3>
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
                  gap: 14,
                }}
              >
                {(
                  [
                    ['By Market Tier', selected.report.breakdowns.by_market_tier],
                    ['By Sector', selected.report.breakdowns.by_sector],
                    ['By Score Bucket', selected.report.breakdowns.by_score_bucket],
                    ['By AI Confidence', selected.report.breakdowns.by_ai_confidence_bucket],
                    ['By Entry Time (ET)', selected.report.breakdowns.by_entry_time],
                    ['By Intraday Confirmation', selected.report.breakdowns.by_intraday_confirmation],
                  ] as Array<[string, Record<string, BucketStat> | undefined]>
                ).map(([title, buckets]) => (
                  <div
                    key={title}
                    style={{ padding: 12, borderRadius: 8, background: 'rgba(255,255,255,0.03)' }}
                  >
                    <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 8 }}>{title}</div>
                    {!buckets || Object.keys(buckets).length === 0 ? (
                      <div style={{ fontSize: 12, opacity: 0.65 }}>No trades (n=0)</div>
                    ) : (
                      Object.entries(buckets).map(([k, b]) => (
                        <div key={k} style={{ fontSize: 12, marginBottom: 4 }}>
                          <strong>{k}</strong> (n={b.sample_size}):{' '}
                          {b.status === 'insufficient data'
                            ? `insufficient data (${b.avg_return_pct ?? 0}% avg)`
                            : `${b.win_rate_pct}% WR, ${b.avg_return_pct}% avg`}
                        </div>
                      ))
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Scan & Data Quality Summary */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 14 }}>
            {selected.report.scan_statistics && (
              <div className="card" style={{ padding: 18 }}>
                <h3 style={{ margin: '0 0 8px', fontSize: 15, fontWeight: 700 }}>Scan Statistics</h3>
                <div style={{ fontSize: 13, lineHeight: 1.6 }}>
                  <div>Total Scans: {selected.report.scan_statistics.total_scans}</div>
                  <div>No-Trade Days: {selected.report.scan_statistics.no_trade_days_count}</div>
                  <div>
                    AI Approval Rate:{' '}
                    {selected.report.scan_statistics.ai_approval_rate_pct !== null
                      ? `${selected.report.scan_statistics.ai_approval_rate_pct}%`
                      : 'N/A'}
                  </div>
                </div>
              </div>
            )}
            {selected.report.data_quality_summary && (
              <div className="card" style={{ padding: 18 }}>
                <h3 style={{ margin: '0 0 8px', fontSize: 15, fontWeight: 700 }}>Data Quality &amp; Alerts</h3>
                <div style={{ fontSize: 13, lineHeight: 1.6 }}>
                  <div>Total Health Checks: {selected.report.data_quality_summary.total_checks}</div>
                  <div>Total Alerts: {selected.report.data_quality_summary.total_alerts}</div>
                  <div>
                    Baseline: {selected.report.baseline_comparison?.baseline_source} (
                    {selected.report.baseline_comparison?.win_rate_status})
                  </div>
                </div>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
