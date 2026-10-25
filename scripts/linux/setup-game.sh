#!/usr/bin/env bash
# One-shot setup of MW2 + IW4x on a Linux desktop, to play (the server setup is setup.sh):
#   1. installs Wine, cabextract and unzip (if missing)
#   2. creates a Wine prefix with DXVK (MW2's DirectX 9 on Vulkan) and the runtimes IW4x
#      needs, using winetricks (downloaded, so every machine gets the same version)
#   3. downloads the prepared game package (mw.zip) and installs only the game folder from it
#   4. configures it: fresh profile, fullscreen at native resolution, shared game
#      settings (config/client.cfg)
#   5. installs the custom maps + bots pack (install-maps.sh)
#   6. creates an app menu entry that starts the game
#
# Plain Wine instead of IW4x's own Linux launcher: that one needs Steam with Proton, and
# updates IW4x on every start. Like the Mac and Windows shortcuts this starts the IW4x
# version from the package, the one the servers run.
#
# Run it straight from GitHub, in a terminal:
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/dorostanian/iw4x-friends/main/scripts/linux/setup-game.sh)"
# or as a downloaded file:   bash setup-game.sh
# Safe to re-run: every step skips what is already done, and an interrupted
# download resumes where it stopped.
# Options:
#   --dir <path>     where to install (default: ~/Games/iw4x): game/, the Wine prefix/,
#                    winetricks and the iw4x.sh starter go in there
#   --force          reinstall the game folder (old one is renamed, not deleted)
#   --game-url <link>  download link of mw.zip (a Google Drive share link works); also
#                    MW_GAME_URL. When a download is needed and it's not given, it asks for
#                    the setup password (decrypts the links below) or the link itself
#   --maps-url <link>  same for the custom maps + bots pack (MW_MAPS_URL)
#   --zip <path>     use this mw.zip (otherwise it looks in ~/Downloads and the current
#                    folder before downloading), e.g. one on an external drive
#   --keep-zip       keep mw.zip after installing (default: delete it if this script downloaded it)

set -euo pipefail

GAME_REL="drive_c/Program Files (x86)/Call of Duty Modern Warfare 2"
DOWNLOAD_ZIP="$HOME/Downloads/mw.zip"
MARK_PREFIX=".iw4x-setup-prefix"
MARK_CONFIGURED=".iw4x-setup-configured"
WINETRICKS_VERSION="20260125"
# winetricks verb: DXVK 2.6.2. 2.7 needs VK_KHR_maintenance5, which Wine 8's Vulkan layer
# doesn't pass on even when the driver has it: DXVK then finds no GPU and the game crashes
DXVK="dxvk2062"
# download links, encrypted with the setup password (written by `task links`)
LINKS_ENC="U2FsdGVkX18BSFqqHMCQ++5w+wJL5cdh3asQpzzejdBx2HWUrjeVW3q15pMGc31tolezaREbLw7dPLBzNarkDGagqk5k81ChbyM7uVo97si+Qc/A/GDQ+Y1Gkje41pLweL2l2zWtdoyWSKS33+xtZ92FbDNb5kYs4B9rHU3DfkJFIP0naKFFciIY7ikspmyrxsHNiTtW8zGg5eFIJbcxXe/vVJiCjUDQyPGbkry3TdA="

DIR="$HOME/Games/iw4x" FORCE=0 KEEP_ZIP=0 ZIP="" GAME_LINK="${MW_GAME_URL:-}" MAPS_LINK="${MW_MAPS_URL:-}"
while (( $# )); do
  case "$1" in
    --dir) DIR="$2"; shift ;;
    --force) FORCE=1 ;;
    --keep-zip) KEEP_ZIP=1 ;;
    --zip) ZIP="$2"; KEEP_ZIP=1; shift ;;
    --game-url) GAME_LINK="$2"; shift ;;
    --maps-url) MAPS_LINK="$2"; shift ;;
    *) echo "unknown option: $1"; exit 1 ;;
  esac
  shift
