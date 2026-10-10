#!/usr/bin/env bash
# Set up a Linux machine (e.g. a VPS) to host the IW4x server with Docker:
#   1. installs Docker and unzip (if missing)
#   2. downloads the prepared game package (mw.zip) from Google Drive
#   3. extracts only the MW2 game folder into game/
#   4. installs a public server.cfg with a random rcon password
#   5. fills in .env (domain for the web UI, UI password)
#   6. opens the firewall (ufw) for the game and the web UI
#
# Run from the repo:   task setup     (or: bash scripts/linux/setup.sh)
# Safe to re-run: every step skips what is already done, and an interrupted
# download resumes where it stopped.
# Options:
#   --game-url <link>  download link of mw.zip (a Google Drive share link works); also
#                  MW_GAME_URL. When a download is needed and it's not given, it asks for
#                  the setup password (decrypts the links below) or the link itself
#   --maps-url <link>  same for the custom maps + bots pack (MW_MAPS_URL)
#   --zip <path>   use this mw.zip (otherwise it looks for mw.zip in the repo and ~)
#   --keep-zip     keep mw.zip after installing (default: delete it if this script downloaded it)

set -euo pipefail

GAME_REL="drive_c/Program Files (x86)/Call of Duty Modern Warfare 2"

cd "$(dirname "$0")/../.."
REPO="$PWD"
GAME="$REPO/game"
DOWNLOAD_ZIP="$REPO/mw.zip"
# download links, encrypted with the setup password (written by `task links`)
LINKS_ENC="U2FsdGVkX19z1JucWZqUi9mbrydBrz7IZBKu1HjwaeSCQDgD/3GuECrT/uzIB2CMUT2zrJQjzDpdIpg/QGnq37w6ffsO0QhnF3C0pjpajXOtdr4yhCmyERBwk+rtJcfWy3gff8aVtAIkGb/0CDFa4mkFQLIPeZKgi4CFBPW2BIt7uXJVUOVoG913KBwD5J8abSgTe8nCDO5zG0I+cRFpWUuJYs4g6WEppu1DiaBTRgX0Ug+P3VNv17X9xN6vwjxmPzXzPh2jmUAE9feoNV9sVcIMuUi3DIk7ToHtwhS/xyaWcAbByQltQ3mPJMNO0IFB"

KEEP_ZIP=0 ZIP="" GAME_LINK="${MW_GAME_URL:-}" MAPS_LINK="${MW_MAPS_URL:-}"
while (( $# )); do
  case "$1" in
    --keep-zip) KEEP_ZIP=1 ;;
    --zip) ZIP="$2"; KEEP_ZIP=1; shift ;;
    --game-url) GAME_LINK="$2"; shift ;;
    --maps-url) MAPS_LINK="$2"; shift ;;
    *) echo "unknown option: $1"; exit 1 ;;
  esac
  shift
done

step() { printf '\n\033[36m==> %s\033[0m\n' "$1"; }
ok()   { printf '    \033[32m✓\033[0m %s\n' "$1"; }
warn() { printf '    \033[33m!\033[0m %s\n' "$1"; }
die()  { printf '    \033[31m✗ %s\033[0m\n' "$1"; exit 1; }

SUDO=""; (( EUID )) && SUDO="sudo"
size_of() { [[ -f "$1" ]] && stat -c%s "$1" || echo 0; }
free_gb() { echo $(( $(df -Pk "$1" | awk 'NR==2 {print $4}') / 1024 / 1024 )); }
random() { tr -dc 'A-Za-z0-9' < /dev/urandom | head -c "$1"; }

