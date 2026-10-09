# Start the IW4x client with the shared game settings from config/client.cfg.
# Default skips the launcher's GitHub update check; pass -Update to update IW4x first.
param([switch]$Update)
. (Join-Path $PSScriptRoot "env.ps1")
Copy-Item "config\client.cfg" (Join-Path $GameDir "main\client_tweaks.cfg") -Force
Copy-Item "config\classes.cfg" (Join-Path $GameDir "main\classes.cfg") -Force   # loaded on demand: exec classes.cfg
$launcherArgs = @("--arch", "x86")
if (-not $Update) { $launcherArgs += "--skip-remote", "--no-self-update", "--no-shortcuts", "--no-connect-protocol" }
$launcherArgs += "--game-args", '"+exec client_tweaks.cfg"'
Start-Process -FilePath (Join-Path $GameDir "iw4x-launcher.exe") -ArgumentList $launcherArgs -WorkingDirectory $GameDir
