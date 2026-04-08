# Blitz Trader

Automated NASDAQ day trading bot with AI-powered stock scanning and a Next.js dashboard at [blitz-trader.com](https://www.blitz-trader.com).

## Tech Stack

| Layer | Technology |
|-------|------------|
| Frontend | Next.js 14 (App Router) |
| Backend / API | FastAPI (Python 3.11) |
| Trading | IBKR via `ib_insync` |
| AI Scanner | Google Gemini 1.5 Flash + NewsAPI |
| Database | PostgreSQL (Railway) / SQLite (local) |
| Scheduler | APScheduler (09:20 ET scan, 15:30 ET sell) |
| Hosting | Railway (backend) + Vercel (frontend) |
| Domain | www.blitz-trader.com |

## How It Works

1. **09:20 ET** — AI scans NASDAQ news via NewsAPI + Gemini, picks top stocks
2. **09:30 ET** — Market opens, buy orders are already placed
3. **15:30 ET** — All positions sold before market close
4. Repeat daily, fully automated in the cloud

## Project Structure

```
automated-trader/
├── backend/              # FastAPI + ib_insync + APScheduler
│   ├── api_server.py     # REST API
│   ├── scheduler.py      # Job definitions
│   ├── jobs.py           # Scan+buy and sell jobs
│   ├── trader.py         # IBKR client
│   ├── ai_analyst.py     # Gemini + NewsAPI scanner
│   ├── database.py       # SQLAlchemy + PostgreSQL
│   ├── models.py         # DB models
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/             # Next.js dashboard
│   ├── app/
│   ├── components/
│   │   ├── Sidebar.tsx
│   │   ├── PortfolioTab.tsx
│   │   ├── TradeHistoryTab.tsx
│   │   ├── SystemLogsTab.tsx
│   │   └── SettingsTab.tsx
│   └── Dockerfile
└── docker-compose.yml    # Local dev
```

## Quick Start (Local Dev)

### 1. Set environment variables
```bash
cp backend/.env.example backend/.env
# Fill in your keys in backend/.env
```

### 2. Start with Docker Compose
```bash
docker-compose up -d
```

### 3. Start frontend
```bash
cd frontend
npm install
npm run dev
```

Visit `http://localhost:3000`

## Deployment

See [DEPLOYMENT.md](./DEPLOYMENT.md) for Railway + Vercel deployment steps.
