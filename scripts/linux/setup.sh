#!/usr/bin/env bash
# Set up a Linux machine (e.g. a VPS) to host the IW4x server with Docker:
#   1. installs Docker and unzip (if missing)
#   2. downloads the prepared game package (mw.zip) from Google Drive
#   3. extracts only the MW2 game folder into game/
#   4. installs a public server.cfg with a random rcon password
#   5. fills in .env (domain for the web UI)
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
#   --game-only    only the game, maps and server.cfg: no Docker, .env or firewall (the fleet's
#                  game servers, deploy/node/bootstrap.sh, do those themselves)
# Environment, for running it unattended:
#   MW_SETUP_PASSWORD  the setup password, instead of asking for it
#   IW4X_GAME_DIR      the game folder (default: game/ in the repo)
#   IW4X_DOWNLOAD_DIR  where mw.zip is downloaded to (default: the repo)

set -euo pipefail

GAME_REL="drive_c/Program Files (x86)/Call of Duty Modern Warfare 2"

cd "$(dirname "$0")/../.."
REPO="$PWD"
GAME="${IW4X_GAME_DIR:-$REPO/game}"
DOWNLOAD_ZIP="${IW4X_DOWNLOAD_DIR:-$REPO}/mw.zip"
# download links, encrypted with the setup password (written by `task links`)
LINKS_ENC="U2FsdGVkX18BSFqqHMCQ++5w+wJL5cdh3asQpzzejdBx2HWUrjeVW3q15pMGc31tolezaREbLw7dPLBzNarkDGagqk5k81ChbyM7uVo97si+Qc/A/GDQ+Y1Gkje41pLweL2l2zWtdoyWSKS33+xtZ92FbDNb5kYs4B9rHU3DfkJFIP0naKFFciIY7ikspmyrxsHNiTtW8zGg5eFIJbcxXe/vVJiCjUDQyPGbkry3TdA="

KEEP_ZIP=0 ZIP="" GAME_ONLY=0 GAME_LINK="${MW_GAME_URL:-}" MAPS_LINK="${MW_MAPS_URL:-}"
while (( $# )); do
  case "$1" in
    --keep-zip) KEEP_ZIP=1 ;;
    --game-only) GAME_ONLY=1 ;;
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
random() { LC_ALL=C tr -dc 'A-Za-z0-9' < /dev/urandom | head -c "$1" || true; }   # tr gets SIGPIPE when head is done

# Download $1 ($2 bytes) to $3 over $PARTS connections at once: S3 serves each one at only
# ~13 MB/s. Parts are kept in $3.parts/ so a re-run resumes them, then joined into $3. Each part
# tries again on its own when its connection drops or stalls (up to PART_TRIES times), so one
# slow connection doesn't hold up the others (on a weak network, many drop: Istanbul).
PARTS=16
PART_TRIES=30
fetch_part() {  # fetch_part <url> <part file> <first byte> <last byte>
  local url=$1 file=$2 start=$3 last=$4 have try
  for (( try = 1; try <= PART_TRIES; try++ )); do
    have=$(size_of "$file")
    (( start + have <= last )) || return 0
    # a stalled connection gives up after 30s, and this part goes on where it stopped
    curl -sfL --speed-limit 1000 --speed-time 30 -r $(( start + have ))-"$last" "$url" >> "$file" ||
      sleep $(( try < 5 ? try * 2 : 10 ))
  done
  have=$(size_of "$file")
  (( start + have > last ))
}
fetch_parallel() {
  local url=$1 size=$2 out=$3 n=$PARTS chunk i start last p alive
  local -a pids=()
  chunk=$(( (size + n - 1) / n ))
  # parts cut for another count of connections (an older run) don't fit these: start over
  [[ "$(cat "$out.parts/count" 2>/dev/null)" == "$n" ]] || rm -rf "$out.parts"
  mkdir -p "$out.parts"
  echo "$n" > "$out.parts/count"
  for (( i = 0; i < n; i++ )); do
    start=$(( i * chunk )) last=$(( (i + 1) * chunk - 1 ))
    (( last < size )) || last=$(( size - 1 ))
    fetch_part "$url" "$out.parts/$i" "$start" "$last" &
    pids+=($!)
  done
  alive=1
  while (( alive )); do
    sleep 2
    alive=0; for p in "${pids[@]}"; do kill -0 "$p" 2>/dev/null && alive=1; done
    printf '\r    %d of %d MB' $(( $(parts_size "$out") / 1048576 )) $(( size / 1048576 ))
  done
  wait "${pids[@]}" || true
  echo
  (( $(parts_size "$out") == size )) || return 1
  rm -f "$out"
  for (( i = 0; i < n; i++ )); do cat "$out.parts/$i" >> "$out"; rm "$out.parts/$i"; done
  rm "$out.parts/count"
  rmdir "$out.parts"
}

