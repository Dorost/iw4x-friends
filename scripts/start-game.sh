#!/bin/zsh
# Start the IW4x client (x86) with everything from this repo applied:
#   - config/client.cfg   shared settings (graphics, hit fixes, sound), loaded on every start
#   - custom maps + bots  installed if missing (scripts/install-maps.sh)
#   - config/classes.cfg  custom classes, loaded automatically when the file is new or changed
# Default skips the launcher's GitHub update check, which can hang under CrossOver.
# Pass --update to let the launcher update IW4x first.
source "$(dirname "$0")/env.sh"
# a second copy would sit behind an invisible "Game already running" dialog
if ./scripts/kill-game.sh --dry-run | grep -q .; then
  echo "IW4x is already running. If you can't see it, stop it with 'task game:kill' (or scripts/kill-game.sh) and try again."
  exit 1
fi

main="$IW4X_GAME_DIR/main"
cp config/client.cfg "$main/client_tweaks.cfg"
cp config/classes.cfg "$main/classes.cfg"
bash scripts/install-maps.sh --dir "$IW4X_GAME_DIR" || echo "Custom maps not installed, starting anyway."

args="+exec client_tweaks.cfg"
# Classes are stored in the player's stats, which load a few seconds after startup,
# so they're applied after a delay. Only when classes.cfg changed, so classes edited
# in the game aren't overwritten on every start.
classes_hash=$(shasum config/classes.cfg | cut -d' ' -f1)
if [[ "$(cat "$main/.classes-applied" 2>/dev/null)" != "$classes_hash" ]]; then
  printf 'wait 600\nexec classes.cfg\n' > "$main/classes_auto.cfg"
  args+=" +exec classes_auto.cfg"
  echo "$classes_hash" > "$main/.classes-applied"
  echo "Custom classes will be loaded a few seconds after the menu appears."
fi

cd "$IW4X_GAME_DIR" || exit 1
skip=(--skip-remote --no-self-update --no-shortcuts --no-connect-protocol)
[[ "$1" == "--update" ]] && skip=()
exec "$WINE" --bottle "$IW4X_GAME_BOTTLE" --cx-app iw4x-launcher.exe \
  --arch x86 "${skip[@]}" --game-args "$args"