done
DIR=$(realpath -m "$DIR")
GAME="$DIR/game"
HERE=$(cd "$(dirname "${BASH_SOURCE[0]:-.}")" && pwd)

step() { printf '\n\033[36m==> %s\033[0m\n' "$1"; }
ok()   { printf '    \033[32m✓\033[0m %s\n' "$1"; }
warn() { printf '    \033[33m!\033[0m %s\n' "$1"; }
die()  { printf '    \033[31m✗ %s\033[0m\n' "$1"; exit 1; }

SUDO=""; (( EUID )) && SUDO="sudo"
size_of() { [[ -f "$1" ]] && stat -c%s "$1" || echo 0; }
free_gb() { echo $(( $(df -Pk "$1" | awk 'NR==2 {print $4}') / 1024 / 1024 )); }

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

# set a "seta key value" line in a .cfg file, appending it if missing
setcfg() {
  local key=$1 val=$2 file=$3
  if grep -q "^seta $key " "$file"; then
    sed -i "s|^seta $key .*|seta $key \"$val\"|" "$file"
  else
    echo "seta $key \"$val\"" >> "$file"
  fi
}

# ---------------------------------------------------------------- checks
step "Checking this machine"
[[ "$(uname)" == "Linux" ]] || die "this script is for Linux"
[[ "$(uname -m)" == "x86_64" ]] || die "needs an x86_64 machine (Wine runs the 32-bit Windows game)"
(( EUID )) || die "run this as your own user, not root (it asks for sudo when it installs packages)"

need=()
for cmd in wine cabextract unzip curl; do
  command -v "$cmd" >/dev/null || need+=("$cmd")
