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
