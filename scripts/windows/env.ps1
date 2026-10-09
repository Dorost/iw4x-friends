# Shared defaults for the Windows helper scripts (go-task loads .env before running them)
Set-Location (Join-Path $PSScriptRoot "..\..")
$DefaultDir = "C:\Games\Call of Duty Modern Warfare 2"
$ServerDir = if ($env:IW4X_SERVER_DIR) { $env:IW4X_SERVER_DIR } else { $DefaultDir }
$GameDir = if ($env:IW4X_GAME_DIR) { $env:IW4X_GAME_DIR } else { $DefaultDir }
$Port = if ($env:IW4X_PORT) { $env:IW4X_PORT } else { "28960" }
