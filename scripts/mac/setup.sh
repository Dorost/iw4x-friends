#!/bin/zsh
# One-shot setup of MW2 + IW4x on a Mac:
#   1. installs CrossOver (if missing)
#   2. downloads the prepared "mw" bottle from Google Drive
#   3. installs it into CrossOver's Bottles folder
#   4. configures it: unique player identity, fullscreen at native resolution,
#      Auto graphics, MSync on, shared game settings (config/client.cfg)
#   5. installs the custom maps + bots pack (install-maps.sh)
#   6. creates a Desktop launcher that skips IW4x's remote update check
#
# Run it straight from GitHub, in Terminal:
#   zsh -c "$(curl -fsSL https://raw.githubusercontent.com/dorostanian/iw4x-friends/main/scripts/mac/setup.sh)"
# or as a downloaded file:   zsh setup.sh
# Safe to re-run: every step skips what is already done, and an interrupted
# download resumes where it stopped.
# Options:
#   --bottle <name>  bottle name to install as (default: mw)
#   --force          reinstall even if the bottle exists (old one is renamed, not deleted)
#   --game-url <link>  download link of mw.zip (a Google Drive share link works); also
#                    MW_GAME_URL. When a download is needed and it's not given, it asks for
#                    the setup password (decrypts the links below) or the link itself
#   --maps-url <link>  same for the custom maps + bots pack (MW_MAPS_URL)
#   --zip <path>     use this mw.zip (otherwise it looks in ~/Downloads, the Bottles
#                    folder and the current folder before downloading)
#   --keep-zip       keep mw.zip after installing (default: delete it if this script downloaded it)

set -euo pipefail

CROSSOVER_URL="https://media.codeweavers.com/pub/crossover/cxmac/demo/crossover-26.3.0.zip"
BOTTLE="mw"
BOTTLES="$HOME/Library/Application Support/CrossOver/Bottles"
GAME_REL="drive_c/Program Files (x86)/Call of Duty Modern Warfare 2"
WINE="/Applications/CrossOver.app/Contents/SharedSupport/CrossOver/bin/wine"
DOWNLOAD_ZIP="$HOME/Downloads/mw.zip"
MARK_INSTALLED=".iw4x-setup-installed"
MARK_CONFIGURED=".iw4x-setup-configured"
# download links, encrypted with the setup password (written by `task links`)
LINKS_ENC="U2FsdGVkX19z1JucWZqUi9mbrydBrz7IZBKu1HjwaeSCQDgD/3GuECrT/uzIB2CMUT2zrJQjzDpdIpg/QGnq37w6ffsO0QhnF3C0pjpajXOtdr4yhCmyERBwk+rtJcfWy3gff8aVtAIkGb/0CDFa4mkFQLIPeZKgi4CFBPW2BIt7uXJVUOVoG913KBwD5J8abSgTe8nCDO5zG0I+cRFpWUuJYs4g6WEppu1DiaBTRgX0Ug+P3VNv17X9xN6vwjxmPzXzPh2jmUAE9feoNV9sVcIMuUi3DIk7ToHtwhS/xyaWcAbByQltQ3mPJMNO0IFB"

FORCE=0 KEEP_ZIP=0 ZIP="" GAME_LINK="${MW_GAME_URL:-}" MAPS_LINK="${MW_MAPS_URL:-}"
while (( $# )); do
  case "$1" in
    --bottle) BOTTLE="$2"; shift ;;
    --force) FORCE=1 ;;
    --keep-zip) KEEP_ZIP=1 ;;
    --zip) ZIP="$2"; KEEP_ZIP=1; shift ;;
    --game-url) GAME_LINK="$2"; shift ;;
    --maps-url) MAPS_LINK="$2"; shift ;;
    *) echo "unknown option: $1"; exit 1 ;;
  esac
  shift
done
BOTTLE_DIR="$BOTTLES/$BOTTLE"
GAME="$BOTTLE_DIR/$GAME_REL"

