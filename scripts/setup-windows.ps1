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
  -Zip <path>         use this mw.zip (otherwise it looks in Downloads and the current folder)
  -KeepZip            keep mw.zip after installing (default: delete it if this script downloaded it)
  -Force              reinstall even if the folder exists (old one is renamed, not deleted)
#>
param(
    [string]$InstallDir = "C:\Games\Call of Duty Modern Warfare 2",
    [string]$Zip = "",
    [switch]$KeepZip,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$DriveId = "REDACTED"
$DriveUrl = "https://drive.usercontent.google.com/download?id=$DriveId&export=download&confirm=t"
$DxUrl = "https://download.microsoft.com/download/1/7/1/1718CCC4-6315-4D8E-9543-8E28A4E18C4C/dxwebsetup.exe"
$GamePrefix = "drive_c/Program Files (x86)/Call of Duty Modern Warfare 2/"
$DownloadZip = Join-Path $HOME "Downloads\mw.zip"
$MarkInstalled = ".iw4x-setup-installed"
$MarkConfigured = ".iw4x-setup-configured"

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Ok($msg)   { Write-Host "    + $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "    ! $msg" -ForegroundColor Yellow }
# throw instead of exit: when run as a one-liner, exit would close the user's PowerShell window
function Die($msg)  { Write-Host "    x $msg" -ForegroundColor Red; throw "Setup stopped, see the message above." }

function FreeGB($path) {
    $root = [IO.Path]::GetPathRoot([IO.Path]::GetFullPath($path))
    [math]::Floor((Get-PSDrive -Name $root.Substring(0, 1)).Free / 1GB)
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
    # Drive answers with an HTML page instead of the file when the share's download
    # quota is used up ("Quota exceeded") or the link stopped working
    $head = (& curl.exe -sIL --max-time 20 $DriveUrl) -join "`n"
    $lengths = [regex]::Matches($head, '(?im)^content-length:\s*(\d+)')
    $remoteSize = if ($lengths.Count) { $lengths[$lengths.Count - 1].Groups[1].Value } else { "" }
    $driveBlocked = ($head -match '(?im)^content-type:\s*text/html') -or ($remoteSize -eq "0")
    if ($driveBlocked) { $remoteSize = "" }

    if (-not $Zip) {
        foreach ($candidate in @($DownloadZip, (Join-Path $PWD "mw.zip"))) {
            if (-not (Test-Path $candidate)) { continue }
            $size = (Get-Item $candidate).Length
            if (($remoteSize -and "$size" -eq $remoteSize) -or (-not $remoteSize -and (Test-ZipComplete $candidate))) {
                $Zip = $candidate
                if ($candidate -ne $DownloadZip) { $KeepZip = $true }   # never delete a copy we didn't download
                break
            }
        }
    } else {
        $KeepZip = $true
    }

    if ($Zip) {
        if (-not (Test-Path $Zip)) { Die "zip not found: $Zip" }
        Ok "using existing $Zip"
    } else {
        $Zip = $DownloadZip
        # a partial file that is really an HTML error page can't be resumed
        if ((Test-Path $Zip) -and (Get-Item $Zip).Length -gt 0) {
            $fs = [IO.File]::OpenRead($Zip); $first = $fs.ReadByte(); $fs.Dispose()
            if ($first -eq 60) { Remove-Item $Zip }   # "<"
        }
        if ($driveBlocked) {
            Die ("Google Drive refused the download (usually 'Quota exceeded': too many downloads of this file today).`n" +
                 "      Try again later, or open this link in a browser while logged in to Google,`n" +
                 "      save mw.zip to your Downloads folder and re-run this script (it picks it up automatically):`n" +
                 "      https://drive.google.com/file/d/$DriveId/view")
        }
        if (-not $remoteSize) {
            if (-not (Test-Path $Zip)) { Die "can't reach Google Drive and no mw.zip found. Check the connection, or pass -Zip <path>." }
            Warn "can't reach Google Drive to check the size, using $Zip as is"
        } else {
            $have = if (Test-Path $Zip) { (Get-Item $Zip).Length } else { 0 }
            $needGB = [math]::Ceiling(([int64]$remoteSize - $have) / 1GB) + 18
            if ((FreeGB $Zip) -lt $needGB) { Die "need about $needGB GB free on $([IO.Path]::GetPathRoot($Zip)), only $(FreeGB $Zip) GB available" }
            if ($have -gt 0) { Write-Host "    Resuming download ($([math]::Floor($have / 1MB)) MB of $([math]::Floor([int64]$remoteSize / 1MB)) MB done)" }
            else { Write-Host "    Downloading to $Zip" }
            Write-Host "    (if it stops, just re-run the script and it continues)"
            New-Item -ItemType Directory -Force -Path (Split-Path $Zip) | Out-Null
            & curl.exe -fL -C - --retry 5 --retry-delay 5 --progress-bar -o $Zip $DriveUrl
            if ("$((Get-Item $Zip).Length)" -ne $remoteSize) { Die "download incomplete, re-run to resume" }
            Ok "downloaded"
        }
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
'@
# END client.cfg
Set-Content -Path (Join-Path $game "main\client_tweaks.cfg") -Value $ClientCfg -Encoding ascii
Ok "game settings installed (lowest graphics, no FPS drops when hit)"

# ---------------------------------------------------------------- custom maps + bots
# Separate pack, also installable on its own with install-maps.ps1. The local copy is
# used when running from the repo, otherwise it's fetched from GitHub.
$mapsScript = if ($PSCommandPath) { Join-Path (Split-Path $PSCommandPath) "install-maps.ps1" } else { "" }
try {
    if ($mapsScript -and (Test-Path $mapsScript)) { & $mapsScript -InstallDir $game }
    else { & ([scriptblock]::Create((irm https://raw.githubusercontent.com/dorostanian/iw4x-lan-server/main/scripts/install-maps.ps1))) -InstallDir $game }
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
