#!/usr/bin/env bash
# Deploys a commit on the bastion. GitHub Actions runs it over SSH (.github/workflows/deploy.yml)
# with a key that can only run this script, and sends the settings on stdin: the .env lines made
# from the GitHub secrets and variables of the "bastion" environment.
#   1. on a new bastion, waits for its first boot setup (deploy/bastion/bootstrap.sh)
#   2. fetches the branches from GitHub: the commit has to be on one of them
#   3. checks out the commit, writes .env, pulls the commit's images (CI pushed them) and
#      restarts what changed
#   4. waits for the control plane and the bot to answer, and goes back to the previous commit
#      and .env when they don't
#   5. keeps the 3 newest images of each
# Running game servers move to the new commit by themselves, once nobody plays on them
# (services/control: deploy/node/update.sh).
#
#   ... | bash deploy/bastion/deploy.sh <commit sha>     (over SSH: deploy <commit sha>)

set -euo pipefail

IMAGE=ghcr.io/dorost/iw4x-friends   # as in deploy/bastion/docker-compose.yml
ENV=deploy/bastion/.env

step() { printf '\n==> %s\n' "$1"; }
ok()   { printf '    ✓ %s\n' "$1"; }
warn() { printf '    ! %s\n' "$1"; }
die()  { printf '    ✗ %s\n' "$1"; exit 1; }

# the control plane runs this commit, the bot answers
healthy() {
  local i
  for (( i = 0; i < 40; i++ )); do
    if [[ "$(curl -fsS --max-time 2 http://127.0.0.1:8070/healthz 2>/dev/null | jq -r .version)" == "$1" ]] &&
       curl -fso /dev/null --max-time 2 http://127.0.0.1:8090/bot/healthz; then
      return 0
    fi
    sleep 3
  done
  return 1
}

# what the compose file needs from deploy/fleet.toml
fleet() {
  python3 - <<'PY'
import tomllib
f = tomllib.load(open("deploy/fleet.toml", "rb"))
print(f"DOMAIN={f['bastion']['domain']}")
# the planner bot: the servers' addresses, the first one in its reminders' "connect ..."
print("TELEGRAM_APP_SERVERS=" + " ".join(s["domain"] for s in f["servers"].values()))
PY
}

# in a function: the checkout replaces this file while it runs
main() {
  local cmd sha rest
  read -r cmd sha rest <<< "${SSH_ORIGINAL_COMMAND:-deploy ${1:-}}"
  [[ "$cmd" == deploy && "$sha" =~ ^[0-9a-f]{40}$ && -z "$rest" ]] || die "usage: deploy <full commit sha>"

  # the settings first: stdin is gone once this waits
  local settings
  settings=$(cat)
  grep -q '^UI_PASSWORD=' <<< "$settings" || die "no settings on stdin (UI_PASSWORD missing)"

  if [[ ! -f /var/lib/iw4x/bootstrapped ]]; then
    step "Waiting for the first boot setup"
    for (( i = 0; i < 180; i++ )); do [[ -f /var/lib/iw4x/bootstrapped ]] && break; sleep 5; done
    [[ -f /var/lib/iw4x/bootstrapped ]] || die "not set up after 15 minutes, see /var/log/iw4x-bootstrap.log"
  fi

  cd "$(dirname "$0")/../.."
  exec 9> /run/lock/iw4x-deploy.lock
  flock -n 9 || die "another deploy is running"

  step "Checking ${sha:0:7}"
  git fetch -q --prune origin '+refs/heads/*:refs/remotes/origin/*'
  local branches old
  branches=$(git branch -r --contains "$sha" --format='%(refname:lstrip=3)' 2>/dev/null || true)
  [[ -n "$branches" ]] || die "$sha is not on a branch of $(git remote get-url origin)"
  [[ -z "$(git status --porcelain --untracked-files=no)" ]] || die "files here were changed by hand: git status"
  old=$(git rev-parse HEAD)
  ok "$(git log -1 --format='%h %s' "$sha")"
  grep -qx main <<< "$branches" && ok "on main" || warn "not on main but on $(paste -sd' ' <<< "$branches")"

  step "Deploying"
  [[ -f "$ENV" ]] && cp -p "$ENV" "$ENV.previous"
  git checkout -q --detach "$sha"
  (umask 077 && { echo "$settings"; echo "IMAGE_TAG=$sha"; fleet; } > "$ENV")
  local compose=(docker compose -f deploy/bastion/docker-compose.yml)
  if "${compose[@]}" pull -q && "${compose[@]}" up -d --remove-orphans && healthy "$sha"; then
    ok "on ${sha:0:7}"
  else
    warn "not answering, going back to ${old:0:7}"
    git checkout -q --detach "$old"
    [[ -f "$ENV.previous" ]] && cp -p "$ENV.previous" "$ENV"
    "${compose[@]}" up -d --remove-orphans || true
    die "deploy of ${sha:0:7} failed, see: docker compose -f deploy/bastion/docker-compose.yml logs"
  fi

  step "Cleaning up"
  {
    for kind in control bot; do
      docker image ls "$IMAGE" --format '{{.Repository}}:{{.Tag}}' | grep ":$kind-" | tail -n +4 \
        | grep -vxF "$IMAGE:$kind-$sha" | xargs -r docker image rm
    done
    docker image prune -f
  } >/dev/null 2>&1 || true
  ok "kept the 3 newest images"
}

main "$@"
