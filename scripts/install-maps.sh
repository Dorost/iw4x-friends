#!/bin/bash
# Moved to scripts/mac/install-maps.sh. Kept so setup scripts downloaded before the move,
# which fetch this path from GitHub, still work.
exec bash -c "$(curl -fsSL https://raw.githubusercontent.com/Dorost/iw4x-friends/main/scripts/mac/install-maps.sh)" install-maps "$@"
