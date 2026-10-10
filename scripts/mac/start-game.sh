#!/bin/zsh
# Start the IW4x client (x86) with everything from this repo applied:
#   - config/client.cfg   shared settings (graphics, hit fixes, sound), loaded on every start
#   - custom maps + bots  installed if missing (scripts/mac/install-maps.sh)
#   - config/classes.cfg  custom classes, loaded with F9 during a match, or exec classes.cfg in the console
# Default skips the launcher's GitHub update check, which can hang under CrossOver.
# Pass --update to let the launcher update IW4x first.
source "$(dirname "$0")/env.sh"
# a second copy would sit behind an invisible "Game already running" dialog
if ./scripts/mac/kill-game.sh --dry-run | grep -q .; then
  echo "IW4x is already running. If you can't see it, stop it with 'task game:kill' (or scripts/mac/kill-game.sh) and try again."
  exit 1
fi

main="$IW4X_GAME_DIR/main"
cp config/client.cfg "$main/client_tweaks.cfg"
cp config/classes.cfg "$main/classes.cfg"
bash scripts/mac/install-maps.sh --dir "$IW4X_GAME_DIR" || echo "Custom maps not installed, starting anyway."

echo "Tip: load the ready-made classes with F9 during a match, or at the main menu: ~ then exec classes.cfg"

cd "$IW4X_GAME_DIR" || exit 1
skip=(--skip-remote --no-self-update --no-shortcuts --no-connect-protocol)
[[ "$1" == "--update" ]] && skip=()
exec "$WINE" --bottle "$IW4X_GAME_BOTTLE" --cx-app iw4x-launcher.exe \
  --arch x86 "${skip[@]}" --game-args "+exec client_tweaks.cfg"