step() { print -P "\n%F{cyan}==> $1%f"; }
ok()   { print -P "    %F{green}✓%f $1"; }
warn() { print -P "    %F{yellow}!%f $1"; }
die()  { print -P "    %F{red}✗ $1%f"; exit 1; }

# a Google Drive share link becomes its direct download URL; other links are used as-is
download_url() {
  if [[ "$1" =~ '/d/([A-Za-z0-9_-]{20,})' ]] || [[ "$1" =~ '[?&]id=([A-Za-z0-9_-]{20,})' ]]; then
    print -r -- "https://drive.usercontent.google.com/download?id=${match[1]}&export=download&confirm=t"
  else
    print -r -- "$1"
  fi
}
size_of() { [[ -f "$1" ]] && stat -f%z "$1" || echo 0; }

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
    read -rs "pass?    Setup password (or Enter to paste a link instead): " < /dev/tty || return 1
    print > /dev/tty
    [[ -n "$pass" ]] || return 1
    plain=$(print -r -- "$LINKS_ENC" | PASS="$pass" openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -md sha256 -a -A -pass env:PASS 2>/dev/null) || plain=""
    [[ "$plain" == game=http* ]] && { print -r -- "$plain"; return 0; }
    warn "wrong password" > /dev/tty
  done
  return 1
}

# set a "seta key value" line in a .cfg file, appending it if missing
setcfg() {
  local key=$1 val=$2 file=$3
  if grep -q "^seta $key " "$file"; then
    sed -i '' "s|^seta $key .*|seta $key \"$val\"|" "$file"
  else
    echo "seta $key \"$val\"" >> "$file"
  fi
}

# set a "KEY" = "value" line in the bottle's [EnvironmentVariables] section
setenvvar() {
  local key=$1 val=$2 file=$3
  if grep -q "^\"$key\" = " "$file"; then
    sed -i '' "s|^\"$key\" = .*|\"$key\" = \"$val\"|" "$file"
  else
    sed -i '' "/^\[EnvironmentVariables\]/a\\
\"$key\" = \"$val\"
" "$file"
  fi
}

# ---------------------------------------------------------------- checks
step "Checking this Mac"
[[ "$(uname)" == "Darwin" ]] || die "this script is for macOS"

if [[ "$(uname -m)" == "arm64" ]]; then
  if arch -x86_64 /usr/bin/true 2>/dev/null; then
    ok "Rosetta 2 installed"
  else
    warn "CrossOver needs Rosetta 2, installing (you'll be asked to agree to its license)"
    softwareupdate --install-rosetta
  fi
fi

# A bottle carrying our marker was installed by a previous run: continue from there.
# A bottle without it belongs to the user: only replace it with --force.
INSTALLED=0
if [[ -d "$BOTTLE_DIR" ]] && (( ! FORCE )); then
  [[ -f "$BOTTLE_DIR/$MARK_INSTALLED" ]] \
    || die "a bottle named '$BOTTLE' already exists. Use --bottle <other-name>, or --force to replace it (the old one is kept as a backup)."
  INSTALLED=1
  ok "bottle '$BOTTLE' already installed by an earlier run, continuing"
fi

# ---------------------------------------------------------------- CrossOver
step "CrossOver"
if [[ -d /Applications/CrossOver.app ]]; then
  ok "already installed"
else
  if command -v brew >/dev/null; then
    brew install --cask crossover
  else
    # keep the download in ~/Downloads so an interrupted run can resume it
    cx_zip="$HOME/Downloads/${CROSSOVER_URL:t}"
    cx_size=$(curl -sIL "$CROSSOVER_URL" | awk 'tolower($1)=="content-length:" {s=$2} END {gsub("\r","",s); print s}')
    if [[ ! -f "$cx_zip" || "$(stat -f%z "$cx_zip")" != "$cx_size" ]]; then
      curl -fL -C - --retry 5 --progress-bar "$CROSSOVER_URL" -o "$cx_zip"
    fi
    ditto -x -k "$cx_zip" /Applications
    rm -f "$cx_zip"
  fi
  [[ -d /Applications/CrossOver.app ]] || die "CrossOver install failed"
  ok "installed"
  echo "    Opening CrossOver once so it can finish its first-run setup."
  echo "    Choose 'Try Now' (or register), wait for the main window, then come back here."
  open -a CrossOver
  read -r "?    Press Enter when CrossOver's main window is open... "
