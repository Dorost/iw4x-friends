#!/bin/zsh
# Start the IW4x dedicated server in the foreground
source "$(dirname "$0")/env.sh"
if lsof -nP -iUDP:"$IW4X_PORT" >/dev/null 2>&1; then
  echo "A server is already running on port $IW4X_PORT (use the web UI or 'task stop')."
  exit 1
fi
echo "LAN address: $(ipconfig getifaddr en0 || ipconfig getifaddr en1):$IW4X_PORT"
cd "$IW4X_SERVER_DIR" || exit 1
exec "$WINE" --bottle "$IW4X_SERVER_BOTTLE" --cx-app iw4x.exe \
  -dedicated +set net_port "$IW4X_PORT" +exec server.cfg +map_rotate
