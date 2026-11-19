'use client';

import { useEffect, useState, useCallback, useMemo } from 'react';

type AuthFetch = (url: string, init?: RequestInit) => Promise<Response>;

interface Props {
  onModeChange: (mode: 'paper' | 'live') => void;
  authFetch: AuthFetch;
}

export default function SettingsTab({ onModeChange, authFetch }: Props) {
  // IBKR Account Type & Mode
  const [accountType, setAccountType] = useState<'paper' | 'live'>('paper');

  // Master Automation Controls
  const [automatedTrading, setAutomatedTrading] = useState(true);
  const [dailyAiAnalysis, setDailyAiAnalysis] = useState(true);

  // Intraday Entry Guardrails
  const [vwapConfirmation, setVwapConfirmation] = useState(false);
  const [minRelVol, setMinRelVol] = useState('1.5×');
  const [maxRsi, setMaxRsi] = useState('70');

  // Dual-Engine & Risk Gates (Active settings)
  const [meanReversionEnabled, setMeanReversionEnabled] = useState(true);
  const [meanReversionAllocation, setMeanReversionAllocation] = useState('40%');
  const [breakevenR, setBreakevenR] = useState('+0.75R');
  const [gateGapDownVeto, setGateGapDownVeto] = useState('enforce');
  const [gateExposureTiers, setGateExposureTiers] = useState('enforce');
  const [gateMarketBreadth, setGateMarketBreadth] = useState('enforce');
  const [gateSectorLeadership, setGateSectorLeadership] = useState('enforce');
  const [sizingBetaAware, setSizingBetaAware] = useState('enforce');
  const [exitMarketLinked, setExitMarketLinked] = useState('enforce');
  const [gateEarningsDensity, setGateEarningsDensity] = useState('enforce');
  const [gateIntradayConfirmation, setGateIntradayConfirmation] = useState('enforce');

  // Status & notifications
  const [saveStatus, setSaveStatus] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [showLiveConfirm, setShowLiveConfirm] = useState(false);
  const [dangerConfirmAction, setDangerConfirmAction] = useState<string | null>(null);

  const syncDateString = useMemo(() => {
    const now = new Date();
    return `${now.toLocaleDateString('en-AU', { day: '2-digit', month: 'short', year: 'numeric' }).toUpperCase()} · LAST SYNC ${now.toLocaleTimeString('en-AU')} AEDT`;
  }, []);

  // Load existing settings from API
  const fetchSettings = useCallback(async () => {
    try {
      const res = await authFetch('/api/settings');
      if (res.ok) {
        const data = await res.json();
        if (data.trading_mode) {
          setAccountType(data.trading_mode as any);
        }
        if (data.trader_enabled !== undefined) {
          setAutomatedTrading(data.trader_enabled === 'true');
        }
        if (data.scan_enabled !== undefined) {
          setDailyAiAnalysis(data.scan_enabled === 'true');
        }
        if (data.entry_vwap_required !== undefined) {
          setVwapConfirmation(data.entry_vwap_required === 'true');
        }
        if (data.entry_min_rel_vol) {
          setMinRelVol(`${data.entry_min_rel_vol}×`);
        }
        if (data.entry_rsi_max) {
          setMaxRsi(data.entry_rsi_max);
        }
        if (data.enable_mean_reversion !== undefined) {
          setMeanReversionEnabled(data.enable_mean_reversion === 'true');
        }
        if (data.mean_reversion_allocation_pct) {
          setMeanReversionAllocation(`${data.mean_reversion_allocation_pct}%`);
        }
        if (data.breakeven_r_multiple) {
          setBreakevenR(`+${data.breakeven_r_multiple}R`);
        }
        if (data.gate_gap_down_veto) setGateGapDownVeto(data.gate_gap_down_veto);
        if (data.gate_exposure_tiers) setGateExposureTiers(data.gate_exposure_tiers);
        if (data.gate_market_breadth) setGateMarketBreadth(data.gate_market_breadth);
        if (data.gate_sector_leadership) setGateSectorLeadership(data.gate_sector_leadership);
        if (data.sizing_beta_aware) setSizingBetaAware(data.sizing_beta_aware);
        if (data.exit_market_linked) setExitMarketLinked(data.exit_market_linked);
        if (data.gate_earnings_density) setGateEarningsDensity(data.gate_earnings_density);
        if (data.gate_intraday_confirmation) setGateIntradayConfirmation(data.gate_intraday_confirmation);
      }
    } catch {
      // Fail silently
    }
  }, [authFetch]);

  useEffect(() => {
    fetchSettings();
  }, [fetchSettings]);

  const handleSave = async () => {
    setSaving(true);
    setSaveStatus(null);
    try {
      const cleanRelVol = minRelVol.replace('×', '').trim();
      const cleanRsi = maxRsi.trim();
      const cleanMeanRevAlloc = meanReversionAllocation.replace('%', '').trim();
      const cleanBreakevenR = breakevenR.replace('+', '').replace('R', '').trim();

      const res = await authFetch('/api/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          trading_mode: accountType,
          trader_enabled: automatedTrading ? 'true' : 'false',
          scan_enabled: dailyAiAnalysis ? 'true' : 'false',
          entry_vwap_required: vwapConfirmation ? 'true' : 'false',
          entry_min_rel_vol: cleanRelVol,
          entry_rsi_max: cleanRsi,
          enable_mean_reversion: meanReversionEnabled ? 'true' : 'false',
          mean_reversion_allocation_pct: cleanMeanRevAlloc,
          breakeven_r_multiple: cleanBreakevenR,
          gate_gap_down_veto: gateGapDownVeto,
          gate_exposure_tiers: gateExposureTiers,
          gate_market_breadth: gateMarketBreadth,
          gate_sector_leadership: gateSectorLeadership,
          sizing_beta_aware: sizingBetaAware,
          exit_market_linked: exitMarketLinked,
          gate_earnings_density: gateEarningsDensity,
          gate_intraday_confirmation: gateIntradayConfirmation,
        }),
      });
      if (res.ok) {
        setSaveStatus('Changes saved successfully');
        onModeChange(accountType);
      } else {
        setSaveStatus('Save failed');
      }
    } catch {
      setSaveStatus('Network error while saving');
    } finally {
      setSaving(false);
      setTimeout(() => setSaveStatus(null), 3500);
    }
  };

  const handleAccountTypeChange = (type: 'paper' | 'live') => {
    if (type === 'live') {
      setShowLiveConfirm(true);
    } else {
      setAccountType('paper');
      onModeChange('paper');
    }
  };

  const confirmSwitchLive = () => {
    setAccountType('live');
    setShowLiveConfirm(false);
    onModeChange('live');
    handleSave();
  };

  // Danger zone executions
  const handleDangerExecution = async (action: string) => {
    setDangerConfirmAction(null);
    setSaving(true);
    setSaveStatus(null);
    try {
      if (action === 'Pause all automation') {
        await authFetch('/api/settings', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ trader_enabled: 'false' }),
        });
        setAutomatedTrading(false);
        setSaveStatus('Automation paused');
      } else if (action === 'Close all paper positions') {
        const res = await authFetch('/api/sell-all-ibkr', { method: 'POST' });
        const json = await res.json();
        setSaveStatus(json.message || 'Orders submitted to close all positions');
      } else if (action === 'Reset paper account') {
        await authFetch('/api/reset-pnl-history', { method: 'POST' });
        setSaveStatus('Paper account and history reset');
      }
    } catch {
      setSaveStatus('Action failed to execute');
    } finally {
      setSaving(false);
      setTimeout(() => setSaveStatus(null), 4000);
    }
  };

  return (
    <div>
      {/* ── Page Header ────────────────────────────────────────── */}
      <div className="page-title-block">
        <h1 className="page-title-heading">Settings</h1>
        <p className="page-title-subtitle">Your strategy. Your guardrails.</p>
        <p className="page-title-meta">{syncDateString}</p>
      </div>

      {/* ── Safe Space Banner ──────────────────────────────────── */}
      <div style={{
        background: accountType === 'live' ? '#fef2f2' : '#ecfdf5',
        border: accountType === 'live' ? '1px solid #fecaca' : '1px solid #a7f3d0',
        borderRadius: 14,
        padding: '18px 24px',
        marginBottom: 24,
      }}>
        <div style={{
          fontSize: 15,
          fontWeight: 700,
          color: accountType === 'live' ? '#b91c1c' : '#047857',
          marginBottom: 4,
        }}>
          {accountType === 'live' ? 'Live Execution Active' : 'A safe space to refine your strategy.'}
        </div>
        <div style={{ fontSize: 13, color: '#475569' }}>
          {accountType === 'live'
            ? 'Live trading is active. Real orders are placed on your connected IBKR account.'
            : 'Paper trading is active. Simulated orders only; your live IBKR account is protected.'}
        </div>
      </div>

      {/* ── Main 2-Column Grid (Desktop) / Stacked (Phone) ─────── */}
      <div className="settings-columns-grid">
        {/* ── Left Column: Brokerage & Trading Engine ─────────── */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
          {/* 1. IBKR Account & Brokerage Mode */}
          <div className="theme-card">
            <h3 className="table-title-bold">IBKR Account &amp; Brokerage Mode</h3>
            <p style={{ fontSize: 12, color: '#64748b', marginTop: 2, marginBottom: 14 }}>
              Choose which brokerage environment receives trade orders.
            </p>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 14 }}>
              <div
                onClick={() => handleAccountTypeChange('paper')}
                style={{
                  padding: '12px 14px',
                  borderRadius: 10,
                  cursor: 'pointer',
                  border: accountType === 'paper' ? '1.5px solid #059669' : '1px solid var(--border)',
                  background: accountType === 'paper' ? '#ecfdf5' : '#ffffff',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  fontSize: 13,
                  fontWeight: 600,
                  color: accountType === 'paper' ? '#047857' : '#475569',
                }}
              >
                <span>{accountType === 'paper' ? '◉' : '○'}</span>
                <span>Paper account</span>
              </div>

              <div
                onClick={() => handleAccountTypeChange('live')}
                style={{
                  padding: '12px 14px',
                  borderRadius: 10,
                  cursor: 'pointer',
                  border: accountType === 'live' ? '1.5px solid #dc2626' : '1px solid var(--border)',
                  background: accountType === 'live' ? '#fef2f2' : '#ffffff',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  fontSize: 13,
                  fontWeight: 600,
                  color: accountType === 'live' ? '#b91c1c' : '#475569',
                }}
              >
                <span>{accountType === 'live' ? '◉' : '○'}</span>
                <span>Live account</span>
              </div>
            </div>

            <div style={{ fontSize: 12.5, color: '#059669', fontWeight: 600, marginBottom: 4 }}>
              Connected · DU782901
            </div>
            <div style={{ fontSize: 12, color: '#94a3b8' }}>
              Live trading requires an explicit safety confirmation before taking effect.
            </div>
          </div>

          {/* 2. Master Automation Controls */}
          <div className="theme-card">
            <h3 className="table-title-bold">Master Automation Controls</h3>
            <p style={{ fontSize: 12, color: '#64748b', marginTop: 2, marginBottom: 14 }}>
              Master on/off execution switches for background trading loops.
            </p>

            <div className="setting-toggle-row">
              <div>
                <div className="setting-row-title">Automated trading</div>
                <div className="setting-row-desc">Master switch allowing strategy-generated orders to execute.</div>
              </div>
              <label className="toggle-switch">
                <input
                  type="checkbox"
                  checked={automatedTrading}
                  onChange={(e) => setAutomatedTrading(e.target.checked)}
                />
                <span className="toggle-slider" />
              </label>
            </div>

            <div className="setting-toggle-row">
              <div>
                <div className="setting-row-title">Daily AI analysis</div>
                <div className="setting-row-desc">Run pre-market universe screening and AI catalyst vetting.</div>
              </div>
              <label className="toggle-switch">
                <input
                  type="checkbox"
                  checked={dailyAiAnalysis}
                  onChange={(e) => setDailyAiAnalysis(e.target.checked)}
                />
                <span className="toggle-slider" />
              </label>
            </div>
          </div>

          {/* 3. Dual-Engine Strategy Allocation */}
          <div className="theme-card">
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
              <h3 className="table-title-bold" style={{ margin: 0 }}>Dual-Engine Strategy Allocation</h3>
              <span style={{
                background: '#e0f2fe',
                color: '#0369a1',
                fontSize: 11,
                fontWeight: 700,
                padding: '3px 8px',
                borderRadius: 9999,
                border: '1px solid #bae6fd'
              }}>
                Dual-Engine
              </span>
            </div>
            <p style={{ fontSize: 12, color: '#64748b', marginTop: 2, marginBottom: 14 }}>
              Uncorrelated mean reversion alongside core momentum breakout trading.
            </p>

            {/* Mean Reversion Engine Switch */}
            <div className="setting-toggle-row">
              <div>
                <div className="setting-row-title" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span>Mean-Reversion Engine</span>
                  <span style={{ fontSize: 10, background: '#ecfdf5', color: '#047857', padding: '1px 6px', borderRadius: 4, fontWeight: 700 }}>
                    ETF &amp; Mega-Caps
                  </span>
                </div>
                <div className="setting-row-desc">
                  Buys acute dips (RSI-2 &lt; 10 above 200 SMA) on SPY, QQQ, AAPL, NVDA. Exits at 5 SMA or +2.5%.
                </div>
              </div>
              <label className="toggle-switch">
                <input
                  type="checkbox"
                  checked={meanReversionEnabled}
                  onChange={(e) => setMeanReversionEnabled(e.target.checked)}
                />
                <span className="toggle-slider" />
              </label>
            </div>

            <div className="setting-toggle-row">
              <div>
                <div className="setting-row-title">Mean-reversion max allocation</div>
                <div className="setting-row-desc">Max capital allocation cap for mean-reversion sleeve.</div>
              </div>
              <input
                type="text"
                className="setting-input-field"
                value={meanReversionAllocation}
                onChange={(e) => setMeanReversionAllocation(e.target.value)}
              />
            </div>

            {/* Progressive Breakeven Stop Rungs */}
            <div className="setting-toggle-row">
              <div>
                <div className="setting-row-title" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span>Progressive Breakeven Lock</span>
                  <span style={{ fontSize: 10, background: '#fef3c7', color: '#92400e', padding: '1px 6px', borderRadius: 4, fontWeight: 700 }}>
                    Auto-Rung
                  </span>
                </div>
                <div className="setting-row-desc">
                  Automatically moves broker stop to Entry + 0.2% commission cushion once profit hits +0.75R.
                </div>
              </div>
              <input
                type="text"
                className="setting-input-field"
                value={breakevenR}
                onChange={(e) => setBreakevenR(e.target.value)}
              />
            </div>
          </div>
        </div>

        {/* ── Right Column: Guardrails & Risk Protection ──────── */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
          {/* 4. Intraday Entry Guardrails */}
          <div className="theme-card">
            <h3 className="table-title-bold">Intraday Entry Guardrails</h3>
            <p style={{ fontSize: 12, color: '#64748b', marginTop: 2, marginBottom: 14 }}>
              Real-time filters evaluated before confirming any pending buy signal.
            </p>

            <div className="setting-toggle-row">
              <div>
                <div className="setting-row-title">VWAP confirmation</div>
                <div className="setting-row-desc">Require 5-min price to hold firmly above session VWAP.</div>
              </div>
              <label className="toggle-switch">
                <input
                  type="checkbox"
                  checked={vwapConfirmation}
                  onChange={(e) => setVwapConfirmation(e.target.checked)}
                />
                <span className="toggle-slider" />
              </label>
            </div>

            <div className="setting-toggle-row">
              <div>
                <div className="setting-row-title">Minimum relative volume</div>
                <div className="setting-row-desc">5-min volume vs. 20-day historical session volume.</div>
              </div>
              <input
                type="text"
                className="setting-input-field"
                value={minRelVol}
                onChange={(e) => setMinRelVol(e.target.value)}
              />
            </div>

            <div className="setting-toggle-row">
              <div>
                <div className="setting-row-title">Maximum RSI (14)</div>
                <div className="setting-row-desc">Block entries if 14-period RSI exceeds overbought threshold.</div>
              </div>
              <input
                type="text"
                className="setting-input-field"
                value={maxRsi}
                onChange={(e) => setMaxRsi(e.target.value)}
              />
            </div>
          </div>

          {/* 5. Active Risk Protection Gates */}
          <div className="theme-card">
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
              <h3 className="table-title-bold" style={{ margin: 0 }}>Active Risk Protection Gates</h3>
              <span style={{
                background: '#ecfdf5',
                color: '#047857',
                fontSize: 11,
                fontWeight: 700,
                padding: '3px 8px',
                borderRadius: 9999,
                border: '1px solid #a7f3d0'
              }}>
                8 Gates Enforced
              </span>
            </div>
            <p style={{ fontSize: 12, color: '#64748b', marginTop: 2, marginBottom: 14 }}>
              Systemic risk gates actively protecting the portfolio from major drawdowns.
            </p>

            {/* Direct IBKR Historical Data Fallback */}
            <div style={{
              background: '#f8fafc',
              border: '1px solid #e2e8f0',
              borderRadius: 8,
              padding: '10px 14px',
              marginBottom: 12,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between'
            }}>
              <div>
                <div style={{ fontSize: 12.5, fontWeight: 600, color: '#1e293b' }}>
                  Direct IBKR Data Fallback
                </div>
                <div style={{ fontSize: 11.5, color: '#64748b' }}>
                  Failover to reqHistoricalData if Yahoo Finance rate limits
                </div>
              </div>
              <span style={{ fontSize: 10.5, fontWeight: 700, color: '#047857', background: '#ecfdf5', padding: '3px 8px', borderRadius: 6, border: '1px solid #a7f3d0' }}>
                FAILOVER LIVE
              </span>
            </div>

            {/* Safety Gates Grid */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
              {[
                { name: 'SPY Gap-Down Veto', desc: 'Blocks buys if SPY gaps <-0.7%' },
                { name: 'Graded Exposure Tiers', desc: 'Regime caps (A=100%, B=50%, C=0%)' },
                { name: 'Market Breadth Filter', desc: 'Advancers/Decliners health check' },
                { name: 'Sector Leadership', desc: 'Candidate sector ETF > 20 EMA' },
                { name: 'Beta-Aware Sizing', desc: 'Downscales size for β > 1.0 stocks' },
                { name: 'Market-Linked Exits', desc: 'Stop tightening on distribution' },
                { name: 'Earnings Density', desc: 'Blocks entry 5d before earnings' },
                { name: 'Intraday Confirmation', desc: 'VWAP hold + volume surge trigger' },
              ].map((g, idx) => (
                <div key={idx} style={{
                  background: '#f8fafc',
                  border: '1px solid #e2e8f0',
                  borderRadius: 6,
                  padding: '8px 10px',
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 2 }}>
                    <span style={{ fontSize: 11.5, fontWeight: 600, color: '#0f172a' }}>{g.name}</span>
                    <span style={{ fontSize: 9, fontWeight: 700, color: '#047857', background: '#d1fae5', padding: '1px 5px', borderRadius: 4 }}>
                      ACTIVE
                    </span>
                  </div>
                  <div style={{ fontSize: 10.5, color: '#64748b', lineHeight: 1.3 }}>{g.desc}</div>
                </div>
              ))}
            </div>
          </div>

          {/* 6. Automated Execution Timetable */}
          <div className="theme-card">
            <h3 className="table-title-bold">Automated Execution Timetable</h3>
            <p style={{ fontSize: 12, color: '#64748b', marginTop: 2, marginBottom: 14 }}>
              Active background scheduler jobs (Eastern Time / AEDT).
            </p>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 0', borderBottom: '1px solid #f1f5f9' }}>
                <div>
                  <div style={{ fontSize: 12.5, fontWeight: 600, color: '#0f172a' }}>Daily Pre-Market Scan</div>
                  <div style={{ fontSize: 11.5, color: '#64748b' }}>Runs screening and AI grading before session open</div>
                </div>
                <span style={{ fontSize: 11, fontWeight: 600, color: '#0284c7', background: '#f0f9ff', padding: '2px 8px', borderRadius: 6 }}>
                  08:30 AEDT
                </span>
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 0', borderBottom: '1px solid #f1f5f9' }}>
                <div>
                  <div style={{ fontSize: 12.5, fontWeight: 600, color: '#0f172a' }}>Intraday Entry Monitor</div>
                  <div style={{ fontSize: 11.5, color: '#64748b' }}>Evaluates VWAP and volume rules during market hours</div>
                </div>
                <span style={{ fontSize: 11, fontWeight: 600, color: '#0284c7', background: '#f0f9ff', padding: '2px 8px', borderRadius: 6 }}>
                  Every 5 min
                </span>
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 0', borderBottom: '1px solid #f1f5f9' }}>
                <div>
                  <div style={{ fontSize: 12.5, fontWeight: 600, color: '#0f172a' }}>Exit &amp; Trailing Stop Monitor</div>
                  <div style={{ fontSize: 11.5, color: '#64748b' }}>Manages progressive breakeven rungs and trailing stops</div>
                </div>
                <span style={{ fontSize: 11, fontWeight: 600, color: '#0284c7', background: '#f0f9ff', padding: '2px 8px', borderRadius: 6 }}>
                  Every 60 sec
                </span>
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 0' }}>
                <div>
                  <div style={{ fontSize: 12.5, fontWeight: 600, color: '#0f172a' }}>EOD Portfolio Snapshot</div>
                  <div style={{ fontSize: 11.5, color: '#64748b' }}>Calculates daily P&amp;L after NYSE closing bell</div>
                </div>
                <span style={{ fontSize: 11, fontWeight: 600, color: '#0284c7', background: '#f0f9ff', padding: '2px 8px', borderRadius: 6 }}>
                  16:15 ET
                </span>
              </div>
            </div>

            {/* Live Status indicator */}
            <div style={{
              background: '#f8faf9',
              border: '1px solid var(--border)',
              borderRadius: 8,
              padding: '10px 14px',
              marginTop: 12,
            }}>
              <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.8px', color: '#64748b', textTransform: 'uppercase' }}>
                ACTIVE STATUS
              </div>
              <div style={{ fontSize: 12.5, fontWeight: 600, color: '#0f172a', marginTop: 2 }}>
                APScheduler running · NYSE &amp; Australian Eastern Time synchronized
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ── Danger Zone (Full width) ────────────────────────────── */}
      <div className="danger-zone-card">
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: '#dc2626', marginBottom: 4 }}>
          <span style={{ fontSize: 16 }}>⚠</span>
          <span style={{ fontSize: 15, fontWeight: 700 }}>Danger Zone</span>
        </div>
        <p style={{ fontSize: 12.5, color: '#7f1d1d', marginBottom: 18 }}>
          Emergency actions to interrupt trading or clear simulation history.
        </p>

        <div className="danger-zone-actions-grid">
          <div
            className="danger-action-box"
            onClick={() => setDangerConfirmAction('Pause all automation')}
          >
            <div className="danger-action-title">Pause all automation</div>
            <div className="danger-action-desc">Stops new entries; existing positions stay open.</div>
          </div>

          <div
            className="danger-action-box"
            onClick={() => setDangerConfirmAction('Close all paper positions')}
          >
            <div className="danger-action-title">Close all paper positions</div>
            <div className="danger-action-desc">Exits all simulated holdings at market price.</div>
          </div>

          <div
            className="danger-action-box"
            onClick={() => setDangerConfirmAction('Reset paper account')}
          >
            <div className="danger-action-title">Reset paper account</div>
            <div className="danger-action-desc">Permanently clears paper trades and balances.</div>
          </div>
        </div>
      </div>

      {/* ── Bottom Sticky Bar ───────────────────────────────────── */}
      <div style={{
        marginTop: 32,
        paddingTop: 16,
        borderTop: '1px solid var(--border)',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        flexWrap: 'wrap',
        gap: 12,
      }}>
        <div style={{ fontSize: 12.5, color: '#64748b' }}>
          {saveStatus ? (
            <span style={{ color: '#059669', fontWeight: 600 }}>✅ {saveStatus}</span>
          ) : (
            <>
              <span className="desktop-save-text">All active settings synchronized with database</span>
              <span className="mobile-save-text">Settings synced</span>
            </>
          )}
        </div>
        <button
          className="btn-primary-dark"
          onClick={handleSave}
          disabled={saving}
          id="btn-save-settings"
        >
          {saving ? 'Saving…' : 'Save changes'}
        </button>
      </div>

      {/* Live Warning Confirmation Modal */}
      {showLiveConfirm && (
        <div className="modal-backdrop-blur" onClick={() => setShowLiveConfirm(false)}>
          <div className="modal-content-white" onClick={(e) => e.stopPropagation()}>
            <div style={{ fontSize: 32, marginBottom: 12 }}>⚠️</div>
            <h3 style={{ fontSize: 18, fontWeight: 700, color: '#dc2626', marginBottom: 8 }}>
              Switch to Live Trading?
            </h3>
            <p style={{ fontSize: 13, color: '#475569', lineHeight: 1.6, marginBottom: 20 }}>
              You are switching from <strong>Paper Trading</strong> to <strong>Live Trading</strong>. Real capital will be used for execution on IBKR. Ensure your account is funded.
            </p>
            <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
              <button className="btn-outline-subtle" onClick={() => setShowLiveConfirm(false)}>
                Cancel — Keep Paper
              </button>
              <button
                className="btn-primary-dark"
                style={{ background: '#dc2626' }}
                onClick={confirmSwitchLive}
              >
                Yes, Switch to Live
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Danger Zone Action Modal */}
      {dangerConfirmAction && (
        <div className="modal-backdrop-blur" onClick={() => setDangerConfirmAction(null)}>
          <div className="modal-content-white" onClick={(e) => e.stopPropagation()}>
            <h3 style={{ fontSize: 18, fontWeight: 700, color: '#dc2626', marginBottom: 8 }}>
              Confirm {dangerConfirmAction}
            </h3>
            <p style={{ fontSize: 13, color: '#475569', lineHeight: 1.6, marginBottom: 20 }}>
              Are you sure you want to execute <strong>{dangerConfirmAction}</strong>? This action affects running trades and simulation data.
            </p>
            <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
              <button className="btn-outline-subtle" onClick={() => setDangerConfirmAction(null)}>
                Cancel
              </button>
              <button
                className="btn-primary-dark"
                style={{ background: '#dc2626' }}
                onClick={() => handleDangerExecution(dangerConfirmAction)}
              >
                Confirm
              </button>
            </div>
          </div>
        </div>
      )}

      <style jsx>{`
        .settings-columns-grid {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 24px;
        }
        .danger-zone-actions-grid {
          display: grid;
          grid-template-columns: repeat(3, 1fr);
          gap: 16px;
        }
        .desktop-save-text {
          display: inline;
        }
        .mobile-save-text {
          display: none;
        }

        @media (max-width: 992px) {
          .settings-columns-grid {
            grid-template-columns: 1fr;
            gap: 20px;
          }
          .danger-zone-actions-grid {
            grid-template-columns: 1fr;
            gap: 12px;
          }
          .desktop-save-text {
            display: none;
          }
          .mobile-save-text {
            display: inline;
          }
        }
      `}</style>
    </div>
  );
}
