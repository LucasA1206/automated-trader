import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Automated Trader',
  description:
    'Automated Trader is an AI-powered automated day trading system for NASDAQ stocks using IBKR.',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body suppressHydrationWarning>{children}</body>
    </html>
  );
}
