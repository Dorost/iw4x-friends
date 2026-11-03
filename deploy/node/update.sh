#!/usr/bin/env bash
# Moves a running game server to another commit, when the bastion was deployed with a new one
# (services/control runs it over SSH once nobody is playing, or from "Update now"):
#   1. fetches the branches from GitHub: the commit has to be on one of them
#   2. checks out the commit. When services/ui differs from what the running image was built
#      from, pulls the commit's image (CI pushed it) and restarts the server with it.
#      Otherwise nothing restarts
#   3. waits for the web UI and the game to answer, and goes back to the previous commit and
#      image when they don't
#   4. keeps the 3 newest images
#
#   bash deploy/node/update.sh <commit sha>

set -euo pipefail

IMAGE=ghcr.io/dorost/iw4x-friends   # as in deploy/node/docker-compose.yml
ENV=deploy/node/.env

ok()   { printf '    ✓ %s\n' "$1"; }
die()  { printf '    ✗ %s\n' "$1"; exit 1; }
setenv() { if grep -q "^$1=" "$ENV"; then sed -i "s|^$1=.*|$1=$2|" "$ENV"; else echo "$1=$2" >> "$ENV"; fi; }
getenv() { sed -n "s/^$1=//p" "$ENV"; }

# the web UI serves its login page on the WireGuard address and the game answers getinfo
healthy() {
  local i host
  host=$(getenv UI_HOST)
  for (( i = 0; i < 40; i++ )); do
    if curl -fso /dev/null --max-time 2 "http://$host:8080/login" &&
       printf '\xff\xff\xff\xffgetinfo update' | timeout 3 nc -u -w1 127.0.0.1 28960 | grep -qa infoResponse; then
      return 0
    fi
    sleep 3
  done
  return 1
}

# in a function: the checkout replaces this file while it runs
main() {
  local sha=${1:-}
  [[ "$sha" =~ ^[0-9a-f]{40}$ ]] || die "usage: update.sh <full commit sha>"
  cd "$(dirname "$0")/../.."
  exec 9> /run/lock/iw4x-update.lock
  flock -n 9 || die "another update is running"

  git fetch -q --prune origin '+refs/heads/*:refs/remotes/origin/*'
  [[ -n "$(git branch -r --contains "$sha" 2>/dev/null)" ]] || die "$sha is not on a branch of $(git remote get-url origin)"
  local old old_tag tag compose=(docker compose -f deploy/node/docker-compose.yml)
  old=$(git rev-parse HEAD) old_tag=$(getenv IMAGE_TAG)

  tag=$sha
  if [[ "$old_tag" =~ ^[0-9a-f]{40}$ ]] && git diff --quiet "$old_tag" "$sha" -- services/ui 2>/dev/null; then
    tag=$old_tag
    ok "services/ui unchanged: keeping the image, no restart"
  else
    docker pull -q "$IMAGE:$tag" >/dev/null || die "no image $IMAGE:$tag (did the ci workflow push it?)"
    ok "pulled $IMAGE:${tag:0:7}"
  fi

  local before
  before=$("${compose[@]}" ps -q server)
  git checkout -q --detach "$sha"
  setenv IMAGE_TAG "$tag"
  if "${compose[@]}" up -d && { [[ "$("${compose[@]}" ps -q server)" == "$before" ]] || healthy; }; then
    ok "on ${sha:0:7}, image ${tag:0:7}"
  else
    git checkout -q --detach "$old"
    setenv IMAGE_TAG "$old_tag"
    "${compose[@]}" up -d || true
    die "${sha:0:7} doesn't answer, back on ${old:0:7}"
  fi

  {
    docker image ls "$IMAGE" --format '{{.Repository}}:{{.Tag}}' | tail -n +4 \
      | grep -vxF -e "$IMAGE:$tag" -e "$IMAGE:$old_tag" | xargs -r docker image rm
    docker image prune -f
  } >/dev/null 2>&1 || true
}

main "$@"
