# Start the IW4x client with everything from this repo applied:
#   - config/client.cfg   shared settings (graphics, hit fixes, sound), loaded on every start
#   - custom maps + bots  installed if missing (scripts/install-maps.ps1)
#   - config/classes.cfg  custom classes, loaded by pressing F9 at the main menu
# Default skips the launcher's GitHub update check; pass -Update to update IW4x first.
param([switch]$Update)
. (Join-Path $PSScriptRoot "env.ps1")

$main = Join-Path $GameDir "main"
Copy-Item "config\client.cfg" (Join-Path $main "client_tweaks.cfg") -Force
Copy-Item "config\classes.cfg" (Join-Path $main "classes.cfg") -Force
try { & "scripts\install-maps.ps1" -InstallDir $GameDir } catch { Write-Host "Custom maps not installed, starting anyway." }

Write-Host "Tip: press F9 at the main menu to load the ready-made classes (config/classes.cfg)."

$launcherArgs = @("--arch", "x86")
if (-not $Update) { $launcherArgs += "--skip-remote", "--no-self-update", "--no-shortcuts", "--no-connect-protocol" }
$launcherArgs += "--game-args", '"+exec client_tweaks.cfg"'
Start-Process -FilePath (Join-Path $GameDir "iw4x-launcher.exe") -ArgumentList $launcherArgs -WorkingDirectory $GameDir
