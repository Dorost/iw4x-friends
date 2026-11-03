"""Boots and shuts down the game servers: by schedule, by the idle rule (control/schedule.py) and
by hand (web UI, Telegram mini app). One task per server at a time; the state of each server is
in the database, so a restart of the control plane picks up where it was.

Booting a server:
  1. its disk (created the first time) and a VM from a user-data script (control/userdata.py)
     with a new WireGuard key and token
  2. the disk attached, its domain pointed at the VM
  3. the VM sets itself up (deploy/node/bootstrap.sh), reporting each step to /node/progress, and
     downloads the game onto the disk the first time
  4. running once its web UI answers over WireGuard
Shutting down: the game stops and the disk is unmounted (deploy/node/stop.sh), the disk detached,
the VM destroyed, the domain pointed back at the bastion."""

import asyncio
import contextlib
import logging
import secrets
import socket
import time
from collections.abc import Callable
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from control import keys, userdata
from control.config import ServerSpec, Settings
from control.db import BOOTING, FAILED, OFF, PROVISIONING, RUNNING, STOPPING, UP, Event, Server
from control.db import Schedule as ScheduleRow
from control.providers import ACTIVE, GONE, CloudError, Machine, Provider
from control.schedule import (
    BadSchedule,
    Decision,
    Weekly,
    active_window,
    decide,
    weekly,
)
from control.telegram import Presence, Telegram, esc, humans_of, presence_text

log = logging.getLogger("control")

VM_TIMEOUT = 15 * 60  # for the cloud to hand over a running VM
SILENCE_TIMEOUT = 15 * 60  # a booting server that stops reporting progress this long failed
BOOT_TIMEOUT = 2 * 3600  # the first boot downloads the game, but never longer than this
FAILED_KEEP = 10 * 60  # a failed server's VM stays this long for a look, then goes
UPDATE_WHEN_EMPTY = 120  # a running server updates to a new commit once nobody played this long
MAX_ATTEMPTS = 3  # boots in a row a schedule window tries before giving up
EVENTS_KEPT = 500


class Busy(Exception):
    """The server is in the middle of something else."""


def machine(spec: ServerSpec) -> Machine:
    return Machine(spec.label, spec.region, spec.plan, spec.volume_gb, spec.options)


