# Start the IW4x server web UI: installs uv if missing, creates .env and the server
# config on first run, then opens the UI in the browser.
if (-not (Test-Path (Join-Path $PSScriptRoot "..\..\.env"))) {
    Copy-Item (Join-Path $PSScriptRoot "..\..\.env.example") (Join-Path $PSScriptRoot "..\..\.env")
}
. (Join-Path $PSScriptRoot "env.ps1")
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "Installing uv (Python runner)..."
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    $env:Path = "$HOME\.local\bin;$env:Path"
}
$cfg = Join-Path $ServerDir "main\server.cfg"
if (-not (Test-Path $cfg)) {
    if (Test-Path (Split-Path $cfg)) { Copy-Item "server.cfg.example" $cfg; Write-Host "installed $cfg" }
    else { Write-Host "Game not found in $ServerDir. Install it first, or set IW4X_SERVER_DIR in .env"; exit 1 }
}
$url = "http://localhost:$(if ($env:UI_PORT) { $env:UI_PORT } else { 8080 })"
Write-Host "Web UI: $url  (close this window to stop the UI; the game server keeps running)"
Write-Host "Allow Python and iw4x.exe through Windows Firewall if asked."
Start-Job { Start-Sleep 4; Start-Process $using:url } | Out-Null
Set-Location "services\ui"
uv run app.py
