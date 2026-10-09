#!/bin/bash
# Install the custom maps + bots pack (usermaps/ and userraw/) into an MW2 game folder.
# macOS (CrossOver bottle) and Linux. Safe to re-run: skips if already installed,
# and an interrupted download resumes.
#
# Run it straight from GitHub:
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/dorostanian/iw4x-lan-server/main/scripts/install-maps.sh)"
# Options:
#   --bottle <name>  macOS: CrossOver bottle to install into (default: mw)
#   --dir <path>     game folder to install into (overrides --bottle; required on Linux)
#   --zip <path>     use this pack zip instead of downloading
#   --keep-zip       keep the zip afterwards (default: delete it if this script downloaded it)
#   --force          install again even if already installed

set -euo pipefail

DRIVE_ID="REDACTED"
DRIVE_URL="https://drive.usercontent.google.com/download?id=${DRIVE_ID}&export=download&confirm=t"
ZIP_NAME="mw2-iw4x-maps-bots.zip"
MARK=".iw4x-maps-installed"

BOTTLE="mw" DIR="" ZIP="" KEEP_ZIP=0 FORCE=0
while (( $# )); do
  case "$1" in
    --bottle) BOTTLE="$2"; shift ;;
    --dir) DIR="$2"; shift ;;
    --zip) ZIP="$2"; KEEP_ZIP=1; shift ;;
    --keep-zip) KEEP_ZIP=1 ;;
    --force) FORCE=1 ;;
    *) echo "unknown option: $1"; exit 1 ;;
  esac
  shift
done

step() { printf '\n\033[36m==> %s\033[0m\n' "$1"; }
ok()   { printf '    \033[32m✓\033[0m %s\n' "$1"; }
die()  { printf '    \033[31m✗ %s\033[0m\n' "$1"; exit 1; }
size_of() { if [[ -f "$1" ]]; then wc -c < "$1" | tr -d ' '; else echo 0; fi; }

if [[ -z "$DIR" ]]; then
  [[ "$(uname)" == "Darwin" ]] || die "pass --dir <game folder> on this system"
  DIR="$HOME/Library/Application Support/CrossOver/Bottles/$BOTTLE/drive_c/Program Files (x86)/Call of Duty Modern Warfare 2"
fi
[[ -f "$DIR/iw4x.exe" ]] || die "no MW2 + IW4x install found in: $DIR"

step "Custom maps + bots pack (~1 GB)"

# already installed: done, without contacting Google Drive (use --force to reinstall)
if (( ! FORCE )) && [[ -f "$DIR/$MARK" ]]; then
  ok "already installed"
  exit 0
fi

# Drive answers with an HTML page instead of the file when its daily download quota is used up
head=$(curl -sIL --max-time 20 "$DRIVE_URL" || true)
remote_size=$(awk 'tolower($1)=="content-length:" {s=$2} END {gsub("\r","",s); print s}' <<< "$head")
blocked=0
if grep -qi '^content-type: text/html' <<< "$head" || [[ "$remote_size" == "0" ]]; then
  blocked=1 remote_size=""
fi

if [[ -z "$ZIP" ]]; then
  # reuse a complete copy if one is lying around
  for candidate in "$HOME/Downloads/$ZIP_NAME" "$PWD/$ZIP_NAME"; do
    [[ -f "$candidate" ]] || continue
    if [[ -n "$remote_size" && "$(size_of "$candidate")" == "$remote_size" ]] \
       || { [[ -z "$remote_size" ]] && unzip -l "$candidate" >/dev/null 2>&1; }; then
      ZIP="$candidate"; [[ "$candidate" == "$HOME/Downloads/$ZIP_NAME" ]] || KEEP_ZIP=1
      break
    fi
  done
fi

if [[ -n "$ZIP" ]]; then
  [[ -f "$ZIP" ]] || die "zip not found: $ZIP"
  ok "using $ZIP"
else
  mkdir -p "$HOME/Downloads"
  ZIP="$HOME/Downloads/$ZIP_NAME"
  # a partial file that is really an HTML error page can't be resumed
  [[ -f "$ZIP" ]] && [[ "$(head -c 1 "$ZIP")" == "<" ]] && rm -f "$ZIP"
  if (( blocked )); then
    die "Google Drive refused the download (usually 'Quota exceeded': too many downloads today).
      Try again later, or download it in a browser while logged in to Google,
      save it to ~/Downloads as $ZIP_NAME and run this again:
      https://drive.google.com/file/d/$DRIVE_ID/view"
  fi
  [[ -n "$remote_size" ]] || die "can't reach Google Drive. Check the connection, or pass --zip <path>."
  echo "    Downloading to $ZIP (if it stops, run this again and it continues)"
  curl -fL -C - --retry 5 --retry-delay 5 --progress-bar "$DRIVE_URL" -o "$ZIP"
  [[ "$(size_of "$ZIP")" == "$remote_size" ]] || die "download incomplete, run this again to resume"
  remote_size=$(size_of "$ZIP")
fi

# extract next to the game (same disk), then merge into the game folder
tmp="$DIR/.maps-setup-$$"
trap 'rm -rf "$tmp"' EXIT
mkdir "$tmp"
echo "    Extracting..."
unzip -q -o "$ZIP" 'usermaps/*' 'userraw/*' -d "$tmp"
for part in usermaps userraw; do
  [[ -d "$tmp/$part" ]] || die "pack doesn't contain $part/"
  mkdir -p "$DIR/$part"
  cp -R "$tmp/$part/." "$DIR/$part/"
done
echo "${remote_size:-$(size_of "$ZIP")}" > "$DIR/$MARK"
ok "installed $(ls "$DIR/usermaps" | wc -l | tr -d ' ') maps and the bots mod into $DIR"
(( KEEP_ZIP )) || { rm -f "$ZIP"; ok "removed $ZIP_NAME"; }
