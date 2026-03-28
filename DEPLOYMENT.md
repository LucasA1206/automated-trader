# Deployment Guide — Blitz Trader

Deploy the full system to Railway (backend + DB) and Vercel (frontend) with your domain `www.blitz-trader.com`.

---

## Overview

| Service | Platform | What it does |
|---------|----------|-------------|
| IB Gateway | Railway (Docker) | Headless IBKR connection |
| Bot Backend | Railway (GitHub) | FastAPI + APScheduler |
| PostgreSQL | Railway (Plugin) | Database |
| Dashboard | Vercel | Next.js frontend |
| Domain | Vercel DNS | blitz-trader.com → Vercel |

---

## Step 1 — Push Code to GitHub

```bash
cd C:\Users\Lucas\projects\automated-trader
git add .
git commit -m "Initial Blitz Trader build"
git remote add origin https://github.com/YOUR_USERNAME/automated-trader.git
git push -u origin main
```

---

## Step 2 — Railway Setup (Backend)

### 2.1 Create Railway Project

1. Go to [railway.app](https://railway.app) → **New Project**
2. Click **Deploy from GitHub repo** → select `automated-trader`

> **⚠️ Important**: Railway will try to build from the **root** of the repo and fail with a "Railpack could not determine how to build" error. You MUST set the Root Directory first (Step 2.3 below).

### 2.2 Add PostgreSQL Plugin

1. In the Railway project → click **+ New** → **Database** → **Add PostgreSQL**
2. Wait for it to provision
3. Click the PostgreSQL service → **Variables** tab → copy the value of `DATABASE_URL`

### 2.3 Deploy Backend Bot Service

1. In the Railway project → click **+ New** → **GitHub Repo** → select `automated-trader`
2. **⚡ Before it deploys**, immediately go to the new service → **Settings** tab
3. Find **Root Directory** → set it to: **`/backend`**
4. Click **Save** — this triggers a redeploy from the correct folder

> **Why?** Your repo has both `backend/` and `frontend/` at the root. Railway must be told to look only at `backend/`. The `backend/railway.toml`, `Procfile`, and `runtime.txt` files inside `/backend` tell Railway exactly how to build and start the Python service.

Now go to the **Variables** tab and add all of these:

```
DATABASE_URL          = (paste from PostgreSQL service above)
GEMINI_API_KEY        = your_gemini_key
NEWS_API_KEY          = your_newsapi_key
IB_HOST               = ib-gateway  (← name of IB Gateway service below)
```

### 2.4 Deploy IB Gateway Service

1. In Railway project → **New** → **Docker Image**
2. Image: `ghcr.io/gnzsnz/ib-gateway:latest`
3. **Service name**: `ib-gateway` (must match `IB_HOST` above)
4. Go to **Variables** tab → Add:

```
TWS_USERID            = your_ibkr_username
TWS_PASSWORD          = your_ibkr_password
TRADING_MODE          = paper
VNC_SERVER_PASSWORD   = any_password_you_want
```

> **Note**: The very first time IB Gateway starts, it may require 2FA approval on your IBKR Mobile app. After the first login, it should auto-reconnect.

### 2.5 Link IB Gateway to Bot (Internal Networking — No Port Exposure Needed)

Railway services in the same project communicate privately and automatically — **you do NOT need to expose ports 4001/4002 publicly**.

In your **Bot service → Variables**, set:

```
IB_HOST = ib-gateway.railway.internal
```

Railway's internal DNS resolves this automatically. The bot connects to `ib-gateway.railway.internal:4002` (paper) or `:4001` (live) entirely within Railway's private network.

> **Optional — External debug access only**: If you ever need to connect to the IB Gateway from your local PC, go to the `ib-gateway` service → **Settings** → **Networking** → **Add TCP Proxy** → enter port `4002`. Railway will give you a public `tcp.railway.app:XXXXX` address. Leave this **off** in normal production use.

---

## Step 3 — Vercel Setup (Frontend)

### 3.1 Import Project

1. Go to [vercel.com](https://vercel.com) → **New Project**
2. Import from GitHub → select `automated-trader`
3. **Root Directory**: `frontend`
4. **Framework Preset**: Next.js (auto-detected)

### 3.2 Set Environment Variable

In Vercel → **Settings** → **Environment Variables**:

```
NEXT_PUBLIC_API_URL = https://your-railway-bot-url.up.railway.app
```

*(Get this URL from your Bot service in Railway → Settings → Domain)*

### 3.3 Deploy

Click **Deploy**. Vercel will build and deploy the frontend.

---

## Step 4 — Connect Your Domain

Since `blitz-trader.com` is already on Vercel:

1. In Vercel → your project → **Settings** → **Domains**
2. Click **Add Domain** → enter `www.blitz-trader.com`
3. Also add `blitz-trader.com` (root) and set it to redirect to `www`
4. Since the domain is already managed by Vercel DNS, it will auto-configure

✅ Your dashboard will be live at `https://www.blitz-trader.com`

---

## Step 5 — Verify Everything is Working

### Check Backend Health
```
curl https://your-railway-url.up.railway.app/api/health
```

Expected response:
```json
{
  "status": "ok",
  "scheduler_running": true,
  "scheduled_jobs": [
    { "id": "morning_scan_buy", "name": "Morning Scan & Buy", "next_run": "..." },
    { "id": "afternoon_sell", "name": "Afternoon Sell-All", "next_run": "..." }
  ]
}
```

### Trigger a Manual Scan (Test)
```
curl -X POST https://your-railway-url.up.railway.app/api/scan
```

Then check **System Logs** in the dashboard to see if the scan ran.

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `IB Gateway not connecting` | Wait 60s for gateway to fully start. Check Railway logs for the ib-gateway service. |
| `No market data` | Ensure IBKR account has market data subscriptions for US equities. |
| `502 Bad Gateway` on frontend | Check `NEXT_PUBLIC_API_URL` is set correctly in Vercel. |
| `postgres:// error` | Already handled in `database.py` — it auto-converts. |
| `2FA required` | Approve on IBKR Mobile app on first gateway start. |

---

## Switching to Live Trading

1. In the dashboard → **Settings** → toggle **Live Trading**
2. In Railway → `ib-gateway` service → Variables → change `TRADING_MODE` to `live`
3. Restart the ib-gateway service in Railway
4. The bot will automatically use port `4001` for live trades

> ⚠️ **Warning**: Live trading uses real money. Start with a small budget % and monitor for a few days.
