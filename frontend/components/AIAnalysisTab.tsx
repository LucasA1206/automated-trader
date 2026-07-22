'use client';

import { useEffect, useState, useCallback } from 'react';

// ─── Types ────────────────────────────────────────────────────────────────────

interface TechnicalIndicators {
  rsi_14?: number | null;
  macd_histogram?: number | null;
  adx_14?: number | null;
  bb_pct_b?: number | null;
  bb_band_width?: number | null;
}

interface Candidate {
  ticker: string;
  ai_status: 'approved' | 'rejected' | 'not_sent_to_ai';
  composite_score?: number | null;
  classification?: string | null;
  price?: number | null;
  sector?: string | null;
  market_cap?: number | null;
  atr_pct?: number | null;
  rel_vol?: number | null;
  rs_63d?: number | null;
  rs_126d?: number | null;
  high_52w_pct?: number | null;
  short_interest_pct_float?: number | null;
  technical_indicators?: TechnicalIndicators;
  component_scores?: Record<string, number>;
  sub_scores?: Record<string, number>;
  data_gaps?: string[];
  penalties?: Record<string, number>;
  proceed?: boolean | null;
  conviction?: number | null;
  entry_notes?: string;
  key_risk?: string;
  final_decision?: string;
  models_agree?: boolean | null;
  gemini_raw?: Record<string, unknown> | null;
  crosscheck_raw?: Record<string, unknown> | null;
  confidence?: number | null;
  position_size_pct?: number | null;
  rank?: number | null;
}

interface DayAnalysis {
  scan_date: string | null;
  regime_status?: string | null;
  regime_details?: string | null;
  action_taken?: string | null;
  candidates_count: number;
  high_conviction_count: number;
  marginal_count: number;
  approved_count: number;
  rejected_count: number;
  not_sent_count: number;
  candidates: Candidate[];
  created_at?: string | null;
}

interface AIAnalysisData {
  days: DayAnalysis[];
  total_days: number;
}

type AuthFetch = (url: string, init?: RequestInit) => Promise<Response>;

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatDate(dateStr: string | null): string {
  if (!dateStr) return '—';
  const d = new Date(dateStr + 'T00:00:00');
  return d.toLocaleDateString('en-AU', {
    weekday: 'long', year: 'numeric', month: 'long', day: 'numeric',
  });
}

function isToday(dateStr: string | null): boolean {
  if (!dateStr) return false;
  const today = new Date();
  const d = new Date(dateStr + 'T00:00:00');
  return d.getFullYear() === today.getFullYear() &&
    d.getMonth() === today.getMonth() &&
    d.getDate() === today.getDate();
}

function fmt(val: number | null | undefined, decimals = 1, suffix = ''): string {
  if (val == null) return '—';
  return val.toFixed(decimals) + suffix;
}

function fmtMktCap(val: number | null | undefined): string {
  if (val == null) return '—';
  if (val >= 1e9) return `$${(val / 1e9).toFixed(1)}B`;
  if (val >= 1e6) return `$${(val / 1e6).toFixed(0)}M`;
  return `$${val.toFixed(0)}`;
}

function scoreColor(score: number | null | undefined): string {
  if (score == null) return '#475569';
  if (score >= 70) return '#22c55e';
  if (score >= 55) return '#3b82f6';
  if (score >= 40) return '#eab308';
  return '#ef4444';
}

function regimeColor(regime: string | null | undefined): { bg: string; color: string; border: string } {
  switch (regime) {
    case 'risk_on':    return { bg: 'rgba(34,197,94,0.12)',  color: '#22c55e', border: 'rgba(34,197,94,0.3)' };
    case 'caution':    return { bg: 'rgba(234,179,8,0.12)',  color: '#eab308', border: 'rgba(234,179,8,0.3)' };
    case 'risk_off':   return { bg: 'rgba(239,68,68,0.12)', color: '#ef4444', border: 'rgba(239,68,68,0.3)' };
    default:           return { bg: 'rgba(100,116,139,0.12)', color: '#94a3b8', border: 'rgba(100,116,139,0.3)' };
  }
}

