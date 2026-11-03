import subprocess

import pytest
from fakes import FLEET

from control import keys, userdata
from control.config import load_fleet

FLEET_ = load_fleet(FLEET)
SHA = "b" * 40


def bash_parses(script: str) -> None:
    subprocess.run(["bash", "-n"], input=script.encode(), check=True)


def test_node_script():
    spec = FLEET_.servers["nl"]
    private, _ = keys.wireguard_pair()
    script = userdata.node(
        FLEET_,
        spec,
        sha=SHA,
        token="tok-123",
        wg_private=private,
        bastion_wg_public="BASTIONPUB=",
        ssh_keys=["ssh-ed25519 AAAA control", "ssh-ed25519 BBBB admin"],
    )
    bash_parses(script)
    assert f"PrivateKey = {private}" in script
    assert "Endpoint = mw2.dorost.nl:51820" in script
    assert "AllowedIPs = 10.66.0.1/32" in script  # only the bastion, not the other servers
    assert "Address = 10.66.0.11/32" in script
    assert "NODE_TOKEN=tok-123" in script and "CONTROL_URL=http://10.66.0.1:8070" in script
    assert f"checkout -q --detach '{SHA}'" in script
    assert "ssh-ed25519 BBBB admin" in script
    assert "deploy/node/bootstrap.sh" in script
    assert "export HOME=/root" in script  # first boot runs without it, setup.sh needs it


def test_bastion_script():
    script = userdata.bastion(
        FLEET_,
        sha=SHA,
        host_key="-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n-----END OPENSSH PRIVATE KEY-----",
        host_key_public="ssh-ed25519 HOST root@mw2.dorost.nl",
        deploy_key_public="ssh-ed25519 DEPLOY iw4x deploy",
        ssh_keys=["ssh-ed25519 ADMIN me"],
    )
    bash_parses(script)
    assert (
        'restrict,command="bash /opt/iw4x/deploy/bastion/deploy.sh" ssh-ed25519 DEPLOY iw4x deploy'
        in script
    )
    assert "PasswordAuthentication no" in script
    assert "deploy/bastion/bootstrap.sh '10.66.0.1' '51820'" in script


def test_a_value_cannot_end_the_heredoc():
    with pytest.raises(ValueError):
        userdata._file("/x", "a\nIW4X_EOF\nrm -rf /")


def test_keys(tmp_path):
    private, public = keys.wireguard_pair()
    assert len(private) == len(public) == 44 and private != public
    line = keys.ssh_key(tmp_path / "ssh" / "id")
    assert line.startswith("ssh-ed25519 ") and keys.ssh_key(tmp_path / "ssh" / "id") == line
    assert (tmp_path / "ssh" / "id").stat().st_mode & 0o777 == 0o600
    pem = (tmp_path / "ssh" / "id").read_text()
    assert keys.public_of(pem, "c").split()[:2] == line.split()[:2]


def test_the_server_brings_up_wireguard_before_it_needs_the_bastion():
    """The user-data only writes the WireGuard config: deploy/node/bootstrap.sh installs and
    starts it, before its first call to the bastion (a first real boot failed on this)."""
    script = (FLEET.parent / "node" / "bootstrap.sh").read_text()
    up = script.index("systemctl enable -q --now wg-quick@wg0")
    assert script.index("apt-get -o DPkg::Lock::Timeout=600 install -yq wireguard-tools") < up
    assert up < script.index('"$CONTROL_URL/healthz"')


def test_the_heartbeat_keeps_reporting_before_the_game_download(tmp_path):
    """Until the download starts there is no mw.zip to measure: the heartbeat must outlive
    that, or a long step leaves the bastion without word and it fails the boot (it did)."""
    script = (FLEET.parent / "node" / "bootstrap.sh").read_text()
    block = script[script.index("# a sign of life") : script.index("heartbeat=$!")]
    block = block.replace("sleep 60", "sleep 0.1").replace("/var/tmp/iw4x", f"{tmp_path}/none")
    (tmp_path / "step").write_text("installing Docker\n")
    (tmp_path / "reports").touch()
    harness = f"""set -euo pipefail
STEP_FILE='{tmp_path}/step'
report() {{ echo "$1" >> '{tmp_path}/reports'; }}
{block}
sleep 1
kill $! 2>/dev/null || true
"""
    subprocess.run(["bash", "-c", harness], check=True, timeout=10)
    reports = (tmp_path / "reports").read_text().splitlines()
    assert len(reports) > 1 and set(reports) == {"installing Docker"}
