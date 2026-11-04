"""The bastion itself, and other one-off chores, from the command line (Taskfile, GitHub Actions):

  python -m control.infra keys            make the deploy key and the bastion's SSH host key and
                                          put them in the GitHub secrets (bastion environment)
  python -m control.infra bastion-up      create the bastion if it isn't there (its disk, the VM,
                                          its domain); --rebuild replaces the VM, the disk stays
  python -m control.infra zenlayer-types  the Zenlayer instance types in the Istanbul zone

bastion-up reads VULTR_API_KEY, CLOUDFLARE_DNS_TOKEN, BASTION_SSH_HOST_KEY, DEPLOY_SSH_KEY,
ADMIN_SSH_KEYS and the commit (GITHUB_SHA or --sha). The services start with the deploy
(deploy/bastion/deploy.sh) that follows it.
"""

import argparse
import asyncio
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from control import keys, userdata
from control.config import BASTION_LABEL, _list, load_fleet
from control.dns import Cloudflare
from control.providers import ACTIVE, GONE, Machine
from control.providers.vultr import Vultr
from control.providers.zenlayer import Zenlayer

ROOT = Path(__file__).resolve().parents[3]
FLEET = ROOT / "deploy/fleet.toml"
LABEL = BASTION_LABEL
ENVIRONMENT = "bastion"  # the GitHub environment with the secrets


def need(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        sys.exit(f"set {name}")
    return value


async def bastion_up(sha: str, rebuild: bool) -> None:
    fleet = load_fleet(FLEET)
    b = fleet.bastion
    if b.provider != "vultr":
        sys.exit("the bastion runs on Vultr")
    vultr = Vultr(need("VULTR_API_KEY"))
    dns = Cloudflare(need("CLOUDFLARE_DNS_TOKEN"))
    host_key = need("BASTION_SSH_HOST_KEY")
    deploy_key = need("DEPLOY_SSH_KEY")
    m = Machine(LABEL, b.region, b.plan, b.volume_gb, {})
    try:
        volume = await vultr.ensure_volume(m)
        print(f"disk: {volume}")
        existing = await vultr.find_instances(LABEL)
        if existing and rebuild:
            for instance_id in existing:
                print(f"destroying the old VM {instance_id} (its disk stays)")
                await vultr.destroy_instance(instance_id, volume)
                while (await vultr.get_instance(instance_id)).status != GONE:
                    await asyncio.sleep(5)
            existing = []
        if existing:
            instance_id = existing[0]
            print(f"the bastion is there: {instance_id}")
        else:
            script = userdata.bastion(
                fleet,
                sha=sha,
                host_key=host_key,
                host_key_public=keys.public_of(host_key, f"root@{b.domain}"),
                deploy_key_public=keys.public_of(deploy_key, "iw4x deploy"),
                ssh_keys=_list(os.environ.get("ADMIN_SSH_KEYS", "")),
            )
            instance_id = await vultr.create_instance(m, script)
            print(f"creating the bastion VM {instance_id} ({b.plan} in {b.region})")
        deadline = time.monotonic() + 900
        while (inst := await vultr.get_instance(instance_id)).status != ACTIVE:
            if time.monotonic() > deadline:
                sys.exit("the VM didn't come up in 15 minutes")
            await asyncio.sleep(5)
        await vultr.attach_volume(volume, instance_id)
        await dns.point(b.domain, inst.ip)
        print(f"{b.domain} -> {inst.ip}")
    finally:
        await vultr.close()
        await dns.close()


def make_keys(force: bool) -> None:
    """Both private keys go straight into the GitHub secrets and nowhere else. The deploy job
    gets the bastion's public host key from the secret too, so nothing goes in the repo."""
    names = ("DEPLOY_SSH_KEY", "BASTION_SSH_HOST_KEY")
    listed = subprocess.run(
        ["gh", "secret", "list", "--env", ENVIRONMENT, "--json", "name", "--jq", ".[].name"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    if listed.returncode:
        sys.exit(f"gh can't list the secrets of the {ENVIRONMENT} environment: {listed.stderr}")
    there = set(listed.stdout.split()) & set(names)
    if there and not force:
        sys.exit(
            f"already set: {', '.join(sorted(there))}. --force replaces them (a bastion made"
            " with the old host key then needs the bastion workflow with rebuild)"
        )
    domain = load_fleet(FLEET).bastion.domain
    with tempfile.TemporaryDirectory() as tmp:
        for name, comment in zip(names, ("iw4x deploy", domain), strict=True):
            path = Path(tmp) / name
            subprocess.run(
                ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", comment, "-f", str(path)],
                check=True,
            )
            subprocess.run(
                ["gh", "secret", "set", name, "--env", ENVIRONMENT],
                input=path.read_bytes(),
                check=True,
                cwd=ROOT,
            )
            print(f"secret {name} set in the {ENVIRONMENT} environment")


async def zenlayer_types() -> None:
    fleet = load_fleet(FLEET)
    zones = {s.region for s in fleet.servers.values() if s.provider == "zenlayer"}
    z = Zenlayer(need("ZENLAYER_ACCESS_KEY_ID"), need("ZENLAYER_ACCESS_KEY_PASSWORD"))
    try:
        for zone in sorted(zones):
            print(f"{zone}:")
            for t in await z.instance_types(zone):
                stock = "" if t.get("withStock") else "  (out of stock)"
                print(
                    f"  {t['instanceType']:<16} {t.get('cpuCount')} CPU {t.get('memory')} GB"
                    f"  {t.get('instanceTypeName', '')}{stock}"
                )
    finally:
        await z.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m control.infra",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    up = sub.add_parser("bastion-up")
    up.add_argument("--sha", default=os.environ.get("GITHUB_SHA", ""))
    up.add_argument("--rebuild", action="store_true", help="replace the VM (the disk stays)")
    k = sub.add_parser("keys")
    k.add_argument("--force", action="store_true")
    sub.add_parser("zenlayer-types")
    args = parser.parse_args()
    if args.cmd == "bastion-up":
        if len(args.sha) != 40:
            sys.exit("--sha: the full commit to set up (GITHUB_SHA in Actions)")
        asyncio.run(bastion_up(args.sha, args.rebuild))
    elif args.cmd == "keys":
        make_keys(args.force)
    else:
        asyncio.run(zenlayer_types())


if __name__ == "__main__":
    main()
