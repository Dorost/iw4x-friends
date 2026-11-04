#!/usr/bin/env bash
# Brings a game server's IW4x to its latest release, as players' launchers do theirs: with IW4x's
# own launcher (its Linux build), which installs into the folder it runs from and downloads only
# what changed. bootstrap.sh runs it on every boot, before the game server starts. Without it a
# server keeps the IW4x of the setup zip, while players' launchers move on.
#   bash deploy/node/update-iw4x.sh <game folder>
# Its last line is the version it leaves, e.g. "r5318, rawfiles v0.2.41".

set -euo pipefail

GAME=${1:?usage: update-iw4x.sh <game folder>}
LAUNCHER=$GAME/iw4x-launcher  # next to the Windows one, iw4x-launcher.exe
REPO=https://github.com/iw4x/launcher

# The launcher first: a new game release can need a new launcher. releases/latest redirects to
# the latest tag, which names the download, without using up GitHub's API limit
tag=$(curl -fsSI -m 20 "$REPO/releases/latest" | sed -n 's|^location: .*/tag/v\([^[:space:]]*\).*|\1|Ip')
have=$("$LAUNCHER" --version 2>/dev/null | awk '{print $2}') || have=""
if [[ -n "$tag" && "$tag" != "$have" ]]; then
  tmp=$(mktemp -d)
  curl -fsSL -m 300 "$REPO/releases/download/v$tag/launcher-$tag-x86_64-linux-musl.tar.xz" \
    | tar -xJ -C "$tmp" iw4x-launcher
  mv "$tmp/iw4x-launcher" "$LAUNCHER"
  rm -rf "$tmp"
  echo "    launcher $tag (was ${have:-none})"
fi

# The 64-bit zlib1.dll of IW4x (mm) stops Wine from starting the 32-bit server, so it lives
# aside as zlib1.dll.x64 (scripts/linux/setup.sh). It's back in place only while the launcher
# runs: missing, the launcher would download the whole IW4x (mm) client again on every boot
zlib_aside() {
  if [[ -f "$GAME/zlib1.dll" ]]; then
    mv -f "$GAME/zlib1.dll" "$GAME/zlib1.dll.x64"
  fi
}
if [[ -f "$GAME/zlib1.dll.x64" && ! -e "$GAME/zlib1.dll" ]]; then
  mv "$GAME/zlib1.dll.x64" "$GAME/zlib1.dll"
fi
trap zlib_aside EXIT

# the client, rawfiles and DLC; no game start, no self-update (done above), no desktop
# shortcuts or iw4x:// links on a server. The first time it checks every file (about 90 s on
# NL, which downloaded 378 MB from r5154 to r5318), after that a few seconds
"$LAUNCHER" --skip-launch --no-self-update --no-shortcuts --no-connect-protocol < /dev/null
echo  # its progress display ends without a line break
zlib_aside

# what it installed, from the launcher's database (component 0: the client, 1: rawfiles)
python3 - "$GAME/cache/iw4x.db" <<'PY'
import sqlite3, sys
with sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True) as db:
    tags = dict(db.execute("SELECT component, tag FROM component_versions"))
print(f"{tags.get(0, '?')}, rawfiles {tags.get(1, '?')}")
PY
