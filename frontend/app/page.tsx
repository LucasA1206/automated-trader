'use client';

import { useState, useEffect } from 'react';
import Sidebar from '@/components/Sidebar';
import PortfolioTab from '@/components/PortfolioTab';
import TradeHistoryTab from '@/components/TradeHistoryTab';
import SystemLogsTab from '@/components/SystemLogsTab';
import SettingsTab from '@/components/SettingsTab';

export type Tab = 'portfolio' | 'trades' | 'logs' | 'settings';

export default function Home() {
  const [activeTab, setActiveTab] = useState<Tab>('portfolio');
  const [tradingMode, setTradingMode] = useState<'paper' | 'live'>('paper');

  useEffect(() => {
    // bootstrap: fetch current trading mode for sidebar badge
    fetch('/api/settings')
      .then((r) => r.json())
      .then((data) => {
        if (data.trading_mode) setTradingMode(data.trading_mode);
      })
      .catch(() => {});
  }, []);

  return (
    <div className="app-layout">
      <Sidebar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        tradingMode={tradingMode}
      />
      <main className="main-content">
        {activeTab === 'portfolio' && <PortfolioTab />}
        {activeTab === 'trades' && <TradeHistoryTab />}
        {activeTab === 'logs' && <SystemLogsTab />}
        {activeTab === 'settings' && (
          <SettingsTab
            onModeChange={(mode) => setTradingMode(mode)}
          />
        )}
      </main>
    </div>
  );
}
