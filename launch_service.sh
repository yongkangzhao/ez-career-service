#!/usr/bin/env bash
conda activate ez-career-service
set -euo pipefail

CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
REMOTE_PORT=9222
MCP_PORT=8931

# 0) If Chrome’s running, quit it so our flags actually stick
if pgrep -x "Google Chrome" >/dev/null; then
  echo "⚠️  Quitting existing Chrome…"
  pkill -x "Google Chrome"
  # give it a moment to shut down
  sleep 1
fi

# 1) Capture Chrome’s output so we can grab the DevTools ws:// URL
OUT=$(mktemp)
trap 'rm -f "$OUT"; pkill -P $$ >/dev/null 2>&1' EXIT

# 2) Launch Chrome with your default profile, in the background
"$CHROME" --remote-debugging-port=$REMOTE_PORT 2>&1 | tee "$OUT" &
CH_PID=$!

# 3) Wait until Chrome prints the DevTools endpoint
while ! grep -q 'DevTools listening on ws://' "$OUT"; do
  sleep 0.1
done

# 4) Extract the ws:// URL
WS_ENDPOINT=$(grep -m1 -o 'ws://[^ ]\+' "$OUT")
echo "✅ Detected CDP endpoint: $WS_ENDPOINT"

# 5) Start Playwright MCP in the background
npx @playwright/mcp@latest \
  --port $MCP_PORT \
  --cdp-endpoint "$WS_ENDPOINT" &
MCP_PID=$!
echo "✅ Playwright MCP running (PID $MCP_PID)"

# 6) Finally, start your FastAPI server (Uvicorn stays in the foreground)
uvicorn api:app \
  --reload \
  --port 8000 \
  --log-level debug \
  --host 0.0.0.0

# When you Ctrl+C Uvicorn, the trap will kill Chrome & MCP and remove the temp file.

