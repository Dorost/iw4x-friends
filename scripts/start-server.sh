#!/bin/zsh
# Start the IW4x dedicated server in the foreground
source "$(dirname "$0")/env.sh"
echo "LAN address: $(ipconfig getifaddr en0 || ipconfig getifaddr en1):$IW4X_PORT"
cd "$IW4X_GAME_DIR" || exit 1
exec "$WINE" --bottle "$IW4X_BOTTLE" --cx-app iw4x.exe \
  -dedicated +set net_port "$IW4X_PORT" +exec server.cfg +map_rotate
