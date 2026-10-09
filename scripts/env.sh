# Shared defaults for the helper scripts
cd "$(dirname "$0")/.." || exit 1
[ -f .env ] && set -a && . ./.env && set +a
IW4X_BOTTLE="${IW4X_BOTTLE:-mw}"
IW4X_GAME_DIR="${IW4X_GAME_DIR:-$HOME/Library/Application Support/CrossOver/Bottles/$IW4X_BOTTLE/drive_c/Program Files (x86)/Call of Duty Modern Warfare 2}"
IW4X_PORT="${IW4X_PORT:-28960}"
WINE="${WINE:-/Applications/CrossOver.app/Contents/SharedSupport/CrossOver/bin/wine}"
