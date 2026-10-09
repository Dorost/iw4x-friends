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
#   zsh -c "$(curl -fsSL https://raw.githubusercontent.com/dorostanian/iw4x-lan-server/main/scripts/setup-mac.sh)"
# or as a downloaded file:   zsh setup-mac.sh
# Safe to re-run: every step skips what is already done, and an interrupted
# download resumes where it stopped.
# Options:
#   --bottle <name>  bottle name to install as (default: mw)
#   --force          reinstall even if the bottle exists (old one is renamed, not deleted)
#   --zip <path>     use this mw.zip (otherwise it looks in ~/Downloads, the Bottles
#                    folder and the current folder before downloading)
#   --keep-zip       keep mw.zip after installing (default: delete it if this script downloaded it)

set -euo pipefail

DRIVE_ID="REDACTED"
DRIVE_URL="https://drive.usercontent.google.com/download?id=${DRIVE_ID}&export=download&confirm=t"
CROSSOVER_URL="https://media.codeweavers.com/pub/crossover/cxmac/demo/crossover-26.3.0.zip"
BOTTLE="mw"
BOTTLES="$HOME/Library/Application Support/CrossOver/Bottles"
GAME_REL="drive_c/Program Files (x86)/Call of Duty Modern Warfare 2"
WINE="/Applications/CrossOver.app/Contents/SharedSupport/CrossOver/bin/wine"
DOWNLOAD_ZIP="$HOME/Downloads/mw.zip"
MARK_INSTALLED=".iw4x-setup-installed"
MARK_CONFIGURED=".iw4x-setup-configured"

FORCE=0 KEEP_ZIP=0 ZIP=""
while (( $# )); do
  case "$1" in
    --bottle) BOTTLE="$2"; shift ;;
    --force) FORCE=1 ;;
    --keep-zip) KEEP_ZIP=1 ;;
    --zip) ZIP="$2"; KEEP_ZIP=1; shift ;;
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
  # Drive answers with an HTML page instead of the file when the share's download
  # quota is used up ("Quota exceeded") or the link stopped working
  head=$(curl -sIL --max-time 20 "$DRIVE_URL" || true)
  remote_size=$(awk 'tolower($1)=="content-length:" {s=$2} END {gsub("\r","",s); print s}' <<< "$head")
  drive_blocked=0
  if grep -qi '^content-type: text/html' <<< "$head" || [[ "$remote_size" == "0" ]]; then
    drive_blocked=1 remote_size=""
  fi
  size_of() { [[ -f "$1" ]] && stat -f%z "$1" || echo 0; }

  if [[ -z "$ZIP" ]]; then
    # reuse a complete copy if one is lying around
    for candidate in "$DOWNLOAD_ZIP" "$BOTTLES/mw.zip" "$PWD/mw.zip"; do
      [[ -f "$candidate" ]] || continue
      # complete = same size as on Drive, or (size unknown) a readable zip index,
      # which a partial download doesn't have yet
      if [[ -n "$remote_size" && "$(size_of "$candidate")" == "$remote_size" ]] \
         || [[ -z "$remote_size" ]] && unzip -l "$candidate" >/dev/null 2>&1; then
        ZIP="$candidate"
        [[ "$candidate" == "$DOWNLOAD_ZIP" ]] || KEEP_ZIP=1   # never delete a copy we didn't download
        break
      fi
    done
  fi

  if [[ -n "$ZIP" ]]; then
    [[ -f "$ZIP" ]] || die "zip not found: $ZIP"
    ok "using existing $ZIP"
  else
    ZIP="$DOWNLOAD_ZIP"
    # a partial file that is really an HTML error page can't be resumed
    [[ -f "$ZIP" ]] && [[ "$(head -c 1 "$ZIP")" == "<" ]] && rm -f "$ZIP"
    if (( drive_blocked )); then
      die "Google Drive refused the download (usually 'Quota exceeded': too many downloads of this file today).
      Try again later, or open this link in a browser while logged in to Google,
      save mw.zip to ~/Downloads and re-run the script (it picks it up automatically):
      https://drive.google.com/file/d/$DRIVE_ID/view"
    elif [[ -z "$remote_size" ]]; then
      [[ -f "$ZIP" ]] || die "can't reach Google Drive and no mw.zip found. Check the connection, or pass --zip <path>."
      warn "can't reach Google Drive to check the size, using $ZIP as is"
    else
      have=$(size_of "$ZIP")
      need_gb=$(( (remote_size - have) / 1024 / 1024 / 1024 + 18 ))   # rest of download + extracted bottle
      free_gb=$(( $(df -k "$HOME" | awk 'NR==2 {print $4}') / 1024 / 1024 ))
      (( free_gb >= need_gb )) || die "need about ${need_gb} GB free disk space, only ${free_gb} GB available"
      (( have > 0 )) && echo "    Resuming download ($(( have / 1024 / 1024 )) MB of $(( remote_size / 1024 / 1024 )) MB done)" \
                     || echo "    Downloading to $ZIP"
      echo "    (if it stops, just re-run the script and it continues)"
      curl -fL -C - --retry 5 --retry-delay 5 --progress-bar "$DRIVE_URL" -o "$ZIP"
      [[ "$(size_of "$ZIP")" == "$remote_size" ]] || die "download incomplete, re-run to resume"
      ok "downloaded"
    fi
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
# BEGIN client.cfg (generated from config/client.cfg by scripts/sync-config.py, don't edit here)
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
CFG
)
# END client.cfg
print -r -- "$CLIENT_CFG" > "$GAME/main/client_tweaks.cfg"
ok "game settings installed (lowest graphics, no FPS drops when hit)"

# ---------------------------------------------------------------- custom maps + bots
# Separate pack, also installable on its own with install-maps.sh. The local copy is
# used when running from the repo, otherwise it's fetched from GitHub.
maps_script="${0:A:h}/install-maps.sh"
if [[ -f "$maps_script" ]]; then
  bash "$maps_script" --bottle "$BOTTLE" || warn "custom maps not installed, run scripts/install-maps.sh later"
else
  bash -c "$(curl -fsSL https://raw.githubusercontent.com/dorostanian/iw4x-lan-server/main/scripts/install-maps.sh)" install-maps --bottle "$BOTTLE" \
    || warn "custom maps not installed. Later, run: bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/dorostanian/iw4x-lan-server/main/scripts/install-maps.sh)\""
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
