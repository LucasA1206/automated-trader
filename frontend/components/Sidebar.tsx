'use client';

import { Tab } from '@/app/page';

interface Props {
  activeTab: Tab;
  setActiveTab: (tab: Tab) => void;
  tradingMode: 'paper' | 'live';
}

const navItems: { id: Tab; icon: string; label: string }[] = [
  { id: 'portfolio', icon: '📊', label: 'Portfolio' },
  { id: 'trades', icon: '📋', label: 'Trade History' },
  { id: 'logs', icon: '🖥️', label: 'System Logs' },
  { id: 'settings', icon: '⚙️', label: 'Settings' },
];

export default function Sidebar({ activeTab, setActiveTab, tradingMode }: Props) {
  return (
    <nav className="sidebar">
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
        <div className="status-badge">
          <div className="status-dot connected" />
          <div className="status-badge-text">
            <span className="label">System</span>
            <span className="value">Running</span>
          </div>
        </div>
      </div>
    </nav>
  );
}
