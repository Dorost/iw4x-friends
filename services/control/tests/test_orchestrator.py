import asyncio
import base64

import pytest
from fakes import SHA, at, make, posts
from sqlalchemy import select

from control.db import FAILED, OFF, RUNNING, Event
from control.db import Schedule as ScheduleRow
from control.orchestrator import FAILED_KEEP, Busy

NOW = at(2026, 11, 4, 18)  # a Wednesday, 19:00 in Amsterdam
NL = "10.66.0.11"
BASTION_IP = "198.51.100.1"


async def settle(orch, name="nl"):
    if name in orch.tasks:
        await orch.tasks[name]


async def up(orch, name="nl", ip=NL):
    """Boots by hand; the pretend server answers once its VM is there."""
    orch.nodes.up.add(ip)
    await orch.boot_now(name, "test")
    await settle(orch, name)


@pytest.fixture
def fleet(tmp_path):
    orch, cloud, clock = make(tmp_path, NOW)

    async def bastion_ip():
        return BASTION_IP

    orch.bastion_ip = bastion_ip
    return orch, cloud, clock


@pytest.mark.anyio
async def test_boot_by_hand(fleet):
    orch, cloud, _ = fleet
    await up(orch)
    row = orch.row("nl")
    assert row.status == RUNNING and row.version == SHA and row.boot_by == "test"
    assert cloud.attached == {row.volume_id: row.instance_id}
    assert orch.dns.records == {"mw2-nl.dorost.nl": row.ip}
    assert orch.wg.peers == {row.wg_public: NL}
    script = cloud.instances[row.instance_id]["user_data"]
    assert f"NODE_TOKEN={row.token}" in script
    assert "MW_SETUP_PASSWORD" not in script  # the password comes over WireGuard, when needed
    assert any("is up" in p and "connect mw2-nl.dorost.nl" in p for p in posts(orch))


@pytest.mark.anyio
async def test_nobody_joins_it_stops_after_15_minutes(fleet):
    orch, cloud, clock = fleet
    await up(orch)
    volume, instance = orch.row("nl").volume_id, orch.row("nl").instance_id
    clock.advance(14)
    await orch.reconcile()
    assert orch.row("nl").status == RUNNING
    clock.advance(1)
    await orch.reconcile()
    await settle(orch)
    row = orch.row("nl")
    assert row.status == OFF and row.instance_id is None and row.token is None
    assert cloud.running() == [] and volume not in cloud.attached  # the disk stays, detached
    assert row.volume_id == volume and cloud.volumes["iw4x-fleet-nl"] == volume
    assert (NL, "bash /opt/iw4x/deploy/node/stop.sh") in orch.nodes.ssh_calls
    assert orch.wg.peers == {} and orch.dns.records["mw2-nl.dorost.nl"] == BASTION_IP
    assert instance not in cloud.running()


@pytest.mark.anyio
async def test_players_keep_it_up_then_15_minutes_after_the_last_leaves(fleet):
    orch, _, clock = fleet
    await up(orch)
    orch.nodes.players[NL] = ["Amin"]
    for _ in range(12):  # an hour of play
        clock.advance(5)
        await orch.poll_servers()
        await orch.reconcile()
    assert orch.row("nl").status == RUNNING
    orch.nodes.players[NL] = []
    clock.advance(14)
    await orch.poll_servers()
    await orch.reconcile()
    assert orch.row("nl").status == RUNNING
    clock.advance(1.5)
    await orch.reconcile()
    await settle(orch)
    assert orch.row("nl").status == OFF


@pytest.mark.anyio
async def test_join_and_leave_messages(fleet):
    orch, _, clock = fleet
    await up(orch)
    posts(orch)
    await orch.poll_servers()  # the first list is taken as is
    orch.nodes.players[NL] = ["Amin"]
    await orch.poll_servers()
    assert posts(orch) == ["🟢 <b>Amin</b> joined Fake server\nPlaying (1): Amin"]
    orch.nodes.players[NL] = []
    await orch.poll_servers()
    assert posts(orch) == []  # gone for a moment: a map change


def schedule(orch, start="19:30", end="23:00", days="2", servers="nl", enabled=True):
    with orch.db.begin() as db:
        db.add(ScheduleRow(servers=servers, days=days, start=start, end=end,
                           tz="Europe/Amsterdam", enabled=enabled, note=""))  # fmt: skip


