#!/usr/bin/env bash

echo "========================================"
echo "   Perplexity-2API Local Python Launcher"
echo "========================================"
echo

# Exit immediately on error
set -e

URL="http://127.0.0.1:8092"
CHROME_BIN="$HOME/.local/bin/chrome"

# ---- Check Python ----
if ! command -v python3 >/dev/null 2>&1; then
  echo "[ERROR] Python not found. Please install Python 3.8+"
  exit 1
fi

echo "[INFO] Python version:"
python3 --version
echo

# ---- Check requirements.txt ----
if [ ! -f "requirements.txt" ]; then
  echo "[ERROR] requirements.txt not found"
  exit 1
fi

# ---- Check dependencies ----
echo "[INFO] Checking dependencies..."
if ! python3 - <<EOF >/dev/null 2>&1
import botasaurus, fastapi, uvicorn, httpx
EOF
then
  echo "[INFO] Installing dependencies..."
  pip3 install -r requirements.txt || {
    echo "[ERROR] Failed to install dependencies"
    exit 1
  }
  echo "[SUCCESS] Dependencies installed"
fi

# ---- Start service ----
echo
echo "[INFO] Starting service..."
echo "[INFO] Access URL: $URL"
echo "[INFO] Press Ctrl+C to stop"
echo

# Start uvicorn in background
uvicorn main:app --host 127.0.0.1 --port 8092 --reload --no-access-log &
UVICORN_PID=$!

# Give server time to start
sleep 3

# ---- Open browser safely ----
echo "[INFO] Opening browser..."

# Detect WSL
if grep -qi microsoft /proc/version; then
  echo "[INFO] WSL detected → opening Windows Chrome"
  cmd.exe /c start "" "chrome" "$URL"

# Use custom Chrome if available
elif [ -x "$CHROME_BIN" ]; then
  echo "[INFO] Using Chrome at $CHROME_BIN"
  "$CHROME_BIN" "$URL" >/dev/null 2>&1 &

# macOS fallback
elif command -v open >/dev/null 2>&1; then
  open "$URL"

# Linux fallback
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$URL"

else
  echo "[INFO] Open $URL manually"
fi

echo "[INFO] Browser opened. Service is running."
echo "[INFO] Press Ctrl+C to stop service."

# ---- Wait for uvicorn ----
wait $UVICORN_PID

