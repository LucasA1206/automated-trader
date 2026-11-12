'use client';

import React from 'react';
import { Tab } from '@/app/page';

interface Props {
  activeTab: Tab;
  setActiveTab: (tab: Tab) => void;
  tradingMode: 'paper' | 'live';
  username?: string;
  onLogout: () => void;
  isOpen?: boolean;
  onCloseMobile?: () => void;
  isCollapsed?: boolean;
  onToggleCollapse?: () => void;
}

interface NavItemDef {
  id: Tab;
  label: string;
  icon: React.ReactNode;
}

export const navItems: NavItemDef[] = [
  {
    id: 'portfolio',
    label: 'Portfolio',
    icon: (
      <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="2" y="7" width="20" height="14" rx="2" ry="2" />
        <path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16" />
      </svg>
    ),
  },
  {
    id: 'trades',
    label: 'Trade History',
    icon: (
      <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <polyline points="1 4 1 10 7 10" />
        <path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10" />
      </svg>
    ),
  },
  {
    id: 'ai-analysis',
    label: 'AI Stock Analysis',
    icon: (
      <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 2L14.5 9.5L22 12L14.5 14.5L12 22L9.5 14.5L2 12L9.5 9.5L12 2Z" />
      </svg>
    ),
  },
  {
    id: 'logs',
    label: 'System Logs',
    icon: (
      <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
        <polyline points="14 2 14 8 20 8" />
        <line x1="16" y1="13" x2="8" y2="13" />
        <line x1="16" y1="17" x2="8" y2="17" />
        <polyline points="10 9 9 9 8 9" />
      </svg>
    ),
  },
  {
    id: 'settings',
    label: 'Settings',
    icon: (
      <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="3" />
        <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
      </svg>
    ),
  },
];

export default function Sidebar({
  activeTab,
  setActiveTab,
  tradingMode,
  username,
  onLogout,
  isOpen = false,
  onCloseMobile,
  isCollapsed = false,
  onToggleCollapse,
}: Props) {
  const brandIcon = (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#10b981" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="23 6 13.5 15.5 8.5 10.5 1 18" />
      <polyline points="17 6 23 6 23 12" />
    </svg>
  );

  return (
    <>
      {/* ── Desktop Sidebar ───────────────────────────────────── */}
      <aside className={`sidebar-root desktop-only ${isCollapsed ? 'sidebar-collapsed' : 'sidebar-expanded'}`}>
        {/* Brand header */}
        <div
          className="sidebar-brand-header"
          onClick={onToggleCollapse}
          title={isCollapsed ? "Expand sidebar" : "Automated Trader"}
        >
          <div className="sidebar-brand-icon">{brandIcon}</div>
          {!isCollapsed && (
            <div className="sidebar-brand-titles">
              <span className="sidebar-brand-top">AUTOMATED</span>
              <span className="sidebar-brand-bottom">TRADER</span>
            </div>
          )}
        </div>

        {/* Hamburger / Workspace collapse toggle */}
        <button
          className="sidebar-collapse-toggle-row"
          onClick={onToggleCollapse}
          title={isCollapsed ? "Expand menu" : "Collapse menu"}
          id="btn-sidebar-collapse"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
            <line x1="3" y1="12" x2="21" y2="12" />
            <line x1="3" y1="6" x2="21" y2="6" />
            <line x1="3" y1="18" x2="21" y2="18" />
          </svg>
          {!isCollapsed && <span style={{ marginLeft: 12 }}>Workspace</span>}
        </button>

        {/* Navigation items */}
        <nav className="sidebar-nav-list">
          {navItems.map((item) => {
            const isActive = activeTab === item.id;
            return (
              <button
                key={item.id}
                className={`sidebar-nav-item ${isActive ? 'active' : ''}`}
                onClick={() => setActiveTab(item.id)}
                title={isCollapsed ? item.label : undefined}
                id={`nav-${item.id}`}
              >
                <span className="sidebar-nav-icon">{item.icon}</span>
                {!isCollapsed && <span>{item.label}</span>}
              </button>
            );
          })}
        </nav>

        {/* Bottom operational status card */}
        <div className="sidebar-bottom-status">
          {!isCollapsed ? (
            <div className="operational-status-card">
              <div className="status-header">
                <span className="status-dot-green" />
                <span>System operational</span>
              </div>
              <div className="status-broker">IBKR connected</div>
              <div className="status-account">
                {tradingMode === 'live' ? 'Live account' : 'Paper account'} · {username || 'DU782901'}
              </div>
              <button
                onClick={onLogout}
                style={{
                  marginTop: 8,
                  background: 'none',
                  border: 'none',
                  color: '#ef4444',
                  fontSize: 11,
                  fontWeight: 600,
                  cursor: 'pointer',
                  padding: 0,
                  display: 'block',
                  textAlign: 'left',
                }}
              >
                Sign out
              </button>
            </div>
          ) : (
            <div
              title={`System operational · IBKR connected (${tradingMode})`}
              style={{
                width: 38,
                height: 38,
                borderRadius: 8,
                background: 'rgba(255,255,255,0.06)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                cursor: 'pointer',
              }}
              onClick={onToggleCollapse}
            >
              <span className="status-dot-green" />
            </div>
          )}
        </div>
      </aside>

      {/* ── Mobile Drawer (Page 16 in design) ────────────────── */}
      <div className={`mobile-drawer-overlay ${isOpen ? 'active' : ''}`} onClick={onCloseMobile}>
        <div className="mobile-drawer-content" onClick={(e) => e.stopPropagation()}>
          {/* Brand header */}
          <div className="sidebar-brand-header" style={{ padding: '24px 20px 12px' }}>
            <div className="sidebar-brand-icon">{brandIcon}</div>
            <div className="sidebar-brand-titles">
              <span className="sidebar-brand-top">AUTOMATED</span>
              <span className="sidebar-brand-bottom">TRADER</span>
            </div>
          </div>

          {/* Close menu button (matching Page 16) */}
          <button
            className="mobile-drawer-close-btn"
            onClick={onCloseMobile}
            id="btn-close-mobile-menu"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
            <span>Close menu</span>
          </button>

          {/* Navigation links */}
          <nav className="sidebar-nav-list" style={{ marginTop: 8 }}>
            {navItems.map((item) => {
              const isActive = activeTab === item.id;
              return (
                <button
                  key={item.id}
                  className={`sidebar-nav-item ${isActive ? 'active' : ''}`}
                  onClick={() => {
                    setActiveTab(item.id);
                    if (onCloseMobile) onCloseMobile();
                  }}
                  id={`mobile-nav-${item.id}`}
                  style={{ fontSize: 15, padding: '12px 14px' }}
                >
                  <span className="sidebar-nav-icon">{item.icon}</span>
                  <span>{item.label}</span>
                </button>
              );
            })}
          </nav>

          {/* Bottom status card */}
          <div className="sidebar-bottom-status" style={{ padding: '20px 16px' }}>
            <div className="operational-status-card">
              <div className="status-header">
                <span className="status-dot-green" />
                <span>System operational</span>
              </div>
              <div className="status-broker">IBKR connected</div>
              <div className="status-account">
                {tradingMode === 'live' ? 'Live account' : 'Paper account'} · {username || 'DU782901'}
              </div>
              <button
                onClick={onLogout}
                style={{
                  marginTop: 10,
                  background: 'none',
                  border: 'none',
                  color: '#ef4444',
                  fontSize: 12,
                  fontWeight: 600,
                  cursor: 'pointer',
                  padding: 0,
                  display: 'block',
                  textAlign: 'left',
                }}
              >
                Sign out
              </button>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