function actionLabel(action: string | null | undefined): string {
  switch (action) {
    case 'trade':            return 'Trades Placed';
    case 'no_trade':         return 'No Trade';
    case 'regime_off':       return 'Regime Off';
    case 'risk_blocked':     return 'Risk Blocked';
    case 'ai_rejected':      return 'AI Rejected All';
    default:                 return action ?? '—';
  }
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: Candidate['ai_status'] }) {
  const styles: Record<Candidate['ai_status'], { bg: string; color: string; border: string; icon: string; label: string }> = {
    approved:       { bg: 'rgba(34,197,94,0.15)',  color: '#22c55e', border: 'rgba(34,197,94,0.3)',  icon: '✅', label: 'Approved' },
    rejected:       { bg: 'rgba(239,68,68,0.12)',  color: '#ef4444', border: 'rgba(239,68,68,0.25)', icon: '❌', label: 'Rejected' },
    not_sent_to_ai: { bg: 'rgba(100,116,139,0.1)', color: '#64748b', border: 'rgba(100,116,139,0.2)', icon: '⏭', label: 'Not Sent' },
  };
  const s = styles[status];
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4,
      padding: '3px 10px', borderRadius: 20,
      fontSize: 11, fontWeight: 700, letterSpacing: '0.3px',
      background: s.bg, color: s.color, border: `1px solid ${s.border}`,
    }}>
      {s.icon} {s.label}
    </span>
  );
}

function ScoreBadge({ score }: { score: number | null | undefined }) {
  const color = scoreColor(score);
  return (
    <div style={{
      display: 'flex', flexDirection: 'column', alignItems: 'center',
      minWidth: 52,
    }}>
      <div style={{
        width: 44, height: 44, borderRadius: '50%',
        background: `conic-gradient(${color} ${(score ?? 0) * 3.6}deg, rgba(255,255,255,0.06) 0)`,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        position: 'relative',
      }}>
        <div style={{
          width: 34, height: 34, borderRadius: '50%',
          background: 'var(--bg-card)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 11, fontWeight: 800, color,
          fontFamily: "'JetBrains Mono', monospace",
        }}>
          {score != null ? Math.round(score) : '—'}
        </div>
      </div>
      <div style={{ fontSize: 9, color: 'var(--text-muted)', marginTop: 2, fontWeight: 600 }}>SCORE</div>
    </div>
  );
}

function MetricPill({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div style={{
      display: 'flex', flexDirection: 'column', gap: 1,
      padding: '5px 10px', borderRadius: 8,
      background: highlight ? 'rgba(59,130,246,0.08)' : 'rgba(255,255,255,0.03)',
      border: `1px solid ${highlight ? 'rgba(59,130,246,0.2)' : 'var(--border)'}`,
      minWidth: 70,
    }}>
      <div style={{ fontSize: 9, color: 'var(--text-muted)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.5px' }}>
        {label}
      </div>
      <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-primary)', fontFamily: "'JetBrains Mono', monospace" }}>
        {value}
      </div>
    </div>
  );
}

function ComponentScoreBar({ name, value, maxVal }: { name: string; value: number; maxVal: number }) {
  const pct = maxVal > 0 ? Math.min(100, (value / maxVal) * 100) : 0;
  const color = value >= maxVal * 0.6 ? '#22c55e' : value >= maxVal * 0.3 ? '#3b82f6' : '#ef4444';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
      <div style={{ fontSize: 10, color: 'var(--text-muted)', width: 90, flexShrink: 0, fontFamily: "'JetBrains Mono', monospace" }}>
        {name.replace(/_/g, '_')}
      </div>
      <div style={{ flex: 1, height: 5, background: 'rgba(255,255,255,0.06)', borderRadius: 3, overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 3, transition: 'width 0.4s' }} />
      </div>
      <div style={{ fontSize: 10, color, fontWeight: 700, width: 30, textAlign: 'right', fontFamily: "'JetBrains Mono', monospace" }}>
        {value.toFixed(1)}
      </div>
    </div>
  );
}

