import asyncio
import time
from typing import Dict, Any, Optional, List, Callable
from kalshi_client import KalshiClient
from config import (
    DEFAULT_BET_AMOUNT_DOLLARS,
    DEFAULT_PRICE_BUFFER_CENTS,
    POLL_INTERVAL_SECONDS
)


class CourtsideEngine:
    """
    Central courtsiding orchestrator.
    Maintains pre-cached real-time quotes for both teams in the active game,
    handles high-speed order calculation and execution, and manages multi-client subscriptions.
    """

    def __init__(self):
        self.client = KalshiClient()
        self.active_event: Optional[Dict[str, Any]] = None
        self.default_bet_amount = DEFAULT_BET_AMOUNT_DOLLARS
        self.default_buffer = DEFAULT_PRICE_BUFFER_CENTS
        self.poll_interval = POLL_INTERVAL_SECONDS
        self._poll_task: Optional[asyncio.Task] = None
        self._subscribers: List[Callable[[Dict[str, Any]], Any]] = []
        self.order_history: List[Dict[str, Any]] = []
        self.is_running = False

    async def start(self):
        """Initializes client and background price streamer."""
        await self.client.initialize()
        self.is_running = True
        self._poll_task = asyncio.create_task(self._price_stream_loop())

    async def stop(self):
        self.is_running = False
        if self._poll_task:
            self._poll_task.cancel()
        await self.client.close()

    def subscribe(self, callback: Callable[[Dict[str, Any]], Any]):
        """Subscribe WebSocket or listener to live state updates."""
        if callback not in self._subscribers:
            self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[Dict[str, Any]], Any]):
        if callback in self._subscribers:
            self._subscribers.remove(callback)

    async def _broadcast(self, msg: Dict[str, Any]):
        for cb in list(self._subscribers):
            try:
                res = cb(msg)
                if asyncio.iscoroutine(res):
                    await res
            except Exception as e:
                print(f"[Engine] Broadcast error: {e}")

    async def select_game_by_event(self, event_data: Dict[str, Any]):
        """Set the active game for courtside betting."""
        self.active_event = event_data
        # Immediately fetch initial quotes
        await self._refresh_quotes()
        await self._broadcast({
            "type": "game_selected",
            "active_event": self.active_event
        })

    async def select_game_by_tickers(
        self,
        event_title: str,
        team_a_name: str,
        team_a_ticker: str,
        team_b_name: str,
        team_b_ticker: str
    ):
        """Manually configure an active game by tickers."""
        self.active_event = {
            "event_ticker": "MANUAL",
            "title": event_title or f"{team_a_name} vs {team_b_name}",
            "team_a": {
                "name": team_a_name,
                "ticker": team_a_ticker,
                "yes_bid": None,
                "yes_ask": None,
                "last_price": None
            },
            "team_b": {
                "name": team_b_name,
                "ticker": team_b_ticker,
                "yes_bid": None,
                "yes_ask": None,
                "last_price": None
            }
        }
        await self._refresh_quotes()
        await self._broadcast({
            "type": "game_selected",
            "active_event": self.active_event
        })

    async def _price_stream_loop(self):
        """Continuously polls orderbook quotes at low interval to ensure zero-stale data."""
        while self.is_running:
            try:
                if self.active_event:
                    await self._refresh_quotes()
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[Engine] Price stream error: {e}")
            await asyncio.sleep(self.poll_interval)

    async def _refresh_quotes(self):
        if not self.active_event:
            return

        ticker_a = self.active_event["team_a"]["ticker"]
        ticker_b = self.active_event["team_b"]["ticker"]

        # Parallel quote fetching
        quote_a_task = self.client.get_market_quote(ticker_a)
        quote_b_task = self.client.get_market_quote(ticker_b)

        quote_a, quote_b = await asyncio.gather(quote_a_task, quote_b_task, return_exceptions=True)

        updated = False
        if isinstance(quote_a, dict) and "error" not in quote_a:
            self.active_event["team_a"]["yes_bid"] = quote_a.get("yes_bid")
            self.active_event["team_a"]["yes_ask"] = quote_a.get("yes_ask")
            self.active_event["team_a"]["last_price"] = quote_a.get("last_price")
            updated = True

        if isinstance(quote_b, dict) and "error" not in quote_b:
            self.active_event["team_b"]["yes_bid"] = quote_b.get("yes_bid")
            self.active_event["team_b"]["yes_ask"] = quote_b.get("yes_ask")
            self.active_event["team_b"]["last_price"] = quote_b.get("last_price")
            updated = True

        if updated:
            await self._broadcast({
                "type": "quote_update",
                "team_a": self.active_event["team_a"],
                "team_b": self.active_event["team_b"],
                "timestamp": time.time()
            })

    async def execute_courtside_bet(
        self,
        team_side: str,  # 'A' or 'B'
        amount_dollars: Optional[float] = None,
        buffer_cents: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        ULTRA-FAST PATH:
        Triggered directly by the courtsider tapping Team A or Team B button.
        """
        engine_start = time.perf_counter()

        if not self.active_event:
            return {"success": False, "error": "No active game selected"}

        team_info = self.active_event["team_a"] if team_side == "A" else self.active_event["team_b"]
        ticker = team_info.get("ticker")
        if not ticker:
            return {"success": False, "error": f"No ticker for Team {team_side}"}

        target_dollars = amount_dollars if amount_dollars and amount_dollars > 0 else self.default_bet_amount
        buffer = buffer_cents if buffer_cents is not None else self.default_buffer

        # Calculate limit price using pre-cached ask or last_price
        cached_ask = team_info.get("yes_ask")
        cached_last = team_info.get("last_price")
        base_price = cached_ask if cached_ask is not None else (cached_last if cached_last is not None else 0.50)

        # Marketable limit price: base + buffer (e.g. 0.36 + 0.03 = 0.39)
        limit_price = round(min(0.99, max(0.01, base_price + buffer)), 2)

        # Calculate contracts count for target dollar size
        # e.g., $1.00 / $0.39 = ~2.56 -> at least 1 contract, or round(target_dollars / limit_price)
        count = max(1, int(round(target_dollars / limit_price)))

        # Send order to exchange
        order_result = await self.client.place_order(
            ticker=ticker,
            side="bid",  # Buy Yes on this team's market
            price=limit_price,
            count=count
        )

        total_elapsed_ms = round((time.perf_counter() - engine_start) * 1000.0, 2)
        order_result["engine_latency_ms"] = total_elapsed_ms
        order_result["team_side"] = team_side
        order_result["team_name"] = team_info.get("name")
        order_result["base_price"] = base_price
        order_result["buffer_used"] = buffer

        # Store in history
        self.order_history.insert(0, order_result)
        if len(self.order_history) > 50:
            self.order_history.pop()

        # Broadcast execution notification to all connected phone views
        await self._broadcast({
            "type": "order_executed",
            "order": order_result
        })

        return order_result

    def get_state(self) -> Dict[str, Any]:
        """Current state for newly connected phones."""
        return {
            "active_event": self.active_event,
            "simulation_mode": self.client.simulation_mode,
            "default_bet_amount": self.default_bet_amount,
            "default_buffer": self.default_buffer,
            "history": self.order_history[:10]
        }
