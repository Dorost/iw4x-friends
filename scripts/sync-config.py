# /// script
# requires-python = ">=3.13"
# ///
"""Copy config/client.cfg into the standalone setup scripts.

The setup scripts must work as single files on a friend's machine, so each carries
its own copy of the shared game settings between BEGIN/END markers. This keeps
those copies identical to config/client.cfg.

  uv run scripts/sync-config.py           update the scripts
  uv run scripts/sync-config.py --check   exit 1 if any script is out of date (CI)
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "config" / "client.cfg"
# script -> (opening line of the embedded block, closing line)
TARGETS = {
    ROOT / "scripts" / "setup-mac.sh": ("CLIENT_CFG=$(cat <<'CFG'", "CFG"),
    ROOT / "scripts" / "setup-windows.ps1": ("$ClientCfg = @'", "'@"),
}


def main() -> int:
    check = "--check" in sys.argv
    cfg = SOURCE.read_text().strip("\n")
    stale = []
    for path, (opening, closing) in TARGETS.items():
        text = path.read_text()
        block = re.compile(
            rf"(# BEGIN client\.cfg[^\n]*\n{re.escape(opening)}\n).*?(^{re.escape(closing)}\n)", re.S | re.M
        )
        if not block.search(text):
            print(f"{path.name}: BEGIN/END client.cfg block not found")
            return 1
        updated = block.sub(lambda m: m.group(1) + cfg + "\n" + m.group(2), text, count=1)
        if updated != text:
            stale.append(path.name)
            if not check:
                path.write_text(updated)
    if check and stale:
        print("out of date, run `task sync-config`:", ", ".join(stale))
        return 1
    print("updated: " + ", ".join(stale) if stale else "all scripts in sync")
    return 0


if __name__ == "__main__":
    sys.exit(main())
