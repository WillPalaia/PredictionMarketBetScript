# Courtside Prediction Market 1-Tap Mobile Betting

An ultra-low-latency, mobile-first betting engine designed specifically for **in-person courtsiding** at live sporting events. 

Featuring a tactile, high-contrast mobile web UI with **two dedicated 1-tap buttons** (one for each team to win), it connects directly to a persistent, pre-warmed backend that executes marketable limit orders on **Kalshi** in **under 100 milliseconds**—bypassing the slow 3–8 second navigation delay of standard exchange mobile apps.

---

## Table of Contents
1. [Viability & Latency Assessment](#viability--latency-assessment)
2. [How It Works](#how-it-works)
3. [Quick Start](#quick-start)
4. [Connecting Your Phone from the Arena](#connecting-your-phone-from-the-arena)
5. [Kalshi API Setup (Demo vs Production)](#kalshi-api-setup)
6. [Mobile UI Features](#mobile-ui-features)
7. [Extending to Other Prediction Markets (Polymarket, etc.)](#extending-to-other-prediction-markets)

---

## Viability & Latency Assessment

### 1. Can you beat the official Kalshi app?
**Yes, decisively.**
* **The Official App Flow:** Unlock phone &rarr; Open app &rarr; Search/find market &rarr; Tap contract &rarr; Select "Buy" &rarr; Enter price &rarr; Enter quantity &rarr; Review & swipe to submit. This takes **3,000ms – 8,000ms (3 to 8 seconds)**.
* **The Courtside 1-Tap Flow:** Screen is already open and ARMED &rarr; Tap Team button &rarr; Payload sent over pre-established WebSocket &rarr; Server uses pre-warmed keep-alive TLS connection and pre-loaded RSA key in memory &rarr; Order placed on Kalshi. Total latency: **50ms – 180ms**.

### 2. Can you beat the bookmakers / market makers from the stands?
* **High-Tier Markets (NFL / NBA National Broadcasts):** Professional market makers use dedicated stadium data scouts (Sportradar, Genius Sports) or automated optical tracking systems (Hawk-Eye) connected over low-latency microwave/fiber links. Their automated quoting bots cancel resting bids within **150ms – 300ms** of a scoring event.
* **Where You Have an Edge:**
  1. **Scout Hesitation / Human Error:** In-stadium data scouts are human operators pressing keypads. On ambiguous plays, fast breaks, contested calls, referee reviews, and injuries, scouts often hesitate for **1 to 3 seconds**.
  2. **Lower-Tier / Mid-Tier Sports:** College games (NCAAF, NCAAM), baseball pitch sequences, soccer set-pieces, and esports often have slower data turnaround or fewer low-latency algorithmic market makers.
  3. **Passive Retail Liquidity:** Many Kalshi contracts have resting limit orders placed by retail participants who do not use automated cancellation bots.
  4. **Marketable Limit Buffer:** By submitting limit orders with a small buffer (e.g. +3¢ or +5¢ above the pre-event ask price), your order immediately matches against available resting quotes before the orderbook adjusts upwards.

---

## System Architecture

```
                      ┌─────────────────────────────────┐
                      │    Courtsider's Mobile Phone    │
                      │  (Tactile UI, Haptics, 1-Tap)   │
                      └────────────────┬────────────────┘
                                       │ WebSocket (JSON)
                                       │ Latency: 10 - 40ms
                                       ▼
                      ┌─────────────────────────────────┐
                      │    FastAPI Server (server.py)   │
                      │   - WebSocket Heartbeat / Ping  │
                      │   - Mobile Viewport / UI Assets │
                      └────────────────┬────────────────┘
                                       │ In-Memory Call
                                       ▼
                      ┌─────────────────────────────────┐
                      │  Courtside Engine (engine.py)   │
                      │   - Pre-cached live ask/bid     │
                      │   - Dynamic count / slippage    │
                      │   - Order history & telemetry   │
                      └────────────────┬────────────────┘
                                       │ Pre-warmed Keep-Alive HTTP/2
                                       │ Pre-loaded RSA-PSS Signer
                                       ▼
                      ┌─────────────────────────────────┐
                      │   Kalshi API v2 Match Engine    │
                      │ (/portfolio/events/orders)      │
                      └─────────────────────────────────┘
```

---

## Quick Start

### 1. Requirements
* Python 3.10+
* Virtual environment (optional, recommended)

### 2. Installation
```powershell
pip install -r requirements.txt
```

### 3. Run the Server
```powershell
python server.py
```
Upon startup, the console will print your local IP address:
```
=================================================================
 >>> COURTSIDE KALSHI BETTING SERVER IS RUNNING <<<
=================================================================
 [>] Local Browser:  http://localhost:8000
 [>] Mobile Phone:   http://192.168.1.150:8000
=================================================================
```

By default, the server runs in **`SIMULATION_MODE=true`** so you can test buttons, latency, and game selection with live Kalshi market prices without risking real money.

---

## Connecting Your Phone from the Arena

### Scenario A: Phone connected to your Laptop's Hotspot (Recommended for lowest latency)
1. Turn on **Mobile Hotspot** on your phone (or laptop).
2. Connect your laptop to the hotspot.
3. Launch `python server.py`.
4. Open the displayed `http://<LAN_IP>:8000` directly in Safari / Chrome on your phone.
5. Latency is typically **< 5ms** between phone and computer.

### Scenario B: Accessing over Cellular Data via Cloudflare Tunnel or Ngrok
If your laptop/VPS is at home or in a cloud datacenter (e.g. AWS us-east-1 close to Kalshi):
1. **Using Cloudflare Tunnel (Free & Fast):**
   ```bash
   cloudflared tunnel --url http://localhost:8000
   ```
2. **Using Ngrok:**
   ```bash
   ngrok http 8000
   ```
3. Open the generated HTTPS URL on your phone.

---

## Kalshi API Setup

To place real money orders on Kalshi:

1. Copy `.env.example` to `.env`:
   ```powershell
   copy .env.example .env
   ```
2. Log into Kalshi and generate an API Key:
   * Go to **Kalshi Account &rarr; API & Keys**.
   * Generate an API Key Pair. You will receive an **API Key ID** and an **RSA Private Key** (`.pem` file).
   * Save the `.pem` file inside this project directory (e.g. `kalshi_private_key.pem`).
3. Update `.env`:
   ```env
   KALSHI_ENV=production
   SIMULATION_MODE=false
   KALSHI_KEY_ID=your_key_id_here
   KALSHI_PRIVATE_KEY_PATH=kalshi_private_key.pem

   DEFAULT_BET_AMOUNT_DOLLARS=1.00
   DEFAULT_PRICE_BUFFER_CENTS=0.03
   ```

---

## Mobile UI Features

* **Tactile Arm / Disarm Switch:** Prevents accidental pocket clicks. When Disarmed, buttons are grayed out. When Armed, one tap immediately fires the order.
* **Instant Haptic Feedback:** Vibrates your phone immediately upon click, double-vibrates on order fill, and long-vibrates on error so you never have to take your eyes off the court.
* **Visual Flash Overlay:** The perimeter of the phone screen briefly flashes neon green on a successful fill or red on rejection.
* **Live Ping Monitor:** Real-time roundtrip millisecond ping between phone and server.
* **Configurable Pills:** 
  * Bet size: `$1`, `$2`, `$5`, `$10`, `$25`.
  * Slippage buffer: `+1¢`, `+3¢`, `+5¢`, `+10¢`.
* **Game Selector Modal:** Instant search of active NFL, MLB, NBA, NCAAF, and soccer games on Kalshi.

---

## Extending to Other Prediction Markets

The codebase is built around `BaseExchange` in [`exchange_base.py`](file:///c:/Users/Will%20Palaia/Downloads/dev/PredictionMarketBetScript/exchange_base.py).

To add **Polymarket** or **SX Bet**:
1. Create `polymarket_client.py` subclassing `BaseExchange`.
2. Implement `get_market_quote()` and `place_order()`.
3. In `engine.py`, instantiate both clients and broadcast/execute simultaneously across multiple exchanges with a single tap.