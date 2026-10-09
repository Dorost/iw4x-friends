<#
Install the custom maps + bots pack (usermaps\ and userraw\) into an MW2 game folder (Windows).
Safe to re-run: skips if already installed, and an interrupted download resumes.

Run it straight from GitHub, in PowerShell:
  & ([scriptblock]::Create((irm https://raw.githubusercontent.com/dorostanian/iw4x-lan-server/main/scripts/install-maps.ps1)))

Options:
  -InstallDir <path>  game folder (default: C:\Games\Call of Duty Modern Warfare 2)
  -MapsUrl <link>     download link of the pack (a Google Drive share link works); also
                      MW_MAPS_URL. Asked for when needed and not given
  -Zip <path>         use this pack zip instead of downloading
  -KeepZip            keep the zip afterwards (default: delete it if this script downloaded it)
  -Force              install again even if already installed
#>
param(
    [string]$InstallDir = "C:\Games\Call of Duty Modern Warfare 2",
    [string]$Zip = "",
    [string]$MapsUrl = $env:MW_MAPS_URL,
    [switch]$KeepZip,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$ZipName = "mw2-iw4x-maps-bots.zip"
$Mark = Join-Path $InstallDir ".iw4x-maps-installed"

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

Add-Type -AssemblyName System.IO.Compression.FileSystem
Write-Host "`n==> Custom maps + bots pack (~1 GB)" -ForegroundColor Cyan
if (-not (Test-Path (Join-Path $InstallDir "iw4x.exe"))) { Die "no MW2 + IW4x install found in: $InstallDir" }

# already installed: done, without contacting Google Drive (use -Force to reinstall)
if (-not $Force -and (Test-Path $Mark)) {
    Ok "already installed"
    return
}

$download = Join-Path $HOME "Downloads\$ZipName"
if (-not $Zip) {
    # reuse a complete copy if one is lying around (a partial download has no zip index yet)
    foreach ($candidate in @($download, (Join-Path $PWD $ZipName))) {
        $complete = (Test-Path $candidate) -and $(try { [IO.Compression.ZipFile]::OpenRead($candidate).Dispose(); $true } catch { $false })
        if ($complete) { $Zip = $candidate; if ($candidate -ne $download) { $KeepZip = $true }; break }
    }
} else { $KeepZip = $true }

# a file path works too (drag the zip into the PowerShell window)
if (-not $Zip -and -not $MapsUrl) { $MapsUrl = (Read-Host "    Paste the download link for the maps pack, or the path to $ZipName").Trim().Trim('"') }
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
    Write-Host "    Downloading to $Zip (if it stops, run this again and it continues)"
    New-Item -ItemType Directory -Force -Path (Split-Path $Zip) | Out-Null
    & curl.exe -fL -C - --retry 5 --retry-delay 5 --progress-bar -o $Zip $url
    if ("$((Get-Item $Zip).Length)" -ne $remoteSize) { Die "download incomplete, run this again to resume" }
}

Write-Host "    Extracting..."
$archive = [IO.Compression.ZipFile]::OpenRead($Zip)
try {
    foreach ($entry in $archive.Entries) {
        if ($entry.FullName -notmatch '^(usermaps|userraw)/') { continue }
        $dest = Join-Path $InstallDir ($entry.FullName -replace "/", "\")
        if ($entry.FullName.EndsWith("/")) { New-Item -ItemType Directory -Force -Path $dest | Out-Null; continue }
        New-Item -ItemType Directory -Force -Path (Split-Path $dest) | Out-Null
        [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $dest, $true)
    }
} finally { $archive.Dispose() }
Set-Content -Path $Mark -Value "$((Get-Item $Zip).Length)" -Encoding ascii
Ok "installed $((Get-ChildItem (Join-Path $InstallDir 'usermaps') -Directory).Count) maps and the bots mod into $InstallDir"
if (-not $KeepZip) { Remove-Item $Zip; Ok "removed $ZipName" }
