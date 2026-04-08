# Switching to Live Trading — Step-by-Step Guide

> [!CAUTION]
> Live trading uses **real money**. Complete every step below before enabling live mode in the dashboard. Mistakes can result in real financial losses.

---

## Overview of What Changes Between Paper and Live

| Component | Paper Trading | Live Trading |
|---|---|---|
| IB Gateway port | `4004` (socat relay → 4002) | `4003` (socat relay → 4001) |
| IBKR account | Paper account | Real funded account |
| IB Gateway env var `TRADING_MODE` | `paper` | `live` |
| Dashboard setting | `paper` | `live` |
| Real money at risk | ❌ No | ✅ Yes |

---

## Part 1 — Prerequisites (do once)

### 1.1 Enable Live Trading API Access in IBKR

1. Log in to [Client Portal](https://www.interactivebrokers.com/portal).
2. Navigate to **Settings → Account Settings**.
3. Under **API**, click **Configure**.
4. Ensure **"Enable TWS API"** is **ON** for your **live** account.
5. Make sure **"Read-Only API"** is **OFF** (you need write access to place orders).

### 1.2 Check Your Account Has Funds

- Confirm your live IBKR account has sufficient **available funds** for the `daily_budget_pct` you have configured.
- Paper accounts start with $1,000,000 in virtual cash — your live account balance will be much lower, so adjust `daily_budget_pct` and `max_positions` accordingly before switching.

### 1.3 Understand the IB Gateway Ports on Railway

The `gnzsnz/ib-gateway` Docker image exposes two socat relays:

| Port | Mode |
|---|---|
| `4003` | **Live** (relays to internal IB port 4001) |
| `4004` | **Paper** (relays to internal IB port 4002) |

The backend already knows about both ports via env vars:
```
IB_PORT      = 4004   ← paper (default)
IB_PORT_LIVE = 4003   ← live
```

These are already set correctly in code and you do **not** need to change them unless your Railway IB Gateway service exposes different ports.

---

## Part 2 — Configure the IB Gateway Railway Service for Live Mode

> [!IMPORTANT]
> The IB Gateway service on Railway must be configured to start in **live** mode. It cannot serve both live and paper simultaneously on the correct ports without a restart.

### 2.1 Set Environment Variables on the IB Gateway Service

In your Railway project, open the **ib-gateway** service → **Variables** tab and set:

| Variable | Value |
|---|---|
| `TRADING_MODE` | `live` |
| `IB_USERNAME` | your live IBKR username |
| `IB_PASSWORD` | your live IBKR password |
| `TWS_USERID` | your live IBKR username (some image versions use this) |
| `TWS_PASSWORD` | your live IBKR password |

> [!NOTE]
> If you were previously running in paper mode, `TRADING_MODE` was set to `paper`. Simply change it to `live`. The gateway will authenticate against your **live** IBKR account and listen on port `4001` internally (exposed as `4003` via socat).

### 2.2 Redeploy the IB Gateway Service

After changing the env vars, click **Deploy** (or **Redeploy**) on the ib-gateway service. Wait ~30 seconds for the IB Gateway Java process to fully start before proceeding.

### 2.3 Verify the Live Connection

From the Railway **ib-gateway** service logs you should see lines like:
```
IB Gateway started
Listening on port 4001
```
And **not** `Market data farm connected: usfarm.nj` with paper data.

---

## Part 3 — Switch the Backend to Live Mode

### 3.1 In the Dashboard Settings

1. Open the **Blitz Trader** dashboard.
2. Navigate to **Settings**.
3. Change **Trading Mode** from `paper` → `live`.
4. Click **Save**.

This does two things automatically (no server restart needed):
- Saves `trading_mode = live` to the database.
- **Restarts the persistent IBKR keepalive** connected to port `4003` (live).
- All future scheduled jobs (morning scan & afternoon sell) will use port `4003`.

### 3.2 Verify in System Logs

In the **System Logs** tab you should see:
```
Trading mode changed to: LIVE — restarting IBKR keepalive.
IBKR keepalive thread started (interval=30s).
Connected to IB Gateway at <host>:4003 (mode=live, clientId=...)
```

---

## Part 4 — Pre-Flight Checklist Before First Live Trade

Go through this checklist the morning before the first live trading day:

- [ ] IB Gateway Railway service is running with `TRADING_MODE=live`
- [ ] Dashboard Settings shows **Live** mode
- [ ] System Logs confirm keepalive connected to port `4003`
- [ ] `/api/portfolio` returns your **real** account balance (not $1,000,000)
- [ ] `daily_budget_pct` is set to an amount you are comfortable risking (e.g. `10` = 10% of available cash)
- [ ] `max_positions` is set appropriately for your budget
- [ ] You have tested a manual sell-all via the dashboard with no errors
- [ ] You have checked there are no open positions from a previous paper session still in the DB (Trade History → All → check for any `open` status rows)

---

## Part 5 — Switching Back to Paper

To revert to paper trading:

1. Set `TRADING_MODE=paper` on the IB Gateway Railway service and redeploy it.
2. In the Dashboard, set **Trading Mode** back to `paper`.
3. The keepalive will automatically reconnect to port `4004`.

---

## Troubleshooting

### "Failed to connect to IB Gateway" after switching to live
- Check that the ib-gateway Railway service has `TRADING_MODE=live` and has been **redeployed**.
- Wait 30–60 s after deployment for the Java process to fully initialise.
- Check ib-gateway Railway logs for authentication errors — your live IBKR credentials may differ from your paper credentials.

### "Warning 2110 — IB upstream connection broken"
- The IB Gateway container is running but cannot reach IB servers.
- Restart the ib-gateway service from the Railway dashboard.
- This is most common shortly after a cold start or after the daily 11:59 PM auto-restart.

### Portfolio shows wrong account / wrong balance
- The IB Gateway is still authenticated to the paper account.
- Verify `TRADING_MODE=live` is set AND the ib-gateway service was redeployed after the change.

### DB trade history shows stale "open" positions
- Run a manual sell-all from the dashboard (`Sell All` button or `POST /api/sell-all`).
- The reconciliation logic will automatically mark any DB records for positions not found in IBKR as closed.