done
if (( ${#need[@]} )); then
  warn "installing ${need[*]}"
  if command -v dnf >/dev/null; then
    $SUDO dnf install -y "${need[@]}" || die "couldn't install ${need[*]}: install them and re-run"
  elif command -v apt-get >/dev/null; then
    # iw4x.exe is a 32-bit Windows program: Debian and Ubuntu ship that half of Wine as wine32 (i386)
    if [[ " ${need[*]} " == *" wine "* ]]; then
      $SUDO dpkg --add-architecture i386
      need+=(wine32)
    fi
    { $SUDO apt-get update -qq && $SUDO apt-get install -y "${need[@]}"; } || die "couldn't install ${need[*]}: install them and re-run"
  elif command -v pacman >/dev/null; then
    $SUDO pacman -S --needed --noconfirm "${need[@]}" || die "couldn't install ${need[*]}: install them and re-run"
  else
    die "install Wine (with 32-bit support), cabextract, unzip and curl, then re-run"
  fi
fi
wine_version=$(wine --version 2>/dev/null || true)
ok "Wine installed (${wine_version:-unknown version})"
major=${wine_version#wine-}; major=${major%%.*}
[[ "$major" =~ ^[0-9]+$ ]] && (( major < 8 )) && warn "this Wine is old, DXVK may not work with it: if the game doesn't start, install a newer Wine (winehq.org)"

# ---------------------------------------------------------------- Wine prefix
step "Wine prefix"
mkdir -p "$DIR"
# no Wine Mono/Gecko install prompts: the game doesn't use .NET or the built-in browser
export WINEPREFIX="$DIR/prefix" WINEDEBUG=-all WINEDLLOVERRIDES="mscoree,mshtml="
if [[ -f "$WINEPREFIX/$MARK_PREFIX" ]]; then
  ok "already set up: $WINEPREFIX"
else
  # winetricks from upstream, the same version everywhere: distro packages lag behind,
  # and Fedora's conflicts with WineHQ's Wine
  winetricks="$DIR/winetricks"
  if [[ ! -x "$winetricks" ]]; then
    curl -fsSL "https://raw.githubusercontent.com/Winetricks/winetricks/$WINETRICKS_VERSION/src/winetricks" -o "$winetricks.part" \
      || die "couldn't download winetricks, re-run to try again"
    chmod +x "$winetricks.part"
    mv "$winetricks.part" "$winetricks"
  fi
  echo "    Creating it and installing DXVK and the runtimes IW4x needs (takes a few minutes)..."
  wineboot -i
  wineserver -w
  # what IW4x's Linux guide lists: the VC++ runtime, the shader compiler, and DXVK,
  # which runs the game's DirectX 9 on Vulkan (much faster than Wine's own on OpenGL)
  "$winetricks" -q vcrun2019 d3dcompiler_47 "$DXVK" || die "winetricks failed, re-run to try again"
  wineserver -w
  touch "$WINEPREFIX/$MARK_PREFIX"
  ok "created $WINEPREFIX"
fi

# ---------------------------------------------------------------- game files
step "Game folder (mw.zip, ~16 GB)"
if [[ -f "$GAME/iw4x.exe" ]] && (( ! FORCE )); then
  ok "already installed in $GAME"
else
  if [[ -z "$ZIP" ]]; then
    # reuse a complete copy if one is lying around (a partial download has no zip index yet)
    for candidate in "$DOWNLOAD_ZIP" "$PWD/mw.zip"; do
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
  GAME_LINK="${GAME_LINK//\\ / }"; GAME_LINK="${GAME_LINK% }"   # a dragged-in file has its spaces escaped
  GAME_LINK="${GAME_LINK/#\~/$HOME}"
  if [[ -z "$ZIP" && -f "$GAME_LINK" ]]; then ZIP="$GAME_LINK"; KEEP_ZIP=1; fi

  if [[ -n "$ZIP" ]]; then
    [[ -f "$ZIP" ]] || die "zip not found: $ZIP"
    ok "using existing $ZIP"
  else
    [[ -n "$GAME_LINK" ]] || die "no download link given. Pass --game-url <link>, or put mw.zip in ~/Downloads"
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
      (too many downloads today), or the link isn't shared. Try again later, or open
      the link in a browser, save mw.zip to ~/Downloads and re-run the script."
    fi
    mkdir -p "${DOWNLOAD_ZIP%/*}"
    ZIP="$DOWNLOAD_ZIP"
    # a partial file that is really an HTML error page can't be resumed
    [[ -f "$ZIP" ]] && [[ "$(head -c 1 "$ZIP")" == "<" ]] && rm -f "$ZIP"
    have=$(( $(size_of "$ZIP") + $(parts_size "$ZIP") ))
    need_gb=$(( (remote_size - have) / 1024 / 1024 / 1024 + 18 ))   # rest of download + game folder
    (( $(free_gb "${ZIP%/*}") >= need_gb )) || die "need about ${need_gb} GB free disk space, only $(free_gb "${ZIP%/*}") GB available.
      Short on space? Download mw.zip to another drive and pass it: --zip /path/to/mw.zip"
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

  (( $(free_gb "$DIR") >= 18 )) || die "need about 18 GB free disk space in $DIR, only $(free_gb "$DIR") GB available"
  if [[ -d "$GAME" ]]; then
    backup="$GAME.backup-$(date +%Y%m%d-%H%M%S)"
    mv "$GAME" "$backup"
    rm -f "$DIR/$MARK_CONFIGURED"
    warn "old game folder moved to: $backup"
  fi
  # The zip holds a whole CrossOver bottle; only the MW2 folder inside it is needed.
  # Extract next to the target, then rename: game/ only appears once it's complete.
  echo "    Extracting the game folder (takes a few minutes)..."
  tmp="$DIR/.setup-tmp"
  rm -rf "$tmp"
  trap 'rm -rf "$tmp"' EXIT
  trap 'exit 130' INT TERM   # make the EXIT cleanup run on Ctrl+C / kill too
  unzip -q "$ZIP" "*/$GAME_REL/*" -x "__MACOSX/*" -d "$tmp" || die "zip does not contain the MW2 game folder"
  src=$(find "$tmp" -mindepth 1 -maxdepth 1 -type d | head -1)
  [[ -f "$src/$GAME_REL/iw4x.exe" ]] || die "zip does not contain the MW2 game folder"
  mv "$src/$GAME_REL" "$GAME"
  rm -rf "$tmp"
  ok "installed to $GAME"
  (( KEEP_ZIP )) || { rm -f "$ZIP"; ok "removed mw.zip"; }
fi
# The game folder also holds the 64-bit Windows launcher's DLLs. Some distros' Wine loads
# zlib1.dll for its own DLLs and finds the 64-bit one here first: the 32-bit game then
# fails to start. The game is started without that launcher here, so move it aside.
if [[ -f "$GAME/zlib1.dll" ]]; then
  mv "$GAME/zlib1.dll" "$GAME/zlib1.dll.x64"
  ok "moved aside the Windows launcher's 64-bit zlib1.dll (stops some Wine builds from starting the game)"
fi

# ---------------------------------------------------------------- configure
step "Configuring"
if [[ -f "$DIR/$MARK_CONFIGURED" ]]; then
  # don't wipe the profile or graphics choices of an install that's already in use
  ok "already configured by an earlier run, keeping current settings"
else
  # players/ holds the copied profile and stats from the machine the package was made on.
  # (The player identity, guid.dat, lives in the Wine prefix, which is new per machine.)
  rm -rf "$GAME/players"
  mkdir -p "$GAME/players"
  ok "removed copied profile (players/), a fresh one is created on first start"

  # Fullscreen at the main screen's current resolution (xrandr also works under Wayland,
  # through XWayland), otherwise the first connected screen's preferred one
  xr=$(xrandr --current 2>/dev/null || true)
  res=$(sed -n 's/.* connected primary \([0-9]*x[0-9]*\)+.*/\1/p' <<< "$xr" | head -1)
  [[ "$res" =~ ^[0-9]+x[0-9]+$ ]] || res=$(awk '/\*/ {print $1; exit}' <<< "$xr")
  if [[ ! "$res" =~ ^[0-9]+x[0-9]+$ ]]; then
    for status in /sys/class/drm/*/status; do
      if [[ "$(cat "$status")" == connected ]]; then
        res=$(head -1 "${status%status}modes")
        break
      fi
    done
  fi
  [[ "$res" =~ ^[0-9]+x[0-9]+$ ]] || res="1280x720"
  cfg="$GAME/players/iw4x_config.cfg"
  touch "$cfg"
  setcfg r_fullscreen 1 "$cfg"
  setcfg r_noborder 0 "$cfg"
  setcfg r_mode "$res" "$cfg"
  setcfg vid_xpos 0 "$cfg"
  setcfg vid_ypos 0 "$cfg"
  ok "fullscreen at $res"

  touch "$DIR/$MARK_CONFIGURED"
fi

# Shared game settings (lowest graphics, no hitches when hit). Loaded on every start via
# "+exec client_tweaks.cfg", so they also cover settings the game itself never saves.
# BEGIN client.cfg (generated from config/client.cfg by scripts/tools/sync-config.py, don't edit here)
CLIENT_CFG=$(cat <<'CFG'
// Game settings for every player, applied on each game start (macOS, Windows and Linux).
// The setup scripts install this as main/client_tweaks.cfg and the launchers start
// the game with "+exec client_tweaks.cfg", so it also covers settings the game
// itself never saves. Edit here, then run: task sync-config
// Display resolution is detected per machine and not set here.

// display
seta r_fullscreen "1"
seta r_noborder "0"
seta r_vsync "0"
seta com_maxfps "85"

// lowest textures
seta r_picmip "3"
seta r_picmip_bump "3"
seta r_picmip_spec "3"
seta r_picmip_manual "1"

// no shadows, AA, anisotropic filtering
seta sm_enable "0"
seta sm_maxLights "0"
seta r_aaSamples "1"
seta r_texFilterAnisoMax "1"

// no expensive effects
seta r_specular "0"
seta r_glow_allowed "0"
seta r_distortion "0"
seta r_dof_enable "0"
seta r_zFeather "0"
seta r_drawWater "0"
seta r_drawSun "0"
seta r_dlightLimit "0"
seta fx_marks "0"
seta fx_marks_ents "0"
seta fx_marks_smodels "0"
seta ragdoll_enable "0"
seta cg_brass "0"

// no hitches: shaders prepared at map load
seta r_preloadShaders "1"

// no FPS drop when hit: blood/damage overlays, damage audio filter, scripted vision effects
seta cg_splatterHitAlpha "0"
seta cg_splatterTrackAlpha "0"
seta cg_drawDamageFlash "0"
seta cg_blood "0"
seta snd_touchStreamFilesOnLoad "1"
seta snd_enableEq "0"
seta snd_enableReverb "0"
seta r_glow_allowed_script_forced "0"
seta r_blur "0"
seta r_filmUseTweaks "0"

// sound: game effects a bit quieter, voices louder. There's no setting for the
// volume of other players' voices, so everyone boosts their own microphone instead
seta snd_volume "0.6"
seta winvoice_mic_scaler "2"
seta winvoice_mic_reclevel "65535"

// F9 during a match loads the ready-made classes (classes.cfg). Key bindings don't work
// in menus; at the main menu use the console instead: exec classes.cfg. They can't load
// automatically at startup: the game reads your stats a few seconds later.
bind F9 "exec classes.cfg"

// in-game server menu (!menu, !gt, !map): Up/Down move, Enter picks. The server only sees
// bound commands, so the arrows act as forward/back and Enter as use (same as F)
bind UPARROW "+forward"
bind DOWNARROW "+back"
bind ENTER "+activate"
bind KP_ENTER "+activate"

// in-game vote (game type, then map): F1 .. F6 vote for option 1 .. 6, same as !1 .. !6 in chat
bind F1 "say !1"
bind F2 "say !2"
bind F3 "say !3"
bind F4 "say !4"
bind F5 "say !5"
bind F6 "say !6"
CFG
)
# END client.cfg
printf '%s\n' "$CLIENT_CFG" > "$GAME/main/client_tweaks.cfg"
ok "game settings installed (lowest graphics, no FPS drops when hit)"

# Ready-made classes, loaded with F9 during a match (bound in client.cfg) or exec classes.cfg
# BEGIN classes.cfg (generated from config/classes.cfg by scripts/tools/sync-config.py, don't edit here)
CLASSES_CFG=$(cat <<'CFG'
// Ten custom classes: agile SMGs and light rifles (no LMGs), two M16 classes,
// a quickscope sniper (5) and a stealth class for Search & Destroy (10).
// Most use Bling (two attachments, Pro also on the secondary) to stack FMJ with
// a silencer or red dot; Lightweight and Commando keep them fast.
// Load them at the main menu: press ~ and type  exec classes.cfg  (or F9 during a match).
// Run unlockstats first so every weapon, attachment and perk is unlocked.
// They replace your custom class slots 1 to 10. inUse makes a slot show up in the
// in-game class selection (the game only sets it when you edit a class yourself).

// 1. UMP Rush: UMP45 keeps full damage silenced, FMJ shoots through cover: sprint, flank, knife
setPlayerData customClasses 0 name "UMP Rush"
setPlayerData customClasses 0 inUse 1
setPlayerData customClasses 0 weaponSetups 0 weapon ump45
setPlayerData customClasses 0 weaponSetups 0 attachment 0 silencer
setPlayerData customClasses 0 weaponSetups 0 attachment 1 fmj
setPlayerData customClasses 0 weaponSetups 1 weapon usp
setPlayerData customClasses 0 weaponSetups 1 attachment 0 tactical
setPlayerData customClasses 0 weaponSetups 1 attachment 1 fmj
setPlayerData customClasses 0 perks 0 semtex_mp
setPlayerData customClasses 0 perks 1 specialty_bling
setPlayerData customClasses 0 perks 2 specialty_lightweight
setPlayerData customClasses 0 perks 3 specialty_extendedmelee
setPlayerData customClasses 0 perks 4 specialty_painkiller
setPlayerData customClasses 0 specialGrenade flash_grenade

// 2. Vector Ghost: invisible to UAV and thermal, silent footsteps
setPlayerData customClasses 1 name "Vector Ghost"
setPlayerData customClasses 1 inUse 1
setPlayerData customClasses 1 weaponSetups 0 weapon kriss
setPlayerData customClasses 1 weaponSetups 0 attachment 0 silencer
setPlayerData customClasses 1 weaponSetups 0 attachment 1 fmj
setPlayerData customClasses 1 weaponSetups 1 weapon pp2000
setPlayerData customClasses 1 weaponSetups 1 attachment 0 silencer
setPlayerData customClasses 1 weaponSetups 1 attachment 1 fmj
setPlayerData customClasses 1 perks 0 throwingknife_mp
setPlayerData customClasses 1 perks 1 specialty_bling
setPlayerData customClasses 1 perks 2 specialty_coldblooded
setPlayerData customClasses 1 perks 3 specialty_heartbreaker
setPlayerData customClasses 1 perks 4 specialty_copycat
setPlayerData customClasses 1 specialGrenade concussion_grenade

// 3. ACR Runner: almost no recoil, silenced with full penetration
setPlayerData customClasses 2 name "ACR Runner"
setPlayerData customClasses 2 inUse 1
setPlayerData customClasses 2 weaponSetups 0 weapon masada
setPlayerData customClasses 2 weaponSetups 0 attachment 0 silencer
setPlayerData customClasses 2 weaponSetups 0 attachment 1 fmj
setPlayerData customClasses 2 weaponSetups 1 weapon usp
setPlayerData customClasses 2 weaponSetups 1 attachment 0 tactical
setPlayerData customClasses 2 weaponSetups 1 attachment 1 fmj
setPlayerData customClasses 2 perks 0 semtex_mp
setPlayerData customClasses 2 perks 1 specialty_bling
setPlayerData customClasses 2 perks 2 specialty_lightweight
setPlayerData customClasses 2 perks 3 specialty_extendedmelee
setPlayerData customClasses 2 perks 4 specialty_painkiller
setPlayerData customClasses 2 specialGrenade flash_grenade

// 4. FAMAS Burst: one-burst kills with a clear red dot
setPlayerData customClasses 3 name "FAMAS Burst"
setPlayerData customClasses 3 inUse 1
setPlayerData customClasses 3 weaponSetups 0 weapon famas
setPlayerData customClasses 3 weaponSetups 0 attachment 0 reflex
setPlayerData customClasses 3 weaponSetups 0 attachment 1 fmj
setPlayerData customClasses 3 weaponSetups 1 weapon usp
setPlayerData customClasses 3 weaponSetups 1 attachment 0 tactical
setPlayerData customClasses 3 weaponSetups 1 attachment 1 fmj
setPlayerData customClasses 3 perks 0 throwingknife_mp
setPlayerData customClasses 3 perks 1 specialty_bling
setPlayerData customClasses 3 perks 2 specialty_lightweight
setPlayerData customClasses 3 perks 3 specialty_extendedmelee
setPlayerData customClasses 3 perks 4 specialty_painkiller
setPlayerData customClasses 3 specialGrenade flash_grenade

// 5. Quickscope: the classic Intervention quickscope setup
setPlayerData customClasses 4 name "Quickscope"
setPlayerData customClasses 4 inUse 1
setPlayerData customClasses 4 weaponSetups 0 weapon cheytac
setPlayerData customClasses 4 weaponSetups 0 attachment 0 fmj
setPlayerData customClasses 4 weaponSetups 0 attachment 1 none
setPlayerData customClasses 4 weaponSetups 1 weapon usp
setPlayerData customClasses 4 weaponSetups 1 attachment 0 tactical
setPlayerData customClasses 4 weaponSetups 1 attachment 1 none
setPlayerData customClasses 4 perks 0 throwingknife_mp
setPlayerData customClasses 4 perks 1 specialty_fastreload
setPlayerData customClasses 4 perks 2 specialty_lightweight
setPlayerData customClasses 4 perks 3 specialty_bulletaccuracy
setPlayerData customClasses 4 perks 4 specialty_painkiller
setPlayerData customClasses 4 specialGrenade flash_grenade

// 6. Shotgun Blitz: close range: rapid MP5K, akimbo 1887s as backup
setPlayerData customClasses 5 name "Shotgun Blitz"
setPlayerData customClasses 5 inUse 1
setPlayerData customClasses 5 weaponSetups 0 weapon mp5k
setPlayerData customClasses 5 weaponSetups 0 attachment 0 rof
setPlayerData customClasses 5 weaponSetups 0 attachment 1 fmj
setPlayerData customClasses 5 weaponSetups 1 weapon model1887
setPlayerData customClasses 5 weaponSetups 1 attachment 0 akimbo
setPlayerData customClasses 5 weaponSetups 1 attachment 1 fmj
setPlayerData customClasses 5 perks 0 semtex_mp
setPlayerData customClasses 5 perks 1 specialty_bling
setPlayerData customClasses 5 perks 2 specialty_lightweight
setPlayerData customClasses 5 perks 3 specialty_extendedmelee
setPlayerData customClasses 5 perks 4 specialty_painkiller
setPlayerData customClasses 5 specialGrenade flash_grenade

// 7. P90 Ninja: huge magazine, silent, killstreaks one kill earlier
setPlayerData customClasses 6 name "P90 Ninja"
setPlayerData customClasses 6 inUse 1
setPlayerData customClasses 6 weaponSetups 0 weapon p90
setPlayerData customClasses 6 weaponSetups 0 attachment 0 silencer
setPlayerData customClasses 6 weaponSetups 0 attachment 1 fmj
setPlayerData customClasses 6 weaponSetups 1 weapon pp2000
setPlayerData customClasses 6 weaponSetups 1 attachment 0 silencer
setPlayerData customClasses 6 weaponSetups 1 attachment 1 fmj
setPlayerData customClasses 6 perks 0 throwingknife_mp
setPlayerData customClasses 6 perks 1 specialty_bling
setPlayerData customClasses 6 perks 2 specialty_hardline
setPlayerData customClasses 6 perks 3 specialty_heartbreaker
setPlayerData customClasses 6 perks 4 specialty_copycat
setPlayerData customClasses 6 specialGrenade flash_grenade

// 8. M16 Ghost: silent M16 bursts, off the radar
setPlayerData customClasses 7 name "M16 Ghost"
setPlayerData customClasses 7 inUse 1
setPlayerData customClasses 7 weaponSetups 0 weapon m16
setPlayerData customClasses 7 weaponSetups 0 attachment 0 silencer
setPlayerData customClasses 7 weaponSetups 0 attachment 1 fmj
setPlayerData customClasses 7 weaponSetups 1 weapon usp
setPlayerData customClasses 7 weaponSetups 1 attachment 0 tactical
setPlayerData customClasses 7 weaponSetups 1 attachment 1 fmj
setPlayerData customClasses 7 perks 0 throwingknife_mp
setPlayerData customClasses 7 perks 1 specialty_bling
setPlayerData customClasses 7 perks 2 specialty_coldblooded
setPlayerData customClasses 7 perks 3 specialty_heartbreaker
setPlayerData customClasses 7 perks 4 specialty_painkiller
setPlayerData customClasses 7 specialGrenade flash_grenade

// 9. M16 Power: M16 with Stopping Power: one-burst kills at range
setPlayerData customClasses 8 name "M16 Power"
setPlayerData customClasses 8 inUse 1
setPlayerData customClasses 8 weaponSetups 0 weapon m16
setPlayerData customClasses 8 weaponSetups 0 attachment 0 reflex
setPlayerData customClasses 8 weaponSetups 0 attachment 1 fmj
setPlayerData customClasses 8 weaponSetups 1 weapon usp
setPlayerData customClasses 8 weaponSetups 1 attachment 0 tactical
setPlayerData customClasses 8 weaponSetups 1 attachment 1 fmj
setPlayerData customClasses 8 perks 0 frag_grenade_mp
setPlayerData customClasses 8 perks 1 specialty_bling
setPlayerData customClasses 8 perks 2 specialty_bulletdamage
setPlayerData customClasses 8 perks 3 specialty_extendedmelee
setPlayerData customClasses 8 perks 4 specialty_painkiller
setPlayerData customClasses 8 specialGrenade flash_grenade

// 10. S&D Stealth: one life, so stay off the radar: claymore guards the bomb, smoke covers plant/defuse
setPlayerData customClasses 9 name "S&D Stealth"
setPlayerData customClasses 9 inUse 1
setPlayerData customClasses 9 weaponSetups 0 weapon scar
setPlayerData customClasses 9 weaponSetups 0 attachment 0 silencer
setPlayerData customClasses 9 weaponSetups 0 attachment 1 fmj
setPlayerData customClasses 9 weaponSetups 1 weapon usp
setPlayerData customClasses 9 weaponSetups 1 attachment 0 tactical
setPlayerData customClasses 9 weaponSetups 1 attachment 1 fmj
setPlayerData customClasses 9 perks 0 claymore_mp
setPlayerData customClasses 9 perks 1 specialty_bling
setPlayerData customClasses 9 perks 2 specialty_coldblooded
setPlayerData customClasses 9 perks 3 specialty_heartbreaker
setPlayerData customClasses 9 perks 4 specialty_null
setPlayerData customClasses 9 specialGrenade smoke_grenade

say "Loaded 10 custom classes"
CFG
)
# END classes.cfg
printf '%s\n' "$CLASSES_CFG" > "$GAME/main/classes.cfg"
ok "ready-made classes installed (load them: F9 during a match, or ~ then exec classes.cfg)"

# ---------------------------------------------------------------- custom maps + bots
# Separate pack, also installable on its own with install-maps.sh. A local copy is used
# when there is one (next to this script, or in the repo), otherwise it's fetched from GitHub.
maps_script=""
for candidate in "$HERE/install-maps.sh" "$HERE/../mac/install-maps.sh"; do
  [[ -f "$candidate" ]] && { maps_script="$candidate"; break; }
done
if [[ -n "$maps_script" ]]; then
  bash "$maps_script" --dir "$GAME" ${MAPS_LINK:+--maps-url "$MAPS_LINK"} || warn "custom maps not installed, run: bash $maps_script --dir \"$GAME\""
else
  bash -c "$(curl -fsSL https://raw.githubusercontent.com/dorostanian/iw4x-friends/main/scripts/mac/install-maps.sh)" install-maps --dir "$GAME" ${MAPS_LINK:+--maps-url "$MAPS_LINK"} \
    || warn "custom maps not installed. Later, run: bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/dorostanian/iw4x-friends/main/scripts/mac/install-maps.sh)\" install-maps --dir \"$GAME\""
fi

# ---------------------------------------------------------------- launcher
step "App menu entry"
launcher="$DIR/iw4x.sh"
cat > "$launcher" <<EOF
#!/usr/bin/env bash
# Start IW4x under Wine with the shared settings (written by setup-game.sh)
export WINEPREFIX="$WINEPREFIX" WINEDEBUG=-all WINEDLLOVERRIDES="mscoree,mshtml="
cd "$GAME" || exit 1
exec wine iw4x.exe +exec client_tweaks.cfg "\$@"
EOF
chmod +x "$launcher"
desktop="$HOME/.local/share/applications/iw4x.desktop"
mkdir -p "${desktop%/*}"
cat > "$desktop" <<EOF
[Desktop Entry]
Type=Application
Name=IW4x
Comment=Call of Duty: Modern Warfare 2 multiplayer
Exec="$launcher"
Icon=applications-games
Terminal=false
Categories=Game;
EOF
ok "created \"IW4x\" in the app menu (starts $launcher)"

# ---------------------------------------------------------------- done
step "Done"
cat <<EOF
    Start the game:   "IW4x" in the app menu, or run: $launcher

    Join a LAN game:  Server Browser > LAN tab,
                      or press ~ and type:  connect <server-ip>:28960

    Graphics are set to the lowest preset. Raise them in Options if it runs well.
EOF

read -rp "    Start IW4x now? [Y/n] " start || start=n
[[ "$start" =~ ^[Nn] ]] || setsid -f "$launcher" >/dev/null 2>&1
