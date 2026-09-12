import asyncio
import time
from typing import Dict, Any, Optional, List, Callable
from kalshi_client import KalshiClient
from config import (
    DEFAULT_BET_AMOUNT_DOLLARS,
    DEFAULT_PRICE_BUFFER_CENTS,
    DEFAULT_PRICE_MODE,
    POLL_INTERVAL_SECONDS
)
from analytics import AnalyticsManager


class FastBetEngine:
    """
    Central fast betting orchestrator.
    Maintains pre-cached real-time quotes for Moneyline, Spread, and Over/Under
    in the active game, handles high-speed order calculation and execution,
    and manages multi-client subscriptions.
    """

    def __init__(self):
        self.client = KalshiClient()
        self.active_event: Optional[Dict[str, Any]] = None
        self.default_bet_amount = DEFAULT_BET_AMOUNT_DOLLARS
        self.default_buffer = DEFAULT_PRICE_BUFFER_CENTS
        self.default_price_mode = DEFAULT_PRICE_MODE
        self.poll_interval = POLL_INTERVAL_SECONDS
        self._ml_poll_task: Optional[asyncio.Task] = None
        self._deriv_poll_task: Optional[asyncio.Task] = None
        self._last_ml_broadcast: float = 0.0
        self._subscribers: List[Callable[[Dict[str, Any]], Any]] = []
        self.order_history: List[Dict[str, Any]] = []
        self.cached_balance: float = 0.0
        self._balance_counter: int = 0
        self.is_running = False

    async def start(self):
        """Initializes client and background high-frequency price streamers."""
        await self.client.initialize()
        self.is_running = True
        await self.refresh_balance()
        # Launch dedicated concurrent split-stream loops:
        # 1. Ultra-fast Moneyline Hot Loop (~65ms)
        # 2. Derivatives & Liquidity Scoring Loop (~280ms)
        self._ml_poll_task = asyncio.create_task(self._moneyline_stream_loop())
        self._deriv_poll_task = asyncio.create_task(self._derivatives_stream_loop())

    async def refresh_balance(self) -> float:
        """Fetches live account balance from Kalshi and caches it."""
        try:
            res = await self.client.get_balance()
            if isinstance(res, dict) and "balance_dollars" in res:
                self.cached_balance = round(float(res["balance_dollars"]), 2)
        except Exception as e:
            print(f"[Engine] Balance refresh error: {e}")
        return self.cached_balance

    async def stop(self):
        self.is_running = False
        if self._ml_poll_task:
            self._ml_poll_task.cancel()
        if self._deriv_poll_task:
            self._deriv_poll_task.cancel()
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

    async def _broadcast_quote_update(self):
        """Broadcast live quotes and most-liquid primary indexes to all phone views."""
        if not self.active_event:
            return
        await self._broadcast({
            "type": "quote_update",
            "team_a": self.active_event.get("team_a", {}),
            "team_b": self.active_event.get("team_b", {}),
            "spread": self.active_event.get("spread", []),
            "total": self.active_event.get("total", []),
            "primary_spread_idx": self.active_event.get("primary_spread_idx", 0),
            "primary_total_idx": self.active_event.get("primary_total_idx", 0),
            "balance": self.cached_balance,
            "timestamp": time.time()
        })

    async def select_game_by_event(self, event_data: Dict[str, Any]):
        """Set the active game for 1-tap direct betting, loading all market types."""
        event_ticker = event_data.get("event_ticker")
        if event_ticker and event_ticker != "MANUAL":
            try:
                bundle = await self.client.get_game_bundle(event_ticker)
                if bundle.get("moneyline"):
                    self.active_event = bundle["moneyline"]
                    self.active_event["spread"] = bundle.get("spread", [])
                    self.active_event["total"] = bundle.get("total", [])
                    self.active_event["primary_spread_idx"] = bundle.get("primary_spread_idx", 0)
                    self.active_event["primary_total_idx"] = bundle.get("primary_total_idx", 0)
                    self.active_event["active_spread_idx"] = bundle.get("primary_spread_idx", 0)
                    self.active_event["active_total_idx"] = bundle.get("primary_total_idx", 0)

                    await self._broadcast({
                        "type": "game_selected",
                        "active_event": self.active_event,
                        "primary_spread_idx": self.active_event["primary_spread_idx"],
                        "primary_total_idx": self.active_event["primary_total_idx"],
                        "balance": self.cached_balance
                    })
                    return
            except Exception as e:
                print(f"[Engine] Error loading full game bundle for {event_ticker}: {e}")

        # Fallback
        self.active_event = event_data
        if "spread" not in self.active_event:
            self.active_event["spread"] = []
        if "total" not in self.active_event:
            self.active_event["total"] = []
        self.active_event["primary_spread_idx"] = 0
        self.active_event["primary_total_idx"] = 0
        self.active_event["active_spread_idx"] = 0
        self.active_event["active_total_idx"] = 0

        await self._broadcast_quote_update()
        await self._broadcast({
            "type": "game_selected",
            "active_event": self.active_event,
            "primary_spread_idx": 0,
            "primary_total_idx": 0,
            "balance": self.cached_balance
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
            },
            "spread": [],
            "total": [],
            "primary_spread_idx": 0,
            "primary_total_idx": 0,
            "active_spread_idx": 0,
            "active_total_idx": 0
        }
        await self._broadcast_quote_update()
        await self._broadcast({
            "type": "game_selected",
            "active_event": self.active_event,
            "primary_spread_idx": 0,
            "primary_total_idx": 0,
            "balance": self.cached_balance
        })

    async def _moneyline_stream_loop(self):
        """
        Ultra-fast loop dedicated to Moneyline quotes running at ~65ms (~15 updates/sec).
        Directly queries the active game's event with minimal payload for sub-50ms odds latency.
        """
        while self.is_running:
            try:
                if self.active_event and self.active_event.get("event_ticker"):
                    ev_ticker = self.active_event["event_ticker"]
                    if ev_ticker != "MANUAL":
                        game_ev = await self.client.get_event(ev_ticker)
                        if game_ev and "team_a" in game_ev and "team_b" in game_ev:
                            new_a_ask = game_ev["team_a"].get("yes_ask")
                            new_b_ask = game_ev["team_b"].get("yes_ask")
                            new_a_bid = game_ev["team_a"].get("yes_bid")
                            new_b_bid = game_ev["team_b"].get("yes_bid")

                            old_a_ask = self.active_event["team_a"].get("yes_ask")
                            old_b_ask = self.active_event["team_b"].get("yes_ask")
                            old_a_bid = self.active_event["team_a"].get("yes_bid")
                            old_b_bid = self.active_event["team_b"].get("yes_bid")

                            price_changed = (
                                new_a_ask != old_a_ask or new_b_ask != old_b_ask or
                                new_a_bid != old_a_bid or new_b_bid != old_b_bid
                            )

                            self.active_event["team_a"]["yes_bid"] = new_a_bid
                            self.active_event["team_a"]["yes_ask"] = new_a_ask
                            self.active_event["team_a"]["last_price"] = game_ev["team_a"].get("last_price")

                            self.active_event["team_b"]["yes_bid"] = new_b_bid
                            self.active_event["team_b"]["yes_ask"] = new_b_ask
                            self.active_event["team_b"]["last_price"] = game_ev["team_b"].get("last_price")

                            # Push immediately if prices changed, or periodic heartbeat
                            now = time.time()
                            if price_changed or (now - self._last_ml_broadcast >= 0.25):
                                await self._broadcast_quote_update()
                                self._last_ml_broadcast = now
                    else:
                        # Fallback for manual or single tickers
                        t_a = self.active_event.get("team_a", {}).get("ticker")
                        t_b = self.active_event.get("team_b", {}).get("ticker")
                        if t_a and t_b:
                            quote_a_task = self.client.get_market_quote(t_a)
                            quote_b_task = self.client.get_market_quote(t_b)
                            quote_a, quote_b = await asyncio.gather(quote_a_task, quote_b_task, return_exceptions=True)
                            if isinstance(quote_a, dict) and "error" not in quote_a:
                                self.active_event["team_a"]["yes_bid"] = quote_a.get("yes_bid")
                                self.active_event["team_a"]["yes_ask"] = quote_a.get("yes_ask")
                                self.active_event["team_a"]["last_price"] = quote_a.get("last_price")
                            if isinstance(quote_b, dict) and "error" not in quote_b:
                                self.active_event["team_b"]["yes_bid"] = quote_b.get("yes_bid")
                                self.active_event["team_b"]["yes_ask"] = quote_b.get("yes_ask")
                                self.active_event["team_b"]["last_price"] = quote_b.get("last_price")
                            await self._broadcast_quote_update()
            except asyncio.CancelledError:
                break
            except Exception as e:
                await asyncio.sleep(0.1)
            await asyncio.sleep(0.065)

    async def _derivatives_stream_loop(self):
        """
        Concurrently polls spread and total markets, runs liquidity scoring,
        identifies the primary featured lines, and syncs account balance.
        """
        while self.is_running:
            try:
                self._balance_counter += 1
                if self._balance_counter % 12 == 0:  # Refresh balance every ~3.5 seconds
                    await self.refresh_balance()

                if self.active_event and self.active_event.get("event_ticker"):
                    ev_ticker = self.active_event["event_ticker"]
                    if ev_ticker != "MANUAL":
                        bundle = await self.client.get_game_bundle(ev_ticker)
                        if bundle:
                            if bundle.get("spread"):
                                self.active_event["spread"] = bundle["spread"]
                                self.active_event["primary_spread_idx"] = bundle.get("primary_spread_idx", 0)
                            if bundle.get("total"):
                                self.active_event["total"] = bundle["total"]
                                self.active_event["primary_total_idx"] = bundle.get("primary_total_idx", 0)

                            await self._broadcast_quote_update()
            except asyncio.CancelledError:
                break
            except Exception as e:
                await asyncio.sleep(0.2)
            await asyncio.sleep(0.28)

    async def execute_direct_bet(
        self,
        team_side: Optional[str] = None,  # 'A', 'B', 'over', 'under'
        market_type: str = "moneyline",    # 'moneyline', 'spread', 'total'
        line_ticker: Optional[str] = None,
        outcome_side: Optional[str] = None,  # 'yes' or 'no'
        amount_dollars: Optional[float] = None,
        buffer_cents: Optional[float] = None,
        price_mode: Optional[str] = None,  # 'ask' (instant/taker) or 'bid' (maker/resting)
        client_send_time: Optional[float] = None,
        custom_label: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        ULTRA-FAST PATH:
        Executes 1-tap direct orders for Moneyline, Spread, or Over/Under markets.
        Supports both 'ask' (instant fill / taker) and 'bid' (resting maker order).
        """
        engine_start = time.perf_counter()

        if not self.active_event:
            return {"success": False, "error": "No active game selected"}

        target_dollars = amount_dollars if amount_dollars and amount_dollars > 0 else self.default_bet_amount
        buffer = buffer_cents if buffer_cents is not None else self.default_buffer
        p_mode = (price_mode or self.default_price_mode).lower()
        m_type = (market_type or "moneyline").lower()
        side_str = (team_side or "A").upper()

        ticker = None
        v2_side = "bid"
        limit_price = 0.50
        contract_cost = 0.50
        bet_label = "Bet"

        # -------------------------------------------------------------
        # 1. MONEYLINE BET
        # -------------------------------------------------------------
        if m_type == "moneyline":
            team_info = self.active_event["team_a"] if side_str == "A" else self.active_event["team_b"]
            ticker = team_info.get("ticker")
            if not ticker:
                return {"success": False, "error": f"No ticker for Team {side_str}"}

            team_name = team_info.get("name", f"Team {side_str}")
            bet_label = f"{team_name} (Moneyline)"

            # Price selection based on user mode
            if p_mode == "bid":
                base_price = team_info.get("yes_bid") or team_info.get("yes_ask") or 0.50
            else:
                base_price = team_info.get("yes_ask") or team_info.get("last_price") or team_info.get("yes_bid") or 0.50

            limit_price = round(min(0.99, max(0.01, base_price + buffer)), 2)
            contract_cost = max(0.01, base_price if p_mode == "dynamic" else limit_price)
            v2_side = "bid"

        # -------------------------------------------------------------
        # 2. SPREAD BET
        # -------------------------------------------------------------
        elif m_type == "spread":
            spread_lines = self.active_event.get("spread", [])
            target_line = None

            if line_ticker:
                for ln in spread_lines:
                    if ln.get("ticker") == line_ticker:
                        target_line = ln
                        break

            if not target_line and spread_lines:
                idx = self.active_event.get("active_spread_idx", 0)
                if 0 <= idx < len(spread_lines):
                    target_line = spread_lines[idx]
                else:
                    target_line = spread_lines[0]

            if not target_line:
                return {"success": False, "error": "No spread lines available for this game"}

            ticker = target_line.get("ticker")
            is_fav = (side_str in ("A", "FAV") or outcome_side == "yes")

            if is_fav:
                # Buying Favorite (YES)
                bet_label = target_line.get("fav_label", f"{target_line.get('team_fav')} Spread")
                if p_mode == "bid":
                    base_price = target_line.get("fav_bid") or target_line.get("fav_ask") or 0.50
                else:
                    base_price = target_line.get("fav_ask") or target_line.get("fav_bid") or 0.50

                limit_price = round(min(0.99, max(0.01, base_price + buffer)), 2)
                contract_cost = max(0.01, base_price if p_mode == "dynamic" else limit_price)
                v2_side = "bid"
            else:
                # Buying Dog (NO)
                bet_label = target_line.get("dog_label", f"{target_line.get('team_dog')} Spread")
                if p_mode == "bid":
                    base_price_no = target_line.get("dog_bid") or target_line.get("dog_ask") or 0.50
                else:
                    base_price_no = target_line.get("dog_ask") or target_line.get("dog_bid") or 0.50

                limit_price_no = round(min(0.99, max(0.01, base_price_no + buffer)), 2)
                contract_cost = max(0.01, base_price_no if p_mode == "dynamic" else limit_price_no)
                # In Kalshi single-book V2, buying NO at limit_price_no is submitted as side="ask" at price (1.0 - limit_price_no)
                limit_price = round(min(0.99, max(0.01, 1.0 - limit_price_no)), 2)
                v2_side = "ask"

        # -------------------------------------------------------------
        # 3. TOTAL (OVER/UNDER) BET
        # -------------------------------------------------------------
        elif m_type == "total":
            total_lines = self.active_event.get("total", [])
            target_line = None

            if line_ticker:
                for ln in total_lines:
                    if ln.get("ticker") == line_ticker:
                        target_line = ln
                        break

            if not target_line and total_lines:
                idx = self.active_event.get("active_total_idx", 0)
                if 0 <= idx < len(total_lines):
                    target_line = total_lines[idx]
                else:
                    target_line = total_lines[0]

            if not target_line:
                return {"success": False, "error": "No total (O/U) lines available for this game"}

            ticker = target_line.get("ticker")
            is_over = (side_str in ("A", "OVER") or outcome_side == "yes")

            if is_over:
                # Buying OVER (YES)
                bet_label = target_line.get("over_label", "OVER")
                if p_mode == "bid":
                    base_price = target_line.get("over_bid") or target_line.get("over_ask") or 0.50
                else:
                    base_price = target_line.get("over_ask") or target_line.get("over_bid") or 0.50

                limit_price = round(min(0.99, max(0.01, base_price + buffer)), 2)
                contract_cost = max(0.01, base_price if p_mode == "dynamic" else limit_price)
                v2_side = "bid"
            else:
                # Buying UNDER (NO)
                bet_label = target_line.get("under_label", "UNDER")
                if p_mode == "bid":
                    base_price_no = target_line.get("under_bid") or target_line.get("under_ask") or 0.50
                else:
                    base_price_no = target_line.get("under_ask") or target_line.get("under_bid") or 0.50

                limit_price_no = round(min(0.99, max(0.01, base_price_no + buffer)), 2)
                contract_cost = max(0.01, base_price_no if p_mode == "dynamic" else limit_price_no)
                limit_price = round(min(0.99, max(0.01, 1.0 - limit_price_no)), 2)
                v2_side = "ask"

        if not ticker:
            return {"success": False, "error": "Unable to determine contract ticker"}

        # Calculate contract count based on target dollar amount or MAX remaining balance
        is_all_in = str(amount_dollars).lower() in ("max", "all", "all_in", "balance", "-1")

        if is_all_in:
            if self.cached_balance <= 0:
                await self.refresh_balance()

            avail_balance = self.cached_balance
            if avail_balance <= 0.50:
                return {
                    "success": False,
                    "error": f"Insufficient balance for Max Bet (${avail_balance:.2f} available)"
                }

            # Use maximum possible execution price (limit_price) so dynamic slippage never exceeds balance
            max_execution_price = contract_cost if p_mode == "dynamic" and buffer <= 0 else max(contract_cost, limit_price if v2_side == "bid" else round(1.0 - limit_price, 2))
            max_execution_price = max(0.01, min(0.99, max_execution_price))

            # Kalshi fee cushion: max fee on taker order is ~0.07 * price * (1 - price)
            fee_per_contract = min(0.02, 0.07 * max_execution_price * (1.0 - max_execution_price) + 0.002)
            effective_unit_cost = max_execution_price + fee_per_contract

            # Keep a tiny 25¢ cushion so order is 100% accepted by Kalshi without "insufficient funds" rejection
            usable_cash = max(0.0, avail_balance - 0.25)
            count = max(1, int(usable_cash / effective_unit_cost))
            target_dollars = round(count * contract_cost, 2)
        else:
            try:
                target_dollars = float(amount_dollars) if amount_dollars and float(amount_dollars) > 0 else self.default_bet_amount
            except (ValueError, TypeError):
                target_dollars = self.default_bet_amount
            count = max(1, int(round(target_dollars / contract_cost)))

        # Time-in-force: dynamic orders use IOC (immediate or cancel); custom limit orders use GTC (resting)
        tif = "immediate_or_cancel" if p_mode == "dynamic" else "good_till_canceled"

        order_result = await self.client.place_order(
            ticker=ticker,
            side=v2_side,
            price=limit_price,
            count=count,
            time_in_force=tif
        )

        total_elapsed_ms = round((time.perf_counter() - engine_start) * 1000.0, 2)
        order_result["engine_latency_ms"] = total_elapsed_ms
        order_result["market_type"] = m_type
        order_result["team_side"] = side_str
        order_result["bet_label"] = custom_label or bet_label

        if v2_side == "ask":
            fill_price = order_result.get("price", limit_price)
            display_price = round(max(0.01, min(0.99, 1.0 - fill_price)), 2)
        else:
            display_price = order_result.get("price", contract_cost)

        order_result["display_price"] = display_price
        order_result["limit_price_submitted"] = limit_price
        order_result["price_mode"] = p_mode
        order_result["buffer_used"] = buffer
        order_result["target_dollars"] = target_dollars
        order_result["count"] = order_result.get("count", count)

        order_result["game_title"] = self.active_event.get("title", "Live Game") if self.active_event else "Live Game"
        order_result["event_ticker"] = self.active_event.get("event_ticker", "") if self.active_event else ""
        order_result["outcome_side"] = outcome_side or ("yes" if side_str == "A" else "no")

        if order_result.get("success"):
            order_result["total_cost"] = round(display_price * order_result["count"], 2)
            try:
                # Offload to background thread pool to guarantee ZERO latency impact on critical order execution path
                asyncio.create_task(asyncio.to_thread(AnalyticsManager.record_trade, order_result.copy()))
                # Asynchronously refresh cached balance after order
                asyncio.create_task(self.refresh_balance())
            except Exception as e:
                print(f"[Engine] Analytics record error: {e}")
        else:
            order_result["total_cost"] = 0.00

        if client_send_time is not None:
            order_result["client_send_time"] = client_send_time

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
            "default_price_mode": self.default_price_mode,
            "primary_spread_idx": self.active_event.get("primary_spread_idx", 0) if self.active_event else 0,
            "primary_total_idx": self.active_event.get("primary_total_idx", 0) if self.active_event else 0,
            "balance": self.cached_balance,
            "history": self.order_history[:10]
        }
