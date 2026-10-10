<#
One-shot setup of MW2 + IW4x on a Windows PC:
  1. finds or downloads the prepared game package (mw.zip) from Google Drive
  2. installs only the game folder from it (no CrossOver needed on Windows)
  3. installs the DirectX 9 runtime if missing
  4. configures the game: fresh profile, fullscreen at native resolution, shared game
     settings from config/client.cfg (lowest graphics, no FPS drops when hit)
  5. installs the custom maps + bots pack (install-maps.ps1)
  6. creates a Desktop shortcut that skips IW4x's remote update check

Run it straight from GitHub, in PowerShell:
  & ([scriptblock]::Create((irm https://raw.githubusercontent.com/dorostanian/iw4x-lan-server/main/scripts/setup-windows.ps1)))
or as a downloaded file:
  powershell -ExecutionPolicy Bypass -File setup-windows.ps1

Safe to re-run: every step skips what is already done, and an interrupted
download resumes where it stopped.

Options:
  -InstallDir <path>  where to install (default: C:\Games\Call of Duty Modern Warfare 2)
  -GameUrl <link>     download link of mw.zip (a Google Drive share link works); also
                      MW_GAME_URL. When a download is needed and it's not given, it asks for
                      the setup password (decrypts the links below) or the link itself
  -MapsUrl <link>     same for the custom maps + bots pack (MW_MAPS_URL)
  -Zip <path>         use this mw.zip (otherwise it looks in Downloads and the current folder)
  -KeepZip            keep mw.zip after installing (default: delete it if this script downloaded it)
  -Force              reinstall even if the folder exists (old one is renamed, not deleted)
#>
param(
    [string]$InstallDir = "C:\Games\Call of Duty Modern Warfare 2",
    [string]$Zip = "",
    [string]$GameUrl = $env:MW_GAME_URL,
    [string]$MapsUrl = $env:MW_MAPS_URL,
    [switch]$KeepZip,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$DxUrl = "https://download.microsoft.com/download/1/7/1/1718CCC4-6315-4D8E-9543-8E28A4E18C4C/dxwebsetup.exe"
$GamePrefix = "drive_c/Program Files (x86)/Call of Duty Modern Warfare 2/"
$DownloadZip = Join-Path $HOME "Downloads\mw.zip"
$MarkInstalled = ".iw4x-setup-installed"
$MarkConfigured = ".iw4x-setup-configured"
# download links, encrypted with the setup password (written by `task links`)
$LinksEnc = "U2FsdGVkX19z1JucWZqUi9mbrydBrz7IZBKu1HjwaeSCQDgD/3GuECrT/uzIB2CMUT2zrJQjzDpdIpg/QGnq37w6ffsO0QhnF3C0pjpajXOtdr4yhCmyERBwk+rtJcfWy3gff8aVtAIkGb/0CDFa4mkFQLIPeZKgi4CFBPW2BIt7uXJVUOVoG913KBwD5J8abSgTe8nCDO5zG0I+cRFpWUuJYs4g6WEppu1DiaBTRgX0Ug+P3VNv17X9xN6vwjxmPzXzPh2jmUAE9feoNV9sVcIMuUi3DIk7ToHtwhS/xyaWcAbByQltQ3mPJMNO0IFB"

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Ok($msg)   { Write-Host "    + $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "    ! $msg" -ForegroundColor Yellow }
# throw instead of exit: when run as a one-liner, exit would close the user's PowerShell window
function Die($msg)  { Write-Host "    x $msg" -ForegroundColor Red; throw "Setup stopped, see the message above." }

function FreeGB($path) {
    $root = [IO.Path]::GetPathRoot([IO.Path]::GetFullPath($path))
    [math]::Floor((Get-PSDrive -Name $root.Substring(0, 1)).Free / 1GB)
}

# A Google Drive share link becomes its direct download URL; other links are used as-is.
function Get-DownloadUrl($link) {
    if ($link -match '/d/([A-Za-z0-9_-]{20,})' -or $link -match '[?&]id=([A-Za-z0-9_-]{20,})') {
        return "https://drive.usercontent.google.com/download?id=$($Matches[1])&export=download&confirm=t"
    }
    return $link
}

# Ask for the setup password and return the decrypted links as @{ game; maps }. Returns
# nothing when there are none, on Enter (paste a link instead) or after 3 wrong tries.
# Same format as `openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -md sha256`.
function Unlock-Links {
    if (-not $LinksEnc) { return }
    $data = [Convert]::FromBase64String($LinksEnc)   # "Salted__", 8-byte salt, ciphertext
    for ($try = 0; $try -lt 3; $try++) {
        $secure = Read-Host "    Setup password (or Enter to paste a link instead)" -AsSecureString
        $pass = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
        if (-not $pass) { return }
        try {
            $kdf = New-Object Security.Cryptography.Rfc2898DeriveBytes(([Text.Encoding]::UTF8.GetBytes($pass)), ([byte[]]$data[8..15]), 200000, ([Security.Cryptography.HashAlgorithmName]::SHA256))
            $keyIv = $kdf.GetBytes(48)
            $aes = [Security.Cryptography.Aes]::Create()
            $aes.Key = [byte[]]$keyIv[0..31]; $aes.IV = [byte[]]$keyIv[32..47]
            $plain = [Text.Encoding]::UTF8.GetString($aes.CreateDecryptor().TransformFinalBlock($data, 16, $data.Length - 16))
            $links = @{}
            foreach ($line in $plain -split "`n") { if ($line -match '^(\w+)=(\S+)') { $links[$Matches[1]] = $Matches[2] } }
            if ($links.game -like "http*") { return $links }
        } catch {}
        Write-Host "    ! wrong password" -ForegroundColor Yellow
    }
}

# Size of the file behind $url, or "" when the server answers with a web page instead
# (Google Drive does that when its daily quota is used up or the link isn't shared).
function Get-RemoteSize($url) {
    $head = (& curl.exe -sIL --max-time 20 $url) -join "`n"
    if ($head -match '(?im)^content-type:\s*text/html') { return "" }
    $lengths = [regex]::Matches($head, '(?im)^content-length:\s*(\d+)')
    if ($lengths.Count -and $lengths[$lengths.Count - 1].Groups[1].Value -ne "0") { return $lengths[$lengths.Count - 1].Groups[1].Value }
    return ""
}

function Remove-HtmlPartial($path) {
    if ((Test-Path $path) -and (Get-Item $path).Length -gt 0) {
        $fs = [IO.File]::OpenRead($path); $first = $fs.ReadByte(); $fs.Dispose()
        if ($first -eq 60) { Remove-Item $path }   # "<": an error page, not the zip
    }
}

$Refused = ("the download was refused. With Google Drive that's usually 'Quota exceeded'`n" +
            "      (too many downloads today), or the link isn't shared. Try again later, or open`n" +
            "      the link in a browser, save the file to your Downloads folder and run this again.")

function SizeOf($path) { if (Test-Path $path) { (Get-Item $path).Length } else { 0 } }

# Download $url ($size bytes) to $out over 8 connections at once: S3 serves each one at
# only ~13 MB/s. Parts are kept in "$out.parts" so a re-run resumes them, then joined.
function Get-Parallel($url, [int64]$size, $out) {
    $n = 8; $chunk = [int64][math]::Ceiling($size / $n)
    New-Item -ItemType Directory -Force -Path "$out.parts" | Out-Null
    $parts = 0..($n - 1) | ForEach-Object { Join-Path "$out.parts" $_ }
    # curl -o overwrites, so each round downloads into part.new and appends it afterwards
    $merge = {
        foreach ($p in $parts) {
            if (-not (Test-Path "$p.new")) { continue }
            $dst = [IO.File]::Open($p, "Append"); $src = [IO.File]::OpenRead("$p.new")
            $src.CopyTo($dst); $src.Dispose(); $dst.Dispose(); Remove-Item "$p.new"
        }
    }
    for ($round = 0; $round -lt 5; $round++) {
        & $merge
        $procs = @()
        for ($i = 0; $i -lt $n; $i++) {
            $start = $i * $chunk + (SizeOf $parts[$i]); $last = [math]::Min(($i + 1) * $chunk, $size) - 1
            if ($start -gt $last) { continue }
            # a stalled connection gives up after 30s, the next round picks up where it stopped
            $procs += Start-Process curl.exe -NoNewWindow -PassThru -ArgumentList @(
                "-sfL", "--speed-limit", "1000", "--speed-time", "30", "-r", "$start-$last", "-o", "`"$($parts[$i]).new`"", "`"$url`"")
        }
        if (-not $procs) { break }
        do {
            Start-Sleep 2
            $got = ($parts | ForEach-Object { (SizeOf $_) + (SizeOf "$_.new") } | Measure-Object -Sum).Sum
            Write-Host -NoNewline "`r    $([math]::Floor($got / 1MB)) of $([math]::Floor($size / 1MB)) MB"
        } while ($procs | Where-Object { -not $_.HasExited })
        Write-Host ""
    }
    & $merge
    if (($parts | ForEach-Object { SizeOf $_ } | Measure-Object -Sum).Sum -ne $size) { return $false }
    $dst = [IO.File]::Create($out)
    foreach ($p in $parts) { $src = [IO.File]::OpenRead($p); $src.CopyTo($dst); $src.Dispose(); Remove-Item $p }
    $dst.Dispose(); Remove-Item "$out.parts"
    return $true
}

# A zip whose central directory can be read is complete; a partial download isn't.
function Test-ZipComplete($path) {
    try { [IO.Compression.ZipFile]::OpenRead($path).Dispose(); $true } catch { $false }
}

# Set a "seta key value" line in a .cfg file, appending it if missing.
function Set-Cfg($file, $key, $value) {
    $line = "seta $key `"$value`""
    $lines = @()
    if (Test-Path $file) { $lines = @(Get-Content $file) }
    $found = $false
    for ($n = 0; $n -lt $lines.Count; $n++) {
        if ($lines[$n] -match "^seta $key ") { $lines[$n] = $line; $found = $true }
    }
    if (-not $found) { $lines += $line }
    Set-Content -Path $file -Value $lines -Encoding ascii
}

Add-Type -AssemblyName System.IO.Compression.FileSystem

# ---------------------------------------------------------------- checks
Step "Checking this PC"
if (-not [Environment]::Is64BitOperatingSystem) { Warn "32-bit Windows: the game may still run, but it's untested" }
if (-not (Get-Command curl.exe -ErrorAction SilentlyContinue)) { Die "curl.exe not found (it ships with Windows 10 1803 and later)" }

# A folder carrying our marker was installed by a previous run: continue from there.
# A folder without it belongs to the user: only replace it with -Force.
$Installed = $false
if ((Test-Path $InstallDir) -and -not $Force) {
    if (-not (Test-Path (Join-Path $InstallDir $MarkInstalled))) {
        Die "'$InstallDir' already exists. Use -InstallDir <other path>, or -Force to replace it (the old one is kept as a backup)."
    }
    $Installed = $true
    Ok "game already installed by an earlier run, continuing"
}

if (-not $Installed) {
    # -------------------------------------------------------------- download
    Step "Game package (mw.zip, ~16 GB)"
    if (-not $Zip) {
        # reuse a complete copy if one is lying around (a partial download has no zip index yet)
        foreach ($candidate in @($DownloadZip, (Join-Path $PWD "mw.zip"))) {
            if ((Test-Path $candidate) -and (Test-ZipComplete $candidate)) {
                $Zip = $candidate
                if ($candidate -ne $DownloadZip) { $KeepZip = $true }   # never delete a copy we didn't download
                break
            }
        }
    } else {
        $KeepZip = $true
    }

    # a file path works too (drag mw.zip into the PowerShell window)
    if (-not $Zip -and -not $GameUrl) {
        $links = Unlock-Links
        if ($links) { $GameUrl = $links.game; if (-not $MapsUrl) { $MapsUrl = $links.maps } }
        else { $GameUrl = (Read-Host "    Paste the game download link, or the path to mw.zip").Trim().Trim('"') }
    }
    if (-not $Zip -and $GameUrl -and (Test-Path -LiteralPath $GameUrl -PathType Leaf)) { $Zip = $GameUrl; $KeepZip = $true }

    if ($Zip) {
        if (-not (Test-Path $Zip)) { Die "zip not found: $Zip" }
        Ok "using existing $Zip"
    } else {
        if (-not $GameUrl) { Die "no download link given. Pass -GameUrl <link>, or put mw.zip in your Downloads folder" }
        $url = Get-DownloadUrl $GameUrl
        $remoteSize = Get-RemoteSize $url
        if (-not $remoteSize) { Die $Refused }
        $Zip = $DownloadZip
        Remove-HtmlPartial $Zip
        $have = (SizeOf $Zip) + ((Get-ChildItem "$Zip.parts" -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum)
        $needGB = [math]::Ceiling(([int64]$remoteSize - $have) / 1GB) + 18
        if ((FreeGB $Zip) -lt $needGB) { Die "need about $needGB GB free on $([IO.Path]::GetPathRoot($Zip)), only $(FreeGB $Zip) GB available" }
        if ($have -gt 0) { Write-Host "    Resuming download ($([math]::Floor($have / 1MB)) MB of $([math]::Floor([int64]$remoteSize / 1MB)) MB done)" }
        else { Write-Host "    Downloading to $Zip" }
        Write-Host "    (if it stops, just re-run the script and it continues)"
        New-Item -ItemType Directory -Force -Path (Split-Path $Zip) | Out-Null
        if ((& curl.exe -sIL --max-time 20 $url) -match '^accept-ranges:\s*bytes') {
            if (-not (Get-Parallel $url $remoteSize $Zip)) { Die "download incomplete, re-run to resume" }
        } else {
            & curl.exe -fL -C - --retry 5 --retry-delay 5 --progress-bar -o $Zip $url
        }
        if ("$((Get-Item $Zip).Length)" -ne $remoteSize) { Die "download incomplete, re-run to resume" }
        Ok "downloaded"
    }

    # -------------------------------------------------------------- install game folder
    Step "Installing game"
    $parent = Split-Path $InstallDir
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    if ((FreeGB $parent) -lt 18) { Die "need about 18 GB free on $([IO.Path]::GetPathRoot($parent)) to extract" }
    $tmp = "$InstallDir.setup-tmp"
    if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }   # leftover from an interrupted extract
    if (Test-Path $InstallDir) {
        $backup = "$InstallDir.backup-$(Get-Date -Format yyyyMMdd-HHmmss)"
        Rename-Item $InstallDir $backup
        Warn "old folder moved to: $backup"
    }

    # The zip holds a whole CrossOver bottle; only the MW2 folder inside it is needed.
    Write-Host "    Extracting (takes a few minutes)..."
    $archive = [IO.Compression.ZipFile]::OpenRead($Zip)
    try {
        $entries = $archive.Entries | Where-Object { $_.FullName -notlike "__MACOSX/*" -and $_.FullName -match "^[^/]+/$([regex]::Escape($GamePrefix))" }
        if (-not $entries) { Die "zip does not contain the MW2 game folder" }
        $i = 0
        foreach ($entry in $entries) {
            $rel = $entry.FullName -replace "^[^/]+/$([regex]::Escape($GamePrefix))", ""
            if (-not $rel) { continue }
            $dest = Join-Path $tmp ($rel -replace "/", "\")
            if ($entry.FullName.EndsWith("/")) { New-Item -ItemType Directory -Force -Path $dest | Out-Null; continue }
            New-Item -ItemType Directory -Force -Path (Split-Path $dest) | Out-Null
            [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $dest, $true)
            $i++
            if ($i % 500 -eq 0) { Write-Host "    $i files..." }
        }
    } finally {
        $archive.Dispose()
    }
    # the folder only appears under its real name once extraction fully succeeded
    Rename-Item $tmp (Split-Path $InstallDir -Leaf)
    New-Item -ItemType File -Path (Join-Path $InstallDir $MarkInstalled) | Out-Null
    Ok "installed to $InstallDir"
    if (-not $KeepZip) { Remove-Item $Zip; Ok "removed mw.zip" }
}

# ---------------------------------------------------------------- DirectX
Step "DirectX 9 runtime"
# IW4x needs d3dx9_43.dll (June 2010 runtime), which Windows 10/11 don't include
if (Test-Path "$env:WINDIR\SysWOW64\d3dx9_43.dll") {
    Ok "already installed"
} else {
    $dx = Join-Path $env:TEMP "dxwebsetup.exe"
    & curl.exe -fsSL -o $dx $DxUrl
    Write-Host "    Installing (Windows will ask for permission)..."
    Start-Process -FilePath $dx -ArgumentList "/Q" -Verb RunAs -Wait
    if (Test-Path "$env:WINDIR\SysWOW64\d3dx9_43.dll") { Ok "installed" }
    else { Warn "DirectX runtime still missing. Install it manually from: $DxUrl" }
}

# ---------------------------------------------------------------- configure
Step "Configuring"
$game = $InstallDir
if (Test-Path (Join-Path $game $MarkConfigured)) {
    # don't wipe the profile or graphics choices of an install that's already in use
    Ok "already configured by an earlier run, keeping current settings"
} else {
    # players\ holds the copied profile and stats from the machine the package was made on.
    # (The player identity lives in %LOCALAPPDATA%\iw4x\guid.dat, which is per PC already.)
    Remove-Item -Recurse -Force (Join-Path $game "players") -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path (Join-Path $game "players") | Out-Null
    Ok "removed copied profile (players\), a fresh one is created on first start"

    $cfg = Join-Path $game "players\iw4x_config.cfg"
    $vc = Get-CimInstance Win32_VideoController | Where-Object CurrentHorizontalResolution | Select-Object -First 1
    $res = if ($vc) { "$($vc.CurrentHorizontalResolution)x$($vc.CurrentVerticalResolution)" } else { "1280x720" }
    foreach ($kv in @{ r_fullscreen = 1; r_noborder = 0; r_mode = $res; vid_xpos = 0; vid_ypos = 0 }.GetEnumerator()) {
        Set-Cfg $cfg $kv.Key $kv.Value
    }
    Ok "fullscreen at $res"

    New-Item -ItemType File -Force -Path (Join-Path $game $MarkConfigured) | Out-Null
}

# Shared game settings (lowest graphics, no hitches when hit). Loaded on every start via
# "+exec client_tweaks.cfg", so they also cover settings the game itself never saves.
# BEGIN client.cfg (generated from config/client.cfg by scripts/sync-config.py, don't edit here)
$ClientCfg = @'
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
'@
# END client.cfg
Set-Content -Path (Join-Path $game "main\client_tweaks.cfg") -Value $ClientCfg -Encoding ascii
Ok "game settings installed (lowest graphics, no FPS drops when hit)"

# Ready-made classes, loaded with F9 during a match (bound in client.cfg) or exec classes.cfg
# BEGIN classes.cfg (generated from config/classes.cfg by scripts/sync-config.py, don't edit here)
$ClassesCfg = @'
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
'@
# END classes.cfg
Set-Content -Path (Join-Path $game "main\classes.cfg") -Value $ClassesCfg -Encoding ascii
Ok "ready-made classes installed (load them: F9 during a match, or ~ then exec classes.cfg)"

# ---------------------------------------------------------------- custom maps + bots
# Separate pack, also installable on its own with install-maps.ps1. The local copy is
# used when running from the repo, otherwise it's fetched from GitHub.
$mapsScript = if ($PSCommandPath) { Join-Path (Split-Path $PSCommandPath) "install-maps.ps1" } else { "" }
try {
    if ($mapsScript -and (Test-Path $mapsScript)) { & $mapsScript -InstallDir $game -MapsUrl $MapsUrl }
    else { & ([scriptblock]::Create((irm https://raw.githubusercontent.com/dorostanian/iw4x-lan-server/main/scripts/install-maps.ps1))) -InstallDir $game -MapsUrl $MapsUrl }
} catch {
    Warn "custom maps not installed. Later, run: & ([scriptblock]::Create((irm https://raw.githubusercontent.com/dorostanian/iw4x-lan-server/main/scripts/install-maps.ps1)))"
}

# ---------------------------------------------------------------- shortcut
Step "Desktop shortcut"
$lnk = Join-Path ([Environment]::GetFolderPath("Desktop")) "IW4x.lnk"
$shell = New-Object -ComObject WScript.Shell
$sc = $shell.CreateShortcut($lnk)
$sc.TargetPath = Join-Path $game "iw4x-launcher.exe"
# skip the GitHub update check (it can hang); run the launcher without these flags to update
$sc.Arguments = '--arch x86 --skip-remote --no-self-update --no-shortcuts --no-connect-protocol --game-args "+exec client_tweaks.cfg"'
$sc.WorkingDirectory = $game
$sc.IconLocation = Join-Path $game "iw4x.exe"
$sc.Save()
Ok "created $lnk"

# ---------------------------------------------------------------- done
Step "Done"
Write-Host @"
    Start the game:   double-click "IW4x" on your Desktop
                      (allow it through Windows Firewall if asked)

    Join a LAN game:  Server Browser > LAN tab,
                      or press ~ and type:  connect <server-ip>:28960

    Graphics are set to the lowest preset. Raise them in Options if it runs well.
"@
$start = Read-Host "    Start IW4x now? [Y/n]"
if ($start -notmatch '^[Nn]') { Start-Process $lnk }
