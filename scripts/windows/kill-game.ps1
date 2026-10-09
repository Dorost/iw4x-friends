# Stop stuck IW4x launcher/game processes, leaving the dedicated server running
Get-CimInstance Win32_Process -Filter "Name = 'iw4x.exe' OR Name = 'iw4x-launcher.exe'" |
    Where-Object { $_.CommandLine -notmatch '-dedicated' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host "stopped $($_.ProcessId)" }
