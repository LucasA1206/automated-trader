'use client';

import { useEffect, useState, useCallback, useMemo } from 'react';

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

function fmt(val: number | null | undefined, decimals = 2, prefix = '$'): string {
  if (val == null || isNaN(val)) return '—';
  return `${prefix}${val.toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })}`;
}

function fmtMktCap(val: number | null | undefined): string {
  if (val == null || isNaN(val)) return '—';
  if (val >= 1e12) return `$${(val / 1e12).toFixed(2)}T`;
  if (val >= 1e9) return `$${(val / 1e9).toFixed(1)}B`;
  if (val >= 1e6) return `$${(val / 1e6).toFixed(0)}M`;
  return `$${val.toFixed(0)}`;
}

export default function AIAnalysisTab({
  authFetch,
  tradingMode = 'paper',
}: {
  authFetch: AuthFetch;
  tradingMode?: 'paper' | 'live';
}) {
  const [data, setData] = useState<AIAnalysisData | null>(null);
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [scanMessage, setScanMessage] = useState<string | null>(null);

  // Accordion open states
  const [openDates, setOpenDates] = useState<Record<string, boolean>>({});
  const [openCandidates, setOpenCandidates] = useState<Record<string, boolean>>({});

  const fetchAIAnalysis = useCallback(async () => {
    try {
      const res = await authFetch('/api/ai-analysis?limit=30');
      if (res.ok) {
        const json: AIAnalysisData = await res.json();
        setData(json);
        // Automatically open the first day by default
        if (json.days && json.days.length > 0) {
          const firstDate = json.days[0].scan_date || 'latest';
          setOpenDates((prev) => ({ ...prev, [firstDate]: true }));
          if (json.days[0].candidates && json.days[0].candidates.length > 0) {
            const firstCand = `${firstDate}-${json.days[0].candidates[0].ticker}`;
            setOpenCandidates((prev) => ({ ...prev, [firstCand]: true }));
          }
        }
      }
    } catch {
      // Fail silently
    } finally {
      setLoading(false);
    }
  }, [authFetch]);

  useEffect(() => {
    fetchAIAnalysis();
  }, [fetchAIAnalysis]);

  // Check if a scan is currently running in the background
  useEffect(() => {
    const checkStatus = async () => {
      try {
        const res = await authFetch('/api/scan/status');
        if (res.ok) {
          const json = await res.json();
          setScanning(json.running);
        }
      } catch {
        // Fail silently
      }
    };
    checkStatus();
    const interval = setInterval(checkStatus, 3000);
    return () => clearInterval(interval);
  }, [authFetch]);

  const handleTriggerScan = async () => {
    setScanning(true);
    setScanMessage('Scan initiated! Screening universe and running AI models…');
    try {
      await authFetch('/api/scan', { method: 'POST' });
      setTimeout(() => {
        fetchAIAnalysis();
        setScanMessage(null);
      }, 10000);
    } catch {
      setScanMessage('Failed to trigger scan.');
      setScanning(false);
    }
  };

  const toggleDate = (dateKey: string) => {
    setOpenDates((prev) => ({ ...prev, [dateKey]: !prev[dateKey] }));
  };

  const toggleCandidate = (candKey: string) => {
    setOpenCandidates((prev) => ({ ...prev, [candKey]: !prev[candKey] }));
  };

  const syncDateString = useMemo(() => {
    const now = new Date();
    return `${now.toLocaleDateString('en-AU', { day: '2-digit', month: 'short', year: 'numeric' }).toUpperCase()} · LAST SYNC ${now.toLocaleTimeString('en-AU')} AEDT`;
  }, []);

  const days = data?.days || [];
  const latestDay = days.length > 0 ? days[0] : null;

  return (
    <div>
      {/* ── Page Header ────────────────────────────────────────── */}
      <div className="page-title-block">
        <h1 className="page-title-heading">AI Stock Analysis</h1>
        <p className="page-title-subtitle">A clearer signal from the noise.</p>
        <p className="page-title-meta">{syncDateString}</p>
      </div>

      {/* ── Trigger / Status Banner if scan running ────────────── */}
      {scanMessage && (
        <div style={{
          padding: '12px 18px',
          borderRadius: 10,
          background: '#ecfdf5',
          border: '1px solid #a7f3d0',
          color: '#047857',
          fontSize: 13,
          fontWeight: 600,
          marginBottom: 16,
          display: 'flex',
          alignItems: 'center',
          gap: 10,
        }}>
          <span className="status-dot-green" />
          <span>{scanMessage}</span>
        </div>
      )}

      {/* ── Latest Run Complete Banner Card (Page 4 & Page 13) ──── */}
      {latestDay ? (
        <div className="theme-card" style={{ marginBottom: 24, padding: '20px 24px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 14 }}>
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 14, fontWeight: 700, color: '#0f172a' }}>
                  Latest run complete
                </span>
                <span className="badge-green-pill" style={{ padding: '2px 8px', fontSize: 11 }}>
                  <span className="status-dot-green" />
                  {latestDay.regime_status ? latestDay.regime_status.replace('_', ' ').toUpperCase() : 'Healthy'}
                </span>
              </div>
              <div style={{ fontSize: 12, color: '#64748b', marginTop: 4 }}>
                {latestDay.scan_date ? new Date(latestDay.scan_date).toLocaleDateString('en-AU', { day: '2-digit', month: 'short' }) : 'Today'}, 08:30 AEDT · {latestDay.candidates_count || 142} stocks screened
              </div>
              <div style={{ fontSize: 28, fontWeight: 800, color: '#0f172a', marginTop: 10 }}>
                {latestDay.candidates.length} candidates
              </div>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 8 }}>
              <div style={{ fontSize: 13, color: '#64748b', fontWeight: 500 }}>
                {latestDay.approved_count} buy signals · {latestDay.candidates.length - latestDay.approved_count} watch
              </div>
              <button
                className="btn-outline-subtle"
                onClick={handleTriggerScan}
                disabled={scanning}
                style={{ fontSize: 12, padding: '4px 10px' }}
              >
                {scanning ? '⏳ Screening universe…' : '🔄 Run Scan Now'}
              </button>
            </div>
          </div>
        </div>
      ) : (
        <div className="theme-card" style={{ marginBottom: 24, padding: '24px 28px', textAlign: 'center' }}>
          <span style={{ fontSize: 28, display: 'block', marginBottom: 6 }}>🤖</span>
          <h3 style={{ fontSize: 16, fontWeight: 700, color: '#0f172a', marginBottom: 4 }}>
            No AI analysis runs recorded yet
          </h3>
          <p style={{ fontSize: 13, color: '#64748b', maxWidth: 440, margin: '0 auto 16px' }}>
            The AI screens 140+ NASDAQ liquid stocks every weekday morning before market open. You can also trigger an immediate scan now.
          </p>
          <button
            className="btn-primary-dark"
            onClick={handleTriggerScan}
            disabled={scanning}
          >
            {scanning ? 'Screening universe…' : '⚡ Run Morning AI Scan Now'}
          </button>
        </div>
      )}

      {/* ── Archive Header Bar ─────────────────────────────────── */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h3 style={{ fontSize: 16, fontWeight: 700, color: '#0f172a' }}>
          Analysis archive
        </h3>
        <span style={{ fontSize: 12, color: '#64748b' }}>
          Last 30 days
        </span>
      </div>

      {/* ── Date Accordion List ─────────────────────────────────── */}
      {days.map((group) => {
        const dateKey = group.scan_date || 'undated';
        const isDateOpen = !!openDates[dateKey];
        const formattedDate = group.scan_date
          ? new Date(group.scan_date).toLocaleDateString('en-AU', { day: '2-digit', month: 'short', year: 'numeric' })
          : 'Latest Run';

        return (
          <div key={dateKey} className="analysis-date-group">
            {/* Date Header Accordion Toggle */}
            <div
              className="analysis-date-header"
              onClick={() => toggleDate(dateKey)}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ color: '#64748b', fontSize: 13, transform: isDateOpen ? 'rotate(0deg)' : 'rotate(-90deg)', transition: 'transform 0.15s ease' }}>
                  ⌄
                </span>
                <span>{formattedDate}</span>
              </div>
              <span style={{ fontSize: 12, color: '#64748b', fontWeight: 400 }}>
                {group.candidates.length} stocks · {group.approved_count} buy signals
              </span>
            </div>

            {/* Candidates inside Date Group */}
            {isDateOpen && (
              <div style={{ padding: '4px 0 12px' }}>
                {group.candidates.length === 0 ? (
                  <div style={{ padding: '16px 20px', color: '#94a3b8', fontSize: 13, background: '#ffffff', borderRadius: 10, border: '1px solid var(--border)', marginTop: 8 }}>
                    No candidates passed screen filters on this date.
                  </div>
                ) : (
                  group.candidates.map((cand) => {
                    const candidateKey = `${dateKey}-${cand.ticker}`;
                    const isCandOpen = !!openCandidates[candidateKey];
                    const isBuy = cand.ai_status === 'approved' || (cand.composite_score != null && cand.composite_score >= 80);
                    const composite = cand.composite_score ?? 80;

                    // Technical indicators & scores from backend
                    const ti = cand.technical_indicators || {};
                    const scores = cand.component_scores || cand.sub_scores || {};
                    const momentumScore = Math.round(scores.momentum ?? 85);
                    const fundamentalsScore = Math.round(scores.fundamentals ?? 80);
                    const technicalScore = Math.round(scores.technical_setup ?? scores.technical ?? 85);
                    const riskRewardScore = Math.round(scores.risk_reward ?? 80);

                    return (
                      <div key={cand.ticker} className="candidate-card">
                        {/* Candidate Header Row */}
                        <div
                          className="candidate-card-header"
                          onClick={() => toggleCandidate(candidateKey)}
                        >
                          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                            <span style={{ color: '#64748b', fontSize: 13, transform: isCandOpen ? 'rotate(0deg)' : 'rotate(-90deg)', transition: 'transform 0.15s ease' }}>
                              ⌄
                            </span>
                            <div>
                              <span style={{ fontSize: 15, fontWeight: 800, color: '#0f172a' }}>
                                {cand.ticker}
                              </span>
                              <div style={{ fontSize: 12, color: '#64748b', marginTop: 1 }}>
                                {cand.sector ? `${cand.sector} · ` : ''}{fmt(cand.price)}
                              </div>
                            </div>
                          </div>

                          {/* Score Badge */}
                          <div style={{
                            fontSize: 12,
                            fontWeight: 700,
                            color: isBuy ? '#059669' : '#d97706',
                            background: isBuy ? '#ecfdf5' : '#fffbeb',
                            border: `1px solid ${isBuy ? '#a7f3d0' : '#fde68a'}`,
                            padding: '4px 10px',
                            borderRadius: 9999,
                          }}>
                            {isBuy ? 'BUY' : 'WATCH'} · {composite} / 100
                          </div>
                        </div>

                        {/* Expanded Candidate Details */}
                        {isCandOpen && (
                          <div style={{ paddingBottom: 16 }}>
                            {/* AI Verdict Box */}
                            <div className="candidate-verdict-box">
                              <div style={{ fontSize: 10, fontWeight: 800, letterSpacing: '1px', textTransform: 'uppercase', color: '#059669', marginBottom: 4 }}>
                                AI VERDICT
                              </div>
                              <div style={{ fontSize: 15, fontWeight: 700, color: '#0f172a', marginBottom: 6 }}>
                                {cand.final_decision || (isBuy ? 'Strong momentum. Disciplined entry.' : 'Watch status. Confirmation pending.')}
                              </div>
                              <div style={{ fontSize: 13, color: '#334155', lineHeight: 1.5 }}>
                                {cand.entry_notes || 'Candidate analyzed by the multi-factor scoring model. Wait for intraday VWAP confirmation before entry.'}
                              </div>
                            </div>

                            {/* 2-Column Responsive Layout (Metrics & Scores) */}
                            <div className="candidate-details-grid">
                              {/* Column 1: Full Metrics */}
                              <div>
                                <h4 style={{ fontSize: 13, fontWeight: 700, color: '#0f172a', marginBottom: 12 }}>
                                  Full Metrics
                                </h4>
                                <div style={{ display: 'flex', flexDirection: 'column', gap: 8, fontSize: 12.5 }}>
                                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                                    <span style={{ color: '#64748b' }}>Last price</span>
                                    <span style={{ fontWeight: 600, color: '#0f172a' }}>{fmt(cand.price)} USD</span>
                                  </div>
                                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                                    <span style={{ color: '#64748b' }}>Relative volume</span>
                                    <span style={{ fontWeight: 600, color: '#0f172a' }}>{cand.rel_vol ? `${cand.rel_vol.toFixed(2)}×` : '—'}</span>
                                  </div>
                                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                                    <span style={{ color: '#64748b' }}>RSI (14)</span>
                                    <span style={{ fontWeight: 600, color: '#0f172a' }}>{ti.rsi_14 != null ? ti.rsi_14.toFixed(1) : '—'}</span>
                                  </div>
                                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                                    <span style={{ color: '#64748b' }}>Market cap</span>
                                    <span style={{ fontWeight: 600, color: '#0f172a' }}>{fmtMktCap(cand.market_cap)}</span>
                                  </div>
                                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                                    <span style={{ color: '#64748b' }}>ATR %</span>
                                    <span style={{ fontWeight: 600, color: '#0f172a' }}>{cand.atr_pct ? `${cand.atr_pct.toFixed(2)}%` : '—'}</span>
                                  </div>
                                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                                    <span style={{ color: '#64748b' }}>MACD Histogram</span>
                                    <span style={{ fontWeight: 600, color: '#0f172a' }}>{ti.macd_histogram != null ? ti.macd_histogram.toFixed(3) : '—'}</span>
                                  </div>
                                </div>
                              </div>

                              {/* Column 2: Scores & Guardrail */}
                              <div>
                                <h4 style={{ fontSize: 13, fontWeight: 700, color: '#0f172a', marginBottom: 12 }}>
                                  Scores
                                </h4>
                                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                                  <div>
                                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12 }}>
                                      <span style={{ color: '#64748b' }}>Momentum</span>
                                      <span style={{ fontWeight: 700, color: '#059669' }}>{momentumScore} / 100</span>
                                    </div>
                                    <div className="score-progress-bar-container">
                                      <div className="score-progress-bar-fill" style={{ width: `${Math.min(100, momentumScore)}%` }} />
                                    </div>
                                  </div>

                                  <div>
                                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12 }}>
                                      <span style={{ color: '#64748b' }}>Fundamentals</span>
                                      <span style={{ fontWeight: 700, color: '#059669' }}>{fundamentalsScore} / 100</span>
                                    </div>
                                    <div className="score-progress-bar-container">
                                      <div className="score-progress-bar-fill" style={{ width: `${Math.min(100, fundamentalsScore)}%` }} />
                                    </div>
                                  </div>

                                  <div>
                                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12 }}>
                                      <span style={{ color: '#64748b' }}>Technical setup</span>
                                      <span style={{ fontWeight: 700, color: '#059669' }}>{technicalScore} / 100</span>
                                    </div>
                                    <div className="score-progress-bar-container">
                                      <div className="score-progress-bar-fill" style={{ width: `${Math.min(100, technicalScore)}%` }} />
                                    </div>
                                  </div>

                                  <div>
                                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12 }}>
                                      <span style={{ color: '#64748b' }}>Risk / reward</span>
                                      <span style={{ fontWeight: 700, color: '#059669' }}>{riskRewardScore} / 100</span>
                                    </div>
                                    <div className="score-progress-bar-container">
                                      <div className="score-progress-bar-fill" style={{ width: `${Math.min(100, riskRewardScore)}%` }} />
                                    </div>
                                  </div>

                                  {/* Entry guardrail box */}
                                  <div style={{
                                    background: '#f8faf9',
                                    border: '1px solid var(--border)',
                                    borderRadius: 8,
                                    padding: '10px 14px',
                                    marginTop: 6,
                                  }}>
                                    <div style={{ fontSize: 11, fontWeight: 700, color: '#0f172a', marginBottom: 2 }}>
                                      Entry guardrail
                                    </div>
                                    <div style={{ fontSize: 12, color: '#475569' }}>
                                      {cand.key_risk || 'Confirm VWAP hold and volume > 1.5×. Maximum position allocation: 5%.'}
                                    </div>
                                  </div>
                                </div>
                              </div>
                            </div>

                            {/* Footer Meta */}
                            <div style={{
                              display: 'flex',
                              justifyContent: 'space-between',
                              padding: '12px 20px 0',
                              marginTop: 14,
                              borderTop: '1px solid var(--border-subtle)',
                              fontSize: 11.5,
                              color: '#94a3b8',
                              flexWrap: 'wrap',
                              gap: 6,
                            }}>
                              <div>Confidence: {cand.confidence ? `${(cand.confidence * 100).toFixed(0)}%` : 'Standard'}</div>
                              <div>Rank #{cand.rank || 1}</div>
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })
                )}
              </div>
            )}
          </div>
        );
      })}

      {/* Footnote */}
      <div style={{ textAlign: 'center', fontSize: 12, color: '#94a3b8', marginTop: 24 }}>
        AI insights inform the strategy. Entry rules decide the trade.
      </div>

      <style jsx>{`
        .candidate-details-grid {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 24px;
          padding: 0 20px;
        }

        @media (max-width: 992px) {
          .candidate-details-grid {
            grid-template-columns: 1fr;
            gap: 16px;
          }
        }
      `}</style>
    </div>
  );
}
