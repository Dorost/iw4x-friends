#!/usr/bin/env bash
# First boot of the bastion, from the user-data `task bastion:up` (services/control/control/infra.py)
# wrote, which also set the SSH host key and the deploy key. Then the deploy (deploy.sh, from
# GitHub Actions) starts the services.
#   1. Docker, WireGuard, the firewall tools
#   2. the data disk at /srv/iw4x: the control plane's and the bot's databases, the HTTPS
#      certificates and the WireGuard key, so a rebuilt bastion carries on where the old one was
#   3. WireGuard (wg0): the game servers connect to it; the control plane adds their peers
#   4. the firewall: SSH, HTTPS, WireGuard; the rest only from the game servers over wg0
#
#   bash deploy/bastion/bootstrap.sh <WireGuard address> <WireGuard port>

set -euo pipefail

WG_IP=${1:?usage: bootstrap.sh <WireGuard address> <port>}
WG_PORT=${2:?usage: bootstrap.sh <WireGuard address> <port>}
DATA=/srv/iw4x
export DEBIAN_FRONTEND=noninteractive
cd "$(dirname "$0")/../.."

echo "==> packages"
apt-get -o DPkg::Lock::Timeout=600 install -yq docker.io docker-compose-v2 wireguard-tools ufw jq curl python3 >/dev/null

echo "==> data disk"
bash deploy/common/mount-data.sh "$DATA"
mkdir -p "$DATA/control" "$DATA/bot" "$DATA/caddy" "$DATA/wireguard"
chmod 700 "$DATA/control" "$DATA/wireguard"

echo "==> WireGuard"
key="$DATA/wireguard/private.key"
[[ -s "$key" ]] || (umask 077 && wg genkey > "$key")
umask 077
cat > /etc/wireguard/wg0.conf <<EOF
# the bastion's end of the fleet's WireGuard network (deploy/fleet.toml). No peers here: the
# control plane adds each game server's while it runs (services/control/control/wireguard.py)
[Interface]
Address = $WG_IP/24
ListenPort = $WG_PORT
PrivateKey = $(cat "$key")
EOF
umask 022
systemctl enable -q wg-quick@wg0
systemctl restart wg-quick@wg0
echo "    public key: $(wg show wg0 public-key)"

echo "==> firewall"
ufw --force reset >/dev/null
ufw default deny incoming >/dev/null
ufw default allow outgoing >/dev/null
ufw allow 22/tcp >/dev/null              # SSH (keys only)
ufw allow 80/tcp >/dev/null              # HTTPS certificates, redirect
ufw allow 443/tcp >/dev/null             # the web UI and the Telegram mini app
ufw allow 443/udp >/dev/null             # HTTP/3
ufw allow "$WG_PORT/udp" >/dev/null      # WireGuard from the game servers
ufw allow in on wg0 >/dev/null           # the control plane, for the game servers
ufw --force enable >/dev/null

mkdir -p /var/lib/iw4x
touch /var/lib/iw4x/bootstrapped
echo "==> ready for the first deploy"
