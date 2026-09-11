# Project Context: Courtside 1-Tap Prediction Market Betting

## 1. Project Overview & Goal
* **Objective:** Real-time in-person "courtsiding" at live sporting events using a mobile phone.
* **Mechanism:** Two giant tactile buttons on the phone (one for Team A, one for Team B to win). Tapping either button immediately fires a marketable limit order (current ask + configurable slippage buffer, e.g. +3¢) to buy winning contracts on **Kalshi**.
* **Speed Advantage:** Bypasses the 3–8 second navigation delay of standard exchange apps. From finger tap to match engine order execution is **under 100 milliseconds** via persistent WebSockets and pre-warmed keep-alive HTTP sessions.
* **Current Exchange:** Kalshi API v2 (structured with an exchange abstraction layer ready for Polymarket, Betfair, etc.).
* **GitHub Repository:** `https://github.com/WillPalaia/PredictionMarketBetScript.git`

---

## 2. Architecture & File Structure

```text
PredictionMarketBetScript/
├── server.py              # FastAPI server: WebSocket /ws, REST endpoints, static file serving
├── static/
│   └── index.html         # Mobile tactile UI: 2 huge buttons, Arm switch, haptics, ping, game selector
├── engine.py              # Courtside Engine: in-memory live quote cache, 1-tap calculation & execution
├── kalshi_client.py       # Kalshi API v2 client: connection pooling, RSA-PSS signing, simulation mode
├── kalshi_auth.py         # RSA-PSS SHA-256 signer required for Kalshi v2 authenticated endpoints
├── exchange_base.py       # Abstract BaseExchange class for multi-exchange expansion
├── config.py              # Environment configuration loader
├── .env.example           # Configuration template (keys, simulation toggle, bet amounts)
├── requirements.txt       # Dependencies: fastapi, uvicorn, httpx, cryptography, websockets, etc.
├── setup_tunnel.sh        # Auto-detects architecture (AMD/ARM) and installs cloudflared binary
├── start.sh               # One-click startup: runs server.py in background + opens Cloudflare tunnel
├── README.md              # Complete guide, latency benchmarks, stadium networking tips
└── context.md             # This handoff context file
```

---

## 3. Remote Server State (Oracle Cloud VM)

* **Host:** `ubuntu@instance-20260910-2051`
* **Datacenter Region:** Ashburn, Virginia (`iad` - same region as AWS `us-east-1` where Kalshi trades, offering ~1–3ms server-to-exchange fiber latency).
* **OS & Environment:** Ubuntu 24.04 LTS (Python 3.12, PEP 668 externally-managed environment).
* **Repository Location:** `~/PredictionMarketBetScript`
* **Remote:** Synced with `origin/main` on GitHub.
* **Local config:** `.env` copied from `.env.example` (defaults to `SIMULATION_MODE=true`).

---

## 4. Commands to Resume & Launch on Oracle Cloud

Whenever reconnecting to the Oracle SSH terminal:

```bash
cd ~/PredictionMarketBetScript
git pull origin main
bash setup_tunnel.sh
bash start.sh
```

### What `start.sh` does:
1. Installs/verifies python dependencies with `--break-system-packages`.
2. Starts `python3 server.py` in the background (logs to `server.log`).
3. Launches `cloudflared tunnel --url http://localhost:8000`.
4. Outputs a public HTTPS URL:
   ```text
   https://random-words.trycloudflare.com
   ```
5. Open that link in Safari/Chrome on your phone.

---

## 5. Live Money vs Simulation Mode

* **Simulation Mode (Default):**
  * `SIMULATION_MODE=true` in `.env`.
  * Pulls 100% real live market odds from Kalshi.
  * Simulates order fills locally in < 1ms with realistic price bounds and logs execution telemetry so you can safely test buttons, latency, and game switching with zero financial risk.
* **Switching to Real Money on Kalshi:**
  1. Generate an API Key in your Kalshi account (Account &rarr; API & Keys).
  2. Download the RSA private key `.pem` file and place it on the server: `~/PredictionMarketBetScript/kalshi_key.pem`.
  3. Edit `.env` (`nano .env`):
     ```env
     KALSHI_ENV=production
     SIMULATION_MODE=false
     KALSHI_KEY_ID=your-kalshi-api-key-id
     KALSHI_PRIVATE_KEY_PATH=kalshi_key.pem
     DEFAULT_BET_AMOUNT_DOLLARS=1.00
     DEFAULT_PRICE_BUFFER_CENTS=0.03
     ```
  4. Restart `bash start.sh`.

---

## 6. Next Steps / Future Roadmap

1. **Polymarket Integration:**
   * Create `polymarket_client.py` implementing `BaseExchange` from `exchange_base.py`.
   * Use py-clob-client with polygon wallet private key.
   * Allow buttons to optionally submit split orders across both Kalshi and Polymarket simultaneously.
2. **Additional Market Types:**
   * Add 2 additional buttons for Over/Under totals (e.g. Over 215.5 / Under 215.5).
   * Add Spread market buttons.
3. **Audio / Tone cues:**
   * Add customizable subtle click/beep tones in `static/index.html` upon order execution.