# bytes downloaded so far into the parts of $1
parts_size() {
  local i total=0
  for (( i = 0; i < PARTS; i++ )); do total=$(( total + $(size_of "$1.parts/$i") )); done   # (( total += 0 )) fails under set -e
  echo $total
}

# ask for the setup password and print the decrypted links ("game=<url>" and "maps=<url>"
# lines). Fails when there are none, on Enter (paste a link instead) or after 3 wrong tries
unlock_links() {
  [[ -n "$LINKS_ENC" ]] && command -v openssl >/dev/null || return 1
  local pass plain try
  if [[ -n "${MW_SETUP_PASSWORD:-}" ]]; then   # unattended: the password from the environment
    plain=$(echo "$LINKS_ENC" | PASS="$MW_SETUP_PASSWORD" openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -md sha256 -a -A -pass env:PASS 2>/dev/null | tr -d '\0') || plain=""
    [[ "$plain" == game=http* ]] && { echo "$plain"; return 0; }
    printf '    ! MW_SETUP_PASSWORD is wrong\n' >&2
    return 1
  fi
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

if (( GAME_ONLY )); then
  ok "game only (--game-only): not checking Docker"
elif command -v docker >/dev/null && docker compose version >/dev/null 2>&1; then
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
  # ask only when needed and there's a terminal to ask on (or the password is given); a file
  # path works too
  if [[ -z "$ZIP" && -z "$GAME_LINK" ]] && { [[ -n "${MW_SETUP_PASSWORD:-}" ]] || { : < /dev/tty; } 2>/dev/null; }; then
    if links=$(unlock_links); then
      GAME_LINK=$(sed -n 's/^game=//p' <<< "$links")
      [[ -n "$MAPS_LINK" ]] || MAPS_LINK=$(sed -n 's/^maps=//p' <<< "$links")
    elif [[ -z "${MW_SETUP_PASSWORD:-}" ]]; then
      read -rp "    Paste the game download link, or the path to mw.zip: " GAME_LINK < /dev/tty || true
    fi
  fi
  if [[ -z "$ZIP" && -f "$GAME_LINK" ]]; then ZIP="$GAME_LINK"; KEEP_ZIP=1; fi

  if [[ -n "$ZIP" ]]; then
    [[ -f "$ZIP" ]] || die "zip not found: $ZIP"
    ok "using existing $ZIP"
  else
    [[ -n "$GAME_LINK" ]] || die "no download link given. Pass --game-url <link>, or put mw.zip in $(dirname "$DOWNLOAD_ZIP")"
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
    need_gb=$(( (remote_size - have) / 1024 / 1024 / 1024 + 1 ))   # rest of the download
    mkdir -p "$(dirname "$ZIP")" "$(dirname "$GAME")"
    if [[ "$(df -P "$(dirname "$ZIP")" | awk 'NR==2 {print $1}')" == "$(df -P "$(dirname "$GAME")" | awk 'NR==2 {print $1}')" ]]; then
      need_gb=$(( need_gb + 18 ))   # and the game folder on the same disk
    else
      (( $(free_gb "$(dirname "$GAME")") >= 18 )) || die "need about 18 GB free for the game in $(dirname "$GAME"), only $(free_gb "$(dirname "$GAME")") GB available"
    fi
    (( $(free_gb "$(dirname "$ZIP")") >= need_gb )) || die "need about ${need_gb} GB free disk space in $(dirname "$ZIP"), only $(free_gb "$(dirname "$ZIP")") GB available"
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
  tmp="$(dirname "$GAME")/.setup-tmp"
  rm -rf "$tmp"
  trap 'rm -rf "$tmp"' EXIT
  unzip -q "$ZIP" "*/$GAME_REL/*" -x "__MACOSX/*" -d "$tmp" || die "zip does not contain the MW2 game folder"
  src=$(find "$tmp" -mindepth 1 -maxdepth 1 -type d | head -1)
  [[ -f "$src/$GAME_REL/iw4x.exe" ]] || die "zip does not contain the MW2 game folder"
  mv "$src/$GAME_REL" "$GAME"
  rm -rf "$tmp" "$GAME/players"   # players/: the copied client profile, a server doesn't need it
  ok "installed to $GAME"
  (( KEEP_ZIP )) || { rm -f "$ZIP"; ok "removed mw.zip"; }
fi
# The game folder also holds the 64-bit IW4x launcher's DLLs. Debian's Wine loads
# zlib1.dll for its own user32.dll and finds the 64-bit one here first: the 32-bit
# server then fails to start. The server never runs the launcher, so move it aside.
if [[ -f "$GAME/zlib1.dll" ]]; then
  mv "$GAME/zlib1.dll" "$GAME/zlib1.dll.x64"
  ok "moved aside the launcher's 64-bit zlib1.dll (stops Wine from starting the server)"
fi

# ---------------------------------------------------------------- server.cfg
step "Custom maps + bots"
# the pack over parallel connections too when its server allows it; install-maps.sh downloads
# it the plain way otherwise, or when this fails
MAPS_ZIP=""
if [[ -n "$MAPS_LINK" && ! -f "$MAPS_LINK" && ! -f "$GAME/.iw4x-maps-installed-v2" ]]; then  # install-maps.sh's mark
  url="$MAPS_LINK"
  if [[ "$MAPS_LINK" =~ /d/([A-Za-z0-9_-]{20,}) ]] || [[ "$MAPS_LINK" =~ [?\&]id=([A-Za-z0-9_-]{20,}) ]]; then
    url="https://drive.usercontent.google.com/download?id=${BASH_REMATCH[1]}&export=download&confirm=t"
  fi
  head=$(curl -sIL --max-time 20 "$url" || true)
  remote_size=$(awk 'tolower($1)=="content-length:" {s=$2} END {gsub("\r","",s); print s}' <<< "$head")
  if grep -qi '^accept-ranges: bytes' <<< "$head" && ! grep -qi '^content-type: text/html' <<< "$head" \
     && [[ "$remote_size" =~ ^[1-9][0-9]*$ ]]; then
    MAPS_ZIP="$(dirname "$DOWNLOAD_ZIP")/mw2-iw4x-maps-bots.zip"
    mkdir -p "$(dirname "$MAPS_ZIP")"
    echo "    Downloading the pack to $MAPS_ZIP"
    if ! fetch_parallel "$url" "$remote_size" "$MAPS_ZIP" || [[ "$(size_of "$MAPS_ZIP")" != "$remote_size" ]]; then
      warn "the parallel download of the pack failed, trying the plain one"
      rm -rf "$MAPS_ZIP" "$MAPS_ZIP.parts"
      MAPS_ZIP=""
    fi
  fi
fi
bash "$REPO/scripts/mac/install-maps.sh" --dir "$GAME" ${MAPS_ZIP:+--zip "$MAPS_ZIP"} ${MAPS_LINK:+--maps-url "$MAPS_LINK"} || warn "custom maps not installed, run: bash scripts/mac/install-maps.sh --dir game"
[[ -z "$MAPS_ZIP" ]] || rm -f "$MAPS_ZIP"

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

if (( GAME_ONLY )); then
  step "Done"
  echo "    Game in $GAME"
  exit 0
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
  read -rsp "    Password for the web UI: " UI_PASSWORD; echo
  [[ -n "$UI_PASSWORD" ]] || die "a password is needed for the web UI"
  setenv UI_PASSWORD "$UI_PASSWORD"
fi
ok "web UI login: password (UI_PASSWORD in .env)"

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
echo "    Players:    connect $DOMAIN$([ "$port" = 28960 ] || echo ":$port")"
