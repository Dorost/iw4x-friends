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
    # Ubuntu's own apt runs are off before the first apt-get: they'd hold the dpkg lock
    masked = script.index("systemctl mask -q --now apt-daily.timer apt-daily-upgrade.timer")
    assert "unattended-upgrades.service || true" in script
    assert masked < script.index("apt-get")
    assert """echo 'Acquire::Languages "none";' > /etc/apt/apt.conf.d/99iw4x""" in script


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
    assert "systemctl mask" not in script  # always on: it keeps its security updates


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


def test_the_server_pulls_its_image_while_it_sets_up():
    """One apt run for WireGuard and Docker, Docker held back until the data disk is mounted
    (its images live there), then the commit's image downloads in the background while the
    settings, the game and the firewall go on; compose pulls it if that failed."""
    script = (FLEET.parent / "node" / "bootstrap.sh").read_text()
    assert script.count("apt-get ") == 1
    held = script.index("> /usr/sbin/policy-rc.d")
    install = script.index("install -yq wireguard-tools \\\n  docker.io docker-compose-v2")
    released = script.index("rm -f /usr/sbin/policy-rc.d")
    mount = script.index('bash deploy/common/mount-data.sh "$DATA"')
    data_root = script.index('{"data-root": "/srv/iw4x/docker"')
    docker = script.index("systemctl restart containerd docker")
    pull = script.index('docker pull -q "$IMAGE:$GIT_SHA" >/dev/null &')
    assert held < install < released < mount < data_root < docker < pull
    assert pull < script.index('step "getting its settings"')
    waited = script.index('if ! wait "$pull" || [[ "$(value image_tag)" != "$GIT_SHA" ]]; then')
    fallback = script.index('"${COMPOSE[@]}" pull -q')
    assert script.index('step "opening the firewall"') < waited < fallback
    up = script.index('"${COMPOSE[@]}" up -d')
    assert fallback < up < script.index("docker image prune -af")
    image = (FLEET.parent / "node" / "docker-compose.yml").read_text()
    assert "image: ghcr.io/dorost/iw4x-friends:${IMAGE_TAG" in image
    assert "IMAGE=ghcr.io/dorost/iw4x-friends " in script


def test_stopping_stops_docker_before_the_disk_goes():
    """Docker's images are on the data disk: it has to stop before the unmount."""
    script = (FLEET.parent / "node" / "stop.sh").read_text()
    down = script.index("down -t 20")
    assert down < script.index("systemctl stop docker.socket docker") < script.index("umount")


@pytest.mark.parametrize("early_pull_works", [True, False])
def test_a_failed_early_pull_falls_back_to_compose(tmp_path, early_pull_works):
    script = (FLEET.parent / "node" / "bootstrap.sh").read_text()
    start = script[script.index("docker pull -q") : script.index("pull=$!") + len("pull=$!")]
    end = script[
        script.index('if ! wait "$pull"') : script.index('step "starting the game server"')
    ]
    calls = tmp_path / "calls"
    pull = "true" if early_pull_works else "false"
    harness = f"""set -euo pipefail
IMAGE=ghcr.io/dorost/iw4x-friends GIT_SHA={SHA} COMPOSE=(docker compose)
docker() {{ echo "$*" >> '{calls}'; [[ "$1" == compose ]] || {pull}; }}
value() {{ echo {SHA}; }}
{start}
{end}
"""
    subprocess.run(["bash", "-c", harness], check=True, timeout=10)
    pulls = calls.read_text().splitlines()
    assert pulls[0] == f"pull -q ghcr.io/dorost/iw4x-friends:{SHA}"
    assert pulls[1:] == ([] if early_pull_works else ["compose pull -q"])


def test_bootstrap_timings_never_fail_it():
    script = (FLEET.parent / "node" / "bootstrap.sh").read_text()
    assert 'local text="$1 (at ${SECONDS}s)"' in script and 'report "$text" 0 1' in script
    assert "timeout 30 cloud-init analyze blame 2>&1 | head -25 || true" in script
    assert "timeout 30 systemd-analyze critical-chain 2>&1 || true" in script


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


NAME, EMPTY, OWN = 'set sv_hostname "NL"', 'set g_password ""', 'set g_password "own"'
JOIN = 'set g_password "s3cr"'


@pytest.mark.parametrize(
    "password, before, after",
    [
        ("s3cr", [EMPTY, NAME], [NAME, JOIN]),
        ("s3cr", [NAME], [NAME, JOIN]),
        ("", [OWN], ['set g_password ""']),  # the server is open to everyone
        ("null", [OWN], [OWN]),  # no fleet password (jq prints null): the server's own stays
    ],
)
def test_the_join_password_goes_into_server_cfg(tmp_path, password, before, after):
    """bootstrap.sh's own lines, run on a server.cfg: GAME_JOIN_PASSWORD replaces g_password."""
    script = (FLEET.parent / "node" / "bootstrap.sh").read_text()
    start = script.index("# the fleet's join password")
    block = script[start : script.index("\nPY\n", start) + 4]
    cfg = tmp_path / "game" / "main" / "server.cfg"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("\n".join(before) + "\n")
    harness = f"""set -euo pipefail
DATA='{tmp_path}'
value() {{ echo '{password}'; }}
{block}"""
    subprocess.run(["bash", "-c", harness], check=True, timeout=10)
    assert cfg.read_text().splitlines() == after
