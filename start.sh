#!/bin/bash

# Ensure requirements are installed
echo ">>> Checking dependencies..."
pip install -r requirements.txt --break-system-packages -q

# Kill any existing instances
pkill -f "python3 server.py" || true
pkill -f "cloudflared tunnel" || true

# Start server in background
echo ">>> Starting Courtside Betting Server..."
python3 server.py > server.log 2>&1 &
SERVER_PID=$!
sleep 2

# Check if server is running
if ps -p $SERVER_PID > /dev/null; then
   echo ">>> Server is running! (PID: $SERVER_PID)"
else
   echo ">>> Server failed to start. Check server.log:"
   cat server.log
   exit 1
fi

# Start Cloudflare tunnel
echo ">>> Starting Cloudflare Tunnel..."
echo ">>> LOOK BELOW FOR YOUR PHONE URL (https://...trycloudflare.com) <<<"
echo "-------------------------------------------------------------------"
cloudflared tunnel --url http://localhost:8000