fi

# CrossOver can rewrite bottle settings while running, so quit it during setup
osascript -e 'quit app "CrossOver"' 2>/dev/null || true

if (( ! INSTALLED )); then
  # -------------------------------------------------------------- download
  step "Game bottle (mw.zip, ~16 GB)"

  if [[ -z "$ZIP" ]]; then
    # reuse a complete copy if one is lying around (a partial download has no zip index yet)
    for candidate in "$DOWNLOAD_ZIP" "$BOTTLES/mw.zip" "$PWD/mw.zip"; do
      if [[ -f "$candidate" ]] && unzip -l "$candidate" >/dev/null 2>&1; then
        ZIP="$candidate"
        [[ "$candidate" == "$DOWNLOAD_ZIP" ]] || KEEP_ZIP=1   # never delete a copy we didn't download
        break
      fi
    done
  fi

  # ask only when needed and there's a terminal to ask on; a file path works too
  # (drag mw.zip into the Terminal window)
  if [[ -z "$ZIP" && -z "$GAME_LINK" ]] && { : < /dev/tty; } 2>/dev/null; then
    if links=$(unlock_links); then
      GAME_LINK=$(sed -n 's/^game=//p' <<< "$links")
      [[ -n "$MAPS_LINK" ]] || MAPS_LINK=$(sed -n 's/^maps=//p' <<< "$links")
    else
      read -r "GAME_LINK?    Paste the game download link, or the path to mw.zip: " < /dev/tty || true
    fi
  fi
  GAME_LINK="${GAME_LINK//\\ / }"; GAME_LINK="${GAME_LINK% }"   # drag-and-drop escapes spaces, adds a space
  GAME_LINK="${GAME_LINK/#\~/$HOME}"
  if [[ -z "$ZIP" && -f "$GAME_LINK" ]]; then ZIP="$GAME_LINK"; KEEP_ZIP=1; fi

  if [[ -n "$ZIP" ]]; then
    [[ -f "$ZIP" ]] || die "zip not found: $ZIP"
    ok "using existing $ZIP"
  else
    [[ -n "$GAME_LINK" ]] || die "no download link given. Pass --game-url <link>, or put mw.zip in ~/Downloads"
    url=$(download_url "$GAME_LINK")
    # Google Drive answers with an HTML page instead of the file when its daily download
    # quota is used up ("Quota exceeded") or the link isn't shared
    head=$(curl -sIL --max-time 20 "$url" || true)
    remote_size=$(awk 'tolower($1)=="content-length:" {s=$2} END {gsub("\r","",s); print s}' <<< "$head")
    if grep -qi '^content-type: text/html' <<< "$head" || [[ -z "$remote_size" || "$remote_size" == "0" ]]; then
      die "the download was refused. With Google Drive that's usually 'Quota exceeded'
      (too many downloads today), or the link isn't shared. Try again later, or open
      the link in a browser, save mw.zip to ~/Downloads and re-run the script."
    fi
    ZIP="$DOWNLOAD_ZIP"
    # a partial file that is really an HTML error page can't be resumed
    [[ -f "$ZIP" ]] && [[ "$(head -c 1 "$ZIP")" == "<" ]] && rm -f "$ZIP"
    have=$(( $(size_of "$ZIP") + $(parts_size "$ZIP") ))
    need_gb=$(( (remote_size - have) / 1024 / 1024 / 1024 + 18 ))   # rest of download + extracted bottle
    free_gb=$(( $(df -k "$HOME" | awk 'NR==2 {print $4}') / 1024 / 1024 ))
    (( free_gb >= need_gb )) || die "need about ${need_gb} GB free disk space, only ${free_gb} GB available"
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

  # -------------------------------------------------------------- install bottle
  step "Installing bottle"
  mkdir -p "$BOTTLES"
  rm -rf "$BOTTLES"/.setup-*(N)   # leftovers from an interrupted extract
  free_gb=$(( $(df -k "$HOME" | awk 'NR==2 {print $4}') / 1024 / 1024 ))
  (( free_gb >= 18 )) || die "need about 18 GB free disk space to extract, only ${free_gb} GB available"
  if [[ -d "$BOTTLE_DIR" ]]; then
    backup="$BOTTLE_DIR.backup-$(date +%Y%m%d-%H%M%S)"
    mv "$BOTTLE_DIR" "$backup"
    warn "old bottle moved to: $backup"
  fi
  echo "    Extracting (takes a few minutes)..."
  # extract next to the bottles (same disk, so the final move is instant), then rename;
  # the bottle only appears under its real name once extraction fully succeeded
  tmp="$BOTTLES/.setup-$$"
  trap 'rm -rf "$tmp"' EXIT
  trap 'exit 130' INT TERM   # make the EXIT cleanup run on Ctrl+C / kill too
  mkdir "$tmp"
  ditto -x -k "$ZIP" "$tmp"
  rm -rf "$tmp/__MACOSX"
  src=$(find "$tmp" -mindepth 1 -maxdepth 1 -type d | head -1)
  [[ -n "$src" && -d "$src/$GAME_REL" ]] || die "zip does not contain a bottle with MW2 installed"
  mv "$src" "$BOTTLE_DIR"
  # the zip's menu list has the original bottle name and paths baked in, so
  # CrossOver shows no apps under another name: rebuild it for this bottle
  rm -f "$BOTTLE_DIR/desktopdata/cxmenu/cxmenu_macosx.plist"
  "${WINE:h}/cxmenu" --bottle "$BOTTLE" --sync --mode install >/dev/null 2>&1 || true
  "${WINE:h}/cxmenu" --bottle "$BOTTLE" --install >/dev/null 2>&1 || true
  touch "$BOTTLE_DIR/$MARK_INSTALLED"
  ok "installed to $BOTTLE_DIR"
  (( KEEP_ZIP )) || { rm -f "$ZIP"; ok "removed mw.zip"; }