@pytest.mark.anyio
async def test_schedule_boots_it_early_and_keeps_it_up_empty(fleet):
    orch, _, clock = fleet
    schedule(orch)  # Wednesday 19:30 to 23:00 Amsterdam
    orch.nodes.up.add(NL)
    clock.advance(19)  # 19:19: not yet
    await orch.reconcile()
    assert orch.row("nl").status == OFF
    clock.advance(1)  # 19:20: ten minutes before
    await orch.reconcile()
    await settle(orch)
    row = orch.row("nl")
    assert row.status == RUNNING and row.boot_by == "schedule"
    clock.advance(120)  # nobody, but the window is on
    await orch.reconcile()
    assert orch.row("nl").status == RUNNING
    clock.advance(100)  # 23:00: over, nobody played
    await orch.reconcile()
    await settle(orch)
    assert orch.row("nl").status == OFF


@pytest.mark.anyio
async def test_shut_down_by_hand_in_a_window_stays_off(fleet):
    orch, _, clock = fleet
    schedule(orch, start="19:00")
    orch.nodes.up.add(NL)
    await orch.reconcile()
    await settle(orch)
    assert orch.row("nl").status == RUNNING
    await orch.shutdown_now("nl", "Yashar")
    await settle(orch)
    clock.advance(30)
    await orch.reconcile()
    assert orch.row("nl").status == OFF and not orch.busy("nl")
    await orch.boot_now("nl", "Amin")  # booting by hand lifts it
    await settle(orch)
    assert orch.row("nl").status == RUNNING and orch.row("nl").hold_off_until is None


@pytest.mark.anyio
async def test_a_disabled_schedule_does_nothing(fleet):
    orch, _, _ = fleet
    schedule(orch, start="19:00", enabled=False)
    await orch.reconcile()
    assert orch.row("nl").status == OFF and not orch.busy("nl")


@pytest.mark.anyio
async def test_failed_boot_is_cleaned_up(fleet):
    orch, cloud, clock = fleet
    cloud.fail_create = True
    await orch.boot_now("nl", "test")
    await settle(orch)
    row = orch.row("nl")
    assert row.status == FAILED and "no capacity" in row.error
    assert any("didn't start" in p for p in posts(orch))
    clock.advance(FAILED_KEEP / 60)
    await orch.reconcile()
    await settle(orch)
    assert orch.row("nl").status == OFF and orch.wg.peers == {}


@pytest.mark.anyio
async def test_scheduled_boots_give_up_after_three_failures(fleet):
    orch, cloud, clock = fleet
    schedule(orch, start="19:00", end="23:30")
    cloud.fail_create = True
    boots = 0
    for _ in range(8):
        before = len([c for c in cloud.calls if c[0] == "create_instance"])
        await orch.reconcile()
        await settle(orch)
        boots += len([c for c in cloud.calls if c[0] == "create_instance"]) - before
        clock.advance(FAILED_KEEP / 60)
    assert boots == 3


@pytest.mark.anyio
async def test_server_reports_a_failed_setup(fleet):
    orch, _, _ = fleet
    await orch.boot_now("nl", "test")
    for _ in range(50):  # until the VM is there and the server sets itself up
        await asyncio.sleep(0)
        if orch.row("nl").status == "booting":
            break
    orch.node_progress("nl", "downloading the game (bootstrap.sh line 80)", failed=True)
    await settle(orch)
    row = orch.row("nl")
    assert row.status == FAILED and "downloading the game" in row.error


def test_bootstrap_steps_are_kept_as_events_and_heartbeats_are_not(fleet):
    orch, _, _ = fleet
    orch.node_progress("nl", "mounting its disk (at 41s)", failed=False, event=True)
    orch.node_progress("nl", "mounting its disk (at 41s)", failed=False)  # the heartbeat
    with orch.db.begin() as db:
        texts = db.scalars(select(Event.text).where(Event.server == "nl")).all()
    assert texts == ["mounting its disk (at 41s)"]
    assert orch.row("nl").step == "mounting its disk (at 41s)"


@pytest.mark.anyio
async def test_shutdown_while_booting_cancels_the_boot(fleet):
    orch, cloud, _ = fleet
    await orch.boot_now("nl", "test")
    for _ in range(20):
        await asyncio.sleep(0)
    await orch.shutdown_now("nl", "test")
    await settle(orch)
    assert orch.row("nl").status == OFF and cloud.running() == []


