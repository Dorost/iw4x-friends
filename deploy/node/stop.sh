#!/usr/bin/env bash
# Before the bastion destroys this VM (services/control, over SSH): the game server stops and the
# data disk is unmounted, so it detaches clean and the next VM finds it as it was.

set -uo pipefail
cd /opt/iw4x || exit 1
docker compose -f deploy/node/docker-compose.yml down -t 20
sync
umount /srv/iw4x 2>/dev/null || umount -l /srv/iw4x
echo "stopped, disk unmounted"
