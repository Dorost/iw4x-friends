# Start the IW4x client with everything from this repo applied:
#   - config/client.cfg   shared settings (graphics, hit fixes, sound), loaded on every start
#   - custom maps + bots  installed if missing (scripts/install-maps.ps1)
#   - config/classes.cfg  custom classes, loaded automatically when the file is new or changed
# Default skips the launcher's GitHub update check; pass -Update to update IW4x first.
param([switch]$Update)
. (Join-Path $PSScriptRoot "env.ps1")

$main = Join-Path $GameDir "main"
Copy-Item "config\client.cfg" (Join-Path $main "client_tweaks.cfg") -Force
Copy-Item "config\classes.cfg" (Join-Path $main "classes.cfg") -Force
try { & "scripts\install-maps.ps1" -InstallDir $GameDir } catch { Write-Host "Custom maps not installed, starting anyway." }

$gameArgs = "+exec client_tweaks.cfg"
# Classes are stored in the player's stats, which load a few seconds after startup,
# so they're applied after a delay. Only when classes.cfg changed, so classes edited
# in the game aren't overwritten on every start.
$hash = (Get-FileHash "config\classes.cfg" -Algorithm SHA1).Hash
$applied = Join-Path $main ".classes-applied"
if (-not (Test-Path $applied) -or (Get-Content $applied) -ne $hash) {
    Set-Content -Path (Join-Path $main "classes_auto.cfg") -Value "wait 600`nexec classes.cfg" -Encoding ascii
    $gameArgs += " +exec classes_auto.cfg"
    Set-Content -Path $applied -Value $hash -Encoding ascii
    Write-Host "Custom classes will be loaded a few seconds after the menu appears."
}

$launcherArgs = @("--arch", "x86")
if (-not $Update) { $launcherArgs += "--skip-remote", "--no-self-update", "--no-shortcuts", "--no-connect-protocol" }
$launcherArgs += "--game-args", "`"$gameArgs`""
Start-Process -FilePath (Join-Path $GameDir "iw4x-launcher.exe") -ArgumentList $launcherArgs -WorkingDirectory $GameDir
