import asyncio
import time
import uuid
from typing import Dict, Any, List, Optional
import httpx

from config import (
    KALSHI_BASE_URL,
    KALSHI_KEY_ID,
    KALSHI_PRIVATE_KEY_PATH,
    SIMULATION_MODE,
    KALSHI_ENV
)
from kalshi_auth import KalshiAuth
from exchange_base import BaseExchange


class KalshiClient(BaseExchange):
    """
    High-performance Kalshi API client optimized for courtsiding.
    Maintains a pre-warmed HTTP/2 / HTTP/1.1 persistent session,
    in-memory RSA keys for zero-latency signature generation,
    and fast-path order routing.
    """

    def __init__(self, key_id: str = None, private_key_path: str = None, simulation_mode: bool = None):
        self.base_url = KALSHI_BASE_URL.rstrip('/')
        self.auth = KalshiAuth(
            key_id=key_id or KALSHI_KEY_ID,
            private_key_path=private_key_path or KALSHI_PRIVATE_KEY_PATH
        )
        self.simulation_mode = SIMULATION_MODE if simulation_mode is None else simulation_mode
        self.client: Optional[httpx.AsyncClient] = None

    async def initialize(self):
        """Pre-warm HTTP client and TLS connections."""
        if self.client is None or self.client.is_closed:
            limits = httpx.Limits(max_keepalive_connections=20, max_connections=50, keepalive_expiry=60.0)
            timeout = httpx.Timeout(connect=2.0, read=4.0, write=2.0, pool=1.0)
            self.client = httpx.AsyncClient(
                base_url=self.base_url,
                limits=limits,
                timeout=timeout,
                headers={"User-Agent": "CourtsideKalshi/1.0", "Accept": "application/json"}
            )
            # Pre-warm connection with a quick ping
            try:
                await self.client.get("/series?limit=1")
            except Exception:
                pass

    async def close(self):
        if self.client and not self.client.is_closed:
            await self.client.aclose()

    def _get_auth_headers(self, method: str, path: str) -> Dict[str, str]:
        # Full path for Kalshi signature: e.g. /trade-api/v2/portfolio/events/orders
        full_path = f"/trade-api/v2{path}" if not path.startswith("/trade-api/v2") else path
        return self.auth.sign_request(method, full_path)

    async def get_balance(self) -> Dict[str, Any]:
        """Fetch account portfolio balance."""
        if self.simulation_mode or not self.auth.is_configured:
            return {"balance_dollars": 1000.00, "simulated": True}

        path = "/portfolio/balance"
        headers = self._get_auth_headers("GET", path)
        resp = await self.client.get(path, headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            balance_cents = data.get("balance", 0)
            return {"balance_dollars": balance_cents / 100.0, "raw": data, "simulated": False}
        return {"error": resp.text, "status_code": resp.status_code, "simulated": False}

    async def search_game_events(self, query: str = "", limit: int = 30) -> List[Dict[str, Any]]:
        """
        Search open events that look like sports games.
        Parses teams, event tickers, and market contracts.
        """
        if self.client is None:
            await self.initialize()

        # Popular sports series tickers on Kalshi
        sports_series = [
            "KXNFLGAME", "KXMLBGAME", "KXNBAGAME", "KXNCAAFGAME",
            "KXNHLGAME", "KXEPLGAME", "KXMLS", "KXUFC"
        ]

        found_events = []
        # Try fetching from major sports series
        for series in sports_series:
            try:
                resp = await self.client.get(
                    f"/events?series_ticker={series}&status=open&with_nested_markets=true&limit={limit}"
                )
                if resp.status_code == 200:
                    data = resp.json()
                    for ev in data.get("events", []):
                        markets = ev.get("markets", [])
                        if len(markets) >= 2:
                            # Format for courtsiding
                            event_info = self._format_event(ev)
                            if event_info:
                                if query:
                                    q_lower = query.lower()
                                    if q_lower not in event_info["title"].lower() and \
                                       q_lower not in event_info["team_a"]["name"].lower() and \
                                       q_lower not in event_info["team_b"]["name"].lower():
                                        continue
                                found_events.append(event_info)
            except Exception as e:
                print(f"[KalshiClient] Search error on series {series}: {e}")

        # Fallback: if fewer than 5 found, fetch general open events
        if len(found_events) < 5:
            try:
                resp = await self.client.get(f"/events?status=open&with_nested_markets=true&limit=100")
                if resp.status_code == 200:
                    data = resp.json()
                    for ev in data.get("events", []):
                        if ev.get("category") == "Sports" or any(k in ev.get("title", "").lower() for k in [" vs ", "game", "winner"]):
                            markets = ev.get("markets", [])
                            if len(markets) >= 2:
                                event_info = self._format_event(ev)
                                if event_info and event_info["event_ticker"] not in [x["event_ticker"] for x in found_events]:
                                    found_events.append(event_info)
            except Exception as e:
                print(f"[KalshiClient] Fallback search error: {e}")

        return found_events[:limit]

    def _format_event(self, ev: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        markets = ev.get("markets", [])
        if len(markets) < 2:
            return None

        # Sort or identify Team A and Team B
        m_a = markets[0]
        m_b = markets[1]

        # Clean team names from yes_sub_title or title
        team_a_name = m_a.get("yes_sub_title") or m_a.get("title", "").split(" wins")[0]
        team_b_name = m_b.get("yes_sub_title") or m_b.get("title", "").split(" wins")[0]

        return {
            "event_ticker": ev.get("event_ticker"),
            "title": ev.get("title"),
            "sub_title": ev.get("sub_title", ""),
            "category": ev.get("category", "Sports"),
            "team_a": {
                "name": team_a_name,
                "ticker": m_a.get("ticker"),
                "title": m_a.get("title"),
                "yes_bid": self._parse_price(m_a.get("yes_bid") or m_a.get("yes_bid_dollars")),
                "yes_ask": self._parse_price(m_a.get("yes_ask") or m_a.get("yes_ask_dollars")),
                "last_price": self._parse_price(m_a.get("last_price") or m_a.get("last_price_dollars"))
            },
            "team_b": {
                "name": team_b_name,
                "ticker": m_b.get("ticker"),
                "title": m_b.get("title"),
                "yes_bid": self._parse_price(m_b.get("yes_bid") or m_b.get("yes_bid_dollars")),
                "yes_ask": self._parse_price(m_b.get("yes_ask") or m_b.get("yes_ask_dollars")),
                "last_price": self._parse_price(m_b.get("last_price") or m_b.get("last_price_dollars"))
            }
        }

    def _parse_price(self, val) -> Optional[float]:
        if val is None:
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    async def get_market_quote(self, ticker: str) -> Dict[str, Any]:
        """Fetch ultra-fresh orderbook top-of-book for a market ticker."""
        if self.client is None:
            await self.initialize()

        url = f"/markets/{ticker}"
        resp = await self.client.get(url)
        if resp.status_code == 200:
            m = resp.json().get("market", {})
            yes_bid = self._parse_price(m.get("yes_bid_dollars") or m.get("yes_bid"))
            yes_ask = self._parse_price(m.get("yes_ask_dollars") or m.get("yes_ask"))
            last_price = self._parse_price(m.get("last_price_dollars") or m.get("last_price"))
            return {
                "ticker": ticker,
                "yes_bid": yes_bid,
                "yes_ask": yes_ask,
                "last_price": last_price,
                "status": m.get("status", "active")
            }
        return {"ticker": ticker, "error": resp.text, "status_code": resp.status_code}

    async def place_order(
        self,
        ticker: str,
        side: str,  # 'bid' (buy Yes) or 'ask'
        price: float,
        count: int,
        client_order_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Submits an order with exact timing diagnostics.
        """
        start_time = time.perf_counter()
        order_id = client_order_id or str(uuid.uuid4())

        # Safety price bounds (Kalshi contracts trade between $0.01 and $0.99)
        bounded_price = max(0.01, min(0.99, round(price, 2)))
        price_str = f"{bounded_price:.4f}"

        payload = {
            "ticker": ticker,
            "side": side,
            "count": str(count),
            "price": price_str,
            "time_in_force": "good_till_canceled",
            "self_trade_prevention_type": "taker_at_cross",
            "client_order_id": order_id
        }

        if self.simulation_mode:
            # Simulate instantaneous fill
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return {
                "success": True,
                "simulated": True,
                "order_id": f"sim-{order_id[:8]}",
                "ticker": ticker,
                "side": side,
                "price": bounded_price,
                "count": count,
                "total_cost": round(bounded_price * count, 2),
                "status": "executed",
                "roundtrip_ms": round(elapsed_ms, 2),
                "timestamp": time.time()
            }

        if not self.auth.is_configured:
            return {
                "success": False,
                "error": "Kalshi credentials not configured. Please set KALSHI_KEY_ID and KALSHI_PRIVATE_KEY_PATH in .env, or enable SIMULATION_MODE.",
                "roundtrip_ms": (time.perf_counter() - start_time) * 1000.0
            }

        if self.client is None:
            await self.initialize()

        # Kalshi V2 Create Order endpoint
        path = "/portfolio/events/orders"
        headers = self._get_auth_headers("POST", path)

        try:
            resp = await self.client.post(path, json=payload, headers=headers)
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0

            if resp.status_code in (200, 201):
                data = resp.json()
                order_info = data.get("order", data)
                return {
                    "success": True,
                    "simulated": False,
                    "order_id": order_info.get("order_id", order_id),
                    "ticker": ticker,
                    "side": side,
                    "price": bounded_price,
                    "count": count,
                    "total_cost": round(bounded_price * count, 2),
                    "status": order_info.get("status", "resting"),
                    "roundtrip_ms": round(elapsed_ms, 2),
                    "timestamp": time.time(),
                    "raw": data
                }
            else:
                # Try legacy path if V2 event order path returns 404
                if resp.status_code == 404:
                    legacy_path = "/portfolio/orders"
                    headers_leg = self._get_auth_headers("POST", legacy_path)
                    resp_leg = await self.client.post(legacy_path, json=payload, headers=headers_leg)
                    elapsed_ms_leg = (time.perf_counter() - start_time) * 1000.0
                    if resp_leg.status_code in (200, 201):
                        data_leg = resp_leg.json()
                        order_info = data_leg.get("order", data_leg)
                        return {
                            "success": True,
                            "simulated": False,
                            "order_id": order_info.get("order_id", order_id),
                            "ticker": ticker,
                            "price": bounded_price,
                            "count": count,
                            "status": order_info.get("status", "resting"),
                            "roundtrip_ms": round(elapsed_ms_leg, 2)
                        }

                return {
                    "success": False,
                    "simulated": False,
                    "error": resp.text,
                    "status_code": resp.status_code,
                    "roundtrip_ms": round(elapsed_ms, 2)
                }
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return {
                "success": False,
                "error": str(exc),
                "roundtrip_ms": round(elapsed_ms, 2)
            }
