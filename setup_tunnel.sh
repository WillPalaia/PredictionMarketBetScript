#!/bin/bash
set -e

echo "=== Installing Cloudflare Tunnel ==="
ARCH=$(dpkg --print-architecture)

if [ "$ARCH" = "arm64" ] || [ "$ARCH" = "aarch64" ]; then
    BINARY_URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64"
else
    BINARY_URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64"
fi

echo "Detected architecture: $ARCH"
echo "Downloading cloudflared binary..."
sudo curl -L "$BINARY_URL" -o /usr/local/bin/cloudflared
sudo chmod +x /usr/local/bin/cloudflared

echo "=== Success! cloudflared version: ==="
/usr/local/bin/cloudflared --version

echo ""
echo "You can now run:"
echo "cloudflared tunnel --url http://localhost:8000"
