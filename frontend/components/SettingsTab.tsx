'use client';

import { useEffect, useState, useCallback } from 'react';

interface Settings {
  trading_mode: string;
  daily_budget_pct: string;
  max_positions: string;
  scan_enabled: string;
}

interface Props {
  onModeChange: (mode: 'paper' | 'live') => void;
}

export default function SettingsTab({ onModeChange }: Props) {
  const [settings, setSettings] = useState<Settings>({
    trading_mode: 'paper',
    daily_budget_pct: '100',
    max_positions: '5',
    scan_enabled: 'true',
  });
  const [saving, setSaving] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [selling, setSelling] = useState(false);
  const [saveMsg, setSaveMsg] = useState('');
  const [showLiveWarning, setShowLiveWarning] = useState(false);
  const [pendingMode, setPendingMode] = useState<'paper' | 'live' | null>(null);
  const [showSellAllConfirm, setShowSellAllConfirm] = useState(false);

  const fetchSettings = useCallback(async () => {
    const res = await fetch('/api/settings');
    const data = await res.json();
    setSettings(data);
  }, []);

  useEffect(() => {
    fetchSettings();
  }, [fetchSettings]);

  const save = async (patch: Partial<Settings>) => {
    setSaving(true);
    setSaveMsg('');
    try {
      const res = await fetch('/api/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
      });
      if (res.ok) {
        setSettings((prev) => ({ ...prev, ...patch }));
        setSaveMsg('✅ Saved successfully');
        if (patch.trading_mode) {
          onModeChange(patch.trading_mode as 'paper' | 'live');
        }
      } else {
        setSaveMsg('❌ Save failed. Please try again.');
      }
    } catch {
      setSaveMsg('❌ Network error.');
    } finally {
      setSaving(false);
      setTimeout(() => setSaveMsg(''), 3000);
    }
  };

  const handleModeToggle = (checked: boolean) => {
    if (checked) {
      // Switching to live — show confirmation
      setPendingMode('live');
      setShowLiveWarning(true);
    } else {
      save({ trading_mode: 'paper' });
    }
  };

  const confirmLive = () => {
    setShowLiveWarning(false);
    save({ trading_mode: 'live' });
    setPendingMode(null);
  };

  const cancelLive = () => {
    setShowLiveWarning(false);
    setPendingMode(null);
  };

  const triggerScan = async () => {
    setScanning(true);
    try {
      await fetch('/api/scan', { method: 'POST' });
      setSaveMsg('✅ Scan triggered! Check System Logs for progress.');
    } catch {
      setSaveMsg('❌ Failed to trigger scan.');
    } finally {
      setScanning(false);
      setTimeout(() => setSaveMsg(''), 5000);
    }
  };

  const sellAllIBKR = async () => {
    setShowSellAllConfirm(false);
    setSelling(true);
    setSaveMsg('');
    try {
      const res = await fetch('/api/sell-all-ibkr', { method: 'POST' });
      const data = await res.json();
      if (!res.ok) {
        setSaveMsg(`❌ Sell failed: ${data.detail || 'Unknown error'}`);
        return;
      }
      const results: Array<{success: boolean; ticker: string; shares?: number; price?: number; error?: string}> = data.results ?? [];
      if (results.length === 0) {
        setSaveMsg('ℹ️ No open IBKR positions to sell.');
      } else {
        const sold = results.filter((r) => r.success).map((r) => r.ticker).join(', ');
        const failed = results.filter((r) => !r.success).map((r) => r.ticker).join(', ');
        setSaveMsg(
          sold
            ? `✅ Sold: ${sold}${failed ? ` | ❌ Failed: ${failed}` : ''}`
            : `❌ All sells failed: ${failed}`
        );
      }
    } catch {
      setSaveMsg('❌ Network error during sell-all.');
    } finally {
      setSelling(false);
      setTimeout(() => setSaveMsg(''), 8000);
    }
  };

  const isLive = settings.trading_mode === 'live';
  const budgetPct = parseInt(settings.daily_budget_pct, 10) || 100;
  const maxPos = parseInt(settings.max_positions, 10) || 5;
  const scanEnabled = settings.scan_enabled === 'true';

  return (
    <div>
      <div className="page-header">
        <h2>Settings</h2>
        <p>Configure trading behaviour and system preferences</p>
      </div>

      {/* Live trading warning confirmation modal */}
      {showLiveWarning && (
        <div
          style={{
            position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            zIndex: 1000,
          }}
        >
          <div
            style={{
              background: 'var(--bg-card)',
              border: '1px solid rgba(239,68,68,0.4)',
              borderRadius: 16,
              padding: 32,
              maxWidth: 440,
              width: '90%',
            }}
          >
            <div style={{ fontSize: 32, marginBottom: 16, textAlign: 'center' }}>⚠️</div>
            <h3 style={{ fontSize: 18, fontWeight: 700, marginBottom: 12, color: 'var(--accent-red)' }}>
              Switch to Live Trading?
            </h3>
            <p style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.7, marginBottom: 24 }}>
              You are about to switch from <strong>Paper Trading</strong> to <strong style={{ color: 'var(--accent-red)' }}>Live Trading</strong>.
              This means <strong>real money</strong> will be used for all future trades.
              Ensure your IBKR account has sufficient funds and market data subscriptions.
            </p>
            <div style={{ display: 'flex', gap: 12, justifyContent: 'flex-end' }}>
              <button
                id="btn-cancel-live"
                className="btn btn-outline"
                onClick={cancelLive}
              >
                Cancel — Keep Paper
              </button>
              <button
                id="btn-confirm-live"
                className="btn btn-danger"
                onClick={confirmLive}
              >
                Yes, Switch to Live
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Sell All IBKR Confirmation Modal */}
      {showSellAllConfirm && (
        <div
          style={{
            position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.75)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            zIndex: 1000,
          }}
        >
          <div
            style={{
              background: 'var(--bg-card)',
              border: '1px solid rgba(239,68,68,0.5)',
              borderRadius: 16,
              padding: 32,
              maxWidth: 460,
              width: '90%',
            }}
          >
            <div style={{ fontSize: 36, marginBottom: 16, textAlign: 'center' }}>🚨</div>
            <h3 style={{ fontSize: 18, fontWeight: 700, marginBottom: 12, color: 'var(--accent-red)', textAlign: 'center' }}>
              Sell All IBKR Positions?
            </h3>
            <p style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.7, marginBottom: 8 }}>
              This will immediately place <strong>market SELL orders</strong> for every open position
              in your IBKR account — including positions not tracked by the bot.
            </p>
            <p style={{ fontSize: 13, color: 'var(--accent-red)', fontWeight: 600, marginBottom: 24 }}>
              ⚠️ This action cannot be undone and executes instantly.
            </p>
            <div style={{ display: 'flex', gap: 12, justifyContent: 'flex-end' }}>
              <button
                id="btn-cancel-sell-all"
                className="btn btn-outline"
                onClick={() => setShowSellAllConfirm(false)}
              >
                Cancel
              </button>
              <button
                id="btn-confirm-sell-all"
                className="btn btn-danger"
                onClick={sellAllIBKR}
              >
                Yes, Sell Everything Now
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Trading Mode */}
      <div className="settings-section">
        <h3>Trading Mode</h3>
        <p>Switch between paper (simulated) and live (real money) trading.</p>

        <div className="setting-row">
          <div className="setting-info">
            <div className="setting-label">
              Live Trading
              <span
                className={`badge ${isLive ? 'live' : 'paper'}`}
                style={{ marginLeft: 10, fontSize: 10 }}
              >
                {isLive ? '🔴 LIVE' : '🟡 PAPER'}
              </span>
            </div>
            <div className="setting-desc">
              {isLive
                ? 'Real money mode — trades will execute with actual funds.'
                : 'Paper mode — all trades are simulated with no real money.'}
            </div>
          </div>
          <label className="toggle" id="toggle-trading-mode">
            <input
              type="checkbox"
              checked={isLive}
              onChange={(e) => handleModeToggle(e.target.checked)}
              disabled={saving}
            />
            <span className="toggle-slider" />
          </label>
        </div>
      </div>

      {/* Budget */}
      <div className="settings-section">
        <h3>Daily Budget</h3>
        <p>How much of your available cash the bot is allowed to use each trading day.</p>

        <div className="setting-row">
          <div className="setting-info">
            <div className="setting-label">Daily Cash Budget</div>
            <div className="setting-desc">Percentage of available IBKR cash used for buying stocks today.</div>
          </div>
          <div className="range-container">
            <input
              id="range-budget"
              type="range"
              min={5}
              max={100}
              step={5}
              value={budgetPct}
              onChange={(e) => {
                setSettings((prev) => ({ ...prev, daily_budget_pct: e.target.value }));
              }}
              onMouseUp={(e) => save({ daily_budget_pct: (e.target as HTMLInputElement).value })}
              onTouchEnd={(e) => save({ daily_budget_pct: (e.target as HTMLInputElement).value })}
            />
            <div className="range-value">{budgetPct}%</div>
          </div>
        </div>

        <div className="setting-row">
          <div className="setting-info">
            <div className="setting-label">Max Simultaneous Positions</div>
            <div className="setting-desc">Maximum number of stocks to hold at once (budget is split equally).</div>
          </div>
          <div className="range-container">
            <input
              id="range-max-positions"
              type="range"
              min={1}
              max={10}
              step={1}
              value={maxPos}
              onChange={(e) => {
                setSettings((prev) => ({ ...prev, max_positions: e.target.value }));
              }}
              onMouseUp={(e) => save({ max_positions: (e.target as HTMLInputElement).value })}
              onTouchEnd={(e) => save({ max_positions: (e.target as HTMLInputElement).value })}
            />
            <div className="range-value">{maxPos}</div>
          </div>
        </div>
      </div>

      {/* Scanner */}
      <div className="settings-section">
        <h3>Scanner &amp; Automation</h3>
        <p>Control the daily automated scanning and trading schedule.</p>

        <div className="setting-row">
          <div className="setting-info">
            <div className="setting-label">Auto-Scan Enabled</div>
            <div className="setting-desc">Run the AI stock scan automatically at 09:20 ET on trading days.</div>
          </div>
          <label className="toggle" id="toggle-scan-enabled">
            <input
              type="checkbox"
              checked={scanEnabled}
              onChange={(e) => save({ scan_enabled: e.target.checked ? 'true' : 'false' })}
              disabled={saving}
            />
            <span className="toggle-slider" />
          </label>
        </div>

        <div className="setting-row">
          <div className="setting-info">
            <div className="setting-label">Manual Scan Trigger</div>
            <div className="setting-desc">
              Run the AI market scan right now and place buy orders immediately.
              Only works during market hours (09:30–16:00 ET).
            </div>
          </div>
          <button
            id="btn-trigger-scan"
            className="btn btn-primary"
            onClick={triggerScan}
            disabled={scanning}
          >
            {scanning ? '⏳ Scanning...' : '🔍 Run Scan Now'}
          </button>
        </div>
      </div>

      {/* Danger Zone */}
      <div className="settings-section" style={{ borderColor: 'rgba(239,68,68,0.3)' }}>
        <h3 style={{ color: 'var(--accent-red)' }}>⚠️ Danger Zone</h3>
        <p>Irreversible actions — use with caution.</p>

        <div className="setting-row">
          <div className="setting-info">
            <div className="setting-label">Sell All IBKR Positions</div>
            <div className="setting-desc">
              Immediately places market sell orders for <strong>every open position</strong> in your
              IBKR account. Useful for emergency exits or end-of-day manual liquidation.
            </div>
          </div>
          <button
            id="btn-sell-all-ibkr"
            className="btn btn-danger"
            onClick={() => setShowSellAllConfirm(true)}
            disabled={selling}
          >
            {selling ? '⏳ Selling...' : '🚨 Sell All Now'}
          </button>
        </div>
      </div>

      {/* Scheduled jobs info */}
      <div className="settings-section">
        <h3>Scheduled Jobs</h3>
        <p>The bot runs these jobs automatically every weekday in Eastern Time (New York).</p>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 4 }}>
          {[
            { time: '09:20 ET', action: 'AI Market Scan + Buy Orders', icon: '🔍', color: 'var(--cat-scan)' },
            { time: '15:50 ET', action: 'Sell All Open Positions', icon: '💰', color: 'var(--cat-sell)' },
          ].map((job) => (
            <div
              key={job.time}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 16,
                padding: '12px 16px',
                background: 'var(--bg-secondary)',
                borderRadius: 8,
                border: '1px solid var(--border)',
              }}
            >
              <span style={{ fontSize: 20 }}>{job.icon}</span>
              <div>
                <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>
                  {job.time}
                </div>
                <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>
                  {job.action}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Save feedback */}
      {saveMsg && (
        <div
          style={{
            position: 'fixed',
            bottom: 24, right: 24,
            background: 'var(--bg-card)',
            border: '1px solid var(--border-bright)',
            borderRadius: 10,
            padding: '12px 20px',
            fontSize: 13,
            fontWeight: 500,
            color: 'var(--text-primary)',
            zIndex: 100,
            boxShadow: '0 8px 32px rgba(0,0,0,0.4)',
            animation: 'fadeInUp 0.2s ease',
          }}
        >
          {saveMsg}
        </div>
      )}
    </div>
  );
}
