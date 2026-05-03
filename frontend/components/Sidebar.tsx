'use client';

import { Tab } from '@/app/page';

interface Props {
  activeTab: Tab;
  setActiveTab: (tab: Tab) => void;
  tradingMode: 'paper' | 'live';
  username?: string;
  onLogout: () => void;
  isOpen?: boolean;
}

const navItems: { id: Tab; icon: string; label: string }[] = [
  { id: 'portfolio', icon: '📊', label: 'Portfolio' },
  { id: 'trades', icon: '📋', label: 'Trade History' },
  { id: 'logs', icon: '🖥️', label: 'System Logs' },
  { id: 'settings', icon: '⚙️', label: 'Settings' },
];

export default function Sidebar({ activeTab, setActiveTab, tradingMode, username, onLogout, isOpen }: Props) {
  return (
    <nav className={`sidebar ${isOpen ? 'open' : ''}`}>
      <div className="sidebar-logo">
        <div className="sidebar-logo-icon">⚡</div>
        <h1>Blitz Trader</h1>
        <p>Automated NASDAQ Bot</p>
      </div>

      <div className="sidebar-nav">
        <div className="sidebar-nav-label">Navigation</div>
        {navItems.map((item) => (
          <button
            key={item.id}
            className={`nav-item ${activeTab === item.id ? 'active' : ''}`}
            onClick={() => setActiveTab(item.id)}
            id={`nav-${item.id}`}
          >
            <span className="nav-icon">{item.icon}</span>
            {item.label}
          </button>
        ))}
      </div>

      <div className="sidebar-status">
        <div
          className={`mode-indicator ${tradingMode}`}
          style={{ marginBottom: 10, justifyContent: 'center' }}
        >
          {tradingMode === 'live' ? '🔴 LIVE TRADING' : '🟡 PAPER TRADING'}
        </div>
        <div className="status-badge" style={{ flexDirection: 'column', alignItems: 'flex-start', gap: 8 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, width: '100%' }}>
            <div className="status-dot connected" />
            <div className="status-badge-text" style={{ flex: 1 }}>
              <span className="label">Signed in as</span>
              <span className="value" style={{ fontSize: 12, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 140, display: 'block' }}>
                {username ?? '—'}
              </span>
            </div>
          </div>
          <button
            id="btn-logout"
            onClick={onLogout}
            style={{
              width: '100%',
              background: 'rgba(239,68,68,0.08)',
              border: '1px solid rgba(239,68,68,0.2)',
              borderRadius: 6,
              color: 'var(--accent-red)',
              fontSize: 12,
              fontWeight: 600,
              padding: '7px 0',
              cursor: 'pointer',
              transition: 'background 0.15s',
            }}
            onMouseEnter={e => (e.currentTarget.style.background = 'rgba(239,68,68,0.16)')}
            onMouseLeave={e => (e.currentTarget.style.background = 'rgba(239,68,68,0.08)')}
          >
            Sign Out
          </button>
        </div>
      </div>
    </nav>
  );
}
