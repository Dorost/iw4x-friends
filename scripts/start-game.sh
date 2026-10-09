#!/bin/zsh
# Start the IW4x client (x86). Default skips the launcher's GitHub update check,
# which can hang under CrossOver. Pass --update to run the launcher normally.
source "$(dirname "$0")/env.sh"
cd "$IW4X_GAME_DIR" || exit 1
if [[ "$1" == "--update" ]]; then
  exec "$WINE" --bottle "$IW4X_GAME_BOTTLE" --cx-app iw4x-launcher.exe --arch x86
fi
exec "$WINE" --bottle "$IW4X_GAME_BOTTLE" --cx-app iw4x-launcher.exe \
  --arch x86 --skip-remote --no-self-update --no-shortcuts --no-connect-protocol
