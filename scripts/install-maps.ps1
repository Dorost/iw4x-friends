# Moved to scripts/windows/install-maps.ps1. Kept so setup scripts downloaded before the
# move, which fetch this path from GitHub, still work.
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/Dorost/iw4x-friends/main/scripts/windows/install-maps.ps1))) @args
