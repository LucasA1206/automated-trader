'use client';

import { useState } from 'react';

// ─── Types ────────────────────────────────────────────────────────────────────

interface CandidateItem {
  ticker: string;
  name: string;
  exchangePrice: string;
  badgeType: 'BUY' | 'WATCH';
  score: number;
  verdictTitle: string;
  verdictText: string;
  lastPrice: string;
  dailyChange: string;
  relVol: string;
  rsi: string;
  ma50_200: string;
  marketCap: string;
  atr: string;
  pe: string;
  scores: {
    momentum: number;
    fundamentals: number;
    technical: number;
    riskReward: number;
  };
  guardrail: string;
  model: string;
  generatedAt: string;
}

interface DateGroup {
  dateLabel: string;
  summaryLabelDesktop: string;
  summaryLabelMobile: string;
  candidates: CandidateItem[];
}

const ARCHIVE_DATA: DateGroup[] = [
  {
    dateLabel: 'Today, 12 Nov 2026',
    summaryLabelDesktop: '4 stocks',
    summaryLabelMobile: '4 stocks',
    candidates: [
      {
        ticker: 'NVDA',
        name: 'NVIDIA Corporation · NASDAQ',
        exchangePrice: 'NVIDIA Corporation · NASDAQ',
        badgeType: 'BUY',
        score: 92,
        verdictTitle: 'Strong momentum. Disciplined entry.',
        verdictText: 'NVDA leads its sector with sustained earnings growth and above-average volume. Wait for intraday confirmation before entry; avoid chasing an extended opening move.',
        lastPrice: '$137.50 USD',
        dailyChange: '+2.34%',
        relVol: '1.82×',
        rsi: '61.4',
        ma50_200: '$128.42 / $114.86',
        marketCap: '$3.37T',
        atr: '$4.12',
        pe: '32.8×',
        scores: {
          momentum: 94,
          fundamentals: 89,
          technical: 93,
          riskReward: 90,
        },
        guardrail: 'Confirm VWAP hold and volume > 1.5×. Maximum allocation: 5%.',
        model: 'Model v3.2 · Confidence: high',
        generatedAt: 'Generated at 08:30:14 AEDT',
      },
      {
        ticker: 'AAPL',
        name: 'Apple Inc. · $225.00',
        exchangePrice: 'Apple Inc. · $225.00',
        badgeType: 'BUY',
        score: 87,
        verdictTitle: 'Positive momentum with constructive volume.',
        verdictText: 'Positive momentum with constructive volume. Enter only after intraday filters confirm.',
        lastPrice: '$225.00 USD',
        dailyChange: '+1.15%',
        relVol: '1.63×',
        rsi: '58.2',
        ma50_200: '$218.10 / $195.40',
        marketCap: '$3.45T',
        atr: '$3.80',
        pe: '31.2×',
        scores: {
          momentum: 88,
          fundamentals: 84,
          technical: 89,
          riskReward: 85,
        },
        guardrail: 'Confirm VWAP hold. Maximum allocation: 5%.',
        model: 'Model v3.2 · Confidence: high',
        generatedAt: 'Generated at 08:30:14 AEDT',
      },
      {
        ticker: 'MSFT',
        name: 'Microsoft Corporation · $420.00',
        exchangePrice: 'Microsoft Corporation · $420.00',
        badgeType: 'WATCH',
        score: 79,
        verdictTitle: 'Promising setup, but confirmation is incomplete.',
        verdictText: 'Promising setup, but confirmation is incomplete. Monitor volume and avoid an early entry.',
        lastPrice: '$420.00 USD',
        dailyChange: '+0.82%',
        relVol: '1.42×',
        rsi: '66.1',
        ma50_200: '$412.30 / $388.50',
        marketCap: '$3.12T',
        atr: '$6.20',
        pe: '34.5×',
        scores: {
          momentum: 80,
          fundamentals: 76,
          technical: 81,
          riskReward: 77,
        },
        guardrail: 'Wait for relative volume > 1.5x before entry.',
        model: 'Model v3.2 · Confidence: medium',
        generatedAt: 'Generated at 08:30:14 AEDT',
      },
      {
        ticker: 'AMZN',
        name: 'Amazon.com Inc. · $200.00',
        exchangePrice: 'Amazon.com Inc. · $200.00',
        badgeType: 'WATCH',
        score: 74,
        verdictTitle: 'Promising setup, but confirmation is incomplete.',
        verdictText: 'Promising setup, but confirmation is incomplete. Monitor volume and avoid an early entry.',
        lastPrice: '$200.00 USD',
        dailyChange: '-0.45%',
        relVol: '1.21×',
        rsi: '69.3',
        ma50_200: '$192.50 / $180.20',
        marketCap: '$2.08T',
        atr: '$4.50',
        pe: '41.0×',
        scores: {
          momentum: 75,
          fundamentals: 71,
          technical: 76,
          riskReward: 72,
        },
        guardrail: 'High RSI warning. Monitor intraday consolidation.',
        model: 'Model v3.2 · Confidence: medium',
        generatedAt: 'Generated at 08:30:14 AEDT',
      },
    ],
  },
  {
    dateLabel: '11 Nov 2026',
    summaryLabelDesktop: '5 stocks · 3 buy signals',
    summaryLabelMobile: '5 stocks',
    candidates: [
      {
        ticker: 'NVDA',
        name: 'NVIDIA Corporation · $135.20',
        exchangePrice: 'NVIDIA Corporation · $135.20',
        badgeType: 'BUY',
        score: 92,
        verdictTitle: 'Strong momentum. Disciplined entry.',
        verdictText: 'NVDA leads its sector with sustained earnings growth and above-average volume.',
        lastPrice: '$135.20 USD',
        dailyChange: '+3.10%',
        relVol: '1.92×',
        rsi: '62.0',
        ma50_200: '$126.10 / $112.50',
        marketCap: '$3.32T',
        atr: '$4.10',
        pe: '32.1×',
        scores: { momentum: 94, fundamentals: 89, technical: 93, riskReward: 90 },
        guardrail: 'Confirm VWAP hold. Maximum allocation: 5%.',
        model: 'Model v3.2 · Confidence: high',
        generatedAt: 'Generated at 08:30:00 AEDT',
      },
      {
        ticker: 'AAPL',
        name: 'Apple Inc. · $223.50',
        exchangePrice: 'Apple Inc. · $223.50',
        badgeType: 'BUY',
        score: 87,
        verdictTitle: 'Constructive volume and breakout signal.',
        verdictText: 'Apple testing upper channel boundaries with solid institutional flow.',
        lastPrice: '$223.50 USD',
        dailyChange: '+1.40%',
        relVol: '1.60×',
        rsi: '57.8',
        ma50_200: '$217.50 / $194.00',
        marketCap: '$3.42T',
        atr: '$3.75',
        pe: '30.9×',
        scores: { momentum: 88, fundamentals: 84, technical: 88, riskReward: 85 },
        guardrail: 'Standard sizing.',
        model: 'Model v3.2 · Confidence: high',
        generatedAt: 'Generated at 08:30:00 AEDT',
      },
      {
        ticker: 'META',
        name: 'Meta Platforms Inc. · $586.40',
        exchangePrice: 'Meta Platforms Inc. · $586.40',
        badgeType: 'BUY',
        score: 88,
        verdictTitle: 'Positive momentum with constructive volume.',
        verdictText: 'Enter only after intraday filters confirm.',
        lastPrice: '$586.40 USD',
        dailyChange: '+2.10%',
        relVol: '1.71×',
        rsi: '60.8',
        ma50_200: '$560.00 / $510.00',
        marketCap: '$1.48T',
        atr: '$12.40',
        pe: '26.8×',
        scores: { momentum: 89, fundamentals: 85, technical: 89, riskReward: 86 },
        guardrail: 'Confirm VWAP hold.',
        model: 'Model v3.2 · Confidence: high',
        generatedAt: 'Generated at 08:30:00 AEDT',
      },
      {
        ticker: 'MSFT',
        name: 'Microsoft Corporation · $418.00',
        exchangePrice: 'Microsoft Corporation · $418.00',
        badgeType: 'WATCH',
        score: 79,
        verdictTitle: 'Promising setup, but confirmation is incomplete.',
        verdictText: 'Monitor volume and avoid early entry.',
        lastPrice: '$418.00 USD',
        dailyChange: '+0.30%',
        relVol: '1.40×',
        rsi: '65.5',
        ma50_200: '$410.00 / $386.00',
        marketCap: '$3.10T',
        atr: '$6.10',
        pe: '34.2×',
        scores: { momentum: 80, fundamentals: 76, technical: 80, riskReward: 77 },
        guardrail: 'Volume below threshold.',
        model: 'Model v3.2 · Confidence: medium',
        generatedAt: 'Generated at 08:30:00 AEDT',
      },
      {
        ticker: 'AMZN',
        name: 'Amazon.com Inc. · $199.50',
        exchangePrice: 'Amazon.com Inc. · $199.50',
        badgeType: 'WATCH',
        score: 74,
        verdictTitle: 'Consolidation phase.',
        verdictText: 'Awaiting clean directional break.',
        lastPrice: '$199.50 USD',
        dailyChange: '-0.20%',
        relVol: '1.20×',
        rsi: '68.9',
        ma50_200: '$191.00 / $179.00',
        marketCap: '$2.07T',
        atr: '$4.40',
        pe: '40.5×',
        scores: { momentum: 75, fundamentals: 71, technical: 75, riskReward: 72 },
        guardrail: 'RSI near overbought.',
        model: 'Model v3.2 · Confidence: medium',
        generatedAt: 'Generated at 08:30:00 AEDT',
      },
    ],
  },
  {
    dateLabel: '10 Nov 2026',
    summaryLabelDesktop: '3 stocks · 1 buy signal',
    summaryLabelMobile: '3 stocks',
    candidates: [
      {
        ticker: 'TSLA',
        name: 'Tesla Inc. · $256.80',
        exchangePrice: 'Tesla Inc. · $256.80',
        badgeType: 'BUY',
        score: 84,
        verdictTitle: 'Positive momentum with constructive volume.',
        verdictText: 'Enter only after intraday filters confirm.',
        lastPrice: '$256.80 USD',
        dailyChange: '+4.20%',
        relVol: '1.90×',
        rsi: '63.8',
        ma50_200: '$238.00 / $210.00',
        marketCap: '$820B',
        atr: '$9.20',
        pe: '68.0×',
        scores: { momentum: 85, fundamentals: 81, technical: 86, riskReward: 82 },
        guardrail: 'High ATR position size adjustment.',
        model: 'Model v3.2 · Confidence: high',
        generatedAt: 'Generated at 08:30:00 AEDT',
      },
      {
        ticker: 'AMD',
        name: 'Advanced Micro Devices · $149.80',
        exchangePrice: 'Advanced Micro Devices · $149.80',
        badgeType: 'WATCH',
        score: 73,
        verdictTitle: 'Promising setup, but confirmation is incomplete.',
        verdictText: 'Monitor volume and avoid early entry.',
        lastPrice: '$149.80 USD',
        dailyChange: '-0.90%',
        relVol: '1.35×',
        rsi: '52.7',
        ma50_200: '$155.00 / $162.00',
        marketCap: '$242B',
        atr: '$5.80',
        pe: '48.0×',
        scores: { momentum: 74, fundamentals: 70, technical: 73, riskReward: 71 },
        guardrail: 'Below 50d MA.',
        model: 'Model v3.2 · Confidence: low',
        generatedAt: 'Generated at 08:30:00 AEDT',
      },
      {
        ticker: 'MSFT',
        name: 'Microsoft Corporation · $415.00',
        exchangePrice: 'Microsoft Corporation · $415.00',
        badgeType: 'WATCH',
        score: 79,
        verdictTitle: 'Promising setup, but confirmation is incomplete.',
        verdictText: 'Monitor volume and avoid early entry.',
        lastPrice: '$415.00 USD',
        dailyChange: '+0.10%',
        relVol: '1.38×',
        rsi: '64.8',
        ma50_200: '$408.00 / $385.00',
        marketCap: '$3.08T',
        atr: '$6.00',
        pe: '33.9×',
        scores: { momentum: 80, fundamentals: 76, technical: 80, riskReward: 77 },
        guardrail: 'Volume below threshold.',
        model: 'Model v3.2 · Confidence: medium',
        generatedAt: 'Generated at 08:30:00 AEDT',
      },
    ],
  },
  {
    dateLabel: '09 Nov 2026',
    summaryLabelDesktop: '6 stocks · 2 buy signals',
    summaryLabelMobile: '6 stocks',
    candidates: [
      {
        ticker: 'NVDA',
        name: 'NVIDIA Corporation · $133.00',
        exchangePrice: 'NVIDIA Corporation · $133.00',
        badgeType: 'BUY',
        score: 92,
        verdictTitle: 'Strong momentum. Disciplined entry.',
        verdictText: 'NVDA leads its sector with sustained earnings growth.',
        lastPrice: '$133.00 USD',
        dailyChange: '+2.80%',
        relVol: '1.85×',
        rsi: '60.5',
        ma50_200: '$124.00 / $111.00',
        marketCap: '$3.28T',
        atr: '$4.00',
        pe: '31.5×',
        scores: { momentum: 94, fundamentals: 89, technical: 93, riskReward: 90 },
        guardrail: 'Confirm VWAP.',
        model: 'Model v3.2 · Confidence: high',
        generatedAt: 'Generated at 08:30:00 AEDT',
      },
      {
        ticker: 'AAPL',
        name: 'Apple Inc. · $221.00',
        exchangePrice: 'Apple Inc. · $221.00',
        badgeType: 'BUY',
        score: 87,
        verdictTitle: 'Positive momentum.',
        verdictText: 'Enter after filters confirm.',
        lastPrice: '$221.00 USD',
        dailyChange: '+0.90%',
        relVol: '1.58×',
        rsi: '56.9',
        ma50_200: '$216.00 / $192.00',
        marketCap: '$3.38T',
        atr: '$3.70',
        pe: '30.5×',
        scores: { momentum: 88, fundamentals: 84, technical: 88, riskReward: 85 },
        guardrail: 'Standard sizing.',
        model: 'Model v3.2 · Confidence: high',
        generatedAt: 'Generated at 08:30:00 AEDT',
      },
      {
        ticker: 'META',
        name: 'Meta Platforms Inc. · $580.00',
        exchangePrice: 'Meta Platforms Inc. · $580.00',
        badgeType: 'BUY',
        score: 88,
        verdictTitle: 'Positive momentum with constructive volume.',
        verdictText: 'Enter only after intraday filters confirm.',
        lastPrice: '$580.00 USD',
        dailyChange: '+1.80%',
        relVol: '1.68×',
        rsi: '59.5',
        ma50_200: '$555.00 / $505.00',
        marketCap: '$1.46T',
        atr: '$12.10',
        pe: '26.4×',
        scores: { momentum: 89, fundamentals: 85, technical: 89, riskReward: 86 },
        guardrail: 'VWAP hold required.',
        model: 'Model v3.2 · Confidence: high',
        generatedAt: 'Generated at 08:30:00 AEDT',
      },
      {
        ticker: 'TSLA',
        name: 'Tesla Inc. · $250.00',
        exchangePrice: 'Tesla Inc. · $250.00',
        badgeType: 'BUY',
        score: 84,
        verdictTitle: 'Positive momentum with constructive volume.',
        verdictText: 'Enter only after intraday filters confirm.',
        lastPrice: '$250.00 USD',
        dailyChange: '+3.50%',
        relVol: '1.82×',
        rsi: '61.2',
        ma50_200: '$235.00 / $208.00',
        marketCap: '$795B',
        atr: '$8.90',
        pe: '65.0×',
        scores: { momentum: 85, fundamentals: 81, technical: 86, riskReward: 82 },
        guardrail: 'Confirm volume.',
        model: 'Model v3.2 · Confidence: high',
        generatedAt: 'Generated at 08:30:00 AEDT',
      },
      {
        ticker: 'MSFT',
        name: 'Microsoft Corporation · $412.00',
        exchangePrice: 'Microsoft Corporation · $412.00',
        badgeType: 'WATCH',
        score: 79,
        verdictTitle: 'Promising setup.',
        verdictText: 'Monitor volume.',
        lastPrice: '$412.00 USD',
        dailyChange: '+0.20%',
        relVol: '1.35×',
        rsi: '64.0',
        ma50_200: '$406.00 / $383.00',
        marketCap: '$3.05T',
        atr: '$5.90',
        pe: '33.6×',
        scores: { momentum: 80, fundamentals: 76, technical: 80, riskReward: 77 },
        guardrail: 'Volume low.',
        model: 'Model v3.2 · Confidence: medium',
        generatedAt: 'Generated at 08:30:00 AEDT',
      },
      {
        ticker: 'AMD',
        name: 'Advanced Micro Devices · $148.00',
        exchangePrice: 'Advanced Micro Devices · $148.00',
        badgeType: 'WATCH',
        score: 73,
        verdictTitle: 'Promising setup, but confirmation is incomplete.',
        verdictText: 'Monitor volume and avoid early entry.',
        lastPrice: '$148.00 USD',
        dailyChange: '-1.20%',
        relVol: '1.30×',
        rsi: '51.5',
        ma50_200: '$153.00 / $160.00',
        marketCap: '$239B',
        atr: '$5.70',
        pe: '47.5×',
        scores: { momentum: 74, fundamentals: 70, technical: 73, riskReward: 71 },
        guardrail: 'Below moving averages.',
        model: 'Model v3.2 · Confidence: low',
        generatedAt: 'Generated at 08:30:00 AEDT',
      },
    ],
  },
];