function CandidateCard({ candidate, dayDate }: { candidate: Candidate; dayDate: string | null }) {
  const [expanded, setExpanded] = useState(false);
  const [tab, setTab] = useState<'ai' | 'metrics' | 'scores'>('ai');

  const ti = candidate.technical_indicators ?? {};
  const compScores = candidate.component_scores ?? {};
  const maxCompVal = Math.max(...Object.values(compScores), 1);
  const confPct = candidate.confidence != null ? Math.round(candidate.confidence * 100) : null;
  const convPct = candidate.conviction;

  const borderAccent =
    candidate.ai_status === 'approved' ? 'rgba(34,197,94,0.35)' :
    candidate.ai_status === 'rejected' ? 'rgba(239,68,68,0.25)' :
    'var(--border)';

  return (
    <div style={{
      background: 'var(--bg-card)',
      border: `1px solid ${expanded ? borderAccent : 'var(--border)'}`,
      borderRadius: 14,
      overflow: 'hidden',
      transition: 'border-color 0.2s, box-shadow 0.2s',
      boxShadow: expanded ? '0 4px 24px rgba(0,0,0,0.22)' : 'none',
    }}>
      {/* ── Header row ─────────────────────────────────────────────────── */}
      <div
        onClick={() => setExpanded(e => !e)}
        style={{
          display: 'flex', alignItems: 'center', gap: 14,
          padding: '14px 18px', cursor: 'pointer', userSelect: 'none',
        }}
      >
        <ScoreBadge score={candidate.composite_score} />

        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 4 }}>
            <span style={{ fontWeight: 800, fontSize: 16, color: 'var(--text-primary)', letterSpacing: '0.5px' }}>
              {candidate.ticker}
            </span>
            <StatusBadge status={candidate.ai_status} />
            {candidate.sector && (
              <span style={{
                fontSize: 10, padding: '2px 8px', borderRadius: 10,
                background: 'rgba(168,85,247,0.1)', color: '#a855f7',
                border: '1px solid rgba(168,85,247,0.2)', fontWeight: 600,
              }}>
                {candidate.sector}
              </span>
            )}
            {candidate.rank != null && candidate.ai_status === 'approved' && (
              <span style={{
                fontSize: 10, padding: '2px 8px', borderRadius: 10,
                background: 'rgba(234,179,8,0.15)', color: '#eab308',
                border: '1px solid rgba(234,179,8,0.3)', fontWeight: 700,
                fontFamily: "'JetBrains Mono', monospace",
              }}>
                Rank #{candidate.rank}
              </span>
            )}
          </div>

          {/* Quick metrics row */}
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', fontSize: 11, color: 'var(--text-muted)' }}>
            {candidate.price != null && (
              <span>Price: <b style={{ color: 'var(--text-secondary)' }}>${fmt(candidate.price, 2)}</b></span>
            )}
            {candidate.rel_vol != null && (
              <span>Rel Vol: <b style={{ color: candidate.rel_vol >= 1.5 ? '#22c55e' : 'var(--text-secondary)' }}>{fmt(candidate.rel_vol, 2)}×</b></span>
            )}
            {ti.rsi_14 != null && (
              <span>RSI: <b style={{ color: ti.rsi_14 > 70 ? '#ef4444' : ti.rsi_14 < 30 ? '#22c55e' : 'var(--text-secondary)' }}>{fmt(ti.rsi_14, 1)}</b></span>
            )}
            {candidate.rs_63d != null && (
              <span>RS 3M: <b style={{ color: 'var(--text-secondary)' }}>{fmt(candidate.rs_63d, 2)}</b></span>
            )}
            {confPct != null && (
              <span>Confidence: <b style={{ color: confPct >= 70 ? '#22c55e' : '#3b82f6' }}>{confPct}%</b></span>
            )}
            {convPct != null && (
              <span>Conviction: <b style={{ color: convPct >= 70 ? '#22c55e' : convPct >= 55 ? '#3b82f6' : '#eab308' }}>{convPct}%</b></span>
            )}
          </div>
        </div>

        <div style={{ color: 'var(--text-muted)', fontSize: 14, transition: 'transform 0.2s', transform: expanded ? 'rotate(180deg)' : 'none', flexShrink: 0 }}>
          ▾
        </div>
      </div>

      {/* ── Expanded detail panel ───────────────────────────────────────── */}
      {expanded && (
        <div style={{ borderTop: '1px solid var(--border)' }}>
          {/* Tab selector */}
          <div style={{
            display: 'flex', gap: 0, borderBottom: '1px solid var(--border)',
            background: 'rgba(0,0,0,0.15)',
          }}>
            {(['ai', 'metrics', 'scores'] as const).map(t => (
              <button
                key={t}
                onClick={() => setTab(t)}
                style={{
                  padding: '9px 18px', fontSize: 11, fontWeight: 700, cursor: 'pointer',
                  background: 'none', border: 'none', letterSpacing: '0.5px',
                  color: tab === t ? 'var(--accent-blue)' : 'var(--text-muted)',
                  borderBottom: tab === t ? '2px solid var(--accent-blue)' : '2px solid transparent',
                  textTransform: 'uppercase', transition: 'color 0.15s',
                }}
              >
                {t === 'ai' ? '🤖 AI Verdict' : t === 'metrics' ? '📈 Metrics' : '📊 Scores'}
              </button>
            ))}
          </div>

          <div style={{ padding: '18px 20px', background: 'rgba(0,0,0,0.08)' }}>

            {/* ── AI Verdict Tab ── */}
            {tab === 'ai' && (
              <div>
                {candidate.ai_status === 'not_sent_to_ai' ? (
                  <div style={{ color: 'var(--text-muted)', fontSize: 13, lineHeight: 1.7 }}>
                    <span style={{ fontSize: 16 }}>⏭</span>{' '}
                    This stock scored below the threshold to be sent to the AI for analysis.
                    Only the top 10 high-conviction and 5 marginal candidates are forwarded.
                  </div>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                    {/* Decision banner */}
                    <div style={{
                      display: 'flex', alignItems: 'center', gap: 12,
                      padding: '12px 16px', borderRadius: 10,
                      background: candidate.ai_status === 'approved'
                        ? 'rgba(34,197,94,0.08)' : 'rgba(239,68,68,0.08)',
                      border: `1px solid ${candidate.ai_status === 'approved' ? 'rgba(34,197,94,0.25)' : 'rgba(239,68,68,0.25)'}`,
                    }}>
                      <div style={{ fontSize: 22 }}>{candidate.ai_status === 'approved' ? '✅' : '❌'}</div>
                      <div>
                        <div style={{
                          fontSize: 12, fontWeight: 800,
                          color: candidate.ai_status === 'approved' ? '#22c55e' : '#ef4444',
                          marginBottom: 2,
                        }}>
                          {candidate.ai_status === 'approved' ? 'AI APPROVED' : 'AI REJECTED'}
                          {candidate.final_decision && (
                            <span style={{
                              marginLeft: 8, fontSize: 10, fontWeight: 600,
                              color: 'var(--text-muted)', fontFamily: "'JetBrains Mono', monospace",
                            }}>
                              ({candidate.final_decision})
                            </span>
                          )}
                        </div>
                        {candidate.models_agree != null && (
                          <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                            Models {candidate.models_agree ? '🤝 agreed' : '⚔️ disagreed'}
                          </div>
                        )}
                      </div>
                      {convPct != null && (
                        <div style={{ marginLeft: 'auto', textAlign: 'center' }}>
                          <div style={{
                            fontSize: 18, fontWeight: 800, fontFamily: "'JetBrains Mono', monospace",
                            color: convPct >= 70 ? '#22c55e' : convPct >= 55 ? '#3b82f6' : '#eab308',
                          }}>
                            {convPct}%
                          </div>
                          <div style={{ fontSize: 9, color: 'var(--text-muted)', fontWeight: 600 }}>CONVICTION</div>
                        </div>
                      )}
                    </div>

                    {/* Entry notes */}
                    {candidate.entry_notes && (
                      <div>
                        <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--accent-blue)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                          AI Rationale
                        </div>
                        <div style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.75, padding: '10px 14px', borderRadius: 8, background: 'rgba(59,130,246,0.04)', border: '1px solid rgba(59,130,246,0.1)' }}>
                          {candidate.entry_notes}
                        </div>
                      </div>
                    )}

                    {/* Key risk */}
                    {candidate.key_risk && (
                      <div>
                        <div style={{ fontSize: 10, fontWeight: 700, color: '#eab308', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                          Key Risk
                        </div>
                        <div style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.75, padding: '10px 14px', borderRadius: 8, background: 'rgba(234,179,8,0.04)', border: '1px solid rgba(234,179,8,0.12)' }}>
                          {candidate.key_risk}
                        </div>
                      </div>
                    )}

                    {/* Approved details */}
                    {candidate.ai_status === 'approved' && (
                      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
                        {confPct != null && (
                          <div style={{ padding: '8px 14px', borderRadius: 8, background: 'rgba(34,197,94,0.08)', border: '1px solid rgba(34,197,94,0.2)' }}>
                            <div style={{ fontSize: 9, color: 'var(--text-muted)', fontWeight: 600, marginBottom: 2, textTransform: 'uppercase' }}>Confidence</div>
                            <div style={{ fontSize: 16, fontWeight: 800, color: '#22c55e', fontFamily: "'JetBrains Mono', monospace" }}>{confPct}%</div>
                          </div>
                        )}
                        {candidate.position_size_pct != null && (
                          <div style={{ padding: '8px 14px', borderRadius: 8, background: 'rgba(168,85,247,0.08)', border: '1px solid rgba(168,85,247,0.2)' }}>
                            <div style={{ fontSize: 9, color: 'var(--text-muted)', fontWeight: 600, marginBottom: 2, textTransform: 'uppercase' }}>Allocation</div>
                            <div style={{ fontSize: 16, fontWeight: 800, color: '#a855f7', fontFamily: "'JetBrains Mono', monospace" }}>{candidate.position_size_pct.toFixed(0)}%</div>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}

            {/* ── Metrics Tab ── */}
            {tab === 'metrics' && (
              <div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 16 }}>
                  <MetricPill label="Price" value={candidate.price != null ? `$${fmt(candidate.price, 2)}` : '—'} />
                  <MetricPill label="Mkt Cap" value={fmtMktCap(candidate.market_cap)} />
                  <MetricPill label="Rel Vol" value={fmt(candidate.rel_vol, 2) + '×'} highlight={(candidate.rel_vol ?? 0) >= 1.5} />
                  <MetricPill label="ATR %" value={fmt(candidate.atr_pct, 2) + '%'} />
                  <MetricPill label="52W Hi %" value={fmt(candidate.high_52w_pct, 1) + '%'} />
                  <MetricPill label="Short %" value={candidate.short_interest_pct_float != null ? fmt(candidate.short_interest_pct_float, 1) + '%' : '—'} />
                  <MetricPill label="RS 3M" value={fmt(candidate.rs_63d, 3)} highlight={(candidate.rs_63d ?? 0) > 1} />
                  <MetricPill label="RS 6M" value={fmt(candidate.rs_126d, 3)} highlight={(candidate.rs_126d ?? 0) > 1} />
                </div>

                <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                  Technical Indicators
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 16 }}>
                  <MetricPill label="RSI 14" value={fmt(ti.rsi_14, 1)} highlight={ti.rsi_14 != null && ti.rsi_14 > 50 && ti.rsi_14 < 70} />
                  <MetricPill label="MACD Hist" value={fmt(ti.macd_histogram, 4)} highlight={(ti.macd_histogram ?? 0) > 0} />
                  <MetricPill label="ADX 14" value={fmt(ti.adx_14, 1)} highlight={(ti.adx_14 ?? 0) >= 25} />
                  <MetricPill label="BB %B" value={fmt(ti.bb_pct_b, 3)} />
                  <MetricPill label="BB Width" value={fmt(ti.bb_band_width, 4)} />
                </div>

                {(candidate.data_gaps?.length ?? 0) > 0 && (
                  <div style={{
                    padding: '8px 12px', borderRadius: 8, fontSize: 11,
                    background: 'rgba(234,179,8,0.06)', border: '1px solid rgba(234,179,8,0.15)',
                    color: '#eab308',
                  }}>
                    <strong>⚠ Data gaps:</strong> {candidate.data_gaps!.join(', ')} — excluded from scoring
                  </div>
                )}

                {Object.keys(candidate.penalties ?? {}).length > 0 && (
                  <div style={{ marginTop: 10 }}>
                    <div style={{ fontSize: 10, fontWeight: 700, color: '#ef4444', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                      Penalties Applied
                    </div>
                    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                      {Object.entries(candidate.penalties!).map(([k, v]) => (
                        <span key={k} style={{
                          padding: '3px 10px', borderRadius: 10, fontSize: 11, fontWeight: 600,
                          background: 'rgba(239,68,68,0.08)', color: '#ef4444',
                          border: '1px solid rgba(239,68,68,0.2)',
                          fontFamily: "'JetBrains Mono', monospace",
                        }}>
                          {k}: -{v.toFixed(2)}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* ── Scores Tab ── */}
            {tab === 'scores' && (
              <div>
                <div style={{ marginBottom: 12 }}>
                  <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                    Component Scores (weighted contribution)
                  </div>
                  {Object.entries(compScores)
                    .sort(([, a], [, b]) => b - a)
                    .map(([name, val]) => (
                      <ComponentScoreBar key={name} name={name} value={val} maxVal={maxCompVal} />
                    ))}
                  {Object.keys(compScores).length === 0 && (
                    <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>No component score data available.</div>
                  )}
                </div>

                <div style={{
                  display: 'flex', alignItems: 'center', gap: 12,
                  padding: '10px 14px', borderRadius: 8, marginTop: 10,
                  background: 'rgba(255,255,255,0.03)', border: '1px solid var(--border)',
                }}>
                  <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                    Final Composite Score:
                  </div>
                  <div style={{
                    fontSize: 20, fontWeight: 800, fontFamily: "'JetBrains Mono', monospace",
                    color: scoreColor(candidate.composite_score),
                  }}>
                    {candidate.composite_score != null ? candidate.composite_score.toFixed(1) : '—'} / 100
                  </div>
                  {candidate.classification && (
                    <span style={{
                      padding: '2px 8px', borderRadius: 8, fontSize: 10, fontWeight: 700,
                      background: candidate.classification === 'high_conviction' ? 'rgba(34,197,94,0.12)' : 'rgba(59,130,246,0.12)',
                      color: candidate.classification === 'high_conviction' ? '#22c55e' : '#3b82f6',
                      border: `1px solid ${candidate.classification === 'high_conviction' ? 'rgba(34,197,94,0.3)' : 'rgba(59,130,246,0.3)'}`,
                    }}>
                      {candidate.classification.replace('_', ' ')}
                    </span>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Main Component ───────────────────────────────────────────────────────────

export default function AIAnalysisTab({ authFetch }: { authFetch: AuthFetch }) {
  const [data, setData] = useState<AIAnalysisData | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastRefreshed, setLastRefreshed] = useState<Date | null>(null);
  const [filterStatus, setFilterStatus] = useState<'all' | 'approved' | 'rejected' | 'not_sent_to_ai'>('all');
  const [expandedDays, setExpandedDays] = useState<Set<string>>(new Set());
  const [runningBuyRound, setRunningBuyRound] = useState(false);
  const [buyRoundMsg, setBuyRoundMsg] = useState('');

  const triggerBuyRound = async () => {
    setRunningBuyRound(true);
    setBuyRoundMsg('');
    try {
      const res = await authFetch('/api/entry-monitor?force=true', { method: 'POST' });
      const data = await res.json();
      if (res.ok) {
        setBuyRoundMsg(`⚡ ${data.message || 'Buy round completed.'} (${data.placed || 0} placed)`);
      } else {
        setBuyRoundMsg(`❌ ${data.detail || 'Buy round failed'}`);
      }
    } catch {
      setBuyRoundMsg('❌ Network error');
    } finally {
      setRunningBuyRound(false);
      setTimeout(() => setBuyRoundMsg(''), 6000);
    }
  };

  const fetchData = useCallback(async () => {
    try {
      const res = await authFetch('/api/ai-analysis');
      const json: AIAnalysisData = await res.json();
      setData(json);
      setLastRefreshed(new Date());
      // Auto-expand the most recent day
      if (json.days.length > 0 && json.days[0].scan_date) {
        setExpandedDays(new Set([json.days[0].scan_date]));
      }
    } catch {
      /* silently fail */
    } finally {
      setLoading(false);
    }
  }, [authFetch]);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 30_000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const toggleDay = (dateStr: string | null) => {
    if (!dateStr) return;
    setExpandedDays(prev => {
      const next = new Set(prev);
      if (next.has(dateStr)) next.delete(dateStr);
      else next.add(dateStr);
      return next;
    });
  };

  const hasDays = (data?.days?.length ?? 0) > 0;

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto' }}>
      {/* ── Header ─────────────────────────────────────────────────────── */}
      <div className="page-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 16 }}>
        <div>
          <h2>AI Stock Analysis</h2>
          <p>
            Complete historical log of daily stock screening and AI verdicts
            {lastRefreshed && ` · Refreshed ${lastRefreshed.toLocaleTimeString()}`}
          </p>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button
            className="btn btn-primary"
            onClick={triggerBuyRound}
            disabled={runningBuyRound}
            style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 16px', fontSize: 13 }}
          >
            {runningBuyRound ? '⏳ Running...' : '⚡ Run Buy Round'}
          </button>
          <button
            className="btn btn-outline btn-icon"
            onClick={fetchData}
            title="Refresh"
            id="btn-refresh-analysis"
          >
            🔄
          </button>
        </div>
      </div>

      {buyRoundMsg && (
        <div style={{
          padding: '10px 16px', borderRadius: 8, marginBottom: 16, fontSize: 13, fontWeight: 600,
          background: 'var(--bg-card)', border: '1px solid var(--border-bright)', color: 'var(--text-primary)'
        }}>
          {buyRoundMsg}
        </div>
      )}

      {/* ── Filter pills ───────────────────────────────────────────────── */}
      {!loading && hasDays && (
        <div style={{ display: 'flex', gap: 8, marginBottom: 24, flexWrap: 'wrap' }}>
          {(['all', 'approved', 'rejected', 'not_sent_to_ai'] as const).map(f => (
            <button
              key={f}
              onClick={() => setFilterStatus(f)}
              style={{
                padding: '5px 14px', borderRadius: 20, fontSize: 11, fontWeight: 700,
                cursor: 'pointer', border: '1px solid',
                transition: 'all 0.15s',
                background: filterStatus === f
                  ? f === 'approved' ? 'rgba(34,197,94,0.2)'
                    : f === 'rejected' ? 'rgba(239,68,68,0.2)'
                    : f === 'not_sent_to_ai' ? 'rgba(100,116,139,0.15)'
                    : 'rgba(59,130,246,0.2)'
                  : 'rgba(255,255,255,0.03)',
                borderColor: filterStatus === f
                  ? f === 'approved' ? 'rgba(34,197,94,0.5)'
                    : f === 'rejected' ? 'rgba(239,68,68,0.4)'
                    : f === 'not_sent_to_ai' ? 'rgba(100,116,139,0.4)'
                    : 'rgba(59,130,246,0.5)'
                  : 'var(--border)',
                color: filterStatus === f
                  ? f === 'approved' ? '#22c55e'
                    : f === 'rejected' ? '#ef4444'
                    : f === 'not_sent_to_ai' ? '#64748b'
                    : 'var(--accent-blue)'
                  : 'var(--text-muted)',
              }}
            >
              {f === 'all' ? '📋 All' : f === 'approved' ? '✅ Approved' : f === 'rejected' ? '❌ Rejected' : '⏭ Not Sent'}
            </button>
          ))}
        </div>
      )}

      {/* ── Loading ─────────────────────────────────────────────────────── */}
      {loading && (
        <div className="table-container">
          <div className="empty-state">
            <div className="skeleton" style={{ width: '100%', height: 200, borderRadius: 8 }} />
          </div>
        </div>
      )}

      {/* ── Empty ───────────────────────────────────────────────────────── */}
      {!loading && !hasDays && (
        <div className="table-container">
          <div className="empty-state">
            <div className="icon">🔍</div>
            <p>No AI analysis data yet</p>
            <p style={{ fontSize: 12 }}>
              Analysis records will appear here after the next scan run. You can trigger a manual scan in Settings.
            </p>
          </div>
        </div>
      )}

      {/* ── Days ────────────────────────────────────────────────────────── */}
      {!loading && hasDays && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          {data!.days.map(day => {
            const dateStr = day.scan_date;
            const isOpen = dateStr ? expandedDays.has(dateStr) : false;
            const rc = regimeColor(day.regime_status);

            const filteredCandidates = day.candidates.filter(c =>
              filterStatus === 'all' || c.ai_status === filterStatus
            );

            return (
              <div key={dateStr ?? 'unknown'} style={{
                borderRadius: 16,
                border: '1px solid var(--border)',
                overflow: 'hidden',
                background: 'var(--bg-card)',
              }}>
                {/* ── Day header ────────────────────────────────────────── */}
                <div
                  onClick={() => toggleDay(dateStr)}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 12,
                    padding: '16px 20px', cursor: 'pointer', userSelect: 'none',
                    background: isOpen ? 'rgba(59,130,246,0.04)' : 'none',
                    borderBottom: isOpen ? '1px solid var(--border)' : 'none',
                    transition: 'background 0.2s',
                  }}
                >
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 6 }}>
                      <div style={{ fontWeight: 800, fontSize: 14, color: 'var(--text-primary)' }}>
                        📅 {formatDate(dateStr)}
                      </div>
                      {isToday(dateStr) && (
                        <span style={{
                          fontSize: 10, fontWeight: 700,
                          background: 'rgba(34,197,94,0.15)', color: '#22c55e',
                          border: '1px solid rgba(34,197,94,0.3)', borderRadius: 6, padding: '1px 6px',
                        }}>TODAY</span>
                      )}
                      {/* Regime badge */}
                      {day.regime_status && (
                        <span style={{
                          fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 10,
                          background: rc.bg, color: rc.color, border: `1px solid ${rc.border}`,
                        }}>
                          {day.regime_status.replace('_', ' ').toUpperCase()}
                        </span>
                      )}
                      {/* Action badge */}
                      {day.action_taken && (
                        <span style={{
                          fontSize: 10, fontWeight: 600, padding: '2px 8px', borderRadius: 10,
                          background: 'rgba(255,255,255,0.05)', color: 'var(--text-muted)',
                          border: '1px solid var(--border)',
                        }}>
                          {actionLabel(day.action_taken)}
                        </span>
                      )}
                    </div>

                    {/* Stats row */}
                    <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', fontSize: 11, color: 'var(--text-muted)' }}>
                      <span>{day.candidates.length} stocks analyzed</span>
                      <span style={{ color: '#22c55e' }}>✅ {day.approved_count} approved</span>
                      <span style={{ color: '#ef4444' }}>❌ {day.rejected_count} rejected</span>
                      {day.not_sent_count > 0 && (
                        <span style={{ color: '#64748b' }}>⏭ {day.not_sent_count} not sent to AI</span>
                      )}
                      <span style={{ color: '#3b82f6' }}>HC: {day.high_conviction_count} · Mgn: {day.marginal_count}</span>
                    </div>
                  </div>

                  <div style={{
                    color: 'var(--text-muted)', fontSize: 16,
                    transition: 'transform 0.25s', transform: isOpen ? 'rotate(180deg)' : 'none',
                    flexShrink: 0,
                  }}>
                    ▾
                  </div>
                </div>

                {/* ── Candidate list ────────────────────────────────────── */}
                {isOpen && (
                  <div style={{ padding: '16px 16px' }}>
                    {/* Regime details */}
                    {day.regime_details && (
                      <div style={{
                        padding: '10px 14px', borderRadius: 10, marginBottom: 14, fontSize: 12,
                        background: `${rc.bg}`, border: `1px solid ${rc.border}`, color: rc.color,
                        lineHeight: 1.6,
                      }}>
                        <strong>Market Regime:</strong> {day.regime_details}
                      </div>
                    )}

                    {filteredCandidates.length === 0 ? (
                      <div style={{ textAlign: 'center', padding: '24px 0', color: 'var(--text-muted)', fontSize: 13 }}>
                        No candidates match the current filter.
                      </div>
                    ) : (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                        {filteredCandidates.map(c => (
                          <CandidateCard key={c.ticker} candidate={c} dayDate={dateStr} />
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* ── Info footer ─────────────────────────────────────────────────── */}
      {!loading && hasDays && (
        <div style={{
          marginTop: 20, padding: '12px 16px', borderRadius: 10,
          background: 'rgba(255,255,255,0.02)', border: '1px solid var(--border)',
          fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.6,
        }}>
          <strong style={{ color: 'var(--text-secondary)' }}>How AI Analysis works: </strong>
          Each morning the system screens the NASDAQ universe and scores the top candidates.
          The top 10 high-conviction and 5 marginal stocks are forwarded to Gemini (and a cross-check model)
          for qualitative analysis. Both models must agree to approve a trade — disagreement means rejection.
          All decisions and rationales are stored here for review.
        </div>
      )}
    </div>
  );
}
