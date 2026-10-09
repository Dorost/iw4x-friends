#!/bin/zsh
# Stop stuck IW4x launcher/game processes, leaving the dedicated server running.
# --dry-run only lists what would be stopped.
for pid in $(pgrep -f 'iw4x(-launcher)?\.exe'); do
  cmd=$(ps -o command= -p "$pid") || continue
  # only real game processes (Windows path or wine wrapper), never the server or a shell
  [[ "$cmd" == C:\\* || "$cmd" == *winewrapper* ]] || continue
  [[ "$cmd" == *-dedicated* ]] && continue
  if [[ "$1" == "--dry-run" ]]; then
    echo "would stop $pid: ${cmd:0:80}"
  else
    kill "$pid" && echo "stopped $pid"
  fi
done