class Orchestrator:
    def __init__(
        self,
        s: Settings,
        db: sessionmaker[Session],
        providers: dict[str, Provider],
        dns,
        wg,
        nodes,
        tg: Telegram,
        now: Callable[[], float] = time.time,
        poll: float = 5,
    ):
        self.s, self.db, self.providers = s, db, providers
        self.dns, self.wg, self.nodes, self.tg = dns, wg, nodes, tg
        self.clock, self.poll = now, poll
        self.tasks: dict[str, asyncio.Task] = {}
        self.kinds: dict[str, str] = {}  # what each server's task does: boot, stop or update
        self.creating: dict[str, asyncio.Task] = {}  # a VM the cloud is making right now
        self.states: dict[str, dict | None] = {}  # what each running server's web UI last said
        self.presence: dict[str, Presence] = {}
        self.progress_at: dict[str, float] = {}  # last /node/progress report per server
        self.update_failed: dict[str, str] = {}  # server -> commit it couldn't update to
        self.ssh_public = keys.ssh_key(Path(s.data_dir) / "ssh" / "id_ed25519")
        with self.db.begin() as db:
            for name in s.fleet.servers:
                if not db.get(Server, name):
                    db.add(Server(name=name, status=OFF, changed_at=int(self.now())))

    def now(self) -> int:
        return int(self.clock())

    # ---------- reading ----------

    def schedules(self) -> list[Weekly]:
        out = []
        with self.db.begin() as db:
            rows = list(db.scalars(select(ScheduleRow)))
        for r in rows:
            with contextlib.suppress(BadSchedule):
                out.append(weekly(r.servers, r.days, r.start, r.end, r.tz, r.enabled, r.id))
        return out

    def decision(self, row: Server, schedules: list[Weekly] | None = None) -> Decision:
        now = self.now()
        window = active_window(
            self.schedules() if schedules is None else schedules,
            row.name,
            now,
            self.s.lead_minutes * 60,
        )
        return decide(
            row.status,
            window,
            now,
            self.s.idle_minutes * 60,
            row.ready_at,
            row.last_human_at,
            row.hold_off_until,
        )

    def busy(self, name: str) -> bool:
        return name in self.tasks and not self.tasks[name].done()

    def event(self, server: str, text: str) -> None:
        log.info("%s: %s", server or "fleet", text)
        with self.db.begin() as db:
            db.add(Event(at=self.now(), server=server, text=text))
            oldest = db.scalars(
                select(Event.id).order_by(Event.id.desc()).offset(EVENTS_KEPT).limit(1)
            ).first()
            if oldest:
                db.execute(delete(Event).where(Event.id <= oldest))

    def update(self, name: str, **fields) -> None:
        with self.db.begin() as db:
            row = db.get(Server, name)
            for k, v in fields.items():
                setattr(row, k, v)
            if "status" in fields:
                row.changed_at = self.now()

    def row(self, name: str) -> Server:
        with self.db.begin() as db:
            return db.get(Server, name)

    # ---------- the loops ----------

    async def run(self) -> None:
        await self.sync_peers()
        tick = 0
        while True:
            try:
                await self.poll_servers()
                if tick % 2 == 0:
                    await self.reconcile()
            except Exception:
                log.exception("loop")
            tick += 1
            await asyncio.sleep(5)

    async def reconcile(self) -> None:
        """Starts what the rules ask for: boots, shutdowns, retries, updates."""
        now = self.now()
        schedules = self.schedules()
        for name in self.s.servers:
            if self.busy(name):
                continue
            row = self.row(name)
            d = self.decision(row, schedules)
            window = active_window(schedules, name, now, self.s.lead_minutes * 60)
            if row.status == PROVISIONING:  # the control plane restarted in the middle of it
                self.start(name, "boot", self._boot(name, "restart"))
            elif row.status == BOOTING:
                self.start(name, "boot", self._wait_ready(name))
            elif row.status == STOPPING:
                self.start(name, "stop", self._stop(name, "restart"))
            elif row.status == OFF and d.on:
                # only a window turns an idle server on; it gives up after MAX_ATTEMPTS failures
                if row.attempts < MAX_ATTEMPTS:
                    self.start(name, "boot", self._boot(name, "schedule"))
            elif row.status == OFF and row.attempts and not window:
                self.update(name, attempts=0)  # the next window tries again
            elif row.status == RUNNING and not d.on:
                self.start(name, "stop", self._stop(name, d.reason))
            elif row.status == FAILED and now - row.changed_at >= FAILED_KEEP:
                if d.on and window and row.attempts < MAX_ATTEMPTS:
                    self.start(name, "boot", self._boot(name, "schedule, again"))
                elif row.instance_id or row.wg_public:
                    self.start(name, "stop", self._stop(name, "clean up after a failure"))
                else:
                    self.update(name, status=OFF)
            elif row.status == RUNNING and self.should_update(row, now):
                self.start(name, "update", self._update(name))

    def should_update(self, row: Server, now: int) -> bool:
        if not self.s.version or row.version == self.s.version:
            return False
        if self.update_failed.get(row.name) == self.s.version:
            return False
        empty = humans_of(self.states.get(row.name)) == {}
        return empty and (not row.last_human_at or now - row.last_human_at >= UPDATE_WHEN_EMPTY)

    def start(self, name: str, kind: str, coro) -> None:
        self.kinds[name] = kind
        self.tasks[name] = asyncio.create_task(coro, name=f"{kind} {name}")

    def stopping(self, name: str) -> bool:
        return (
            self.busy(name) and self.kinds.get(name) == "stop" or self.row(name).status == STOPPING
        )

    async def poll_servers(self) -> None:
        """Asks each server that is up what is going on, for the idle rule, the web UI and the
        join/leave messages."""
        now = self.now()
        for name, spec in self.s.servers.items():
            row = self.row(name)
            if row.status not in (BOOTING, RUNNING) or not row.token:
                self.states.pop(name, None)
                continue
            state = await self.nodes.state(spec.wg_ip, row.token)
            self.states[name] = state
            if row.status != RUNNING:
                continue
            humans = humans_of(state)
            if humans:
                self.update(name, last_human_at=now)
            joined, left = self.presence.setdefault(name, Presence()).update(
                humans, time.monotonic()
            )
            if joined or left:
                server = (state or {}).get("name") or spec.title
                text = presence_text(server, joined, left, self.presence[name].players.values())
                self.tg.post(text, silent=not joined)  # only leaves: no notification sound

    async def sync_peers(self) -> None:
        peers = {}
        with self.db.begin() as db:
            for row in db.scalars(select(Server)):
                spec = self.s.fleet.servers.get(row.name)
                if spec and row.wg_public and row.status != OFF:
                    peers[row.wg_public] = spec.wg_ip
        try:
            await self.wg.sync(peers)
        except (RuntimeError, OSError) as e:
            log.error("WireGuard peers not set: %s", e)

    # ---------- by hand ----------

    async def boot_now(self, name: str, by: str) -> None:
        spec = self.s.servers.get(name)
        if not spec:
            raise KeyError(name)
        if self.stopping(name):
            raise Busy(f"{spec.title} is shutting down, try again in a minute")
        row = self.row(name)
        self.update(name, hold_off_until=None)
        if row.status in UP or self.busy(name):  # up, or a boot or an update is on it already
            return
        self.update(name, attempts=0)
        self.start(name, "boot", self._boot(name, by))

    async def shutdown_now(self, name: str, by: str) -> None:
        spec = self.s.servers.get(name)
        if not spec:
            raise KeyError(name)
        row = self.row(name)
        window = active_window(self.schedules(), name, self.now(), self.s.lead_minutes * 60)
        self.update(name, hold_off_until=window.end if window else None)
        if row.status == OFF and not self.busy(name) or self.stopping(name):
            return
        if self.busy(name):
            self.tasks[name].cancel()  # a boot or an update: stop it where it is
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self.tasks[name]
        self.start(name, "stop", self._stop(name, f"by {by}"))

    async def update_now(self, name: str) -> None:
        row = self.row(name)
        if row.status != RUNNING:
            raise Busy("only a running server can be updated")
        if self.busy(name):
            raise Busy("the server is busy")
        self.update_failed.pop(name, None)
        self.start(name, "update", self._update(name))

    # ---------- reports from the servers (/node/*) ----------

    def server_of_token(self, token: str) -> str | None:
        with self.db.begin() as db:
            for row in db.scalars(select(Server).where(Server.token.is_not(None))):
                if secrets.compare_digest(row.token, token) and row.status in UP:
                    return row.name
        return None

    def node_progress(self, name: str, step: str, failed: bool, event: bool = False) -> None:
        self.progress_at[name] = time.monotonic()
        step = step[:200]
        if failed:
            self.update(name, error=f"setup failed: {step}")
        else:
            self.update(name, step=step)
            if event:  # the steps with their times stay in the events, for how long a boot took
                self.event(name, step)

    def node_config(self, name: str, need_game: bool) -> dict:
        spec = self.s.fleet.servers[name]
        return {
            "image_tag": self.s.version or "main",
            "join_host": spec.domain,
            "ui_host": spec.wg_ip,
            "hostname": spec.hostname,
            "setup_password": self.s.setup_password if need_game else "",
        }

    # ---------- the tasks ----------

    async def _boot(self, name: str, by: str) -> None:
        spec = self.s.servers[name]
        p = self.providers[spec.provider]
        m = machine(spec)
        row = self.row(name)
        self.update(
            name,
            status=PROVISIONING,
            step="starting",
            error="",
            boot_by=by,
            booted_at=self.now(),
            ready_at=None,
            last_human_at=None,
            attempts=row.attempts + 1,
        )
        self.event(name, f"booting ({by})")
        self.presence.pop(name, None)
        try:
            if row.instance_id:
                self.update(name, step="removing the VM of the last try")
                await p.destroy_instance(row.instance_id, row.volume_id)
                self.update(name, instance_id=None, ip=None)
            self.update(name, step="preparing its disk")
            volume = await p.ensure_volume(m)
            token, (wg_private, wg_public) = keys.token(), keys.wireguard_pair()
            self.update(name, volume_id=volume, token=token, wg_public=wg_public)
            await self.sync_peers()
            script = userdata.node(
                self.s.fleet,
                spec,
                sha=self.s.version or "main",
                token=token,
                wg_private=wg_private,
                bastion_wg_public=await self.wg.public_key(),
                ssh_keys=[self.ssh_public, *self.s.admin_ssh_keys],
            )
            self.update(name, step="creating the VM")
            # shielded: a VM the cloud made must end up in the database, even if this is
            # cancelled (a shutdown waits for it, see _stop)
            self.creating[name] = asyncio.ensure_future(self._create(name, p, m, script))
            instance_id = await asyncio.shield(self.creating[name])
            self.update(name, step="waiting for the VM")
            ip = await self._vm_ready(p, instance_id)
            self.update(name, ip=ip, step="attaching its disk")
            await p.attach_volume(volume, instance_id)
            if self.dns:
                self.update(name, step=f"pointing {spec.domain} at it")
                await self.dns.point(spec.domain, ip)
            self.update(name, status=BOOTING, step="setting itself up")
            self.progress_at[name] = time.monotonic()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            await self._failed(name, e)
            return
        await self._wait_ready(name)

    async def _create(self, name: str, p: Provider, m: Machine, script: str) -> str:
        instance_id = await p.create_instance(m, script)
        self.update(name, instance_id=instance_id)
        return instance_id

    async def _vm_ready(self, p: Provider, instance_id: str) -> str:
        deadline = time.monotonic() + VM_TIMEOUT
        while time.monotonic() < deadline:
            inst = await p.get_instance(instance_id)
            if inst.status == ACTIVE and inst.ip:
                return inst.ip
            if inst.status in ("failed", GONE):
                raise CloudError(f"the cloud says the VM is {inst.status}")
            await asyncio.sleep(self.poll)
        raise CloudError("the VM didn't come up in 15 minutes")

    async def _wait_ready(self, name: str) -> None:
        """Until the server's web UI answers over WireGuard with a match or the lobby."""
        spec = self.s.servers[name]
        started = time.monotonic()
        self.progress_at.setdefault(name, started)
        try:
            while True:
                row = self.row(name)
                if row.error:
                    raise RuntimeError(row.error)
                state = await self.nodes.state(spec.wg_ip, row.token or "")
                if state and state.get("status") in ("match", "lobby"):
                    break
                silent = time.monotonic() - self.progress_at[name]
                if silent > SILENCE_TIMEOUT:
                    raise RuntimeError(f"no word from the server for {SILENCE_TIMEOUT // 60} min")
                if time.monotonic() - started > BOOT_TIMEOUT:
                    raise RuntimeError("setting up took over 2 hours")
                await asyncio.sleep(self.poll)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            await self._failed(name, e)
            return
        self.update(
            name, status=RUNNING, step="", ready_at=self.now(), attempts=0, version=self.s.version
        )
        row = self.row(name)
        self.event(name, f"up at {row.ip}")
        self.tg.post(
            f"🟢 <b>{esc(spec.title)}</b> is up\n🎯 <code>connect {esc(spec.domain)}</code>"
        )

    async def _failed(self, name: str, e: Exception) -> None:
        spec = self.s.servers[name]
        text = str(e) or type(e).__name__
        log.warning("%s failed: %s", name, text)
        self.update(name, status=FAILED, error=text, step="")
        self.event(name, f"failed: {text}")
        self.tg.post(f"⚠️ <b>{esc(spec.title)}</b> didn't start: {esc(text)}", silent=True)

    async def _stop(self, name: str, reason: str) -> None:
        spec = self.s.servers[name]
        p = self.providers[spec.provider]
        creating = self.creating.pop(name, None)
        if creating and not creating.done():  # a cancelled boot's VM: wait for its id
            with contextlib.suppress(Exception):
                await creating
        row = self.row(name)
        was_running = row.status == RUNNING
        self.update(name, status=STOPPING, step="stopping the game")
        self.event(name, f"shutting down ({reason})")
        try:
            if row.instance_id:
                inst = await p.get_instance(row.instance_id)
                if inst.status != GONE:
                    if row.token:  # a clean unmount of the disk before it is detached
                        code, out = await self.nodes.ssh(
                            spec.wg_ip, "bash /opt/iw4x/deploy/node/stop.sh", timeout=180
                        )
                        if code:
                            log.warning("%s: stop.sh: %s %s", name, code, out[-300:])
                    self.update(name, step="destroying the VM")
                    await p.destroy_instance(row.instance_id, row.volume_id)
                    deadline = time.monotonic() + 600
                    while (await p.get_instance(row.instance_id)).status != GONE:
                        if time.monotonic() > deadline:
                            raise CloudError("the VM is still there after 10 minutes")
                        await asyncio.sleep(self.poll)
            self.update(
                name,
                status=OFF,
                step="",
                error="",
                instance_id=None,
                ip=None,
                token=None,
                wg_public=None,
                version=None,
                ready_at=None,
            )
            await self.sync_peers()
            self.states.pop(name, None)
            self.presence.pop(name, None)
            if self.dns and (ip := await self.bastion_ip()):
                with contextlib.suppress(CloudError):
                    await self.dns.point(spec.domain, ip)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            text = f"shutdown failed: {e}"
            self.update(name, status=FAILED, error=text, step="")
            self.event(name, text)
            self.tg.post(f"⚠️ <b>{esc(spec.title)}</b>: {esc(text)}", silent=True)
            return
        self.event(name, "off")
        if was_running:
            self.tg.post(f"⚪ <b>{esc(spec.title)}</b> shut down ({esc(reason)})", silent=True)

    async def _update(self, name: str) -> None:
        spec = self.s.servers[name]
        sha = self.s.version
        self.update(name, step=f"updating to {sha[:7]}")
        self.event(name, f"updating to {sha[:7]}")
        code, out = await self.nodes.ssh(
            spec.wg_ip, f"bash /opt/iw4x/deploy/node/update.sh {sha}", timeout=1200
        )
        if code == 0:
            self.update(name, version=sha, step="")
            self.event(name, f"updated to {sha[:7]}")
        else:
            self.update_failed[name] = sha
            self.update(name, step="")
            self.event(name, f"update to {sha[:7]} failed: {out.strip()[-300:]}")

    async def bastion_ip(self) -> str | None:
        """Where an idle server's domain points: here."""
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(
                self.s.fleet.bastion.domain, None, family=socket.AF_INET
            )
            return infos[0][4][0]
        except OSError:
            return None
