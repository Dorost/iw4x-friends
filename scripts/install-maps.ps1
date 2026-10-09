<#
Install the custom maps + bots pack (usermaps\ and userraw\) into an MW2 game folder (Windows).
Safe to re-run: skips if already installed, and an interrupted download resumes.

Run it straight from GitHub, in PowerShell:
  & ([scriptblock]::Create((irm https://raw.githubusercontent.com/dorostanian/iw4x-lan-server/main/scripts/install-maps.ps1)))

Options:
  -InstallDir <path>  game folder (default: C:\Games\Call of Duty Modern Warfare 2)
  -Zip <path>         use this pack zip instead of downloading
  -KeepZip            keep the zip afterwards (default: delete it if this script downloaded it)
  -Force              install again even if already installed
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
$ZipName = "mw2-iw4x-maps-bots.zip"
$Mark = Join-Path $InstallDir ".iw4x-maps-installed"

function Ok($msg)  { Write-Host "    + $msg" -ForegroundColor Green }
# throw instead of exit: when run as a one-liner, exit would close the user's PowerShell window
function Die($msg) { Write-Host "    x $msg" -ForegroundColor Red; throw "Stopped, see the message above." }

Add-Type -AssemblyName System.IO.Compression.FileSystem
Write-Host "`n==> Custom maps + bots pack (~1 GB)" -ForegroundColor Cyan
if (-not (Test-Path (Join-Path $InstallDir "iw4x.exe"))) { Die "no MW2 + IW4x install found in: $InstallDir" }

# already installed: done, without contacting Google Drive (use -Force to reinstall)
if (-not $Force -and (Test-Path $Mark)) {
    Ok "already installed"
    return
}

# Drive answers with an HTML page instead of the file when its daily download quota is used up
$head = (& curl.exe -sIL --max-time 20 $DriveUrl) -join "`n"
$lengths = [regex]::Matches($head, '(?im)^content-length:\s*(\d+)')
$remoteSize = if ($lengths.Count) { $lengths[$lengths.Count - 1].Groups[1].Value } else { "" }
$blocked = ($head -match '(?im)^content-type:\s*text/html') -or ($remoteSize -eq "0")
if ($blocked) { $remoteSize = "" }

$download = Join-Path $HOME "Downloads\$ZipName"
if (-not $Zip) {
    foreach ($candidate in @($download, (Join-Path $PWD $ZipName))) {
        if (-not (Test-Path $candidate)) { continue }
        $size = "$((Get-Item $candidate).Length)"
        $complete = if ($remoteSize) { $size -eq $remoteSize } else {
            try { [IO.Compression.ZipFile]::OpenRead($candidate).Dispose(); $true } catch { $false } }
        if ($complete) { $Zip = $candidate; if ($candidate -ne $download) { $KeepZip = $true }; break }
    }
} else { $KeepZip = $true }

if ($Zip) {
    Ok "using $Zip"
} else {
    $Zip = $download
    if ((Test-Path $Zip) -and (Get-Item $Zip).Length -gt 0) {
        $fs = [IO.File]::OpenRead($Zip); $first = $fs.ReadByte(); $fs.Dispose()
        if ($first -eq 60) { Remove-Item $Zip }   # a partial file that is really an HTML error page
    }
    if ($blocked) {
        Die ("Google Drive refused the download (usually 'Quota exceeded': too many downloads today).`n" +
             "      Try again later, or download it in a browser while logged in to Google,`n" +
             "      save it to Downloads as $ZipName and run this again:`n" +
             "      https://drive.google.com/file/d/$DriveId/view")
    }
    if (-not $remoteSize) { Die "can't reach Google Drive. Check the connection, or pass -Zip <path>." }
    Write-Host "    Downloading to $Zip (if it stops, run this again and it continues)"
    New-Item -ItemType Directory -Force -Path (Split-Path $Zip) | Out-Null
    & curl.exe -fL -C - --retry 5 --retry-delay 5 --progress-bar -o $Zip $DriveUrl
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
