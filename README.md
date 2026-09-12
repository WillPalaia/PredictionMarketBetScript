# FastBet: 1-Tap Direct API Client for Prediction Markets

An ultra-low-latency, mobile-first trading client designed for **instant 1-tap order execution directly through prediction market exchange APIs (Kalshi)**. 

Standard exchange mobile apps require 3 to 8 seconds of manual navigation (finding the market, selecting contracts, setting prices, choosing quantities, and confirming). **FastBet** bypasses app latency entirely, providing a dedicated tactile interface backed by persistent WebSockets and pre-warmed keep-alive sessions directly into Kalshi's order matching engine in **under 100 milliseconds**.

---

## Why Direct API Execution Beats Mobile Apps

| Feature | Standard Exchange Mobile App | FastBet Direct API Client |
| :--- | :--- | :--- |
| **Execution Path** | Navigate &rarr; Select &rarr; Price &rarr; Quantity &rarr; Confirm | **Instant 1-Tap** (Pre-armed tactile button) |
| **Order Routing Time** | 3,000ms – 8,000ms (3 to 8 seconds) | **50ms – 150ms** |
| **Connection State** | Cold REST requests upon every tap | Pre-warmed persistent TLS / WebSocket session |
| **Cryptographic Signing** | On-device key lookup & app overhead | In-memory pre-loaded RSA-PSS signature generator |
| **Tactile & Haptic Cues** | Standard software touch | Immediate physical vibration & visual confirmation |
| **Slippage Protection** | Manual price slider adjustments | Automated marketable limit buffer (+1¢ to +10¢) |

---

## System Architecture

`	ext
[User's Mobile Device] 
         │ 
         ▼ WebSocket (Real-Time Bid/Ask & 1-Tap Actions)
[FastAPI Server (server.py)]
         │ 
         ▼ In-Memory Cache (0ms Quote Lookup & Order Construction)
[FastBet Engine (engine.py)]
         │ 
         ▼ Pre-warmed Keep-Alive HTTP/2 (In-Memory RSA-PSS Signer)
[Kalshi API v2 Matching Engine (/portfolio/events/orders)]
`

---

## Key Features

* **Multi-Market Betting in 1 Tap:**
  * **Moneyline:** Bet Team A or Team B straight up to win.
  * **Point Spread:** Instant cover lines (e.g. -1.5, -3.5, +1.5, +3.5) with automatic consensus line pre-selection.
  * **Over / Under (Totals):** Instant game total lines (e.g. 7.5, 41.5) with single-tap OVER or UNDER execution.
* **Granular Price Target Control (Taker vs Maker):**
  * **AT ASK (Instant Fill):** Submits at the current best ask for immediate market fill.
  * **AT BID (Maker Order):** Submits at the current best bid, posting a resting limit order and saving the spread.
* **Exact Price & Slippage Protection:**
  * **+0¢ (Exact Price):** Default setting ensuring your limit price will never pay a single cent above what you selected.
  * **+1¢, +2¢, +3¢, +5¢:** Optional slippage buffer for fast-moving volatile momentum.
* **Safety Arm / Disarm Toggle:** Prevents accidental taps. When Disarmed, buttons are grayed out. When Armed, 1-tap mode is active.
* **Haptic & Visual Feedback:** Immediate tactile phone vibration on tap, double vibration on fill confirmation, and screen flash green/red.
* **Live Market Telemetry:** Live 150ms top-of-book orderbook streaming and round-trip touch-to-fill latency tracking (⚡ XX ms).
* **Configurable Bet Sizes:** $1, $2, $5, $10, $25.
* **Game & Market Selector:** Search active NFL, MLB, NBA, NCAAF, and soccer markets with one click.
* **Simulation Mode:** Test touch latency, UI, and market switching with 100% real live market odds without risking capital.

---

## Quick Start

### 1. Installation
`ash
git clone https://github.com/WillPalaia/PredictionMarketBetScript.git
cd PredictionMarketBetScript
pip install -r requirements.txt
`

### 2. Run Locally (Simulation Mode)
`ash
python server.py
`
Open http://localhost:8000 on your computer or http://<YOUR_LOCAL_IP>:8000 on your phone.

---

## 24/7 Cloud Deployment (Oracle Cloud / VPS)

For minimum latency to Kalshi's matching engine (hosted in AWS Ashburn us-east-1), deploy to a cloud instance in Ashburn, VA.

1. **Install Cloudflare Tunnel:**
   `ash
   bash setup_tunnel.sh
   `
2. **Start Background Daemon:**
   `ash
   bash start.sh --bg
   `
   This launches the server and Cloudflare tunnel as detached background daemons, prints your public HTTPS URL, and allows you to disconnect and turn off your computer.
3. **Stop the Service:**
   `ash
   bash stop.sh
   `

---

## Kalshi Real Money API Setup

1. Copy .env.example to .env:
   `ash
   cp .env.example .env
   `
2. In your Kalshi account (**Account &rarr; API & Keys**):
   * Generate an API Key Pair. Copy your **API Key ID** and download the **RSA Private Key** (.pem file).
3. Place your private key in the project directory as kalshi_key.pem.
4. Configure .env:
   `env
   KALSHI_ENV=production
   SIMULATION_MODE=false
   KALSHI_KEY_ID=your-kalshi-key-id-here
   KALSHI_PRIVATE_KEY_PATH=kalshi_key.pem
   DEFAULT_BET_AMOUNT_DOLLARS=1.00
   DEFAULT_PRICE_BUFFER_CENTS=0.03
   POLL_INTERVAL_SECONDS=0.15
   `
5. Restart the server (ash start.sh --bg).

---

## Multi-Exchange Expansion

The engine implements BaseExchange in [exchange_base.py](exchange_base.py), making it simple to plug in additional prediction markets:
* **Polymarket:** Subclass BaseExchange using Polygon CLOB client.
* **SX Bet / Betfair:** Add direct API endpoints to split orders or cross-arbitrage.