export default function AIAnalysisTab({
  authFetch,
  tradingMode = 'paper',
}: {
  authFetch: (url: string, init?: RequestInit) => Promise<Response>;
  tradingMode?: 'paper' | 'live';
}) {
  // Expanded date groups (first one open by default)
  const [openDates, setOpenDates] = useState<Record<string, boolean>>({
    'Today, 12 Nov 2026': true,
  });

  // Expanded candidates (NVDA open by default)
  const [openCandidates, setOpenCandidates] = useState<Record<string, boolean>>({
    'Today, 12 Nov 2026-NVDA': true,
  });

  const toggleDate = (dateLabel: string) => {
    setOpenDates((prev) => ({ ...prev, [dateLabel]: !prev[dateLabel] }));
  };

  const toggleCandidate = (key: string) => {
    setOpenCandidates((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const syncDateString = '12 NOV 2026 · LAST SYNC 09:42:08 AEDT';

  return (
    <div>
      {/* ── Page Header ────────────────────────────────────────── */}
      <div className="page-title-block">
        <h1 className="page-title-heading">AI Stock Analysis</h1>
        <p className="page-title-subtitle">A clearer signal from the noise.</p>
        <p className="page-title-meta">{syncDateString}</p>
      </div>

      {/* ── Latest Run Complete Banner Card (Page 4 & Page 13) ──── */}
      <div className="theme-card" style={{ marginBottom: 24, padding: '20px 24px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 14 }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 14, fontWeight: 700, color: '#0f172a' }}>
                Latest run complete
              </span>
              <span className="badge-green-pill" style={{ padding: '2px 8px', fontSize: 11 }}>
                <span className="status-dot-green" />
                Healthy
              </span>
            </div>
            <div style={{ fontSize: 12, color: '#64748b', marginTop: 4 }}>
              12 Nov, 08:30 AEDT · 142 stocks screened
            </div>
            <div style={{ fontSize: 28, fontWeight: 800, color: '#0f172a', marginTop: 10 }}>
              4 candidates
            </div>
          </div>
          <div style={{ fontSize: 13, color: '#64748b', fontWeight: 500 }}>
            2 buy signals · 2 watch
          </div>
        </div>
      </div>

      {/* ── Archive Header Bar ─────────────────────────────────── */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h3 style={{ fontSize: 16, fontWeight: 700, color: '#0f172a' }}>
          Analysis archive
        </h3>
        <span style={{ fontSize: 12, color: '#64748b', cursor: 'pointer' }}>
          Last 7 days ▾
        </span>
      </div>

      {/* ── Date Accordion List ─────────────────────────────────── */}
      {ARCHIVE_DATA.map((group) => {
        const isDateOpen = !!openDates[group.dateLabel];
        return (
          <div key={group.dateLabel} className="analysis-date-group">
            {/* Date Header Accordion Toggle */}
            <div
              className="analysis-date-header"
              onClick={() => toggleDate(group.dateLabel)}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ color: '#64748b', fontSize: 13, transform: isDateOpen ? 'rotate(0deg)' : 'rotate(-90deg)', transition: 'transform 0.15s ease' }}>
                  ⌄
                </span>
                <span>{group.dateLabel}</span>
              </div>
              <span style={{ fontSize: 12, color: '#64748b', fontWeight: 400 }}>
                <span className="desktop-date-summary">{group.summaryLabelDesktop}</span>
                <span className="mobile-date-summary">{group.summaryLabelMobile}</span>
              </span>
            </div>

            {/* Candidates inside Date Group */}
            {isDateOpen && (
              <div style={{ padding: '4px 0 12px' }}>
                {group.candidates.map((cand) => {
                  const candidateKey = `${group.dateLabel}-${cand.ticker}`;
                  const isCandOpen = !!openCandidates[candidateKey];
                  const isBuy = cand.badgeType === 'BUY';

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
                              {cand.exchangePrice}
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
                          {cand.badgeType} · {cand.score} {cand.score === 92 ? '/ 100' : ''}
                        </div>
                      </div>

                      {/* Expanded Candidate Details */}
                      {isCandOpen && (
                        <div style={{ paddingBottom: 16 }}>
                          {/* AI Verdict Box (Green container) */}
                          <div className="candidate-verdict-box">
                            <div style={{ fontSize: 10, fontWeight: 800, letterSpacing: '1px', textTransform: 'uppercase', color: '#059669', marginBottom: 4 }}>
                              AI VERDICT
                            </div>
                            <div style={{ fontSize: 15, fontWeight: 700, color: '#0f172a', marginBottom: 6 }}>
                              {cand.verdictTitle}
                            </div>
                            <div style={{ fontSize: 13, color: '#334155', lineHeight: 1.5 }}>
                              {cand.verdictText}
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
                                  <span style={{ fontWeight: 600, color: '#0f172a' }}>{cand.lastPrice}</span>
                                </div>
                                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                                  <span style={{ color: '#64748b' }}>Daily change</span>
                                  <span style={{ fontWeight: 600, color: cand.dailyChange.startsWith('+') ? '#059669' : '#dc2626' }}>{cand.dailyChange}</span>
                                </div>
                                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                                  <span style={{ color: '#64748b' }}>Relative volume</span>
                                  <span style={{ fontWeight: 600, color: '#0f172a' }}>{cand.relVol}</span>
                                </div>
                                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                                  <span style={{ color: '#64748b' }}>RSI (14)</span>
                                  <span style={{ fontWeight: 600, color: '#0f172a' }}>{cand.rsi}</span>
                                </div>
                                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                                  <span style={{ color: '#64748b' }}>50 / 200-day MA</span>
                                  <span style={{ fontWeight: 600, color: '#0f172a' }}>{cand.ma50_200}</span>
                                </div>
                                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                                  <span style={{ color: '#64748b' }}>Market cap</span>
                                  <span style={{ fontWeight: 600, color: '#0f172a' }}>{cand.marketCap}</span>
                                </div>
                                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                                  <span style={{ color: '#64748b' }}>ATR (14)</span>
                                  <span style={{ fontWeight: 600, color: '#0f172a' }}>{cand.atr}</span>
                                </div>
                                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                                  <span style={{ color: '#64748b' }}>Forward P/E</span>
                                  <span style={{ fontWeight: 600, color: '#0f172a' }}>{cand.pe}</span>
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
                                    <span style={{ fontWeight: 700, color: '#059669' }}>{cand.scores.momentum} / 100</span>
                                  </div>
                                  <div className="score-progress-bar-container">
                                    <div className="score-progress-bar-fill" style={{ width: `${cand.scores.momentum}%` }} />
                                  </div>
                                </div>

                                <div>
                                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12 }}>
                                    <span style={{ color: '#64748b' }}>Fundamentals</span>
                                    <span style={{ fontWeight: 700, color: '#059669' }}>{cand.scores.fundamentals} / 100</span>
                                  </div>
                                  <div className="score-progress-bar-container">
                                    <div className="score-progress-bar-fill" style={{ width: `${cand.scores.fundamentals}%` }} />
                                  </div>
                                </div>

                                <div>
                                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12 }}>
                                    <span style={{ color: '#64748b' }}>Technical setup</span>
                                    <span style={{ fontWeight: 700, color: '#059669' }}>{cand.scores.technical} / 100</span>
                                  </div>
                                  <div className="score-progress-bar-container">
                                    <div className="score-progress-bar-fill" style={{ width: `${cand.scores.technical}%` }} />
                                  </div>
                                </div>

                                <div>
                                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12 }}>
                                    <span style={{ color: '#64748b' }}>Risk / reward</span>
                                    <span style={{ fontWeight: 700, color: '#059669' }}>{cand.scores.riskReward} / 100</span>
                                  </div>
                                  <div className="score-progress-bar-container">
                                    <div className="score-progress-bar-fill" style={{ width: `${cand.scores.riskReward}%` }} />
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
                                    {cand.guardrail}
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
                            <div>{cand.model}</div>
                            <div>{cand.generatedAt}</div>
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })}
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
        .desktop-date-summary {
          display: inline;
        }
        .mobile-date-summary {
          display: none;
        }

        @media (max-width: 768px) {
          .candidate-details-grid {
            grid-template-columns: 1fr;
            gap: 16px;
          }
          .desktop-date-summary {
            display: none;
          }
          .mobile-date-summary {
            display: inline;
          }
        }
      `}</style>
    </div>
  );
}
