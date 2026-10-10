#!/bin/zsh
# Double-click to start the IW4x server web UI (macOS). Installs uv if missing,
# creates .env and the server config on first run, then opens the UI in the browser.
cd "$(dirname "$0")" || exit 1
[[ -f .env ]] || cp .env.example .env
set -a; source ./.env; set +a
if ! command -v uv >/dev/null; then
  echo "Installing uv (Python runner)..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
./scripts/mac/install-config.sh
url="http://localhost:${UI_PORT:-8080}"
if curl -s -o /dev/null "$url"; then open "$url"; exit 0; fi   # already running
echo "Web UI: $url  (close this window to stop the UI; the game server keeps running)"
(sleep 4 && open "$url") &
cd services/ui && exec uv run app.py