@pytest.mark.anyio
async def test_boot_while_shutting_down_is_refused(fleet):
    orch, _, _ = fleet
    await up(orch)
    await orch.shutdown_now("nl", "test")
    with pytest.raises(Busy):
        await orch.boot_now("nl", "test")
    await settle(orch)


@pytest.mark.anyio
async def test_new_commit_reaches_a_running_server_once_it_is_empty(fleet):
    orch, _, clock = fleet
    await up(orch)
    orch.s = orch.s.__class__(**{**orch.s.__dict__, "version": "c" * 40})
    orch.nodes.players[NL] = ["Amin"]
    await orch.poll_servers()
    await orch.reconcile()
    assert not orch.busy("nl")  # someone plays: not now
    orch.nodes.players[NL] = []
    await orch.poll_servers()
    clock.advance(2)
    await orch.reconcile()
    await settle(orch)
    assert (NL, f"bash /opt/iw4x/deploy/node/update.sh {'c' * 40}") in orch.nodes.ssh_calls
    assert orch.row("nl").version == "c" * 40


@pytest.mark.anyio
async def test_node_config_gives_the_password_only_for_the_download(fleet):
    orch, _, _ = fleet
    assert orch.node_config("nl", need_game=True)["setup_password"] == "setup"
    config = orch.node_config("nl", need_game=False)
    assert config["setup_password"] == "" and config["join_host"] == "mw2-nl.dorost.nl"
    assert config["ui_host"] == NL and config["image_tag"] == SHA


@pytest.mark.anyio
async def test_server_of_token(fleet):
    orch, _, _ = fleet
    await up(orch)
    token = orch.row("nl").token
    assert orch.server_of_token(token) == "nl"
    assert orch.server_of_token(base64.b64encode(b"nope").decode()) is None


@pytest.mark.anyio
async def test_double_boot_makes_one_vm(fleet):
    orch, cloud, _ = fleet
    orch.nodes.up.add(NL)
    await orch.boot_now("nl", "a")
    await orch.boot_now("nl", "b")
    await settle(orch)
    assert len(cloud.running()) == 1 and orch.row("nl").boot_by == "a"


@pytest.mark.anyio
async def test_shutdown_right_after_boot_stops_it(fleet):
    orch, cloud, _ = fleet
    await orch.boot_now("nl", "test")
    await orch.shutdown_now("nl", "test")  # before the boot task even ran
    await settle(orch)
    assert orch.row("nl").status == OFF and cloud.running() == []


@pytest.mark.anyio
async def test_shutdown_while_the_cloud_makes_the_vm_leaves_no_vm(fleet):
    orch, cloud, _ = fleet
    release = asyncio.Event()
    make_vm = cloud.create_instance

    async def slow_create(m, script):
        await release.wait()
        return await make_vm(m, script)

    cloud.create_instance = slow_create
    await orch.boot_now("nl", "test")
    for _ in range(20):
        await asyncio.sleep(0)
    assert "nl" in orch.creating
    stopping = asyncio.create_task(orch.shutdown_now("nl", "test"))
    for _ in range(5):
        await asyncio.sleep(0)
    release.set()  # the cloud answers after the boot was cancelled
    await stopping
    await settle(orch)
    assert orch.row("nl").status == OFF and cloud.running() == []


@pytest.mark.anyio
async def test_one_player_is_one_join_and_one_leave(fleet):
    """Players go by guid: a slot without a name (connecting) or a new name is no new player."""
    orch, _, clock = fleet
    await up(orch)
    states = []

    async def state(ip, token):
        return {"status": "match", "name": "Dorost NL", "players": [], **states[-1]}

    orch.nodes.state = state
    for humans in ({}, {"g1": "XerS"}, {"g1": "XerS", "g2": " "}, {"g1": "XerS2"}, {}):
        states.append({"humans": humans})
        await orch.poll_servers()
    for _ in range(7):  # gone for longer than a map change
        clock.advance(0.2)
        orch.presence["nl"].last -= 10
        await orch.poll_servers()
    texts = posts(orch)[1:]  # after "is up"
    assert texts == [
        "🟢 <b>XerS</b> joined Dorost NL\nPlaying (1): XerS",
        "🔴 <b>XerS2</b> left Dorost NL\nNobody playing now",
    ]
