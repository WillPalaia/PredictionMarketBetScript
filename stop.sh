#!/bin/bash
echo ">>> Stopping FastBet Server & Tunnel..."
pkill -f "python3 server.py" || true
pkill -f "cloudflared tunnel" || true
echo ">>> Stopped."