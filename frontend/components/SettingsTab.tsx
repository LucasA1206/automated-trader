'use client';

import { useEffect, useState, useCallback, useMemo } from 'react';

type AuthFetch = (url: string, init?: RequestInit) => Promise<Response>;

interface Props {
  onModeChange: (mode: 'paper' | 'live') => void;
  authFetch: AuthFetch;
}

export default function SettingsTab({ onModeChange, authFetch }: Props) {
  // Master Controls & Automation
  const [automatedTrading, setAutomatedTrading] = useState(true);
  const [dailyAiAnalysis, setDailyAiAnalysis] = useState(true);
  const [newEntries, setNewEntries] = useState(true);
  const [exitManagement, setExitManagement] = useState(true);

  // Entry Confirmation Rules
  const [vwapConfirmation, setVwapConfirmation] = useState(false);
  const [volumeConfirmation, setVolumeConfirmation] = useState(true);
  const [minRelVol, setMinRelVol] = useState('1.5×');
  const [maxRsi, setMaxRsi] = useState('70');
  const [openingRangeWait, setOpeningRangeWait] = useState('15 min');

  // Paper Simulation Strategy
  const [startingCapital, setStartingCapital] = useState('$100,000');
  const [maxPosSize, setMaxPosSize] = useState('5%');
  const [maxOpenPositions, setMaxOpenPositions] = useState('8');
  const [stopLoss, setStopLoss] = useState('3%');
  const [takeProfit, setTakeProfit] = useState('6% / 50%');

  // IBKR Account Type & Mode
  const [accountType, setAccountType] = useState<'paper' | 'live'>('paper');
  const [tradingModeSelect, setTradingModeSelect] = useState('Automated paper trading');

  // Scheduled Jobs
  const [jobDailyAi, setJobDailyAi] = useState(true);
  const [jobEntryConf, setJobEntryConf] = useState(true);
  const [jobPortfolioSync, setJobPortfolioSync] = useState(true);

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
        if (data.max_positions) {
          setMaxOpenPositions(data.max_positions);
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
      const cleanMaxPos = maxOpenPositions.trim();
      const cleanRsi = maxRsi.trim();

      const res = await authFetch('/api/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          trading_mode: accountType,
          trader_enabled: automatedTrading ? 'true' : 'false',
          scan_enabled: dailyAiAnalysis ? 'true' : 'false',
          max_positions: cleanMaxPos,
          entry_vwap_required: vwapConfirmation ? 'true' : 'false',
          entry_min_rel_vol: cleanRelVol,
          entry_rsi_max: cleanRsi,
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

      {/* ── Safe Space Banner (Page 6 & Page 15) ────────────────── */}
      <div style={{
        background: '#ecfdf5',
        border: '1px solid #a7f3d0',
        borderRadius: 14,
        padding: '18px 24px',
        marginBottom: 24,
      }}>
        <div style={{ fontSize: 15, fontWeight: 700, color: '#047857', marginBottom: 4 }}>
          A safe space to refine your strategy.
        </div>
        <div style={{ fontSize: 13, color: '#475569' }}>
          {accountType === 'live'
            ? 'Live trading is active. Real orders are placed on your IBKR account.'
            : 'Paper trading is active. Your live IBKR account is not being used.'}
        </div>
      </div>

      {/* ── Main 2-Column Grid (Desktop) / Stacked (Phone) ─────── */}
      <div className="settings-columns-grid">
        {/* ── Left Column ──────────────────────────────────────── */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
          {/* Master Controls & Automation */}
          <div className="theme-card">
            <h3 className="table-title-bold">Master Controls &amp; Automation</h3>
            <p style={{ fontSize: 12, color: '#64748b', marginTop: 2, marginBottom: 14 }}>
              Control the automated trading engine.
            </p>

            <div className="setting-toggle-row">
              <div>
                <div className="setting-row-title">Automated trading</div>
                <div className="setting-row-desc">Allow strategy-generated orders.</div>
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
                <div className="setting-row-desc">Screen stocks before the session.</div>
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

            <div className="setting-toggle-row">
              <div>
                <div className="setting-row-title">New entries</div>
                <div className="setting-row-desc">Allow new positions within risk limits.</div>
              </div>
              <label className="toggle-switch">
                <input
                  type="checkbox"
                  checked={newEntries}
                  onChange={(e) => setNewEntries(e.target.checked)}
                />
                <span className="toggle-slider" />
              </label>
            </div>

            <div className="setting-toggle-row">
              <div>
                <div className="setting-row-title">Exit management</div>
                <div className="setting-row-desc">Manage stop-loss and profit targets.</div>
              </div>
              <label className="toggle-switch">
                <input
                  type="checkbox"
                  checked={exitManagement}
                  onChange={(e) => setExitManagement(e.target.checked)}
                />
                <span className="toggle-slider" />
              </label>
            </div>
          </div>

          {/* Entry Confirmation Rules (Intraday Filters) */}
          <div className="theme-card">
            <h3 className="table-title-bold">Entry Confirmation Rules (Intraday Filters)</h3>
            <p style={{ fontSize: 12, color: '#64748b', marginTop: 2, marginBottom: 14 }}>
              A candidate must pass every enabled filter.
            </p>

            <div className="setting-toggle-row">
              <div>
                <div className="setting-row-title">VWAP confirmation</div>
                <div className="setting-row-desc">Price must hold above session VWAP.</div>
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
                <div className="setting-row-title">Volume confirmation</div>
                <div className="setting-row-desc">Require relative volume above threshold.</div>
              </div>
              <label className="toggle-switch">
                <input
                  type="checkbox"
                  checked={volumeConfirmation}
                  onChange={(e) => setVolumeConfirmation(e.target.checked)}
                />
                <span className="toggle-slider" />
              </label>
            </div>

            <div className="setting-toggle-row">
              <div className="setting-row-title">Minimum relative volume</div>
              <input
                type="text"
                className="setting-input-field"
                value={minRelVol}
                onChange={(e) => setMinRelVol(e.target.value)}
              />
            </div>

            <div className="setting-toggle-row">
              <div className="setting-row-title">Maximum RSI (14)</div>
              <input
                type="text"
                className="setting-input-field"
                value={maxRsi}
                onChange={(e) => setMaxRsi(e.target.value)}
              />
            </div>

            <div className="setting-toggle-row">
              <div className="setting-row-title">Opening range wait</div>
              <input
                type="text"
                className="setting-input-field"
                value={openingRangeWait}
                onChange={(e) => setOpeningRangeWait(e.target.value)}
              />
            </div>
          </div>

          {/* Paper Simulation Strategy */}
          <div className="theme-card">
            <h3 className="table-title-bold">Paper Simulation Strategy</h3>
            <p style={{ fontSize: 12, color: '#64748b', marginTop: 2, marginBottom: 14 }}>
              Risk controls for simulated positions.
            </p>

            <div className="setting-toggle-row">
              <div className="setting-row-title">Starting capital (AUD)</div>
              <input
                type="text"
                className="setting-input-field"
                value={startingCapital}
                onChange={(e) => setStartingCapital(e.target.value)}
              />
            </div>

            <div className="setting-toggle-row">
              <div className="setting-row-title">Max position size</div>
              <input
                type="text"
                className="setting-input-field"
                value={maxPosSize}
                onChange={(e) => setMaxPosSize(e.target.value)}
              />
            </div>

            <div className="setting-toggle-row">
              <div className="setting-row-title">Maximum open positions</div>
              <input
                type="text"
                className="setting-input-field"
                value={maxOpenPositions}
                onChange={(e) => setMaxOpenPositions(e.target.value)}
              />
            </div>

            <div className="setting-toggle-row">
              <div className="setting-row-title">Stop-loss</div>
              <input
                type="text"
                className="setting-input-field"
                value={stopLoss}
                onChange={(e) => setStopLoss(e.target.value)}
              />
            </div>

            <div className="setting-toggle-row">
              <div className="setting-row-title">Take profit / partial exit</div>
              <input
                type="text"
                className="setting-input-field"
                value={takeProfit}
                onChange={(e) => setTakeProfit(e.target.value)}
              />
            </div>
          </div>
        </div>

        {/* ── Right Column ─────────────────────────────────────── */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
          {/* IBKR Account Type */}
          <div className="theme-card">
            <h3 className="table-title-bold">IBKR Account Type</h3>
            <p style={{ fontSize: 12, color: '#64748b', marginTop: 2, marginBottom: 14 }}>
              Choose which brokerage environment to use.
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
              Live trading requires a separate confirmation.
            </div>
          </div>

          {/* Trading Mode */}
          <div className="theme-card">
            <h3 className="table-title-bold">Trading Mode</h3>
            <p style={{ fontSize: 12, color: '#64748b', marginTop: 2, marginBottom: 14 }}>
              Decide how signals become orders.
            </p>

            <select
              value={tradingModeSelect}
              onChange={(e) => setTradingModeSelect(e.target.value)}
              style={{
                width: '100%',
                padding: '10px 14px',
                borderRadius: 8,
                border: '1px solid var(--border)',
                background: '#ffffff',
                fontSize: 13.5,
                color: '#0f172a',
                outline: 'none',
                cursor: 'pointer',
                marginBottom: 12,
              }}
            >
              <option value="Automated paper trading">Automated paper trading ▾</option>
              <option value="Semi-automated (Confirmation required)">Semi-automated (Confirmation required)</option>
              <option value="Signal only (No execution)">Signal only (No execution)</option>
            </select>

            <div style={{ fontSize: 12, color: '#64748b', lineHeight: 1.5 }}>
              Signals are confirmed by your entry rules before a simulated order is placed.
            </div>
          </div>

          {/* Scheduled Jobs */}
          <div className="theme-card">
            <h3 className="table-title-bold">Scheduled Jobs</h3>
            <p style={{ fontSize: 12, color: '#64748b', marginTop: 2, marginBottom: 14 }}>
              All schedules use Australia / Sydney (AEDT).
            </p>

            <div className="setting-toggle-row">
              <div>
                <div className="setting-row-title">Daily AI analysis</div>
                <div className="setting-row-desc">08:30 AEDT · Every trading day</div>
              </div>
              <label className="toggle-switch">
                <input
                  type="checkbox"
                  checked={jobDailyAi}
                  onChange={(e) => setJobDailyAi(e.target.checked)}
                />
                <span className="toggle-slider" />
              </label>
            </div>

            <div className="setting-toggle-row">
              <div>
                <div className="setting-row-title">Entry confirmation</div>
                <div className="setting-row-desc">Every 5 min · During US market hours</div>
              </div>
              <label className="toggle-switch">
                <input
                  type="checkbox"
                  checked={jobEntryConf}
                  onChange={(e) => setJobEntryConf(e.target.checked)}
                />
                <span className="toggle-slider" />
              </label>
            </div>

            <div className="setting-toggle-row">
              <div>
                <div className="setting-row-title">Portfolio sync</div>
                <div className="setting-row-desc">Every 60 sec · While the broker is connected</div>
              </div>
              <label className="toggle-switch">
                <input
                  type="checkbox"
                  checked={jobPortfolioSync}
                  onChange={(e) => setJobPortfolioSync(e.target.checked)}
                />
                <span className="toggle-slider" />
              </label>
            </div>

            {/* NEXT RUN Box */}
            <div style={{
              background: '#f8faf9',
              border: '1px solid var(--border)',
              borderRadius: 8,
              padding: '12px 14px',
              marginTop: 14,
            }}>
              <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.8px', color: '#64748b', textTransform: 'uppercase' }}>
                NEXT RUN
              </div>
              <div style={{ fontSize: 13, fontWeight: 600, color: '#0f172a', marginTop: 2 }}>
                Entry confirmation · 09:45 AEDT
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
          These actions interrupt trading or permanently remove simulation data.
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
              <span className="desktop-save-text">All changes saved · Last updated 12 Nov 2026, 09:30 AEDT</span>
              <span className="mobile-save-text">Last saved 09:30 AEDT</span>
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

        @media (max-width: 900px) {
          .settings-columns-grid {
            grid-template-columns: 1fr;
            gap: 20px;
          }
          .danger-zone-actions-grid {
            grid-template-columns: 1fr;
            gap: 12px;
          }
        }

        @media (max-width: 768px) {
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
