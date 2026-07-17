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

export default function Home() {
  const { token, username, logout, authFetch } = useAuth();
  const [activeTab, setActiveTab] = useState<Tab>('portfolio');
  const [tradingMode, setTradingMode] = useState<'paper' | 'live'>('paper');
  const [authReady, setAuthReady] = useState(false);
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);

  // Wait one tick for localStorage rehydration before deciding to show login
  useEffect(() => {
    setAuthReady(true);
  }, []);

  // Fetch trading mode once we have a valid token
  useEffect(() => {
    if (!token) return;
    authFetch('/api/settings')
      .then((r) => {
        if (r.status === 401) { logout(); return null; }
        return r.json();
      })
      .then((data) => {
        if (data?.trading_mode) setTradingMode(data.trading_mode);
      })
      .catch(() => {});
  }, [token, authFetch, logout]);

  // Show nothing while we're rehydrating from localStorage (avoids flash)
  if (!authReady) return null;

  // Show login if not authenticated
  if (!token) return <LoginPage />;

  return (
    <div className="app-layout">
      <div className="mobile-header">
        <button className="mobile-menu-btn" onClick={() => setIsMobileMenuOpen(!isMobileMenuOpen)}>
          ☰
        </button>
        <div className="mobile-header-title">
          <div className="mobile-header-icon">⚡</div>
          <h1>Blitz Trader</h1>
        </div>
      </div>

      {isMobileMenuOpen && (
        <div className="mobile-overlay" onClick={() => setIsMobileMenuOpen(false)}></div>
      )}

      <Sidebar
        activeTab={activeTab}
        setActiveTab={(tab) => {
          setActiveTab(tab);
          setIsMobileMenuOpen(false);
        }}
        tradingMode={tradingMode}
        username={username ?? undefined}
        onLogout={logout}
        isOpen={isMobileMenuOpen}
      />
      <main className="main-content">
        {activeTab === 'portfolio'  && <PortfolioTab authFetch={authFetch} />}
        {activeTab === 'trades'     && <TradeHistoryTab authFetch={authFetch} />}
        {activeTab === 'ai-analysis'  && <AIAnalysisTab authFetch={authFetch} />}
        {activeTab === 'logs'       && <SystemLogsTab authFetch={authFetch} />}
        {activeTab === 'settings'   && (
          <SettingsTab
            onModeChange={(mode) => setTradingMode(mode)}
            authFetch={authFetch}
          />
        )}
      </main>
    </div>
  );
}
