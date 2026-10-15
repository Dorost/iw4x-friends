#!/bin/zsh
# Hide the IW4x game window (like Cmd+H), leaving the dedicated server alone.
# Bring it back from the Dock or with Cmd+Tab.
hidden=0
for pid in $(pgrep -f 'iw4x\.exe'); do
  cmd=$(ps -o command= -p "$pid") || continue
  # only the real game process (Windows path or wine wrapper), never the server or a shell
  [[ "$cmd" == C:\\* || "$cmd" == *winewrapper* ]] || continue
  [[ "$cmd" == *-dedicated* ]] && continue
  osascript -e "tell application \"System Events\" to set visible of (first process whose unix id is $pid) to false" \
    && hidden=1
done
(( hidden )) && echo "game hidden" || echo "game not running"
