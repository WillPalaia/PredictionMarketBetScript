#!/bin/bash
echo ">>> Stopping Courtside Betting Server & Tunnel..."
pkill -f "python3 server.py" || true
pkill -f "cloudflared tunnel" || true
echo ">>> Stopped."