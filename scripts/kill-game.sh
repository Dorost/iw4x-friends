#!/bin/zsh
# Stop stuck IW4x launcher/game processes, leaving the dedicated server running.
# --dry-run only lists what would be stopped.
for pid in $(pgrep -f 'iw4x(-launcher)?\.exe'); do
  cmd=$(ps -o command= -p "$pid") || continue
  [[ "$cmd" == *-dedicated* || "$pid" == $$ ]] && continue
  if [[ "$1" == "--dry-run" ]]; then
    echo "would stop $pid: ${cmd:0:80}"
  else
    kill "$pid" && echo "stopped $pid"
  fi
done
