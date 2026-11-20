<#
Install the maps + bots pack into an MW2 game folder (Windows): the custom maps (usermaps\), the
bots (userraw\), MW2's own DLC maps (zone\dlc\, or zone\iw4x\x86\dlc\ where recent IW4x keeps
map zones, with their textures main\iw_dlc1_00.iwd and iw_dlc2_00.iwd, and from MW2's Steam
update zone\english\patch_mp.ff with the maps' scripts and names: the disc's 2009 one can't
start 4 of them) and main\iw_23.iwd, textures some IW4x maps (e.g. Shipment) need but IW4x
doesn't ship.
Safe to re-run: skips if already installed, and an interrupted download resumes.
Every run also deletes the usermaps\ folders of maps IW4x ships itself (zone\**\<map>.ff).
Older packs had 7 of those (Backlot, Broadcast, District, Ambush, Countdown, Seatown,
Showdown). IW4x plays its own copy anyway but still loads the folder's textures on top,
a server with the folder only lets in players with the same copy, and on IW4x before
r5292 the pack's Countdown froze the server.

Run it straight from GitHub, in PowerShell:
  & ([scriptblock]::Create((irm https://raw.githubusercontent.com/Dorost/iw4x-friends/main/scripts/windows/install-maps.ps1)))

Options:
  -InstallDir <path>  game folder (default: the first with iw4x.exe of the folder this runs in,
                      the IW4x Desktop icon's and C:\Games\Call of Duty Modern Warfare 2)
  -MapsUrl <link>     download link of the pack (a Google Drive share link works); also
                      MW_MAPS_URL. When needed and not given, it asks for the setup
                      password (decrypts the links below) or the link itself
  -Zip <path>         use this pack zip instead of downloading
  -KeepZip            keep the zip afterwards (default: delete it if this script downloaded it)
  -Force              install again even if already installed
#>
param(
    [string]$InstallDir = "",
    [string]$Zip = "",
    [string]$MapsUrl = $env:MW_MAPS_URL,
    [switch]$KeepZip,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$ZipName = "mw2-iw4x-maps-bots.zip"
# download links, encrypted with the setup password (written by `task links`)
$LinksEnc = "U2FsdGVkX18BSFqqHMCQ++5w+wJL5cdh3asQpzzejdBx2HWUrjeVW3q15pMGc31tolezaREbLw7dPLBzNarkDGagqk5k81ChbyM7uVo97si+Qc/A/GDQ+Y1Gkje41pLweL2l2zWtdoyWSKS33+xtZ92FbDNb5kYs4B9rHU3DfkJFIP0naKFFciIY7ikspmyrxsHNiTtW8zGg5eFIJbcxXe/vVJiCjUDQyPGbkry3TdA="

function Ok($msg)  { Write-Host "    + $msg" -ForegroundColor Green }
# throw instead of exit: when run as a one-liner, exit would close the user's PowerShell window
function Die($msg) { Write-Host "    x $msg" -ForegroundColor Red; throw "Stopped, see the message above." }

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

# Delete the usermaps\ folders of maps IW4x ships itself (see the top of this file).
function Remove-DuplicateMaps {
    $usermaps = Join-Path $InstallDir "usermaps"
    $zone = Join-Path $InstallDir "zone"
    if (-not (Test-Path $usermaps) -or -not (Test-Path $zone)) { return }
    $shipped = @{}
    Get-ChildItem $zone -Recurse -File -Filter "*.ff" | ForEach-Object { $shipped[$_.BaseName.ToLower()] = $true }
    $removed = @()
    foreach ($folder in Get-ChildItem $usermaps -Directory) {
        if (-not $shipped.ContainsKey($folder.Name.ToLower())) { continue }
        Remove-Item -Recurse -Force $folder.FullName
        $removed += $folder.Name
    }
    if ($removed) { Ok "removed $($removed -join ', ') from usermaps (IW4x has its own copy)" }
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

Add-Type -AssemblyName System.IO.Compression.FileSystem
Write-Host "`n==> Maps + bots pack (~2 GB)" -ForegroundColor Cyan
# the game folder: -InstallDir, else the folder this runs in, else the one the IW4x Desktop icon
# starts in (setup.ps1 makes it), else setup.ps1's default
if ($InstallDir) {
    if (-not (Test-Path -LiteralPath ([IO.Path]::Combine($InstallDir, "iw4x.exe")))) { Die "no MW2 + IW4x install found in: $InstallDir" }
} else {
    $looked = @((Get-Location).Path)
    $desktop = [Environment]::GetFolderPath("Desktop")
    $icon = if ($desktop) { Join-Path $desktop "IW4x.lnk" } else { "" }
    if ($icon -and (Test-Path $icon)) { try { $looked += (New-Object -ComObject WScript.Shell).CreateShortcut($icon).WorkingDirectory } catch {} }
    $looked += "C:\Games\Call of Duty Modern Warfare 2"
    $looked = @($looked | Where-Object { $_ } | Select-Object -Unique)
    $InstallDir = $looked | Where-Object { Test-Path -LiteralPath ([IO.Path]::Combine($_, "iw4x.exe")) } | Select-Object -First 1  # Combine: no error for a drive that is gone
    if (-not $InstallDir) { Die "no MW2 + IW4x install found in: $($looked -join ', '). Add -InstallDir `"<your game folder>`" (the folder with iw4x.exe)" }
    Ok "game folder: $InstallDir"
}
$Mark = Join-Path $InstallDir ".iw4x-maps-installed-v3"  # v3: the pack gained MW2's DLC maps, so older installs update

# already installed: done, without contacting Google Drive (use -Force to reinstall)
if (-not $Force -and (Test-Path $Mark)) {
    Remove-DuplicateMaps
    Ok "already installed"
    return
}

$download = Join-Path $HOME "Downloads\$ZipName"
if (-not $Zip) {
    # reuse a complete copy if one is lying around (a partial download has no zip index yet)
    foreach ($candidate in @($download, (Join-Path $PWD $ZipName))) {
        # an older pack without the DLC maps doesn't count: download the current one
        $complete = (Test-Path $candidate) -and $(try { $a = [IO.Compression.ZipFile]::OpenRead($candidate); $has = [bool]$a.GetEntry("zone/english/patch_mp.ff"); $a.Dispose(); $has } catch { $false })
        if ($complete) { $Zip = $candidate; if ($candidate -ne $download) { $KeepZip = $true }; break }
    }
} else { $KeepZip = $true }

# a file path works too (drag the zip into the PowerShell window)
if (-not $Zip -and -not $MapsUrl) {
    $links = Unlock-Links
    if ($links) { $MapsUrl = $links.maps }
    else { $MapsUrl = (Read-Host "    Paste the download link for the maps pack, or the path to $ZipName").Trim().Trim('"') }
}
if (-not $Zip -and $MapsUrl -and (Test-Path -LiteralPath $MapsUrl -PathType Leaf)) { $Zip = $MapsUrl; $KeepZip = $true }

if ($Zip) {
    Ok "using $Zip"
} else {
    if (-not $MapsUrl) { Die "no download link given. Pass -MapsUrl <link>, or put $ZipName in your Downloads folder" }
    $url = Get-DownloadUrl $MapsUrl
    $remoteSize = Get-RemoteSize $url
    if (-not $remoteSize) { Die $Refused }
    $Zip = $download
    Remove-HtmlPartial $Zip
    # a complete zip here is an older pack (the current one would have been used above), and
    # resuming it would glue the end of the new pack onto it; a partial one has no zip index yet
    if ((Test-Path $Zip) -and $(try { [IO.Compression.ZipFile]::OpenRead($Zip).Dispose(); $true } catch { $false })) { Remove-Item $Zip }
    Write-Host "    Downloading to $Zip (if it stops, run this again and it continues)"
    New-Item -ItemType Directory -Force -Path (Split-Path $Zip) | Out-Null
    & curl.exe -fL -C - --retry 5 --retry-delay 5 --progress-bar -o $Zip $url
    if ("$((Get-Item $Zip).Length)" -ne $remoteSize) { Die "download incomplete, run this again to resume" }
}

# only the pack this script is for: an older one (from a link that still serves it, or an old
# file) would get this version's mark and never be replaced
$current = $(try { $a = [IO.Compression.ZipFile]::OpenRead($Zip); $has = [bool]$a.GetEntry("zone/english/patch_mp.ff"); $a.Dispose(); $has } catch { $false })
if (-not $current) {
    if (-not $KeepZip) { Remove-Item $Zip -ErrorAction SilentlyContinue }
    Die "$Zip is an older maps pack, without MW2's DLC maps. If it came from the download link, the new pack isn't there yet: try again later."
}

Write-Host "    Extracting..."
# Recent IW4x keeps every map's zone in zone\iw4x\x86\dlc. On start it copies the ones it finds
# in zone\dlc there and keeps the originals, so the DLC maps would take their 1.4 GB twice: put
# them there directly when the game has that folder (IW4x's launcher leaves files it doesn't
# know alone), and drop the copies an earlier install left in zone\dlc
$oldDlc = Join-Path $InstallDir "zone\dlc"
$intoIw4x = Test-Path (Join-Path $InstallDir "zone\iw4x\x86\dlc")
$archive = [IO.Compression.ZipFile]::OpenRead($Zip)
try {
    $dlc = @($archive.Entries | Where-Object { $_.FullName -like "zone/dlc/*_load.ff" }).Count
    foreach ($entry in $archive.Entries) {
        if ($entry.FullName -notmatch '^(usermaps|userraw|main|zone)/') { continue }
        $name = $entry.FullName
        if ($intoIw4x -and $name.StartsWith("zone/dlc/")) {
            if ($entry.Name) { Remove-Item (Join-Path $oldDlc $entry.Name) -Force -ErrorAction SilentlyContinue }
            $name = "zone/iw4x/x86/dlc/" + $name.Substring("zone/dlc/".Length)
        }
        $dest = Join-Path $InstallDir ($name -replace "/", "\")
        if ($entry.FullName.EndsWith("/")) { New-Item -ItemType Directory -Force -Path $dest | Out-Null; continue }
        New-Item -ItemType Directory -Force -Path (Split-Path $dest) | Out-Null
        [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $dest, $true)
    }
} finally { $archive.Dispose() }
if ($intoIw4x -and (Test-Path $oldDlc) -and -not (Get-ChildItem $oldDlc -Force)) { Remove-Item $oldDlc }  # only if nothing else is in it
Remove-DuplicateMaps  # an older pack (e.g. one left in Downloads) still has them
Remove-Item (Join-Path $InstallDir ".iw4x-maps-installed*") -Force -ErrorAction SilentlyContinue  # an older version's mark
Set-Content -Path $Mark -Value "$((Get-Item $Zip).Length)" -Encoding ascii
Ok "installed $((Get-ChildItem (Join-Path $InstallDir 'usermaps') -Directory).Count) custom maps, $dlc DLC maps and the bots mod into $InstallDir"
if (-not $KeepZip) { Remove-Item $Zip; Ok "removed $ZipName" }
