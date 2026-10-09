# Shared defaults for the helper scripts
cd "$(dirname "$0")/.." || exit 1
[ -f .env ] && set -a && . ./.env && set +a
BOTTLES_DIR="$HOME/Library/Application Support/CrossOver/Bottles"
MW2_REL="drive_c/Program Files (x86)/Call of Duty Modern Warfare 2"
# the dedicated server runs in its own bottle, so it doesn't share a wineserver with the game
IW4X_SERVER_BOTTLE="${IW4X_SERVER_BOTTLE:-mw}"
IW4X_SERVER_DIR="${IW4X_SERVER_DIR:-$BOTTLES_DIR/$IW4X_SERVER_BOTTLE/$MW2_REL}"
IW4X_GAME_BOTTLE="${IW4X_GAME_BOTTLE:-mw}"
IW4X_GAME_DIR="${IW4X_GAME_DIR:-$BOTTLES_DIR/$IW4X_GAME_BOTTLE/$MW2_REL}"
IW4X_PORT="${IW4X_PORT:-28960}"
WINE="${WINE:-/Applications/CrossOver.app/Contents/SharedSupport/CrossOver/bin/wine}"
