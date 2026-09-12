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
    High-performance Kalshi API client optimized for ultra-low latency direct trading.
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
                headers={"User-Agent": "FastBetKalshi/1.0", "Accept": "application/json"}
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
                            # Format for direct betting
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
            p = float(val)
            # Kalshi contracts trade between $0.01 and $0.99. If API returns cents (>1.0), normalize to dollars
            if p > 1.0:
                p = p / 100.0
            return p
        except (ValueError, TypeError):
            return None

    async def get_event(self, event_ticker: str) -> Optional[Dict[str, Any]]:
        """Fetch full event object with nested markets in a single fast HTTP call."""
        if self.client is None:
            await self.initialize()

        url = f"/events/{event_ticker}?with_nested_markets=true"
        resp = await self.client.get(url)
        if resp.status_code == 200:
            ev = resp.json().get("event", {})
            return self._format_event(ev)
        return None

    async def get_game_bundle(self, event_ticker: str) -> Dict[str, Any]:
        """
        Fetches full game bundle: Moneyline, Point Spread lines, and Total (Over/Under) lines.
        Queries the game event and its associated spread and total events concurrently.
        """
        if self.client is None:
            await self.initialize()

        bundle = {
            "event_ticker": event_ticker,
            "title": "",
            "category": "Sports",
            "moneyline": None,
            "spread": [],
            "total": [],
            "spread_ticker": None,
            "total_ticker": None
        }

        # Derive spread and total event tickers from standard Kalshi naming pattern
        spread_ticker = None
        total_ticker = None
        if "GAME" in event_ticker:
            spread_ticker = event_ticker.replace("GAME", "SPREAD")
            total_ticker = event_ticker.replace("GAME", "TOTAL")
            bundle["spread_ticker"] = spread_ticker
            bundle["total_ticker"] = total_ticker

        async def fetch_event_data(url: str) -> Dict[str, Any]:
            try:
                r = await self.client.get(url)
                if r.status_code == 200:
                    return r.json().get("event", {})
            except Exception as exc:
                print(f"[KalshiClient] fetch_event_data error ({url}): {exc}")
            return {}

        tasks = [fetch_event_data(f"/events/{event_ticker}?with_nested_markets=true")]
        if spread_ticker:
            tasks.append(fetch_event_data(f"/events/{spread_ticker}?with_nested_markets=true"))
        else:
            tasks.append(asyncio.sleep(0, result={}))

        if total_ticker:
            tasks.append(fetch_event_data(f"/events/{total_ticker}?with_nested_markets=true"))
        else:
            tasks.append(asyncio.sleep(0, result={}))

        res_game, res_spread, res_total = await asyncio.gather(*tasks, return_exceptions=True)

        team_a_name = "Team A"
        team_b_name = "Team B"

        # 1. Parse Moneyline
        if isinstance(res_game, dict) and res_game:
            bundle["title"] = res_game.get("title", "")
            bundle["category"] = res_game.get("category", "Sports")
            markets = res_game.get("markets", [])
            if len(markets) >= 2:
                m_a = markets[0]
                m_b = markets[1]
                team_a_name = m_a.get("yes_sub_title") or m_a.get("title", "").split(" wins")[0]
                team_b_name = m_b.get("yes_sub_title") or m_b.get("title", "").split(" wins")[0]

                bundle["moneyline"] = {
                    "event_ticker": event_ticker,
                    "title": res_game.get("title"),
                    "team_a": {
                        "name": team_a_name,
                        "ticker": m_a.get("ticker"),
                        "title": m_a.get("title"),
                        "yes_bid": self._parse_price(m_a.get("yes_bid_dollars") if m_a.get("yes_bid_dollars") is not None else m_a.get("yes_bid")),
                        "yes_ask": self._parse_price(m_a.get("yes_ask_dollars") if m_a.get("yes_ask_dollars") is not None else m_a.get("yes_ask")),
                        "last_price": self._parse_price(m_a.get("last_price_dollars") if m_a.get("last_price_dollars") is not None else m_a.get("last_price"))
                    },
                    "team_b": {
                        "name": team_b_name,
                        "ticker": m_b.get("ticker"),
                        "title": m_b.get("title"),
                        "yes_bid": self._parse_price(m_b.get("yes_bid_dollars") if m_b.get("yes_bid_dollars") is not None else m_b.get("yes_bid")),
                        "yes_ask": self._parse_price(m_b.get("yes_ask_dollars") if m_b.get("yes_ask_dollars") is not None else m_b.get("yes_ask")),
                        "last_price": self._parse_price(m_b.get("last_price_dollars") if m_b.get("last_price_dollars") is not None else m_b.get("last_price"))
                    }
                }

        # 2. Parse Spread Lines
        if isinstance(res_spread, dict) and res_spread:
            spread_mkts = res_spread.get("markets", [])
            for m in spread_mkts:
                sub = m.get("yes_sub_title") or m.get("title", "")
                team_fav = team_a_name if team_a_name.lower() in sub.lower() else team_b_name
                team_dog = team_b_name if team_fav == team_a_name else team_a_name
                strike = m.get("floor_strike")

                y_bid = self._parse_price(m.get("yes_bid_dollars") if m.get("yes_bid_dollars") is not None else m.get("yes_bid"))
                y_ask = self._parse_price(m.get("yes_ask_dollars") if m.get("yes_ask_dollars") is not None else m.get("yes_ask"))
                n_bid = self._parse_price(m.get("no_bid_dollars") if m.get("no_bid_dollars") is not None else m.get("no_bid"))
                n_ask = self._parse_price(m.get("no_ask_dollars") if m.get("no_ask_dollars") is not None else m.get("no_ask"))

                if n_ask is None and y_bid is not None:
                    n_ask = round(1.0 - y_bid, 2)
                if n_bid is None and y_ask is not None:
                    n_bid = round(1.0 - y_ask, 2)

                bundle["spread"].append({
                    "ticker": m.get("ticker"),
                    "strike": strike,
                    "team_fav": team_fav,
                    "team_dog": team_dog,
                    "fav_label": f"{team_fav} -{strike}" if strike is not None else f"{team_fav} Cover",
                    "dog_label": f"{team_dog} +{strike}" if strike is not None else f"{team_dog} Cover",
                    "fav_bid": y_bid,
                    "fav_ask": y_ask,
                    "dog_bid": n_bid,
                    "dog_ask": n_ask,
                    "status": m.get("status", "active")
                })

        # 3. Parse Total (Over/Under) Lines
        if isinstance(res_total, dict) and res_total:
            total_mkts = res_total.get("markets", [])
            for m in total_mkts:
                strike = m.get("floor_strike")
                y_bid = self._parse_price(m.get("yes_bid_dollars") if m.get("yes_bid_dollars") is not None else m.get("yes_bid"))
                y_ask = self._parse_price(m.get("yes_ask_dollars") if m.get("yes_ask_dollars") is not None else m.get("yes_ask"))
                n_bid = self._parse_price(m.get("no_bid_dollars") if m.get("no_bid_dollars") is not None else m.get("no_bid"))
                n_ask = self._parse_price(m.get("no_ask_dollars") if m.get("no_ask_dollars") is not None else m.get("no_ask"))

                if n_ask is None and y_bid is not None:
                    n_ask = round(1.0 - y_bid, 2)
                if n_bid is None and y_ask is not None:
                    n_bid = round(1.0 - y_ask, 2)

                bundle["total"].append({
                    "ticker": m.get("ticker"),
                    "strike": strike,
                    "over_label": f"OVER {strike}" if strike is not None else "OVER",
                    "under_label": f"UNDER {strike}" if strike is not None else "UNDER",
                    "over_bid": y_bid,
                    "over_ask": y_ask,
                    "under_bid": n_bid,
                    "under_ask": n_ask,
                    "status": m.get("status", "active")
                })
            bundle["total"].sort(key=lambda x: x["strike"] if x["strike"] is not None else 0)

        return bundle

    async def get_market_quote(self, ticker: str) -> Dict[str, Any]:
        """Fetch ultra-fresh orderbook top-of-book for a market ticker."""
        if self.client is None:
            await self.initialize()

        url = f"/markets/{ticker}"
        resp = await self.client.get(url)
        if resp.status_code == 200:
            m = resp.json().get("market", {})
            yes_bid = self._parse_price(m.get("yes_bid_dollars") if m.get("yes_bid_dollars") is not None else m.get("yes_bid"))
            yes_ask = self._parse_price(m.get("yes_ask_dollars") if m.get("yes_ask_dollars") is not None else m.get("yes_ask"))
            last_price = self._parse_price(m.get("last_price_dollars") if m.get("last_price_dollars") is not None else m.get("last_price"))
            no_bid = self._parse_price(m.get("no_bid_dollars") if m.get("no_bid_dollars") is not None else m.get("no_bid"))
            no_ask = self._parse_price(m.get("no_ask_dollars") if m.get("no_ask_dollars") is not None else m.get("no_ask"))

            if no_ask is None and yes_bid is not None:
                no_ask = round(1.0 - yes_bid, 2)
            if no_bid is None and yes_ask is not None:
                no_bid = round(1.0 - yes_ask, 2)

            return {
                "ticker": ticker,
                "yes_bid": yes_bid,
                "yes_ask": yes_ask,
                "no_bid": no_bid,
                "no_ask": no_ask,
                "last_price": last_price,
                "status": m.get("status", "active")
            }
        return {"ticker": ticker, "error": resp.text, "status_code": resp.status_code}

    async def place_order(
        self,
        ticker: str,
        side: str,  # 'bid' (buy Yes) or 'ask' (buy No in single-book)
        price: float,
        count: int,
        time_in_force: str = "immediate_or_cancel",
        client_order_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Submits an order with exact timing diagnostics.
        In Kalshi single-book V2:
        - side: 'bid' buys YES outcome at limit price
        - side: 'ask' buys NO outcome in single-book at limit price
        - time_in_force: 'immediate_or_cancel' (IOC) ensures dynamic market execution without resting orders
        """
        start_time = time.perf_counter()
        order_id = client_order_id or str(uuid.uuid4())

        # Safety price bounds (Kalshi contracts trade between $0.01 and $0.99)
        bounded_price = max(0.01, min(0.99, round(price, 2)))
        price_str = f"{bounded_price:.4f}"
        order_count = max(1, count)

        payload = {
            "ticker": ticker,
            "side": side,
            "count": str(order_count),
            "price": price_str,
            "time_in_force": time_in_force,
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
                "count": order_count,
                "total_cost": round(bounded_price * order_count, 2),
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
                fill_cnt_raw = order_info.get("fill_count")
                fill_cnt = float(fill_cnt_raw) if fill_cnt_raw is not None else float(order_count)

                # If IOC and fill_count is 0, the order was canceled by exchange due to price moving past dynamic cap
                if fill_cnt == 0 and time_in_force == "immediate_or_cancel":
                    return {
                        "success": False,
                        "simulated": False,
                        "order_id": order_info.get("order_id", order_id),
                        "ticker": ticker,
                        "side": side,
                        "price": bounded_price,
                        "error": "Price moved beyond dynamic cap (Unfilled/Canceled)",
                        "roundtrip_ms": round(elapsed_ms, 2),
                        "timestamp": time.time(),
                        "raw": data
                    }

                avg_price = self._parse_price(order_info.get("average_fill_price"))
                actual_fill_price = avg_price if avg_price is not None else bounded_price
                actual_count = int(round(fill_cnt)) if fill_cnt > 0 else order_count

                return {
                    "success": True,
                    "simulated": False,
                    "order_id": order_info.get("order_id", order_id),
                    "ticker": ticker,
                    "side": side,
                    "price": actual_fill_price,
                    "count": actual_count,
                    "total_cost": round(actual_fill_price * actual_count, 2),
                    "status": order_info.get("status", "executed"),
                    "roundtrip_ms": round(elapsed_ms, 2),
                    "timestamp": time.time(),
                    "raw": data
                }
            else:
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


