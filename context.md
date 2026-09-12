# Project Context: FastBet 1-Tap Prediction Market Direct API Client

## 1. Project Overview & Goal
* **Objective:** Direct API execution for prediction markets (Kalshi) to execute trades orders of magnitude faster than standard mobile apps.
* **Mechanism:** Two tactile buttons on the mobile interface for instant 1-tap betting across three market categories:
  * **Moneyline:** Team A Win vs Team B Win
  * **Point Spread:** Cover lines with line selector carousel (e.g. -1.5, -3.5, +1.5, +3.5)
  * **Over / Under (Totals):** Total score lines with 1-tap OVER or UNDER execution
* **Price Execution Modes:**
  * **AT ASK (Taker):** Immediate marketable fill at best ask.
  * **AT BID (Maker):** Limit order at best bid to post and save the spread.
  * **+0¢ Buffer (Default):** Exact price guarantee (never pays a penny above chosen price).
* **Speed Advantage:** Bypasses the 3–8 second navigation delay of standard exchange apps. From finger tap to match engine order execution is **under 100 milliseconds** via persistent WebSockets and pre-warmed keep-alive HTTP sessions.
* **Current Exchange:** Kalshi API v2 (structured with an exchange abstraction layer ready for Polymarket, Betfair, etc.).
* **GitHub Repository:** https://github.com/WillPalaia/PredictionMarketBetScript.git

---

## 2. Architecture & File Structure

`	ext
PredictionMarketBetScript/
├── server.py              # FastAPI server: WebSocket /ws, REST endpoints, static file serving
├── static/
│   └── index.html         # Mobile tactile UI: 2 huge buttons, Arm switch, haptics, ping, game selector
├── engine.py              # FastBet Engine: in-memory live quote cache, 1-tap calculation & execution
├── kalshi_client.py       # Kalshi API v2 client: connection pooling, RSA-PSS signing, simulation mode
├── kalshi_auth.py         # RSA-PSS SHA-256 signer required for Kalshi v2 authenticated endpoints
├── exchange_base.py       # Abstract BaseExchange class for multi-exchange expansion
├── config.py              # Environment configuration loader
├── .env.example           # Configuration template (keys, simulation toggle, bet amounts)
├── requirements.txt       # Dependencies: fastapi, uvicorn, httpx, cryptography, websockets, etc.
├── setup_tunnel.sh        # Auto-detects architecture (AMD/ARM) and installs cloudflared binary
├── start.sh               # One-click startup: runs server.py in background + opens Cloudflare tunnel
├── stop.sh                # Graceful shutdown script for background processes
├── README.md              # Complete guide, benchmarks, direct API architecture
└── context.md             # This handoff context file
`

---

## 3. Remote Server State (Oracle Cloud VM)

* **Host:** ubuntu@instance-20260910-2051 (129.213.122.140)
* **Datacenter Region:** Ashburn, Virginia (iad - same region as AWS us-east-1 where Kalshi trades, offering ~1–3ms server-to-exchange fiber latency).
* **OS & Environment:** Ubuntu 24.04 LTS (Python 3.12).
* **Repository Location:** ~/PredictionMarketBetScript
* **Remote:** Synced with origin/main on GitHub.
* **Local config:** .env (configured for live production odds and direct API orders).

---

## 4. Commands to Resume & Launch on Oracle Cloud

`ash
cd ~/PredictionMarketBetScript
git pull origin main
bash start.sh --bg
`

### What start.sh --bg does:
1. Verifies python dependencies.
2. Starts python3 server.py as a detached background daemon.
3. Launches cloudflared tunnel in the background.
4. Outputs your public HTTPS URL to open in Safari/Chrome on your phone.
5. Allows you to close your terminal and shut off your computer.

---

## 5. Live Money vs Simulation Mode

* **Simulation Mode:**
  * SIMULATION_MODE=true in .env.
  * Pulls 100% real live market odds from Kalshi.
  * Simulates order fills locally in < 1ms with realistic price bounds and logs execution telemetry so you can safely test buttons and latency with zero financial risk.
* **Switching to Real Money on Kalshi:**
  1. Generate an API Key in your Kalshi account (Account &rarr; API & Keys).
  2. Put your Key ID in .env and ensure kalshi_key.pem is present.
  3. Set SIMULATION_MODE=false.
  4. Run ash start.sh --bg.
