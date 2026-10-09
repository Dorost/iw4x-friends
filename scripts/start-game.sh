#!/bin/zsh
# Start the IW4x client (x86) with the shared game settings from config/client.cfg.
# Default skips the launcher's GitHub update check, which can hang under CrossOver.
# Pass --update to let the launcher update IW4x first.
source "$(dirname "$0")/env.sh"
cp config/client.cfg "$IW4X_GAME_DIR/main/client_tweaks.cfg"
cd "$IW4X_GAME_DIR" || exit 1
skip=(--skip-remote --no-self-update --no-shortcuts --no-connect-protocol)
[[ "$1" == "--update" ]] && skip=()
exec "$WINE" --bottle "$IW4X_GAME_BOTTLE" --cx-app iw4x-launcher.exe \
  --arch x86 "${skip[@]}" --game-args "+exec client_tweaks.cfg"
