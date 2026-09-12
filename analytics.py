import sqlite3
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

from config import BASE_DIR

DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "analytics.db"


def get_db_connection() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initializes SQLite tables for sessions and trades."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                game_title TEXT,
                event_ticker TEXT,
                start_time REAL NOT NULL,
                end_time REAL,
                is_active INTEGER NOT NULL DEFAULT 1,
                notes TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                order_id TEXT PRIMARY KEY,
                session_id TEXT,
                timestamp REAL NOT NULL,
                created_at TEXT NOT NULL,
                game_title TEXT,
                event_ticker TEXT,
                market_type TEXT,
                market_ticker TEXT,
                side TEXT,
                label TEXT,
                order_type TEXT,
                price REAL NOT NULL,
                count INTEGER NOT NULL,
                total_cost REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                payout REAL DEFAULT 0.0,
                pnl REAL DEFAULT 0.0,
                latency_ms REAL,
                source TEXT DEFAULT 'fastbet',
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            )
        """)
        conn.commit()


# Initialize tables on import
init_db()


class AnalyticsManager:
    """Manages trade sessions, stats aggregation, and Kalshi portfolio reconciliation."""

    @staticmethod
    def get_active_session() -> Optional[Dict[str, Any]]:
        with get_db_connection() as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE is_active = 1 ORDER BY start_time DESC LIMIT 1"
            ).fetchone()
            if row:
                return dict(row)
        return None

    @staticmethod
    def get_or_create_active_session(game_title: Optional[str] = None, event_ticker: Optional[str] = None) -> Dict[str, Any]:
        active = AnalyticsManager.get_active_session()
        if active:
            # If current active session already matches event or no specific event requested
            if not event_ticker or active.get("event_ticker") == event_ticker:
                return active
            # If a different game was explicitly selected, close previous and start new session for new game
            AnalyticsManager.end_active_session()

        # Create new session
        session_id = f"sess_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        now = time.time()
        time_label = datetime.fromtimestamp(now).strftime("%b %d, %I:%M %p")
        title = game_title or "Live Session"
        name = f"{title} ({time_label})"

        with get_db_connection() as conn:
            conn.execute(
                """INSERT INTO sessions (id, name, game_title, event_ticker, start_time, is_active)
                   VALUES (?, ?, ?, ?, ?, 1)""",
                (session_id, name, game_title, event_ticker, now)
            )
            conn.commit()

        return {
            "id": session_id,
            "name": name,
            "game_title": game_title,
            "event_ticker": event_ticker,
            "start_time": now,
            "is_active": 1
        }

    @staticmethod
    def start_new_session(name: Optional[str] = None, game_title: Optional[str] = None, event_ticker: Optional[str] = None) -> Dict[str, Any]:
        AnalyticsManager.end_active_session()
        session_id = f"sess_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        now = time.time()
        time_label = datetime.fromtimestamp(now).strftime("%b %d, %I:%M %p")
        sess_name = name or (f"{game_title} ({time_label})" if game_title else f"Session {time_label}")

        with get_db_connection() as conn:
            conn.execute(
                """INSERT INTO sessions (id, name, game_title, event_ticker, start_time, is_active)
                   VALUES (?, ?, ?, ?, ?, 1)""",
                (session_id, sess_name, game_title, event_ticker, now)
            )
            conn.commit()

        return {
            "id": session_id,
            "name": sess_name,
            "game_title": game_title,
            "event_ticker": event_ticker,
            "start_time": now,
            "is_active": 1
        }

    @staticmethod
    def end_active_session() -> Optional[Dict[str, Any]]:
        active = AnalyticsManager.get_active_session()
        if not active:
            return None
        now = time.time()
        with get_db_connection() as conn:
            conn.execute(
                "UPDATE sessions SET is_active = 0, end_time = ? WHERE id = ?",
                (now, active["id"])
            )
            conn.commit()
        active["is_active"] = 0
        active["end_time"] = now
        return active

    @staticmethod
    def record_trade(order_result: Dict[str, Any], session_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Records a newly placed order from FastBet."""
        if not order_result.get("success"):
            return None

        now = time.time()
        iso_time = datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M:%S")
        order_id = str(order_result.get("order_id") or uuid.uuid4())

        # Determine session
        if not session_id:
            sess = AnalyticsManager.get_or_create_active_session(
                game_title=order_result.get("game_title") or order_result.get("bet_label"),
                event_ticker=order_result.get("event_ticker")
            )
            session_id = sess["id"]

        price = float(order_result.get("display_price", order_result.get("price", 0.50)))
        count = int(order_result.get("count", 1))
        total_cost = float(order_result.get("total_cost", round(price * count, 2)))
        status = "resting" if order_result.get("status") == "resting" else "open"
        latency = float(order_result.get("roundtrip_ms") or order_result.get("engine_latency_ms") or 0.0)

        trade_data = {
            "order_id": order_id,
            "session_id": session_id,
            "timestamp": now,
            "created_at": iso_time,
            "game_title": order_result.get("game_title", "Live Game"),
            "event_ticker": order_result.get("event_ticker", ""),
            "market_type": order_result.get("market_type", "moneyline"),
            "market_ticker": order_result.get("ticker", ""),
            "side": str(order_result.get("outcome_side", order_result.get("side", "yes"))).lower(),
            "label": order_result.get("bet_label", order_result.get("team_name", "Pick")),
            "order_type": order_result.get("price_mode", "dynamic"),
            "price": price,
            "count": count,
            "total_cost": total_cost,
            "status": status,
            "payout": 0.0,
            "pnl": 0.0,
            "latency_ms": latency,
            "source": "fastbet"
        }

        with get_db_connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO trades 
                   (order_id, session_id, timestamp, created_at, game_title, event_ticker,
                    market_type, market_ticker, side, label, order_type, price, count,
                    total_cost, status, payout, pnl, latency_ms, source)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    trade_data["order_id"], trade_data["session_id"], trade_data["timestamp"],
                    trade_data["created_at"], trade_data["game_title"], trade_data["event_ticker"],
                    trade_data["market_type"], trade_data["market_ticker"], trade_data["side"],
                    trade_data["label"], trade_data["order_type"], trade_data["price"],
                    trade_data["count"], trade_data["total_cost"], trade_data["status"],
                    trade_data["payout"], trade_data["pnl"], trade_data["latency_ms"],
                    trade_data["source"]
                )
            )
            conn.commit()

        return trade_data

    @staticmethod
    def get_trades(
        session_id: Optional[str] = None,
        limit: int = 200,
        market_type: Optional[str] = None,
        status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        query = "SELECT * FROM trades WHERE 1=1"
        params = []

        if session_id and session_id != "all":
            query += " AND session_id = ?"
            params.append(session_id)

        if market_type and market_type != "all":
            query += " AND market_type = ?"
            params.append(market_type.lower())

        if status and status != "all":
            query += " AND status = ?"
            params.append(status.lower())

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        with get_db_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    @staticmethod
    def get_performance_summary(session_id: Optional[str] = None) -> Dict[str, Any]:
        """Calculates comprehensive KPIs, win rate, P&L curve, and market breakdowns."""
        trades = AnalyticsManager.get_trades(session_id=session_id, limit=5000)

        total_bets = len(trades)
        total_wagered = sum(t["total_cost"] for t in trades)
        total_payout = sum(t["payout"] for t in trades)
        net_pnl = sum(t["pnl"] for t in trades)

        settled_trades = [t for t in trades if t["status"] in ("settled_won", "settled_lost")]
        wins = [t for t in settled_trades if t["status"] == "settled_won"]
        losses = [t for t in settled_trades if t["status"] == "settled_lost"]
        open_trades = [t for t in trades if t["status"] in ("open", "resting")]

        win_count = len(wins)
        loss_count = len(losses)
        settled_count = len(settled_trades)

        win_rate = round((win_count / settled_count) * 100.0, 1) if settled_count > 0 else 0.0
        roi = round((net_pnl / total_wagered) * 100.0, 1) if total_wagered > 0 else 0.0

        avg_price_cents = round(sum(t["price"] for t in trades) / total_bets * 100.0, 1) if total_bets > 0 else 0.0
        latencies = [t["latency_ms"] for t in trades if t.get("latency_ms") and t["latency_ms"] > 0]
        avg_latency = round(sum(latencies) / len(latencies), 1) if latencies else 0.0

        # Market breakdown: Moneyline vs Spread vs Total
        market_stats = {
            "moneyline": {"bets": 0, "pnl": 0.0, "wagered": 0.0, "wins": 0},
            "spread": {"bets": 0, "pnl": 0.0, "wagered": 0.0, "wins": 0},
            "total": {"bets": 0, "pnl": 0.0, "wagered": 0.0, "wins": 0}
        }

        for t in trades:
            m = t.get("market_type", "moneyline")
            if m not in market_stats:
                market_stats[m] = {"bets": 0, "pnl": 0.0, "wagered": 0.0, "wins": 0}
            market_stats[m]["bets"] += 1
            market_stats[m]["pnl"] = round(market_stats[m]["pnl"] + t["pnl"], 2)
            market_stats[m]["wagered"] = round(market_stats[m]["wagered"] + t["total_cost"], 2)
            if t["status"] == "settled_won":
                market_stats[m]["wins"] += 1

        # Cumulative P&L Timeline for charts
        chronological = sorted(trades, key=lambda x: x["timestamp"])
        cumulative = 0.0
        timeline = []
        for t in chronological:
            cumulative = round(cumulative + t["pnl"], 2)
            time_str = datetime.fromtimestamp(t["timestamp"]).strftime("%I:%M %p")
            timeline.append({
                "time": time_str,
                "pnl": t["pnl"],
                "cumulative_pnl": cumulative,
                "label": t["label"]
            })

        return {
            "total_bets": total_bets,
            "settled_count": settled_count,
            "win_count": win_count,
            "loss_count": loss_count,
            "open_count": len(open_trades),
            "win_rate": win_rate,
            "total_wagered": round(total_wagered, 2),
            "total_payout": round(total_payout, 2),
            "net_pnl": round(net_pnl, 2),
            "roi": roi,
            "avg_price_cents": avg_price_cents,
            "avg_latency_ms": avg_latency,
            "market_stats": market_stats,
            "timeline": timeline
        }

    @staticmethod
    def list_sessions() -> List[Dict[str, Any]]:
        """Returns all sessions with aggregated summary data."""
        with get_db_connection() as conn:
            rows = conn.execute("SELECT * FROM sessions ORDER BY start_time DESC").fetchall()
            sessions = [dict(r) for r in rows]

        for s in sessions:
            with get_db_connection() as conn:
                trade_rows = conn.execute(
                    "SELECT status, total_cost, pnl FROM trades WHERE session_id = ?",
                    (s["id"],)
                ).fetchall()
            bets = len(trade_rows)
            wagered = sum(r["total_cost"] for r in trade_rows)
            pnl = sum(r["pnl"] for r in trade_rows)
            wins = sum(1 for r in trade_rows if r["status"] == "settled_won")
            losses = sum(1 for r in trade_rows if r["status"] == "settled_lost")
            settled = wins + losses
            win_rate = round((wins / settled) * 100.0, 1) if settled > 0 else 0.0

            s["total_bets"] = bets
            s["total_wagered"] = round(wagered, 2)
            s["net_pnl"] = round(pnl, 2)
            s["win_count"] = wins
            s["loss_count"] = losses
            s["win_rate"] = win_rate
            s["start_formatted"] = datetime.fromtimestamp(s["start_time"]).strftime("%b %d, %I:%M %p")
            s["end_formatted"] = datetime.fromtimestamp(s["end_time"]).strftime("%b %d, %I:%M %p") if s.get("end_time") else "Active"

        return sessions

    @staticmethod
    async def sync_with_kalshi(kalshi_client) -> Dict[str, Any]:
        """
        Reconciles local trades with live Kalshi fills & settlements.
        Imports any missing fills and marks settled won/lost contracts with real payouts.
        """
        if kalshi_client.simulation_mode or not kalshi_client.auth.is_configured:
            return {"success": True, "message": "Simulation mode (no live account sync)", "synced_trades": 0}

        # 1. Fetch live balance
        balance_res = await kalshi_client.get_balance()
        live_balance = balance_res.get("balance_dollars", 0.0)

        # 2. Fetch settlements to resolve open bets
        settlements = await kalshi_client.get_settlements(limit=100)
        settled_map = {}
        for s in settlements:
            ticker = s.get("ticker")
            if ticker:
                settled_map[ticker] = {
                    "market_result": str(s.get("market_result", "")).lower(),
                    "revenue": float(s.get("revenue", 0)) / 100.0,
                    "settled_time": s.get("settled_time")
                }

        # 3. Update existing trades in DB
        updated_count = 0
        with get_db_connection() as conn:
            open_trades = conn.execute(
                "SELECT * FROM trades WHERE status IN ('open', 'resting')"
            ).fetchall()

            for t in open_trades:
                m_ticker = t["market_ticker"]
                if m_ticker in settled_map:
                    settlement = settled_map[m_ticker]
                    result = settlement["market_result"]  # 'yes' or 'no'
                    user_side = t["side"].lower()

                    if user_side == result:
                        status = "settled_won"
                        payout = round(t["count"] * 1.00, 2)
                        pnl = round(payout - t["total_cost"], 2)
                    else:
                        status = "settled_lost"
                        payout = 0.0
                        pnl = round(-t["total_cost"], 2)

                    conn.execute(
                        "UPDATE trades SET status = ?, payout = ?, pnl = ? WHERE order_id = ?",
                        (status, payout, pnl, t["order_id"])
                    )
                    updated_count += 1
            conn.commit()

        # 4. Fetch recent fills to import any trades placed outside FastBet or missed
        fills = await kalshi_client.get_fills(limit=50)
        imported_count = 0
        active_sess = AnalyticsManager.get_active_session()
        active_id = active_sess["id"] if active_sess else None

        with get_db_connection() as conn:
            for f in fills:
                oid = str(f.get("order_id") or f.get("trade_id"))
                existing = conn.execute("SELECT order_id FROM trades WHERE order_id = ?", (oid,)).fetchone()
                if not existing:
                    ticker = f.get("ticker", "")
                    side = str(f.get("side", "yes")).lower()
                    cnt = int(f.get("count", 1))
                    price_cents = f.get("yes_price") if side == "yes" else f.get("no_price", 50)
                    price = float(price_cents) / 100.0 if price_cents else 0.50
                    cost = round(price * cnt, 2)
                    ts = time.time()
                    created_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")

                    # Check if already settled
                    if ticker in settled_map:
                        res = settled_map[ticker]["market_result"]
                        if side == res:
                            st = "settled_won"
                            po = round(cnt * 1.00, 2)
                            pl = round(po - cost, 2)
                        else:
                            st = "settled_lost"
                            po = 0.0
                            pl = round(-cost, 2)
                    else:
                        st = "open"
                        po = 0.0
                        pl = 0.0

                    conn.execute(
                        """INSERT INTO trades 
                           (order_id, session_id, timestamp, created_at, game_title, event_ticker,
                            market_type, market_ticker, side, label, order_type, price, count,
                            total_cost, status, payout, pnl, latency_ms, source)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (oid, active_id, ts, created_str, "Kalshi Account Trade", "",
                         "moneyline", ticker, side, ticker, "imported", price, cnt,
                         cost, st, po, pl, 0.0, "kalshi_sync")
                    )
                    imported_count += 1
            conn.commit()

        return {
            "success": True,
            "live_balance": live_balance,
            "updated_settlements": updated_count,
            "imported_fills": imported_count
        }
