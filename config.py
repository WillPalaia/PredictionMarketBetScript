import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file if present
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

# Kalshi API Configuration
# Options: "demo" or "production"
KALSHI_ENV = os.getenv("KALSHI_ENV", "production").lower()

if KALSHI_ENV == "production":
    KALSHI_BASE_URL = "https://external-api.kalshi.com/trade-api/v2"
    KALSHI_WS_URL = "wss://external-api-ws.kalshi.com/trade-api/ws/v2"
else:
    KALSHI_BASE_URL = "https://demo-api.kalshi.co/trade-api/v2"
    KALSHI_WS_URL = "wss://demo-api.kalshi.co/trade-api/ws/v2"

# Authentication:
# Kalshi API v2 uses Key ID + RSA Private Key
KALSHI_KEY_ID = os.getenv("KALSHI_KEY_ID", "")
KALSHI_PRIVATE_KEY_PATH = os.getenv("KALSHI_PRIVATE_KEY_PATH", "")

# Fallback email/password (if using session auth)
KALSHI_EMAIL = os.getenv("KALSHI_EMAIL", "")
KALSHI_PASSWORD = os.getenv("KALSHI_PASSWORD", "")

# Simulation Mode: if True, orders will be simulated locally and logged without risking real money
# Excellent for dry runs, testing phone buttons, and testing latency
SIMULATION_MODE = os.getenv("SIMULATION_MODE", "true").lower() in ("true", "1", "yes")

# Default Courtsiding Betting Parameters
DEFAULT_BET_AMOUNT_DOLLARS = float(os.getenv("DEFAULT_BET_AMOUNT_DOLLARS", "1.00"))
DEFAULT_PRICE_BUFFER_CENTS = float(os.getenv("DEFAULT_PRICE_BUFFER_CENTS", "0.03"))  # +3 cents above ask
POLL_INTERVAL_SECONDS = float(os.getenv("POLL_INTERVAL_SECONDS", "0.15"))

# Server settings
SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("SERVER_PORT", "8000"))
