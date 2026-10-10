#!/bin/zsh
# Copy server.cfg.example into the game's main/ folder if no config exists yet
source "$(dirname "$0")/env.sh"
target="$IW4X_SERVER_DIR/main/server.cfg"
if [ -f "$target" ]; then
  echo "exists, not touching: $target"
else
  cp server.cfg.example "$target" && echo "installed: $target"
fi