# Download $1 ($2 bytes) to $3 over 8 connections at once: S3 serves each one at only
# ~13 MB/s. Parts are kept in $3.parts/ so a re-run resumes them, then joined into $3.
fetch_parallel() {
  local url=$1 size=$2 out=$3 n=8 chunk i start last have round p alive
  local -a pids
  chunk=$(( (size + n - 1) / n ))
  mkdir -p "$out.parts"
  for round in 1 2 3 4 5; do
    pids=()
    for (( i = 0; i < n; i++ )); do
      start=$(( i * chunk )) last=$(( (i + 1) * chunk - 1 ))
      (( last < size )) || last=$(( size - 1 ))
      have=$(size_of "$out.parts/$i")
      (( start + have <= last )) || continue
      # a stalled connection gives up after 30s, the next round picks up where it stopped
      curl -sfL --speed-limit 1000 --speed-time 30 -r $(( start + have ))-$last "$url" >> "$out.parts/$i" &
      pids+=($!)
    done
    (( ${#pids[@]} )) || break
    alive=1
    while (( alive )); do
      sleep 2
      alive=0; for p in "${pids[@]}"; do kill -0 "$p" 2>/dev/null && alive=1; done
      printf '\r    %d of %d MB' $(( $(parts_size "$out") / 1048576 )) $(( size / 1048576 ))
    done
    wait "${pids[@]}" || true
    echo
  done
  (( $(parts_size "$out") == size )) || return 1
  rm -f "$out"
  for (( i = 0; i < n; i++ )); do cat "$out.parts/$i" >> "$out"; rm "$out.parts/$i"; done
  rmdir "$out.parts"
}

# bytes downloaded so far into the parts of $1
parts_size() {
  local i total=0
  for (( i = 0; i < 8; i++ )); do total=$(( total + $(size_of "$1.parts/$i") )); done   # (( total += 0 )) fails under set -e
  echo $total
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

# set KEY=value in .env, appending it if missing
setenv() {
  if grep -q "^$1=" .env; then sed -i "s|^$1=.*|$1=$2|" .env; else echo "$1=$2" >> .env; fi
}

# ---------------------------------------------------------------- packages
step "Checking this machine"
[[ "$(uname)" == "Linux" ]] || die "this script is for Linux"
[[ "$(uname -m)" == "x86_64" ]] || die "needs an x86_64 machine (Wine runs the 32-bit Windows server)"

if command -v docker >/dev/null && docker compose version >/dev/null 2>&1; then
  ok "Docker installed"
else
  warn "installing Docker (official get.docker.com script)"
  curl -fsSL https://get.docker.com | $SUDO sh
  if (( EUID )); then
    $SUDO usermod -aG docker "$USER"
    warn "added $USER to the docker group: log out and back in before 'task up'"
  fi
  ok "Docker installed"
fi
if ! command -v unzip >/dev/null; then
  command -v apt-get >/dev/null || die "install unzip and re-run"
  $SUDO apt-get install -y -qq unzip
fi
ok "unzip installed"

# ---------------------------------------------------------------- game files
step "Game folder"
if [[ -f "$GAME/iw4x.exe" ]]; then
  ok "already installed in $GAME"
else
  if [[ -z "$ZIP" ]]; then
    # reuse a complete copy if one is lying around (a partial download has no zip index yet)
    for candidate in "$DOWNLOAD_ZIP" "$HOME/mw.zip"; do
      if [[ -f "$candidate" ]] && unzip -l "$candidate" >/dev/null 2>&1; then
        ZIP="$candidate"
        [[ "$candidate" == "$DOWNLOAD_ZIP" ]] || KEEP_ZIP=1   # never delete a copy we didn't download
        break
      fi
    done
  fi
  # ask only when needed and there's a terminal to ask on; a file path works too
  if [[ -z "$ZIP" && -z "$GAME_LINK" ]] && { : < /dev/tty; } 2>/dev/null; then
    if links=$(unlock_links); then
      GAME_LINK=$(sed -n 's/^game=//p' <<< "$links")
      [[ -n "$MAPS_LINK" ]] || MAPS_LINK=$(sed -n 's/^maps=//p' <<< "$links")
    else
      read -rp "    Paste the game download link, or the path to mw.zip: " GAME_LINK < /dev/tty || true
    fi
  fi
  if [[ -z "$ZIP" && -f "$GAME_LINK" ]]; then ZIP="$GAME_LINK"; KEEP_ZIP=1; fi

  if [[ -n "$ZIP" ]]; then
    [[ -f "$ZIP" ]] || die "zip not found: $ZIP"
    ok "using existing $ZIP"
  else
    [[ -n "$GAME_LINK" ]] || die "no download link given. Pass --game-url <link>, or put mw.zip in $REPO"
    url="$GAME_LINK"
    if [[ "$GAME_LINK" =~ /d/([A-Za-z0-9_-]{20,}) ]] || [[ "$GAME_LINK" =~ [?\&]id=([A-Za-z0-9_-]{20,}) ]]; then
      url="https://drive.usercontent.google.com/download?id=${BASH_REMATCH[1]}&export=download&confirm=t"
    fi
    # Google Drive answers with an HTML page instead of the file when its daily download
    # quota is used up ("Quota exceeded") or the link isn't shared
    head=$(curl -sIL --max-time 20 "$url" || true)
    remote_size=$(awk 'tolower($1)=="content-length:" {s=$2} END {gsub("\r","",s); print s}' <<< "$head")
    if grep -qi '^content-type: text/html' <<< "$head" || [[ -z "$remote_size" || "$remote_size" == "0" ]]; then
      die "the download was refused. With Google Drive that's usually 'Quota exceeded'
      (too many downloads today), or the link isn't shared. Try again later, or download
      mw.zip elsewhere, copy it to $DOWNLOAD_ZIP and re-run."
    fi
    ZIP="$DOWNLOAD_ZIP"
    # a partial file that is really an HTML error page can't be resumed
    [[ -f "$ZIP" ]] && [[ "$(head -c 1 "$ZIP")" == "<" ]] && rm -f "$ZIP"
    have=$(( $(size_of "$ZIP") + $(parts_size "$ZIP") ))
    need_gb=$(( (remote_size - have) / 1024 / 1024 / 1024 + 18 ))   # rest of download + game folder
    (( $(free_gb "$REPO") >= need_gb )) || die "need about ${need_gb} GB free disk space, only $(free_gb "$REPO") GB available"
    (( have > 0 )) && echo "    Resuming download ($(( have / 1024 / 1024 )) MB of $(( remote_size / 1024 / 1024 )) MB done)" \
                   || echo "    Downloading to $ZIP"
    echo "    (if it stops, just re-run the script and it continues)"
    if grep -qi '^accept-ranges: bytes' <<< "$head"; then
      fetch_parallel "$url" "$remote_size" "$ZIP" || die "download incomplete, re-run to resume"
    else
      curl -fL -C - --retry 5 --retry-delay 5 --progress-bar "$url" -o "$ZIP"
    fi
    [[ "$(size_of "$ZIP")" == "$remote_size" ]] || die "download incomplete, re-run to resume"
    ok "downloaded"
  fi

  # The zip holds a whole CrossOver bottle; only the MW2 folder inside it is needed.
  # Extract next to the target, then rename: game/ only appears once it's complete.
  echo "    Extracting the game folder (takes a few minutes)..."
  tmp="$REPO/.setup-tmp"
  rm -rf "$tmp"
  trap 'rm -rf "$tmp"' EXIT
  unzip -q "$ZIP" "*/$GAME_REL/*" -d "$tmp" || die "zip does not contain the MW2 game folder"
  src=$(find "$tmp" -mindepth 1 -maxdepth 1 -type d | head -1)
  [[ -f "$src/$GAME_REL/iw4x.exe" ]] || die "zip does not contain the MW2 game folder"
  mv "$src/$GAME_REL" "$GAME"
  rm -rf "$tmp" "$GAME/players"   # players/: the copied client profile, a server doesn't need it
  ok "installed to $GAME"
  (( KEEP_ZIP )) || { rm -f "$ZIP"; ok "removed mw.zip"; }
fi

# ---------------------------------------------------------------- server.cfg
step "Custom maps + bots"
bash "$REPO/scripts/mac/install-maps.sh" --dir "$GAME" ${MAPS_LINK:+--maps-url "$MAPS_LINK"} || warn "custom maps not installed, run: bash scripts/mac/install-maps.sh --dir game"

step "Server config"
cfg="$GAME/main/server.cfg"
if [[ -f "$cfg" ]]; then
  ok "exists, not touching: $cfg"
else
  # public server: listed outside the LAN, and an rcon password nobody can guess,
  # since rcon goes over the public game port
  sed -e 's|^set sv_lanOnly .*|set sv_lanOnly "0"|' \
      -e "s|^set rcon_password .*|set rcon_password \"$(random 20)\"|" \
      server.cfg.example > "$cfg"
  ok "installed $cfg (public, random rcon password)"
fi

# ---------------------------------------------------------------- .env
step "Settings (.env)"
[[ -f .env ]] || cp .env.example .env
set -a; . ./.env; set +a
if [[ -z "${DOMAIN:-}" ]]; then
  echo "    The web UI is served over HTTPS on a domain (Caddy gets the certificate)."
  echo "    Point an A record at this machine's public IP first."
  read -rp "    Domain for the web UI (e.g. iw4x.example.com): " DOMAIN
  [[ -n "$DOMAIN" ]] || die "a domain is needed for the web UI"
  setenv DOMAIN "$DOMAIN"
fi
ok "web UI domain: $DOMAIN"
if [[ -z "${UI_PASSWORD:-}" ]]; then
  UI_PASSWORD=$(random 16)
  setenv UI_PASSWORD "$UI_PASSWORD"
  ok "web UI password generated: $UI_PASSWORD (any username, change it in .env)"
else
  ok "web UI password set"
fi

# ---------------------------------------------------------------- firewall
step "Firewall"
port="${IW4X_PORT:-28960}"
if command -v ufw >/dev/null && $SUDO ufw status | grep -q "Status: active"; then
  $SUDO ufw allow "$port/udp" >/dev/null
  $SUDO ufw allow 80/tcp >/dev/null
  $SUDO ufw allow 443/tcp >/dev/null
  ok "ufw: opened $port/udp (game), 80 and 443/tcp (web UI)"
else
  ok "no active ufw"
fi
warn "if your provider has its own firewall (security group), open $port/udp and 80, 443/tcp there too"

step "Done"
echo "    Start it:   task up"
echo "    Web UI:     https://$DOMAIN"
echo "    Players:    connect $(curl -s --max-time 5 https://api.ipify.org || echo '<server-ip>'):$port"
