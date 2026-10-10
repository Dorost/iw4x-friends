# Start the IW4x dedicated server in this window, as a lobby server (the web UI starts the matches)
. (Join-Path $PSScriptRoot "env.ps1")
if (Get-NetUDPEndpoint -LocalPort $Port -ErrorAction SilentlyContinue) {
    Write-Host "A server is already running on port $Port (use the web UI or 'task stop')."
    exit 1
}
$ip = (Get-NetIPConfiguration | Where-Object IPv4DefaultGateway | Select-Object -First 1).IPv4Address.IPAddress
Write-Host "LAN address: ${ip}:$Port  (allow iw4x.exe through Windows Firewall if asked)"
Set-Location $ServerDir
& .\iw4x.exe -dedicated +set net_port $Port +exec server.cfg +set party_enable 1 +set party_minLobbyTime 2147483 +playlist 0
