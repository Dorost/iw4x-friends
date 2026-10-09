# Shared defaults for the Windows helper scripts
Set-Location (Join-Path $PSScriptRoot "..\..")
# load .env (go-task does this too, but the scripts also run without it)
if (Test-Path ".env") {
    foreach ($line in Get-Content ".env") {
        if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$' -and -not (Test-Path "env:$($Matches[1])")) {
            Set-Item "env:$($Matches[1])" ($Matches[2].Trim().Trim('"'))
        }
    }
}
$DefaultDir = "C:\Games\Call of Duty Modern Warfare 2"
$ServerDir = if ($env:IW4X_SERVER_DIR) { $env:IW4X_SERVER_DIR } else { $DefaultDir }
$GameDir = if ($env:IW4X_GAME_DIR) { $env:IW4X_GAME_DIR } else { $DefaultDir }
$Port = if ($env:IW4X_PORT) { $env:IW4X_PORT } else { "28960" }
