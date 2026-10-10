#!/bin/bash
# Install the custom maps + bots pack (usermaps/ and userraw/) into an MW2 game folder.
# macOS (CrossOver bottle) and Linux. Safe to re-run: skips if already installed,
# and an interrupted download resumes.
#
# Run it straight from GitHub:
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/dorostanian/iw4x-friends/main/scripts/mac/install-maps.sh)"
# Options:
#   --bottle <name>  macOS: CrossOver bottle to install into (default: mw)
#   --dir <path>     game folder to install into (overrides --bottle; required on Linux)
#   --maps-url <link>  download link of the pack (a Google Drive share link works);
#                    also MW_MAPS_URL. When needed and not given, it asks for the setup
#                    password (decrypts the links below) or the link itself
#   --zip <path>     use this pack zip instead of downloading
#   --keep-zip       keep the zip afterwards (default: delete it if this script downloaded it)
#   --force          install again even if already installed

set -euo pipefail

ZIP_NAME="mw2-iw4x-maps-bots.zip"
MARK=".iw4x-maps-installed"
# download links, encrypted with the setup password (written by `task links`)
LINKS_ENC="U2FsdGVkX19z1JucWZqUi9mbrydBrz7IZBKu1HjwaeSCQDgD/3GuECrT/uzIB2CMUT2zrJQjzDpdIpg/QGnq37w6ffsO0QhnF3C0pjpajXOtdr4yhCmyERBwk+rtJcfWy3gff8aVtAIkGb/0CDFa4mkFQLIPeZKgi4CFBPW2BIt7uXJVUOVoG913KBwD5J8abSgTe8nCDO5zG0I+cRFpWUuJYs4g6WEppu1DiaBTRgX0Ug+P3VNv17X9xN6vwjxmPzXzPh2jmUAE9feoNV9sVcIMuUi3DIk7ToHtwhS/xyaWcAbByQltQ3mPJMNO0IFB"

BOTTLE="mw" DIR="" ZIP="" KEEP_ZIP=0 FORCE=0 LINK="${MW_MAPS_URL:-}"
while (( $# )); do
  case "$1" in
    --bottle) BOTTLE="$2"; shift ;;
    --dir) DIR="$2"; shift ;;
    --maps-url) LINK="$2"; shift ;;
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
# a Google Drive share link becomes its direct download URL; other links are used as-is
download_url() {
  if [[ "$1" =~ /d/([A-Za-z0-9_-]{20,}) ]] || [[ "$1" =~ [?\&]id=([A-Za-z0-9_-]{20,}) ]]; then
    echo "https://drive.usercontent.google.com/download?id=${BASH_REMATCH[1]}&export=download&confirm=t"
  else
    echo "$1"
  fi
}

# ask for the setup password and print the decrypted links ("game=<url>" and "maps=<url>"
# lines). Fails when there are none, on Enter (paste a link instead) or after 3 wrong tries
unlock_links() {
  [[ -n "$LINKS_ENC" ]] && command -v openssl >/dev/null || return 1
  local pass plain try
  for try in 1 2 3; do
    read -rsp "    Setup password (or Enter to paste a link instead): " pass < /dev/tty || return 1
    echo > /dev/tty
    [[ -n "$pass" ]] || return 1
    plain=$(echo "$LINKS_ENC" | PASS="$pass" openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -md sha256 -a -A -pass env:PASS 2>/dev/null | tr -d '\0') || plain=""
    [[ "$plain" == game=http* ]] && { echo "$plain"; return 0; }
    printf '    \033[33m!\033[0m wrong password\n' > /dev/tty
  done
  return 1
}

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

if [[ -z "$ZIP" ]]; then
  # reuse a complete copy if one is lying around (a partial download has no zip index yet)
  for candidate in "$HOME/Downloads/$ZIP_NAME" "$PWD/$ZIP_NAME"; do
    if [[ -f "$candidate" ]] && unzip -l "$candidate" >/dev/null 2>&1; then
      ZIP="$candidate"; [[ "$candidate" == "$HOME/Downloads/$ZIP_NAME" ]] || KEEP_ZIP=1
      break
    fi
  done
fi

# ask only when needed and there's a terminal to ask on; a file path works too
if [[ -z "$ZIP" && -z "$LINK" ]] && { : < /dev/tty; } 2>/dev/null; then
  if links=$(unlock_links); then
    LINK=$(sed -n 's/^maps=//p' <<< "$links")
  else
    printf '    Paste the download link for the maps pack, or the path to %s: ' "$ZIP_NAME" > /dev/tty
    read -r LINK < /dev/tty || true
  fi
fi
LINK="${LINK//\\ / }"; LINK="${LINK% }"; LINK="${LINK/#\~/$HOME}"   # drag-and-drop escapes spaces
if [[ -z "$ZIP" && -f "$LINK" ]]; then ZIP="$LINK"; KEEP_ZIP=1; fi

if [[ -n "$ZIP" ]]; then
  [[ -f "$ZIP" ]] || die "zip not found: $ZIP"
  ok "using $ZIP"
else
  [[ -n "$LINK" ]] || die "no download link given. Pass --maps-url <link>, or put $ZIP_NAME in ~/Downloads"
  URL=$(download_url "$LINK")
  # Google Drive answers with an HTML page instead of the file when its daily download
  # quota is used up ("Quota exceeded") or the link doesn't work
  head=$(curl -sIL --max-time 20 "$URL" || true)
  remote_size=$(awk 'tolower($1)=="content-length:" {s=$2} END {gsub("\r","",s); print s}' <<< "$head")
  if grep -qi '^content-type: text/html' <<< "$head" || [[ -z "$remote_size" || "$remote_size" == "0" ]]; then
    die "the download was refused. With Google Drive that's usually 'Quota exceeded'
      (too many downloads today), or the link isn't shared. Try again later, or open
      the link in a browser, save it to ~/Downloads as $ZIP_NAME and run this again."
  fi
  mkdir -p "$HOME/Downloads"
  ZIP="$HOME/Downloads/$ZIP_NAME"
  # a partial file that is really an HTML error page can't be resumed
  [[ -f "$ZIP" ]] && [[ "$(head -c 1 "$ZIP")" == "<" ]] && rm -f "$ZIP"
  echo "    Downloading to $ZIP (if it stops, run this again and it continues)"
  curl -fL -C - --retry 5 --retry-delay 5 --progress-bar "$URL" -o "$ZIP"
  [[ "$(size_of "$ZIP")" == "$remote_size" ]] || die "download incomplete, run this again to resume"
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
size_of "$ZIP" > "$DIR/$MARK"
ok "installed $(ls "$DIR/usermaps" | wc -l | tr -d ' ') maps and the bots mod into $DIR"
(( KEEP_ZIP )) || { rm -f "$ZIP"; ok "removed $ZIP_NAME"; }
