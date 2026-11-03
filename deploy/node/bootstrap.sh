#!/usr/bin/env bash
# First boot of a game server of the fleet (deploy/fleet.toml). The user-data the bastion wrote
# (services/control/control/userdata.py) wrote the WireGuard config and /etc/iw4x/node.env,
# cloned the repo at the bastion's commit and runs this. Each step is reported to the bastion,
# which counts the server as up once its web UI answers.
#   0. WireGuard up: the reports and the settings come through it
#   1. Docker; the data disk at /srv/iw4x (formatted the first time)
#   2. the settings from the bastion: the commit's image, the domain, and the setup password
#      when the game isn't on the disk yet
#   3. the game onto the disk, the first time only (scripts/linux/setup.sh --game-only)
#   4. the firewall: the game port open to all, the rest only over WireGuard
#   5. the game server's container (deploy/node/docker-compose.yml)
# The log is in /var/log/iw4x-bootstrap.log.

set -euo pipefail

# shellcheck source=/dev/null
. /etc/iw4x/node.env
cd /opt/iw4x
DATA=/srv/iw4x
STEP_FILE=/run/iw4x-step
COMPOSE=(docker compose -f deploy/node/docker-compose.yml)
export DEBIAN_FRONTEND=noninteractive

report() {  # report <text> [1 = failed]
  local body
  body=$(python3 -c 'import json, sys; print(json.dumps({"step": sys.argv[1], "failed": sys.argv[2] == "1"}))' "$1" "${2:-0}")
  curl -fsS -m 10 -o /dev/null -H "Authorization: Bearer $NODE_TOKEN" -H "Content-Type: application/json" \
    -d "$body" "$CONTROL_URL/node/progress" || true
}
step() {
  echo "$1" > "$STEP_FILE"
  printf '\n==> %s\n' "$1"
  report "$1"
}
trap 'report "$(cat "$STEP_FILE" 2>/dev/null) (bootstrap.sh line $LINENO)" 1' ERR

# a sign of life every minute while a long step runs: the bastion gives up on a silent server
(
  while sleep 60; do
    text=$(cat "$STEP_FILE" 2>/dev/null || true)
    got=$(du -scb /var/tmp/iw4x/mw.zip* 2>/dev/null | awk 'END {print $1}')
    [[ "$text" == downloading* && "${got:-0}" -gt 0 ]] && text="$text: $(( got / 1024 ** 3 )) GB so far"
    report "$text"
  done
) &
heartbeat=$!
trap 'kill $heartbeat 2>/dev/null || true' EXIT

# the tunnel to the bastion first: until it's up, nothing reaches the bastion (not even a report)
echo "connecting to the bastion" > "$STEP_FILE"
apt-get -o DPkg::Lock::Timeout=600 install -yq wireguard-tools >/dev/null
systemctl enable -q --now wg-quick@wg0

step "waiting for the bastion over WireGuard"
for (( i = 0; i < 60; i++ )); do
  curl -fsS -m 5 -o /dev/null "$CONTROL_URL/healthz" && break
  sleep 5
done
curl -fsS -m 5 -o /dev/null "$CONTROL_URL/healthz"

step "installing Docker"
apt-get -o DPkg::Lock::Timeout=600 install -yq docker.io docker-compose-v2 jq unzip openssl netcat-openbsd ufw curl >/dev/null

step "mounting its disk"
bash deploy/common/mount-data.sh "$DATA"
mkdir -p "$DATA/ui-data"
has_game=0
[[ -f "$DATA/game/iw4x.exe" ]] && has_game=1

step "getting its settings"
config=$(curl -fsS -m 20 -H "Authorization: Bearer $NODE_TOKEN" "$CONTROL_URL/node/config?has_game=$has_game")
value() { jq -r ".$1" <<< "$config"; }
umask 077
cat > deploy/node/.env <<EOF
IMAGE_TAG=$(value image_tag)
UI_PASSWORD=$NODE_TOKEN
UI_HOST=$NODE_WG_IP
JOIN_HOST=$(value join_host)
EOF
umask 022

if (( ! has_game )); then
  step "downloading the game (17 GB, only on the first boot)"
  MW_SETUP_PASSWORD=$(value setup_password) IW4X_GAME_DIR="$DATA/game" IW4X_DOWNLOAD_DIR=/var/tmp/iw4x \
    bash scripts/linux/setup.sh --game-only
  rm -rf /var/tmp/iw4x
  # the name from fleet.toml instead of the example's
  hostname=$(value hostname)
  if [[ -n "$hostname" && "$hostname" != null ]]; then
    python3 - "$DATA/game/main/server.cfg" "$hostname" <<'PY'
import sys
path, name = sys.argv[1], sys.argv[2].replace('"', "")
lines = open(path).read().splitlines()
lines = [f'set sv_hostname "{name}"' if l.startswith("set sv_hostname ") else l for l in lines]
open(path, "w").write("\n".join(lines) + "\n")
PY
  fi
fi

step "opening the firewall"
ufw --force reset >/dev/null
ufw default deny incoming >/dev/null
ufw default allow outgoing >/dev/null
ufw allow 28960/udp >/dev/null      # the game
ufw allow in on wg0 >/dev/null      # the web UI and SSH, from the bastion
ufw --force enable >/dev/null

step "pulling the game server"
"${COMPOSE[@]}" pull -q

step "starting the game server"
"${COMPOSE[@]}" up -d

step "waiting for the game to answer"
mkdir -p /var/lib/iw4x
touch /var/lib/iw4x/bootstrapped