fi

# ---------------------------------------------------------------- configure
step "Configuring"
if [[ -f "$BOTTLE_DIR/$MARK_CONFIGURED" ]]; then
  # don't wipe the identity or graphics choices of a bottle that's already in use
  ok "already configured by an earlier run, keeping current settings"
else

# Fresh identity: the bottle is shared between Macs, and two players with the
# same guid.dat kick each other off servers. IW4x creates a new random one.
# players/ holds the copied profile, stats and the (mm) client identity.
rm -f "$BOTTLE_DIR/drive_c/users/crossover/AppData/Local/iw4x/guid.dat"
rm -rf "$GAME/players"
ok "removed copied identity (guid.dat) and profile (players/), fresh ones are created on first start"

# Bottle: Auto graphics backend (D3DMetal stutters with this DX9 game), MSync on,
# DLSS/MetalFX off (MW2 has no DLSS)
conf="$BOTTLE_DIR/cxbottle.conf"
setenvvar CX_GRAPHICS_BACKEND "" "$conf"
setenvvar WINEMSYNC 1 "$conf"
setenvvar D3DM_ENABLE_METALFX 0 "$conf"
setenvvar DXMT_ENABLE_NVEXT 0 "$conf"
# High Resolution Mode off: renders at Retina resolution (4x the pixels) when on
sed -i '' '/"RetinaMode"=/d' "$BOTTLE_DIR/user.reg"
ok "CrossOver bottle: graphics Auto, MSync on, DLSS off, High Resolution Mode off"

# Fullscreen at this Mac's "looks like" resolution (not Retina, 4x cheaper)
res=$(osascript -e 'tell application "Finder" to get bounds of window of desktop' 2>/dev/null \
  | awk -F', ' '{print $3 "x" $4}')
