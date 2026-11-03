"""The scripts a new VM runs at its first boot (the cloud's user-data). They only hold what the VM
can't get otherwise: its WireGuard key, its token, the commit; then they hand over to the
scripts in the repo (deploy/node/bootstrap.sh, deploy/bastion/bootstrap.sh). The game server's
other settings, and the setup password, come from the bastion over WireGuard.

A VM provider keeps the user-data, so nothing here outlives the run: the WireGuard key and the
token are new on every boot."""

from control.config import Bastion, Fleet, ServerSpec

HEAD = """#!/bin/bash
# {what}: written by the bastion (services/control/control/userdata.py), runs at first boot
set -euo pipefail
exec >> /var/log/iw4x-bootstrap.log 2>&1
echo "=== $(date -u) {what}"
export DEBIAN_FRONTEND=noninteractive
"""


def _file(path: str, content: str, mode: str = "600") -> str:
    """A heredoc writing content to path; the quoted delimiter keeps $ and ` as they are."""
    if "IW4X_EOF" in content:
        raise ValueError("content holds the heredoc delimiter")
    return (
        f"install -d -m 700 \"$(dirname '{path}')\"\n"
        f"install -m {mode} /dev/null '{path}'\n"
        f"cat > '{path}' <<'IW4X_EOF'\n{content.rstrip()}\nIW4X_EOF\n"
    )


def _clone(repo: str, sha: str) -> str:
    return (
        "apt-get -o DPkg::Lock::Timeout=600 update -q\n"
        "apt-get -o DPkg::Lock::Timeout=600 install -yq git\n"
        "rm -rf /opt/iw4x\n"
        f"git clone -q '{repo}' /opt/iw4x\n"
        f"git -C /opt/iw4x checkout -q --detach '{sha}'\n"
    )


def node(
    fleet: Fleet,
    spec: ServerSpec,
    *,
    sha: str,
    token: str,
    wg_private: str,
    bastion_wg_public: str,
    ssh_keys: list[str],
) -> str:
    b: Bastion = fleet.bastion
    env = "\n".join(
        [
            f"NODE_NAME={spec.name}",
            f"NODE_TOKEN={token}",
            f"NODE_WG_IP={spec.wg_ip}",
            f"CONTROL_URL=http://{b.wg_ip}:8070",
            f"GIT_SHA={sha}",
        ]
    )
    wg = "\n".join(
        [
            "[Interface]",
            f"PrivateKey = {wg_private}",
            f"Address = {spec.wg_ip}/32",
            "",
            "[Peer]",
            f"PublicKey = {bastion_wg_public}",
            f"Endpoint = {b.domain}:{b.wg_port}",
            f"AllowedIPs = {b.wg_ip}/32",  # the bastion only: servers don't reach each other
            "PersistentKeepalive = 25",
        ]
    )
    return (
        HEAD.format(what=f"iw4x game server {spec.name}")
        + _file("/root/.ssh/authorized_keys", "\n".join(ssh_keys))
        + _file("/etc/iw4x/node.env", env)
        + _file("/etc/wireguard/wg0.conf", wg)
        + _clone(fleet.repo, sha)
        + "exec bash /opt/iw4x/deploy/node/bootstrap.sh\n"
    )


def bastion(
    fleet: Fleet,
    *,
    sha: str,
    host_key: str,
    host_key_public: str,
    deploy_key_public: str,
    ssh_keys: list[str],
) -> str:
    """host_key: the bastion's SSH host key (the BASTION_SSH_HOST_KEY secret), the same on every
    rebuild: the deploy job checks the bastion against it."""
    forced = f'restrict,command="bash /opt/iw4x/deploy/bastion/deploy.sh" {deploy_key_public}'
    return (
        HEAD.format(what="iw4x bastion")
        + _file("/etc/ssh/ssh_host_ed25519_key", host_key.strip())
        + _file("/etc/ssh/ssh_host_ed25519_key.pub", host_key_public, "644")
        + _file("/etc/ssh/sshd_config.d/00-iw4x.conf", "PasswordAuthentication no", "644")
        + _file("/root/.ssh/authorized_keys", "\n".join([*ssh_keys, forced]))
        + "systemctl restart ssh\n"
        + _clone(fleet.repo, sha)
        + f"exec bash /opt/iw4x/deploy/bastion/bootstrap.sh '{fleet.bastion.wg_ip}'"
        + f" '{fleet.bastion.wg_port}'\n"
    )
