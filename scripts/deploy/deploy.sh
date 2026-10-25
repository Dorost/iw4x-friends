#!/usr/bin/env bash
# Deploy a commit on this server: from main, or from another branch (a PR's, from Run
# workflow). GitHub Actions runs it over SSH (the ci workflow's deploy jobs) with a key
# that can only run this script; see "Updates from GitHub" in the README for setting a
# server up for it.
#   1. fetches the branches from GitHub: the commit has to be on one of them (a commit
#      only in a fork isn't)
#   2. stops when tracked files were changed by hand here
#   3. checks out the commit. When services/ui differs from what the running image was
#      built from, pulls the commit's image (CI pushed it) and restarts the server with
#      it, players or not. Otherwise nothing restarts
#   4. waits for the web UI and the game to answer, and goes back to the previous commit
#      and image when they don't
#   5. keeps the 3 newest images
# game/, server.cfg and .env stay as they are, except IMAGE_TAG in .env.
#
#   bash scripts/deploy/deploy.sh <commit sha>     (over SSH: deploy <commit sha>)

set -euo pipefail

IMAGE=ghcr.io/dorost/iw4x-friends   # as in docker-compose.yml

step() { printf '\n==> %s\n' "$1"; }
ok()   { printf '    ✓ %s\n' "$1"; }
warn() { printf '    ! %s\n' "$1"; }
die()  { printf '    ✗ %s\n' "$1"; exit 1; }

# set KEY=value in .env, appending it if missing
setenv() {
  if grep -q "^$1=" .env; then sed -i "s|^$1=.*|$1=$2|" .env; else echo "$1=$2" >> .env; fi
}
getenv() { sed -n "s/^$1=//p" .env; }

# the web UI serves its login page and the game answers getinfo
healthy() {
  local i ui_port game_port
  ui_port=$(getenv UI_PORT) game_port=$(getenv IW4X_PORT)
  for (( i = 0; i < 40; i++ )); do
    if curl -fso /dev/null --max-time 2 "http://127.0.0.1:${ui_port:-8080}/login" &&
       printf '\xff\xff\xff\xffgetinfo deploy' | timeout 3 nc -u -w1 127.0.0.1 "${game_port:-28960}" | grep -qa infoResponse; then
      return 0
    fi
    sleep 3
  done
  return 1
}

# All of it in a function: bash reads the whole script before running it, and the
# checkout below replaces this file
main() {
  # over SSH, the key's forced command runs this script and what was asked for is here
  local cmd sha rest
  read -r cmd sha rest <<< "${SSH_ORIGINAL_COMMAND:-deploy ${1:-}}"
  [[ "$cmd" == deploy && "$sha" =~ ^[0-9a-f]{40}$ && -z "$rest" ]] || die "usage: deploy <full commit sha>"

  cd "$(dirname "$0")/../.."
  [[ -d .git && -f .env ]] || die "$PWD is not set up for deploys (no git checkout or .env), see the README"
  exec 9> /run/lock/iw4x-deploy.lock
  flock -n 9 || die "another deploy is running"

  step "Checking ${sha:0:7}"
  git fetch -q --prune origin '+refs/heads/*:refs/remotes/origin/*'
  local branches edits
  branches=$(git branch -r --contains "$sha" --format='%(refname:lstrip=3)' 2>/dev/null || true)
  [[ -n "$branches" ]] || die "$sha is not on a branch of $(git remote get-url origin)"
  edits=$(git status --porcelain --untracked-files=no)
  [[ -z "$edits" ]] || die "files here were changed by hand, commit them to main or undo them (git checkout -- .):
$edits"
  local old old_tag tag
  old=$(git rev-parse HEAD) old_tag=$(getenv IMAGE_TAG)
  ok "$(git log -1 --format='%h %s' "$sha")"
  if grep -qx main <<< "$branches"; then
    ok "on main"
  else
    warn "not on main but on $(paste -sd' ' <<< "$branches"): the next deploy from main replaces it"
  fi
  ok "running: commit ${old:0:7}, image $([[ -n "$old_tag" ]] && echo "${old_tag:0:7}" || echo none)"

  # IMAGE_TAG is the commit the running image was built from: same services/ui, same image
  tag=$sha
  if [[ "$old_tag" =~ ^[0-9a-f]{40}$ ]] && git diff --quiet "$old_tag" "$sha" -- services/ui 2>/dev/null; then
    tag=$old_tag
    ok "services/ui unchanged: keeping the image, no restart"
  else
    step "Pulling the image"
    docker pull -q "$IMAGE:$tag" >/dev/null || die "no image $IMAGE:$tag (did the ci workflow push it?)"
    ok "$IMAGE:${tag:0:7}"
  fi

  step "Deploying"
  local before
  before=$(docker compose ps -q server)
  git checkout -q --detach "$sha"
  setenv IMAGE_TAG "$tag"
  # up recreates only what changed; a recreated server has to answer
  if docker compose up -d --no-build && { [[ "$(docker compose ps -q server)" == "$before" ]] || healthy; }; then
    ok "on ${sha:0:7}, image ${tag:0:7}"
  else
    warn "the server is not answering, going back to ${old:0:7}"
    git checkout -q --detach "$old"
    setenv IMAGE_TAG "$old_tag"
    docker compose up -d --no-build || true
    if healthy; then ok "back on ${old:0:7}"; else warn "no answer after going back either"; fi
    die "deploy of ${sha:0:7} failed, see: docker compose logs server"
  fi

  step "Cleaning up"
  {
    docker image ls "$IMAGE" --format '{{.Repository}}:{{.Tag}}' | tail -n +4 \
      | grep -vxF -e "$IMAGE:$tag" -e "$IMAGE:$old_tag" | xargs -r docker image rm
    docker image prune -f
    docker builder prune -f --filter until=168h   # left over from local builds
  } >/dev/null 2>&1 || true
  ok "kept the 3 newest images"
}

main "$@"
