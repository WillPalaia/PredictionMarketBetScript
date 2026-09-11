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
from engine import CourtsideEngine

# Global Engine instance
engine = CourtsideEngine()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("[Server] Starting Courtside Betting Engine...")
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
    print("[Server] Shutting down Courtside Betting Engine...")
    await engine.stop()


app = FastAPI(title="Courtside Kalshi Bet Script", lifespan=lifespan)

# Mount static folder
static_path = BASE_DIR / "static"
if static_path.exists():
    app.mount("/static", StaticFiles(directory=str(static_path)), name="static")


@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_file = static_path / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return HTMLResponse("<h1>Courtside UI not found in static/index.html</h1>")


# Request Models
class BetRequest(BaseModel):
    team: str  # 'A' or 'B'
    amount: Optional[float] = None
    buffer: Optional[float] = None


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
    if req.team.upper() not in ("A", "B"):
        raise HTTPException(status_code=400, detail="Team must be 'A' or 'B'")
    result = await engine.execute_courtside_bet(
        team_side=req.team.upper(),
        amount_dollars=req.amount,
        buffer_cents=req.buffer
    )
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
                team_side = str(data.get("team", "")).upper()
                amount = data.get("amount")
                buffer_val = data.get("buffer")
                client_send_time = data.get("client_send_time")

                result = await engine.execute_courtside_bet(
                    team_side=team_side,
                    amount_dollars=amount,
                    buffer_cents=buffer_val
                )
                if client_send_time is not None:
                    result["client_send_time"] = client_send_time

                # Direct response back to this phone
                await websocket.send_json({
                    "type": "order_executed",
                    "order": result
                })

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
    print(" >>> COURTSIDE KALSHI BETTING SERVER IS RUNNING <<<")
    print("="*65)
    print(f" [>] Local Browser:  http://localhost:{port}")
    print(f" [>] Mobile Phone:   http://{ip}:{port}")
    print("="*65)
    print(" [*] To open on your phone at the game:")
    print(f" 1. Connect phone to same Wi-Fi/Hotspot as this PC, or use Tailscale/ngrok.")
    print(f" 2. Navigate to: http://{ip}:{port}")
    print(" 3. Toggle 'ARMED' and tap Team A or Team B to instantly bet!")
    print("="*65 + "\n")


if __name__ == "__main__":
    print_startup_banner()
    uvicorn.run("server:app", host=SERVER_HOST, port=SERVER_PORT, log_level="info")
