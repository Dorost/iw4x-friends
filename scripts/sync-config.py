# /// script
# requires-python = ">=3.13"
# ///
"""Copy the shared game files from config/ into the standalone setup scripts.

The setup scripts must work as single files on a friend's machine, so each carries
its own copy of these files between BEGIN/END markers. This keeps those copies
identical to the files in config/.

  uv run scripts/sync-config.py           update the scripts
  uv run scripts/sync-config.py --check   exit 1 if any script is out of date (CI)
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAC = ROOT / "scripts" / "setup-mac.sh"
WINDOWS = ROOT / "scripts" / "setup-windows.ps1"
# config file -> {script: (opening line of the embedded block, closing line)}
BLOCKS = {
    "client.cfg": {MAC: ("CLIENT_CFG=$(cat <<'CFG'", "CFG"), WINDOWS: ("$ClientCfg = @'", "'@")},
    "classes.cfg": {MAC: ("CLASSES_CFG=$(cat <<'CFG'", "CFG"), WINDOWS: ("$ClassesCfg = @'", "'@")},
}


def main() -> int:
    check = "--check" in sys.argv
    stale = set()
    for name, targets in BLOCKS.items():
        content = (ROOT / "config" / name).read_text().strip("\n")
        for path, (opening, closing) in targets.items():
            text = path.read_text()
            block = re.compile(
                rf"(# BEGIN {re.escape(name)}[^\n]*\n{re.escape(opening)}\n).*?(^{re.escape(closing)}\n)",
                re.DOTALL | re.MULTILINE,
            )
            if not block.search(text):
                print(f"{path.name}: BEGIN/END {name} block not found")
                return 1
            updated = block.sub(lambda m, c=content: m.group(1) + c + "\n" + m.group(2), text, count=1)
            if updated != text:
                stale.add(path.name)
                if not check:
                    path.write_text(updated)
    if check and stale:
        print("out of date, run `task sync-config`:", ", ".join(sorted(stale)))
        return 1
    print("updated: " + ", ".join(sorted(stale)) if stale else "all scripts in sync")
    return 0


if __name__ == "__main__":
    sys.exit(main())
