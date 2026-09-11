#!/bin/bash

# Ensure requirements are installed
echo ">>> Checking dependencies..."
pip install -r requirements.txt --break-system-packages -q

# Kill any existing instances
pkill -f "python3 server.py" || true
pkill -f "cloudflared tunnel" || true

# Start server in background
echo ">>> Starting FastBet Server..."
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

# Check if background daemon mode was requested
if [ "$1" == "--bg" ] || [ "$1" == "-d" ]; then
    echo ">>> Starting Cloudflare Tunnel in background (daemon mode)..."
    nohup cloudflared tunnel --url http://localhost:8000 > tunnel.log 2>&1 &
    
    echo ">>> Waiting for public tunnel URL..."
    for i in {1..15}; do
        URL=$(grep -o 'https://[a-zA-Z0-9.-]*\.trycloudflare\.com' tunnel.log 2>/dev/null | head -n 1)
        if [ -n "$URL" ]; then
            echo ""
            echo "==================================================================="
            echo "🔥 FASTBET IS RUNNING IN BACKGROUND (24/7 CLOUD MODE) 🔥"
            echo "Phone URL: $URL"
            echo "==================================================================="
            echo ">>> You can now CLOSE your terminal and SHUT OFF your computer! <<<"
            echo ">>> The server will keep running 24/7 in Oracle Cloud. <<<"
            echo ""
            echo "Useful commands:"
            echo "  - Check server logs: tail -f server.log"
            echo "  - Check tunnel logs: tail -f tunnel.log"
            echo "  - Stop everything:   bash stop.sh"
            echo ""
            exit 0
        fi
        sleep 1
    done
    echo "Tunnel started. Run 'cat tunnel.log' to view the URL."
    exit 0
fi

# Foreground mode (default)
echo ">>> Starting Cloudflare Tunnel (Foreground)..."
echo ">>> (Tip: Run 'bash start.sh --bg' to run in background so you can shut your computer off)"
echo ">>> LOOK BELOW FOR YOUR PHONE URL (https://...trycloudflare.com) <<<"
echo "-------------------------------------------------------------------"
cloudflared tunnel --url http://localhost:8000
