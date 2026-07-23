'use client';

import { useEffect, useState, useCallback } from 'react';

interface Settings {
  trading_mode: string;
  paper_strategy: string;
  daily_budget_pct: string;
  max_positions: string;
  scan_enabled: string;
  trader_enabled: string;
  account_type: string;
  entry_macd_check?: string;
  entry_min_rel_vol?: string;
  entry_rsi_min?: string;
  entry_rsi_max?: string;
  entry_pullback_max_pct?: string;
  entry_vwap_required?: string;
  entry_adx_min?: string;
}

type AuthFetch = (url: string, init?: RequestInit) => Promise<Response>;

interface Props {
  onModeChange: (mode: 'paper' | 'live') => void;
  authFetch: AuthFetch;
}

export default function SettingsTab({ onModeChange, authFetch }: Props) {
  const [settings, setSettings] = useState<Settings>({
    trading_mode: 'paper',
    paper_strategy: 'cash',
    daily_budget_pct: '100',
    max_positions: '8',
    scan_enabled: 'true',
    trader_enabled: 'true',
    account_type: 'trading_cash',
    entry_macd_check: 'false',
    entry_min_rel_vol: '0.4',
    entry_rsi_min: '30',
    entry_rsi_max: '70',
    entry_pullback_max_pct: '5.0',
    entry_vwap_required: 'false',
    entry_adx_min: '15',
  });
  const [saving, setSaving] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [runningEntryMonitor, setRunningEntryMonitor] = useState(false);
  const [selling, setSelling] = useState(false);
  const [saveMsg, setSaveMsg] = useState('');
  const [showLiveWarning, setShowLiveWarning] = useState(false);
  const [pendingMode, setPendingMode] = useState<'paper' | 'live' | null>(null);
  const [showSellAllConfirm, setShowSellAllConfirm] = useState(false);

  const fetchSettings = useCallback(async () => {
    const res = await authFetch('/api/settings');
    const data = await res.json();
    setSettings(data);
  }, [authFetch]);

  useEffect(() => {
    fetchSettings();
  }, [fetchSettings]);

  useEffect(() => {
    const checkStatus = async () => {
      try {
        const res = await authFetch('/api/scan/status');
        if (res.ok) {
          const data = await res.json();
          setScanning(data.running);
        }
      } catch (err) {
        console.error("Failed to check scan status:", err);
      }
    };
    checkStatus();
    const interval = setInterval(checkStatus, 2000);
    return () => clearInterval(interval);
  }, [authFetch]);

  const save = async (patch: Partial<Settings>) => {
    setSaving(true);
    setSaveMsg('');
    try {
      const res = await authFetch('/api/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
      });
      if (res.ok) {
        await fetchSettings();
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
      await authFetch('/api/scan', { method: 'POST' });
      setSaveMsg('✅ Scan triggered! Check System Logs for progress.');
    } catch {
      setSaveMsg('❌ Failed to trigger scan.');
      setScanning(false);
    }
    setTimeout(() => setSaveMsg(''), 5000);
  };

  const stopScan = async () => {
    try {
      await authFetch('/api/scan/stop', { method: 'POST' });
      setSaveMsg('🛑 Scan cancellation requested.');
    } catch {
      setSaveMsg('❌ Failed to stop scan.');
    }
    setTimeout(() => setSaveMsg(''), 5000);
  };

  const triggerEntryMonitor = async (force = true) => {
    setRunningEntryMonitor(true);
    setSaveMsg('');
    try {
      const res = await authFetch(`/api/entry-monitor?force=${force}`, { method: 'POST' });
      const data = await res.json();
      if (res.ok) {
        setSaveMsg(`⚡ ${data.message || 'Buy round completed.'} (${data.placed || 0} order(s) placed)`);
      } else {
        setSaveMsg(`❌ Buy round failed: ${data.detail || 'Unknown error'}`);
      }
    } catch {
      setSaveMsg('❌ Network error during buy round.');
    } finally {
      setRunningEntryMonitor(false);
      setTimeout(() => setSaveMsg(''), 6000);
    }
  };

  const sellAllIBKR = async () => {
    setShowSellAllConfirm(false);
    setSelling(true);
    setSaveMsg('');
    try {
      const res = await authFetch('/api/sell-all-ibkr', { method: 'POST' });
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
  const isTradingCash = settings.account_type === 'trading_cash';
  const paperStrategy = settings.paper_strategy === 'margin' ? 'margin' : 'cash';
  const scanEnabled = settings.scan_enabled === 'true';
  const traderEnabled = settings.trader_enabled === 'true';

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

      {/* Account Type */}
      <div className="settings-section">
        <h3>IBKR Account Type</h3>
        <p>
          Your live IBKR account is cash-only, so this setting reflects the actual account type rather than a margin strategy.
        </p>

        <div className="setting-row">
          <div className="setting-info">
            <div className="setting-label">
              Trading Account
              <span
                className={`badge ${isTradingCash ? 'paper' : 'live'}`}
                style={{ marginLeft: 10, fontSize: 10 }}
              >
                {isTradingCash ? 'TRADING ACCOUNT (CASH)' : 'INVESTMENT ACCOUNT (CASH)'}
              </span>
            </div>
            <div className="setting-desc">
              {isTradingCash
                ? 'Trading Account (Cash) is suited to active trading and settled-cash rotation.'
                : 'Investment Account (Cash) is the other cash-only IBKR account type.'}
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              className={`filter-btn ${isTradingCash ? 'active' : ''}`}
              onClick={() => save({ account_type: 'trading_cash' })}
              disabled={saving}
            >
              Trading Account (Cash)
            </button>
            <button
              className={`filter-btn ${!isTradingCash ? 'active' : ''}`}
              onClick={() => save({ account_type: 'investment_cash' })}
              disabled={saving}
            >
              Investment Account (Cash)
            </button>
          </div>
        </div>

        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
            gap: 12,
            marginTop: 16,
          }}
        >
          <div
            style={{
              background: 'var(--bg-secondary)',
              border: '1px solid var(--border)',
              borderRadius: 12,
              padding: '14px 16px',
            }}
          >
            <div style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
              Daily Budget (%)
            </div>
            <div style={{ marginTop: 6 }}>
              <input
                type="number"
                min="1"
                max="100"
                value={settings.daily_budget_pct}
                onChange={(e) => setSettings({...settings, daily_budget_pct: e.target.value})}
                onBlur={(e) => save({ daily_budget_pct: e.target.value })}
                disabled={saving}
                style={{
                  background: 'var(--bg-card)',
                  border: '1px solid var(--border-bright)',
                  color: 'var(--text-primary)',
                  padding: '4px 8px',
                  borderRadius: 6,
                  fontSize: 18,
                  fontWeight: 700,
                  width: '80px',
                  outline: 'none'
                }}
              />
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>
              of available cash for the daily buy cycle
            </div>
          </div>
          <div
            style={{
              background: 'var(--bg-secondary)',
              border: '1px solid var(--border)',
              borderRadius: 12,
              padding: '14px 16px',
            }}
          >
            <div style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
              Stocks Per Day
            </div>
            <div style={{ marginTop: 6 }}>
              <input
                type="number"
                min="1"
                max="50"
                value={settings.max_positions}
                onChange={(e) => setSettings({...settings, max_positions: e.target.value})}
                onBlur={(e) => save({ max_positions: e.target.value })}
                disabled={saving}
                style={{
                  background: 'var(--bg-card)',
                  border: '1px solid var(--border-bright)',
                  color: 'var(--text-primary)',
                  padding: '4px 8px',
                  borderRadius: 6,
                  fontSize: 18,
                  fontWeight: 700,
                  width: '80px',
                  outline: 'none'
                }}
              />
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>
              maximum picks the bot will buy in one scan
            </div>
          </div>
          <div
            style={{
              background: 'rgba(59,130,246,0.08)',
              border: '1px solid rgba(59,130,246,0.2)',
              borderRadius: 12,
              padding: '14px 16px',
            }}
          >
            <div style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
              Live Threshold
            </div>
            <div style={{ fontSize: 22, fontWeight: 700, marginTop: 6 }}>
              $25,000
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>
              Cash strategy shows a one-time upgrade alert on the Portfolio screen once live equity crosses this level.
            </div>
          </div>
        </div>

        {settings.trading_mode === 'paper' && (
          <div style={{ marginTop: 14, padding: '12px 14px', borderRadius: 10, background: 'rgba(34,197,94,0.08)', border: '1px solid rgba(34,197,94,0.18)', color: 'var(--text-primary)', fontSize: 13, lineHeight: 1.6 }}>
            Paper mode can still simulate either Cash or Margin strategy in the section below, so you can compare growth without placing real orders.
          </div>
        )}
      </div>

      <div className="settings-section">
        <h3>Paper Simulation Strategy</h3>
        <p>Use this to compare Cash versus Margin growth in paper trading. Live trading stays cash-only.</p>

        <div className="setting-row">
          <div className="setting-info">
            <div className="setting-label">
              Paper Strategy
              <span
                className={`badge ${paperStrategy === 'cash' ? 'paper' : 'live'}`}
                style={{ marginLeft: 10, fontSize: 10 }}
              >
                {paperStrategy === 'cash' ? 'CASH' : 'MARGIN'}
              </span>
            </div>
            <div className="setting-desc">
              {paperStrategy === 'cash'
                ? 'Cash simulation: 3 stocks per day using 50% of cash.'
                : 'Margin simulation: 5 stocks per day using 100% of available funds.'}
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              className={`filter-btn ${paperStrategy === 'cash' ? 'active' : ''}`}
              onClick={() => save({ paper_strategy: 'cash' })}
              disabled={saving}
            >
              Cash
            </button>
            <button
              className={`filter-btn ${paperStrategy === 'margin' ? 'active' : ''}`}
              onClick={() => save({ paper_strategy: 'margin' })}
              disabled={saving}
            >
              Margin
            </button>
          </div>
        </div>

        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
            gap: 12,
            marginTop: 16,
          }}
        >
          <div
            style={{
              background: 'var(--bg-secondary)',
              border: '1px solid var(--border)',
              borderRadius: 12,
              padding: '14px 16px',
            }}
          >
            <div style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
              Daily Budget (%)
            </div>
            <div style={{ marginTop: 6 }}>
              <input
                type="number"
                min="1"
                max="100"
                value={settings.daily_budget_pct}
                onChange={(e) => setSettings({...settings, daily_budget_pct: e.target.value})}
                onBlur={(e) => save({ daily_budget_pct: e.target.value })}
                disabled={saving}
                style={{
                  background: 'var(--bg-card)',
                  border: '1px solid var(--border-bright)',
                  color: 'var(--text-primary)',
                  padding: '4px 8px',
                  borderRadius: 6,
                  fontSize: 18,
                  fontWeight: 700,
                  width: '80px',
                  outline: 'none'
                }}
              />
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>
              of available cash for the daily buy cycle
            </div>
          </div>
          <div
            style={{
              background: 'var(--bg-secondary)',
              border: '1px solid var(--border)',
              borderRadius: 12,
              padding: '14px 16px',
            }}
          >
            <div style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
              Stocks Per Day
            </div>
            <div style={{ marginTop: 6 }}>
              <input
                type="number"
                min="1"
                max="50"
                value={settings.max_positions}
                onChange={(e) => setSettings({...settings, max_positions: e.target.value})}
                onBlur={(e) => save({ max_positions: e.target.value })}
                disabled={saving}
                style={{
                  background: 'var(--bg-card)',
                  border: '1px solid var(--border-bright)',
                  color: 'var(--text-primary)',
                  padding: '4px 8px',
                  borderRadius: 6,
                  fontSize: 18,
                  fontWeight: 700,
                  width: '80px',
                  outline: 'none'
                }}
              />
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>
              maximum picks the bot will buy in one scan
            </div>
          </div>
          <div
            style={{
              background: 'rgba(59,130,246,0.08)',
              border: '1px solid rgba(59,130,246,0.2)',
              borderRadius: 12,
              padding: '14px 16px',
            }}
          >
            <div style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
              Live Threshold
            </div>
            <div style={{ fontSize: 22, fontWeight: 700, marginTop: 6 }}>
              $25,000
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>
              Live cash accounts show an alert here once they cross this level.
            </div>
          </div>
        </div>
      </div>

      {/* Scanner */}
      <div className="settings-section">
        <h3 style={{ color: 'var(--accent-blue)' }}>Master Controls &amp; Automation</h3>
        <p>Control the daily automated scanning and trading schedule.</p>

        <div className="setting-row">
          <div className="setting-info">
            <div className="setting-label">Trader Enabled (Master Switch)</div>
            <div className="setting-desc">If turned off, the bot will NOT scan, buy, or sell. It will sit completely idle.</div>
          </div>
          <label className="toggle toggle-master" id="toggle-trader-enabled">
            <input
              type="checkbox"
              checked={traderEnabled}
              onChange={(e) => save({ trader_enabled: e.target.checked ? 'true' : 'false' })}
              disabled={saving}
            />
            <span className="toggle-slider" />
          </label>
        </div>

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
            onClick={scanning ? stopScan : triggerScan}
            style={scanning ? { backgroundColor: 'var(--accent-red)', borderColor: 'var(--accent-red)' } : {}}
          >
            {scanning ? '🛑 Stop Running Scan' : '🔍 Run Scan Now'}
          </button>
        </div>

        <div className="setting-row">
          <div className="setting-info">
            <div className="setting-label">Run Buy Round (Retry Pending Entries)</div>
            <div className="setting-desc">
              Evaluate all pending candidate stocks that passed pre-market scan and attempt buy orders immediately.
              Useful after loosening restrictions or retrying staged candidates.
            </div>
          </div>
          <button
            id="btn-trigger-buy-round"
            className="btn btn-primary"
            onClick={() => triggerEntryMonitor(true)}
            disabled={runningEntryMonitor}
            style={{ backgroundColor: '#22c55e', borderColor: '#22c55e' }}
          >
            {runningEntryMonitor ? '⏳ Processing Buy Round...' : '⚡ Run Buy Round Now'}
          </button>
        </div>
      </div>

      {/* Entry Confirmation Rules */}
      <div className="settings-section">
        <h3 style={{ color: 'var(--accent-green, #22c55e)' }}>Entry Confirmation Rules (Intraday Filters)</h3>
        <p>Fine-tune the intraday hurdle requirements for placing buy orders on pre-scanned candidates.</p>

        <div className="setting-row">
          <div className="setting-info">
            <div className="setting-label">Intraday MACD Histogram Turning Check</div>
            <div className="setting-desc">
              Require 15-min MACD histogram to be positive or turning upward.
              (Turn OFF / set to false to avoid blocking candidates during healthy intraday pullbacks).
            </div>
          </div>
          <label className="toggle" id="toggle-entry-macd">
            <input
              type="checkbox"
              checked={settings.entry_macd_check === 'true'}
              onChange={(e) => save({ entry_macd_check: e.target.checked ? 'true' : 'false' })}
              disabled={saving}
            />
            <span className="toggle-slider" />
          </label>
        </div>

        <div className="setting-row">
          <div className="setting-info">
            <div className="setting-label">Require VWAP Reclaim</div>
            <div className="setting-desc">Require current stock price to be strictly above today's VWAP before entry.</div>
          </div>
          <label className="toggle" id="toggle-entry-vwap">
            <input
              type="checkbox"
              checked={settings.entry_vwap_required === 'true'}
              onChange={(e) => save({ entry_vwap_required: e.target.checked ? 'true' : 'false' })}
              disabled={saving}
            />
            <span className="toggle-slider" />
          </label>
        </div>

        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
            gap: 12,
            marginTop: 16,
          }}
        >
          <div style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 12, padding: '14px 16px' }}>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
              Min Relative Vol (x)
            </div>
            <div style={{ marginTop: 6 }}>
              <input
                type="number"
                step="0.1"
                min="0.1"
                max="5.0"
                value={settings.entry_min_rel_vol ?? '0.4'}
                onChange={(e) => setSettings({...settings, entry_min_rel_vol: e.target.value})}
                onBlur={(e) => save({ entry_min_rel_vol: e.target.value })}
                disabled={saving}
                style={{ background: 'var(--bg-card)', border: '1px solid var(--border-bright)', color: 'var(--text-primary)', padding: '4px 8px', borderRadius: 6, fontSize: 16, fontWeight: 700, width: '90px', outline: 'none' }}
              />
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>Lower threshold allows buying pullbacks on lighter volume</div>
          </div>

          <div style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 12, padding: '14px 16px' }}>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
              RSI Range (Min – Max)
            </div>
            <div style={{ marginTop: 6, display: 'flex', gap: 6, alignItems: 'center' }}>
              <input
                type="number"
                min="10"
                max="90"
                value={settings.entry_rsi_min ?? '30'}
                onChange={(e) => setSettings({...settings, entry_rsi_min: e.target.value})}
                onBlur={(e) => save({ entry_rsi_min: e.target.value })}
                disabled={saving}
                style={{ background: 'var(--bg-card)', border: '1px solid var(--border-bright)', color: 'var(--text-primary)', padding: '4px 8px', borderRadius: 6, fontSize: 16, fontWeight: 700, width: '65px', outline: 'none' }}
              />
              <span style={{ color: 'var(--text-muted)' }}>–</span>
              <input
                type="number"
                min="10"
                max="90"
                value={settings.entry_rsi_max ?? '70'}
                onChange={(e) => setSettings({...settings, entry_rsi_max: e.target.value})}
                onBlur={(e) => save({ entry_rsi_max: e.target.value })}
                disabled={saving}
                style={{ background: 'var(--bg-card)', border: '1px solid var(--border-bright)', color: 'var(--text-primary)', padding: '4px 8px', borderRadius: 6, fontSize: 16, fontWeight: 700, width: '65px', outline: 'none' }}
              />
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>Allowed intraday RSI window</div>
          </div>

          <div style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 12, padding: '14px 16px' }}>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
              Max Pullback % (20d SMA)
            </div>
            <div style={{ marginTop: 6 }}>
              <input
                type="number"
                step="0.5"
                min="1.0"
                max="15.0"
                value={settings.entry_pullback_max_pct ?? '5.0'}
                onChange={(e) => setSettings({...settings, entry_pullback_max_pct: e.target.value})}
                onBlur={(e) => save({ entry_pullback_max_pct: e.target.value })}
                disabled={saving}
                style={{ background: 'var(--bg-card)', border: '1px solid var(--border-bright)', color: 'var(--text-primary)', padding: '4px 8px', borderRadius: 6, fontSize: 16, fontWeight: 700, width: '90px', outline: 'none' }}
              />
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>Max % price can be above 20-day SMA</div>
          </div>

          <div style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 12, padding: '14px 16px' }}>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
              Min ADX Threshold
            </div>
            <div style={{ marginTop: 6 }}>
              <input
                type="number"
                min="5"
                max="50"
                value={settings.entry_adx_min ?? '15'}
                onChange={(e) => setSettings({...settings, entry_adx_min: e.target.value})}
                onBlur={(e) => save({ entry_adx_min: e.target.value })}
                disabled={saving}
                style={{ background: 'var(--bg-card)', border: '1px solid var(--border-bright)', color: 'var(--text-primary)', padding: '4px 8px', borderRadius: 6, fontSize: 16, fontWeight: 700, width: '90px', outline: 'none' }}
              />
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>Trend strength minimum threshold</div>
          </div>
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
            { time: '15:30 ET', action: 'Sell All Open Positions', icon: '💰', color: 'var(--cat-sell)' },
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
