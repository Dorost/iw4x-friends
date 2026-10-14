# /// script
# requires-python = ">=3.13"
# ///
"""Create or destroy the internet server on a Vultr VPS.

  uv run scripts/tools/vultr.py up      create the VPS, copy this repo, run setup, start
  uv run scripts/tools/vultr.py down    destroy the VPS (game files and all)
  uv run scripts/tools/vultr.py status  show the VPS address and web UI link

Needs VULTR_API_KEY (Vultr: Account -> API) and an SSH key in ~/.ssh. The web UI
is served on https://<ip>.sslip.io, so no domain is needed. setup.sh asks for the
setup password (to download the game) unless MW_GAME_URL / MW_MAPS_URL are set.
"""

import json
import os
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
API = "https://api.vultr.com/v2"
LABEL = "iw4x"
REGION = "ewr"  # New York (New Jersey)
PLAN = "vhf-2c-4gb"  # high frequency CPU, 128 GB disk
OS_NAME = "Ubuntu 24.04 LTS x64"
REMOTE_DIR = "iw4x"
SSH_OPTS = [
    "-o", "StrictHostKeyChecking=no",
    "-o", "UserKnownHostsFile=/dev/null",  # a new VPS can get an IP seen before
    "-o", "LogLevel=ERROR",
    "-o", "ConnectTimeout=10",
]  # fmt: skip


def api(method: str, path: str, body: dict | None = None) -> dict:
    key = os.environ.get("VULTR_API_KEY") or sys.exit("set VULTR_API_KEY in .env")
    req = urllib.request.Request(
        API + path,
        method=method,
        data=json.dumps(body).encode() if body else None,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        sys.exit(f"Vultr API {method} {path}: {e.code} {e.read().decode()}")
    return json.loads(raw) if raw else {}


def find_instance() -> dict | None:
    found = api("GET", f"/instances?label={LABEL}")["instances"]
    return found[0] if found else None


def ssh_key_id() -> str:
    pub = next((p for p in (Path.home() / ".ssh").glob("id_*.pub")), None) or sys.exit(
        "no SSH key in ~/.ssh, create one with: ssh-keygen -t ed25519"
    )
    key = pub.read_text().strip()
    for k in api("GET", "/ssh-keys?per_page=500")["ssh_keys"]:
        if k["ssh_key"].split()[:2] == key.split()[:2]:
            return k["id"]
    return api("POST", "/ssh-keys", {"name": f"{LABEL}-{pub.stem}", "ssh_key": key})[
        "ssh_key"
    ]["id"]


def ssh(
    ip: str, cmd: str, tty: bool = False, check: bool = False, **kw
) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["ssh", *SSH_OPTS, *(["-t"] if tty else []), f"root@{ip}", cmd],
        check=check,
        **kw,
    )


def up() -> None:
    inst = find_instance()
    if inst:
        print(f"VPS exists ({inst['main_ip']}), continuing setup on it")
    else:
        avail = api("GET", f"/regions/{REGION}/availability")["available_plans"]
        if PLAN not in avail:
            sys.exit(f"plan {PLAN} not available in {REGION}")
        os_id = next(
            o["id"]
            for o in api("GET", "/os?per_page=500")["os"]
            if o["name"] == OS_NAME
        )
        inst = api(
            "POST",
            "/instances",
            {
                "region": REGION,
                "plan": PLAN,
                "os_id": os_id,
                "label": LABEL,
                "hostname": LABEL,
                "sshkey_id": [ssh_key_id()],
                "backups": "disabled",
            },
        )["instance"]
        print(f"Creating VPS {PLAN} in {REGION}...")

    while inst["status"] != "active" or inst["main_ip"] == "0.0.0.0":
        time.sleep(5)
        inst = api("GET", f"/instances/{inst['id']}")["instance"]
    ip = inst["main_ip"]
    print(f"VPS up at {ip}, waiting for SSH...")
    while ssh(ip, "true", capture_output=True).returncode:
        time.sleep(5)
    # first boot runs apt updates; setup.sh's apt-get would hit the lock
    ssh(ip, "cloud-init status --wait >/dev/null", check=True)

    print("Copying the repo...")
    files = subprocess.run(
        ["git", "ls-files", "-z", "-c", "-o", "--exclude-standard"],
        cwd=ROOT, capture_output=True, check=True,
    ).stdout  # fmt: skip
    tar = subprocess.run(
        ["tar", "--no-xattrs", "--no-mac-metadata", "--null", "-T", "-", "-czf", "-"],
        cwd=ROOT, input=files, capture_output=True, check=True,
    ).stdout  # fmt: skip
    ssh(ip, f"mkdir -p {REMOTE_DIR} && tar -xzf - -C {REMOTE_DIR}", input=tar, check=True)  # fmt: skip

    domain = f"{ip}.sslip.io"
    env = " ".join(
        f"{k}={shlex.quote(os.environ[k])}"
        for k in ("MW_GAME_URL", "MW_MAPS_URL")
        if os.environ.get(k)
    )
    ssh(
        ip,
        f"cd {REMOTE_DIR} && ([ -f .env ] || printf 'DOMAIN={domain}\\n' > .env)"
        f" && {env} bash scripts/linux/setup.sh && docker compose up -d --build",
        tty=True,
        check=True,
    )
    password = ssh(
        ip, f"sed -n 's/^UI_PASSWORD=//p' {REMOTE_DIR}/.env", capture_output=True, text=True
    ).stdout.strip()  # fmt: skip
    print(f"\nWeb UI:   https://{domain}  (password: {password})")
    print(f"Players:  connect {ip}:28960")
    print(f"SSH:      ssh root@{ip}")


def down() -> None:
    inst = find_instance()
    if not inst:
        print("no VPS running")
        return
    if input(f"Destroy VPS {inst['main_ip']} and everything on it? [y/N] ") != "y":
        return
    api("DELETE", f"/instances/{inst['id']}")
    print("destroyed")


def status() -> None:
    inst = find_instance()
    if not inst:
        print("no VPS running")
        return
    ip = inst["main_ip"]
    print(
        f"{inst['status']} / {inst['power_status']}  {inst['plan']} in {inst['region']}"
    )
    print(f"Web UI:   https://{ip}.sslip.io")
    print(f"Players:  connect {ip}:28960")


if __name__ == "__main__":
    cmds = {"up": up, "down": down, "status": status}
    if len(sys.argv) != 2 or sys.argv[1] not in cmds:
        sys.exit(__doc__)
    cmds[sys.argv[1]]()
