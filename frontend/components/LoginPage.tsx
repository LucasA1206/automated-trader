'use client';

import { useState, FormEvent } from 'react';
import { useAuth } from './AuthContext';

export default function LoginPage() {
  const { login } = useAuth();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!username.trim() || !password.trim()) {
      setError('Please enter your username and password.');
      return;
    }
    setError('');
    setLoading(true);
    const result = await login(username.trim(), password);
    setLoading(false);
    if (result.error) {
      setError(result.error);
    }
  }

  return (
    <div style={{
      minHeight: '100vh',
      background: 'var(--bg-primary)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      padding: 24,
      position: 'relative',
      overflow: 'hidden',
    }}>

      {/* Background glow accents */}
      <div style={{
        position: 'absolute',
        top: '20%',
        left: '50%',
        transform: 'translate(-50%, -50%)',
        width: 600,
        height: 600,
        background: 'radial-gradient(circle, rgba(59,130,246,0.08) 0%, transparent 70%)',
        pointerEvents: 'none',
      }} />
      <div style={{
        position: 'absolute',
        bottom: '10%',
        right: '15%',
        width: 400,
        height: 400,
        background: 'radial-gradient(circle, rgba(99,102,241,0.06) 0%, transparent 70%)',
        pointerEvents: 'none',
      }} />

      {/* Card */}
      <div style={{
        width: '100%',
        maxWidth: 420,
        background: 'var(--bg-card)',
        border: '1px solid var(--border-bright)',
        borderRadius: 20,
        padding: '40px 36px',
        boxShadow: '0 32px 80px rgba(0,0,0,0.6), 0 0 0 1px rgba(255,255,255,0.04) inset',
        position: 'relative',
        zIndex: 1,
      }}>

        {/* Logo */}
        <div style={{ textAlign: 'center', marginBottom: 32 }}>
          <div style={{
            width: 56,
            height: 56,
            background: 'linear-gradient(135deg, #3b82f6, #6366f1)',
            borderRadius: 16,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 26,
            margin: '0 auto 16px',
            boxShadow: '0 0 32px rgba(59,130,246,0.4)',
          }}>
            ⚡
          </div>
          <h1 style={{
            fontSize: 22,
            fontWeight: 800,
            letterSpacing: '-0.5px',
            color: 'var(--text-primary)',
            marginBottom: 6,
          }}>
            Blitz Trader
          </h1>
          <p style={{
            fontSize: 13,
            color: 'var(--text-muted)',
            lineHeight: 1.5,
          }}>
            Sign in with your IBKR credentials
          </p>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} noValidate>
          {/* Username */}
          <div style={{ marginBottom: 16 }}>
            <label
              htmlFor="login-username"
              style={{
                display: 'block',
                fontSize: 12,
                fontWeight: 600,
                color: 'var(--text-secondary)',
                marginBottom: 7,
                letterSpacing: '0.3px',
              }}
            >
              IBKR Username
            </label>
            <input
              id="login-username"
              type="text"
              autoComplete="username"
              autoFocus
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="Enter your IBKR username"
              style={{
                width: '100%',
                background: 'rgba(255,255,255,0.04)',
                border: `1px solid ${error ? 'rgba(239,68,68,0.4)' : 'var(--border-bright)'}`,
                borderRadius: 10,
                padding: '12px 14px',
                fontSize: 14,
                color: 'var(--text-primary)',
                outline: 'none',
                transition: 'border-color 0.15s, box-shadow 0.15s',
                fontFamily: 'inherit',
              }}
              onFocus={e => {
                e.target.style.borderColor = 'rgba(59,130,246,0.6)';
                e.target.style.boxShadow = '0 0 0 3px rgba(59,130,246,0.12)';
              }}
              onBlur={e => {
                e.target.style.borderColor = error ? 'rgba(239,68,68,0.4)' : 'rgba(255,255,255,0.15)';
                e.target.style.boxShadow = 'none';
              }}
            />
          </div>

          {/* Password */}
          <div style={{ marginBottom: 24 }}>
            <label
              htmlFor="login-password"
              style={{
                display: 'block',
                fontSize: 12,
                fontWeight: 600,
                color: 'var(--text-secondary)',
                marginBottom: 7,
                letterSpacing: '0.3px',
              }}
            >
              IBKR Password
            </label>
            <div style={{ position: 'relative' }}>
              <input
                id="login-password"
                type={showPassword ? 'text' : 'password'}
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Enter your IBKR password"
                style={{
                  width: '100%',
                  background: 'rgba(255,255,255,0.04)',
                  border: `1px solid ${error ? 'rgba(239,68,68,0.4)' : 'var(--border-bright)'}`,
                  borderRadius: 10,
                  padding: '12px 44px 12px 14px',
                  fontSize: 14,
                  color: 'var(--text-primary)',
                  outline: 'none',
                  transition: 'border-color 0.15s, box-shadow 0.15s',
                  fontFamily: 'inherit',
                }}
                onFocus={e => {
                  e.target.style.borderColor = 'rgba(59,130,246,0.6)';
                  e.target.style.boxShadow = '0 0 0 3px rgba(59,130,246,0.12)';
                }}
                onBlur={e => {
                  e.target.style.borderColor = error ? 'rgba(239,68,68,0.4)' : 'rgba(255,255,255,0.15)';
                  e.target.style.boxShadow = 'none';
                }}
              />
              <button
                type="button"
                id="btn-toggle-password"
                onClick={() => setShowPassword((p) => !p)}
                style={{
                  position: 'absolute',
                  right: 12,
                  top: '50%',
                  transform: 'translateY(-50%)',
                  background: 'none',
                  border: 'none',
                  cursor: 'pointer',
                  color: 'var(--text-muted)',
                  fontSize: 16,
                  padding: 4,
                  display: 'flex',
                  alignItems: 'center',
                }}
                title={showPassword ? 'Hide password' : 'Show password'}
              >
                {showPassword ? '🙈' : '👁️'}
              </button>
            </div>
          </div>

          {/* Error */}
          {error && (
            <div style={{
              display: 'flex',
              alignItems: 'flex-start',
              gap: 10,
              background: 'rgba(239,68,68,0.08)',
              border: '1px solid rgba(239,68,68,0.2)',
              borderRadius: 10,
              padding: '11px 14px',
              marginBottom: 20,
            }}>
              <span style={{ fontSize: 14, flexShrink: 0 }}>🔴</span>
              <span style={{ fontSize: 13, color: 'var(--accent-red)', lineHeight: 1.5 }}>{error}</span>
            </div>
          )}

          {/* Submit */}
          <button
            id="btn-login"
            type="submit"
            disabled={loading}
            className="btn btn-primary"
            style={{ width: '100%', justifyContent: 'center', padding: '13px 0', fontSize: 14 }}
          >
            {loading ? (
              <>
                <span style={{
                  display: 'inline-block',
                  width: 14,
                  height: 14,
                  border: '2px solid rgba(255,255,255,0.3)',
                  borderTopColor: 'white',
                  borderRadius: '50%',
                  animation: 'spin 0.7s linear infinite',
                }} />
                Signing in…
              </>
            ) : (
              'Sign In →'
            )}
          </button>
        </form>

        {/* Footer note */}
        <p style={{
          textAlign: 'center',
          marginTop: 24,
          fontSize: 11.5,
          color: 'var(--text-muted)',
          lineHeight: 1.6,
        }}>
          Use the same credentials as your IBKR / TWS account.
          <br />Account creation is not available.
        </p>
      </div>

      <style>{`
        @keyframes spin {
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}
