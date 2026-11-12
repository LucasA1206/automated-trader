'use client';

import { useState, useEffect } from 'react';
import { useAuth } from '@/components/AuthContext';
import LoginPage from '@/components/LoginPage';
import Sidebar from '@/components/Sidebar';
import PortfolioTab from '@/components/PortfolioTab';
import TradeHistoryTab from '@/components/TradeHistoryTab';
import SystemLogsTab from '@/components/SystemLogsTab';
import SettingsTab from '@/components/SettingsTab';
import AIAnalysisTab from '@/components/AIAnalysisTab';

export type Tab = 'portfolio' | 'trades' | 'ai-analysis' | 'logs' | 'settings';

const tabTitles: Record<Tab, string> = {
  portfolio: 'Portfolio',
  trades: 'Trade History',
  'ai-analysis': 'AI Stock Analysis',
  logs: 'System Logs',
  settings: 'Settings',
};

export default function Home() {
  const { token, username, logout, authFetch } = useAuth();
  const [activeTab, setActiveTab] = useState<Tab>('portfolio');
  const [tradingMode, setTradingMode] = useState<'paper' | 'live'>('paper');
  const [authReady, setAuthReady] = useState(false);
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);

  // Rehydration check
  useEffect(() => {
    setAuthReady(true);
  }, []);

  // Fetch trading mode once authenticated
  useEffect(() => {
    if (!token) return;
    authFetch('/api/settings')
      .then((r) => {
        if (r.status === 401) {
          logout();
          return null;
        }
        return r.json();
      })
      .then((data) => {
        if (data?.trading_mode) setTradingMode(data.trading_mode);
      })
      .catch(() => {});
  }, [token, authFetch, logout]);

  if (!authReady) return null;
  if (!token) return <LoginPage />;

  return (
    <div className="app-container">
      {/* Mobile Top Header (Phones) */}
      <header className="mobile-app-header">
        <button
          className="mobile-hamburger-btn"
          onClick={() => setIsMobileMenuOpen(true)}
          aria-label="Open menu"
          id="btn-open-mobile-menu"
        >
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="3" y1="12" x2="21" y2="12" />
            <line x1="3" y1="6" x2="21" y2="6" />
            <line x1="3" y1="18" x2="21" y2="18" />
          </svg>
        </button>
        <span className="mobile-app-title">Automated Trader</span>
        <div className={tradingMode === 'live' ? 'badge-live' : 'badge-paper'}>
          <span className="status-dot-green" style={{ background: tradingMode === 'live' ? '#ef4444' : '#10b981' }} />
          <span>{tradingMode === 'live' ? 'Live' : 'Paper'}</span>
        </div>
      </header>

      {/* Sidebar (Desktop collapsible & Mobile drawer) */}
      <Sidebar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        tradingMode={tradingMode}
        username={username ?? undefined}
        onLogout={logout}
        isOpen={isMobileMenuOpen}
        onCloseMobile={() => setIsMobileMenuOpen(false)}
        isCollapsed={isSidebarCollapsed}
        onToggleCollapse={() => setIsSidebarCollapsed((prev) => !prev)}
      />

      {/* Main Content Area */}
      <main className="main-viewport">
        <div className="page-content-wrapper">
          {/* Desktop Top Breadcrumbs Bar */}
          <div className="desktop-top-bar">
            <div className="breadcrumb-path">
              <span>Workspace</span>
              <span className="breadcrumb-separator">/</span>
              <span className="breadcrumb-current">{tabTitles[activeTab]}</span>
            </div>
            <div className="top-bar-badges">
              <div className={tradingMode === 'live' ? 'badge-live' : 'badge-paper'}>
                <span className="status-dot-green" style={{ background: tradingMode === 'live' ? '#ef4444' : '#10b981' }} />
                <span>{tradingMode === 'live' ? 'Live trading' : 'Paper trading'}</span>
              </div>
              <div className="badge-currency-toggle">
                AUD / USD
              </div>
            </div>
          </div>

          {/* Active Tab View */}
          {activeTab === 'portfolio' && (
            <PortfolioTab authFetch={authFetch} tradingMode={tradingMode} />
          )}
          {activeTab === 'trades' && (
            <TradeHistoryTab authFetch={authFetch} tradingMode={tradingMode} />
          )}
          {activeTab === 'ai-analysis' && (
            <AIAnalysisTab authFetch={authFetch} tradingMode={tradingMode} />
          )}
          {activeTab === 'logs' && (
            <SystemLogsTab authFetch={authFetch} tradingMode={tradingMode} />
          )}
          {activeTab === 'settings' && (
            <SettingsTab
              onModeChange={(mode) => setTradingMode(mode)}
              authFetch={authFetch}
            />
          )}
        </div>
      </main>
    </div>
  );
}
