import os
import socket
import asyncio
from contextlib import asynccontextmanager
from typing import Dict, Any, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn

from config import SERVER_HOST, SERVER_PORT, BASE_DIR
from engine import FastBetEngine
from analytics import AnalyticsManager

# Global Engine instance
engine = FastBetEngine()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("[Server] Starting FastBet Direct API Engine...")
    await engine.start()
    
    # Auto-load initial live games if none set
    try:
        games = await engine.client.search_game_events(limit=5)
        if games:
            print(f"[Server] Auto-selected first available game: {games[0]['title']}")
            await engine.select_game_by_event(games[0])
    except Exception as e:
        print(f"[Server] Note: Could not auto-select game on startup: {e}")

    yield

    # Shutdown
    print("[Server] Shutting down FastBet Direct API Engine...")
    await engine.stop()


app = FastAPI(title="FastBet Kalshi Direct API", lifespan=lifespan)

# Mount static folder
static_path = BASE_DIR / "static"
if static_path.exists():
    app.mount("/static", StaticFiles(directory=str(static_path)), name="static")


@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_file = static_path / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return HTMLResponse("<h1>FastBet UI not found in static/index.html</h1>")


@app.get("/stats", response_class=HTMLResponse)
async def serve_stats():
    stats_file = static_path / "stats.html"
    if stats_file.exists():
        return FileResponse(str(stats_file))
    return HTMLResponse("<h1>FastBet Stats UI not found in static/stats.html</h1>")


# Request Models
class BetRequest(BaseModel):
    team: Optional[str] = "A"  # 'A', 'B', 'over', 'under'
    market_type: Optional[str] = "moneyline"  # 'moneyline', 'spread', 'total'
    line_ticker: Optional[str] = None
    side: Optional[str] = None  # 'yes' or 'no'
    amount: Optional[Any] = None  # float or 'max' / 'all'
    buffer: Optional[float] = None
    price_mode: Optional[str] = "ask"  # 'ask' or 'bid'
    label: Optional[str] = None


class ManualGameRequest(BaseModel):
    title: str
    team_a_name: str
    team_a_ticker: str
    team_b_name: str
    team_b_ticker: str


# REST Endpoints
@app.get("/api/state")
async def get_state():
    return engine.get_state()


@app.get("/api/balance")
async def get_balance():
    return await engine.client.get_balance()


@app.get("/api/games")
async def search_games(q: str = ""):
    return await engine.client.search_game_events(query=q, limit=25)


@app.post("/api/select_game")
async def select_game(game: Dict[str, Any]):
    await engine.select_game_by_event(game)
    return {"success": True, "active_event": engine.active_event}


@app.post("/api/manual_game")
async def set_manual_game(req: ManualGameRequest):
    await engine.select_game_by_tickers(
        event_title=req.title,
        team_a_name=req.team_a_name,
        team_a_ticker=req.team_a_ticker,
        team_b_name=req.team_b_name,
        team_b_ticker=req.team_b_ticker
    )
    return {"success": True, "active_event": engine.active_event}


@app.post("/api/bet")
async def place_bet(req: BetRequest):
    result = await engine.execute_direct_bet(
        team_side=req.team.upper() if req.team else "A",
        market_type=req.market_type or "moneyline",
        line_ticker=req.line_ticker,
        outcome_side=req.side,
        amount_dollars=req.amount,
        buffer_cents=req.buffer,
        price_mode=req.price_mode or "ask",
        custom_label=req.label
    )
    return result


# Analytics & Performance Tracking Endpoints
class SessionStartRequest(BaseModel):
    name: Optional[str] = None
    game_title: Optional[str] = None
    event_ticker: Optional[str] = None


@app.get("/api/stats/summary")
async def get_stats_summary(session_id: Optional[str] = None):
    return AnalyticsManager.get_performance_summary(session_id=session_id)


@app.get("/api/stats/trades")
async def get_stats_trades(
    session_id: Optional[str] = None,
    limit: int = 150,
    market_type: Optional[str] = None,
    status: Optional[str] = None
):
    return AnalyticsManager.get_trades(
        session_id=session_id,
        limit=limit,
        market_type=market_type,
        status=status
    )


@app.get("/api/stats/sessions")
async def get_stats_sessions():
    return {
        "sessions": AnalyticsManager.list_sessions(),
        "active_session": AnalyticsManager.get_active_session()
    }


@app.post("/api/stats/session/start")
async def start_session(req: SessionStartRequest):
    sess = AnalyticsManager.start_new_session(
        name=req.name,
        game_title=req.game_title,
        event_ticker=req.event_ticker
    )
    return {"success": True, "session": sess}


@app.post("/api/stats/session/end")
async def end_session():
    ended = AnalyticsManager.end_active_session()
    return {"success": True, "ended_session": ended}


@app.post("/api/stats/sync")
async def sync_kalshi_stats():
    result = await AnalyticsManager.sync_with_kalshi(engine.client)
    return result


# WebSocket Connection for Ultra-Low-Latency Mobile Interaction
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()

    # Callback to push engine updates to this client
    async def send_update(msg: Dict[str, Any]):
        try:
            await websocket.send_json(msg)
        except Exception:
            pass

    engine.subscribe(send_update)

    # Send initial state immediately
    init_msg = {
        "type": "init",
        **engine.get_state()
    }
    await websocket.send_json(init_msg)

    try:
        while True:
            data = await websocket.receive_json()
            action = data.get("action")

            if action == "ping":
                # Heartbeat to measure mobile-to-server latency
                await websocket.send_json({"type": "pong"})

            elif action == "bet":
                # 1-TAP INSTANT EXECUTION
                team_side = str(data.get("team", "A")).upper()
                market_type = str(data.get("market_type", "moneyline"))
                line_ticker = data.get("line_ticker")
                outcome_side = data.get("side")
                amount = data.get("amount")
                buffer_val = data.get("buffer")
                price_mode = data.get("price_mode", "ask")
                client_send_time = data.get("client_send_time")
                label = data.get("label")

                # execute_direct_bet already broadcasts 'order_executed' to all subscribed websockets
                await engine.execute_direct_bet(
                    team_side=team_side,
                    market_type=market_type,
                    line_ticker=line_ticker,
                    outcome_side=outcome_side,
                    amount_dollars=amount,
                    buffer_cents=buffer_val,
                    price_mode=price_mode,
                    client_send_time=client_send_time,
                    custom_label=label
                )

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[Server] WebSocket error: {e}")
    finally:
        engine.unsubscribe(send_update)



def get_lan_ip() -> str:
    """Returns the primary local IPv4 address."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Doesn't actually send packets
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


def print_startup_banner():
    ip = get_lan_ip()
    port = SERVER_PORT
    print("\n" + "="*65)
    print(" >>> FASTBET KALSHI DIRECT API SERVER IS RUNNING <<<")
    print("="*65)
    print(f" [>] Local Browser:  http://localhost:{port}")
    print(f" [>] Mobile Phone:   http://{ip}:{port}")
    print("="*65)
    print(" [*] To open on your phone:")
    print(f" 1. Connect phone to same Wi-Fi/Hotspot as this PC, or use Cloudflare Tunnel.")
    print(f" 2. Navigate to: http://{ip}:{port}")
    print(" 3. Toggle 'ARMED' and tap Team A or Team B to instantly bet!")
    print("="*65 + "\n")


if __name__ == "__main__":
    print_startup_banner()
    uvicorn.run("server:app", host=SERVER_HOST, port=SERVER_PORT, log_level="info")