if [[ ! "$res" =~ ^[0-9]+x[0-9]+$ ]]; then
  # fallback: physical resolution, halved on Retina panels
  res=$(system_profiler SPDisplaysDataType 2>/dev/null | awk '/Resolution:/ {
    w=$2; h=$4; if ($0 ~ /Retina/) { w/=2; h/=2 } print w "x" h; exit }')
fi
[[ "$res" =~ ^[0-9]+x[0-9]+$ ]] || res="1280x800"
cfg="$GAME/players/iw4x_config.cfg"
mkdir -p "$GAME/players"
touch "$cfg"
setcfg r_fullscreen 1 "$cfg"
setcfg r_noborder 0 "$cfg"
setcfg r_mode "$res" "$cfg"
setcfg vid_xpos 0 "$cfg"
setcfg vid_ypos 0 "$cfg"
ok "fullscreen at $res"

touch "$BOTTLE_DIR/$MARK_CONFIGURED"
fi

# Shared game settings (lowest graphics, no hitches when hit). Loaded on every start via
# "+exec client_tweaks.cfg", so they also cover settings the game itself never saves.
# BEGIN client.cfg (generated from config/client.cfg by scripts/tools/sync-config.py, don't edit here)
CLIENT_CFG=$(cat <<'CFG'
// Game settings for every player, applied on each game start (macOS and Windows).
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
CFG
)
# END client.cfg
print -r -- "$CLIENT_CFG" > "$GAME/main/client_tweaks.cfg"
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
print -r -- "$CLASSES_CFG" > "$GAME/main/classes.cfg"
ok "ready-made classes installed (load them: F9 during a match, or ~ then exec classes.cfg)"

# ---------------------------------------------------------------- custom maps + bots
# Separate pack, also installable on its own with install-maps.sh. The local copy is
# used when running from the repo, otherwise it's fetched from GitHub.
maps_script="${0:A:h}/install-maps.sh"
if [[ -f "$maps_script" ]]; then
  bash "$maps_script" --bottle "$BOTTLE" ${MAPS_LINK:+--maps-url "$MAPS_LINK"} || warn "custom maps not installed, run scripts/mac/install-maps.sh later"
else
  bash -c "$(curl -fsSL https://raw.githubusercontent.com/dorostanian/iw4x-friends/main/scripts/mac/install-maps.sh)" install-maps --bottle "$BOTTLE" ${MAPS_LINK:+--maps-url "$MAPS_LINK"} \
    || warn "custom maps not installed. Later, run: bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/dorostanian/iw4x-friends/main/scripts/mac/install-maps.sh)\""
fi

# ---------------------------------------------------------------- launcher
step "Desktop launcher"
launcher="$HOME/Desktop/IW4x.command"
[[ "$BOTTLE" == "mw" ]] || launcher="$HOME/Desktop/IW4x ($BOTTLE).command"
cat > "$launcher" <<EOF
#!/bin/zsh
# Start IW4x, skipping the launcher's GitHub update check (it can hang under CrossOver)
cd "$GAME"
exec "$WINE" --bottle "$BOTTLE" --cx-app iw4x-launcher.exe \\
  --arch x86 --skip-remote --no-self-update --no-shortcuts --no-connect-protocol \\
  --game-args "+exec client_tweaks.cfg"
EOF
chmod +x "$launcher"
ok "created $launcher"

# ---------------------------------------------------------------- done
step "Done"
cat <<EOF
    Start the game:   double-click "${launcher:t:r}" on your Desktop
                      (first time: right-click > Open if macOS blocks it)

    Join a LAN game:  Server Browser > LAN tab,
                      or press ~ and type:  connect <server-ip>:28960

    Graphics are set to the lowest preset. Raise them in Options if it runs well.
EOF

read -r "start?    Start IW4x now? [Y/n] " || start=n
[[ "$start" =~ ^[Nn] ]] || open "$launcher"
