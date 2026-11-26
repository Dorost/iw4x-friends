# /// script
# requires-python = ">=3.13"
# ///
"""Live test of vote.gsc's "Next up" announcements on a real IW4x dedicated server.

Runs the server image (built from services/ui) in Docker on a local game install, the same
way a fleet node does, and drives it through the web UI's own API: picks as the web UI and
the mini app send them (/api/select), single dvar changes as the chat commands make them.
The only change to the real code: the vote.gsc under test gets one logPrint in
announceNextUp, so what players would see (iPrintLn) shows in games_mp.log.

The game folder is never written to: the server gets a copy made of symlinks, and the real
folder is mounted read-only. Needs Docker and a game install with IW4x (setup-game.sh).

  uv run scripts/tools/vote-test.py                        vote.gsc of this checkout
  uv run scripts/tools/vote-test.py --gsc other/vote.gsc   another version (e.g. main's)
  options: --game DIR (default ~/Games/iw4x/game), --work DIR, --keep (leave it running)
"""

import argparse
import base64
import json
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
UI = ROOT / "services" / "ui"
IMAGE = "iw4x-vote-test"
CONTAINER = "iw4x-vote-test"
UI_PORT, GAME_PORT, PASSWORD = 8099, 28990, "test"
SETTLE = 4.0  # seconds after a change by which its announcement must have shown
LATENCY = 3.0  # a change is announced within this many seconds
START_MAP = "mp_rust"
# announceNextUp in every version: the probe goes right after it sets the text players see
ANCHOR = "announceNextUp( bold )\n{\n\tlevel.nextUpShown = nextUpText();\n"
PROBE = '\tlogPrint( "NEXTUP;" + bold + ";" + level.nextUpShown + "\\n" );\n'


def sh(*cmd: str, check: bool = True, quiet: bool = False) -> str:
    out = subprocess.run(cmd, check=check, text=True, capture_output=True)
    if out.returncode and not quiet:
        print(out.stderr.strip(), file=sys.stderr)
    return out.stdout


def api(path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(
        f"http://127.0.0.1:{UI_PORT}{path}",
        data=None if body is None else json.dumps(body).encode(),
        headers={
            "Authorization": "Basic " + base64.b64encode(f":{PASSWORD}".encode()).decode(),
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def rcon(cmd: str) -> str:
    """Through the web UI, as its own commands go (one rcon at a time, spaced)."""
    return api("/api/rcon", {"cmd": cmd})["output"]


class Log:
    """The NEXTUP lines (and map loads) games_mp.log gets from now on."""

    def __init__(self, path: Path):
        self.path, self.pos = path, 0

    def mark(self) -> None:
        self.pos = self.path.stat().st_size if self.path.exists() else 0

    def lines(self) -> list[str]:
        if not self.path.exists():
            return []
        with self.path.open("rb") as f:
            f.seek(self.pos)
            data = f.read()
        end = data.rfind(b"\n") + 1
        self.pos += end
        return [line.strip().partition(" ")[2] for line in data[:end].decode(errors="replace").splitlines()]

    def watch(self, seconds: float, since: float) -> tuple[list[tuple[float, bool, str]], bool]:
        """Announcements for this long: (seconds after since, bold, text), and whether a map
        (re)loaded meanwhile (an S&D round restart, which makes the test inconclusive)."""
        seen, loaded = [], False
        while time.monotonic() - since < seconds:
            for body in self.lines():
                if body.startswith("NEXTUP;"):
                    _, bold, text = body.split(";", 2)
                    seen.append((round(time.monotonic() - since, 1), bold == "1", text))
                loaded |= body == "InitGame"
            time.sleep(0.1)
        return seen, loaded


class Server:
    def __init__(self, game: Path, work: Path, gsc: Path):
        self.game, self.work, self.gsc = game.resolve(), work, gsc
        self.log = Log(work / "game" / "userraw" / "logs" / "games_mp.log")
        self.maps: dict[str, str] = {}
        self.modes: dict[str, str] = {}
        self.started: list[tuple[float, bool, str]] = []  # the announcements of the match start

    def prepare(self) -> None:
        source = self.gsc.read_text()
        if ANCHOR not in source:
            sys.exit(f"{self.gsc}: announceNextUp doesn't start the way the probe expects")
        self.work.mkdir(parents=True, exist_ok=True)
        (self.work / "vote.gsc").write_text(source.replace(ANCHOR, ANCHOR + PROBE))
        game = self.work / "game"
        if not game.exists():
            # symlinks to every file; the server's own files (config, scripts, logs) are real
            sh("cp", "-as", str(self.game), str(game))
            shutil.rmtree(game / "userraw")
            (game / "userraw").mkdir()
            bots = self.game / "userraw" / "z_svr_bots.iwd"
            if bots.exists():
                (game / "userraw" / bots.name).symlink_to(bots)
        cfg = game / "main" / "server.cfg"
        cfg.unlink(missing_ok=True)
        lines = [ln for ln in (ROOT / "server.cfg.example").read_text().splitlines() if "g_gametype" not in ln]
        cfg.write_text(
            "\n".join(lines)
            + f'\nset rcon_password "votetest"\nset g_gametype "sd"\nset ui_gametype "sd"\nset ui_mapname "{START_MAP}"\n'
        )
        (self.work / "data").mkdir(exist_ok=True)

    def check_image(self) -> None:
        """The image must carry this checkout's web UI and scripts (vote.gsc is mounted)."""
        for name in ("app.py", "lobby.gsc", "weapons.gsc", "players.gsc", "sdfun.gsc", "botchat.gsc"):
            inside = sh("docker", "run", "--rm", "--entrypoint", "cat", IMAGE, f"/app/{name}")
            if inside != (UI / name).read_text():
                sys.exit(f"the image's {name} isn't this checkout's: build it again (drop --no-build)")

    def start(self) -> None:
        sh("docker", "rm", "-f", CONTAINER, check=False, quiet=True)
        sh(
            "docker", "run", "-d", "--name", CONTAINER, "--network", "host",
            "--security-opt", "label=disable",
            "-e", "IW4X_SERVER_DIR=/game", "-e", f"IW4X_PORT={GAME_PORT}", "-e", f"UI_PORT={UI_PORT}",
            "-e", "UI_HOST=127.0.0.1", "-e", f"UI_PASSWORD={PASSWORD}", "-e", "UI_DATA_DIR=/data",
            "-e", "AUTOSTART=1", "-e", "JOIN_HOST=localhost",
            "-v", f"{self.work / 'game'}:/game", "-v", f"{self.work / 'data'}:/data",
            "-v", f"{self.game}:{self.game}:ro", "-v", f"{self.work / 'vote.gsc'}:/app/vote.gsc:ro",
            IMAGE,
        )  # fmt: skip

    def wait_for_match(self, seconds: int = 240) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            try:
                live = api("/api/state")["live"]
                if live and live["in_game"]:
                    break
            except OSError:
                pass
            time.sleep(2)
        else:
            sys.exit(f"no match after {seconds} s: docker logs {CONTAINER}")
        vote = self.work / "game" / "userraw" / "scriptdata" / "vote.txt"
        for line in vote.read_text().splitlines():
            kind, key, name, *_ = line.split("\t") + [""]
            (self.maps if kind == "map" else self.modes)[key] = name

    def stop(self, keep: bool) -> None:
        if keep:
            print(f"left running: {CONTAINER}, web UI http://127.0.0.1:{UI_PORT} (password {PASSWORD})")
            return
        sh("docker", "rm", "-f", CONTAINER, check=False, quiet=True)
        # the server wrote these as root
        sh("docker", "run", "--rm", "--entrypoint", "rm", "-v", f"{self.work}:/w", IMAGE, "-rf", "/w/game", "/w/data")

    def next_up(self, map_id: str, mode: str) -> str:
        return f"Next up: {self.maps[map_id]}, {self.modes[mode]}"

    def establish(self, map_id: str, mode: str) -> None:
        """A known next match to start a test from, its announcements out of the way."""
        rcon(f"set sv_vote_map {map_id}")
        rcon(f"set sv_vote_mode {mode}")
        time.sleep(SETTLE)
        self.log.mark()


# ---------- the tests: each returns the problems it found ("" = none) ----------


def t_match_start(s: Server) -> str:
    """The match start announces the next match, bold (announceStart)."""
    if any(bold for _, bold, _ in s.started):
        return ""
    return f"no bold announcement at the match start: {s.started}"


def t_single_change(s: Server) -> str:
    """One dvar changed (as !map does): announced once, right, and soon."""
    s.establish("mp_terminal", "sd")
    t0 = time.monotonic()
    rcon("set sv_vote_map mp_highrise")
    seen, loaded = s.log.watch(SETTLE, t0)
    want = s.next_up("mp_highrise", "sd")
    if loaded:
        return "RETRY"
    if [text for _, _, text in seen] != [want]:
        return f"wanted one {want!r}, got {seen}"
    if seen[0][0] > LATENCY:
        return f"announced {seen[0][0]} s after the change, more than {LATENCY} s"
    return ""


PICKS = [("mp_highrise", "dom"), ("mp_favela", "war"), ("mp_crash", "sd"), ("mp_terminal", "dm")]


def t_web_picks(s: Server) -> str:
    """Picks of map and mode from the web UI / mini app (/api/select): the pick is what's announced last."""
    s.establish("mp_terminal", "sd")
    problems = []
    for map_id, mode in PICKS:
        s.log.mark()
        t0 = time.monotonic()
        api("/api/select", {"map": map_id, "gametype": mode})
        seen, loaded = s.log.watch(SETTLE, t0)
        if loaded:
            return "RETRY"
        want = s.next_up(map_id, mode)
        if not seen or seen[-1][2] != want:
            problems.append(f"{map_id} {mode}: wanted {want!r} last, got {seen}")
    return "; ".join(problems)


def t_same_pick(s: Server) -> str:
    """Picking what is already next announces nothing."""
    s.establish("mp_terminal", "sd")
    t0 = time.monotonic()
    api("/api/select", {"map": "mp_terminal", "gametype": "sd"})
    seen, loaded = s.log.watch(SETTLE, t0)
    if loaded:
        return "RETRY"
    return f"announced {seen}" if seen else ""


TESTS = [t_match_start, t_single_change, t_web_picks, t_same_pick]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--gsc", type=Path, default=UI / "vote.gsc")
    p.add_argument("--game", type=Path, default=Path.home() / "Games" / "iw4x" / "game")
    p.add_argument("--work", type=Path, default=Path.home() / ".cache" / "iw4x-vote-test")
    p.add_argument("--keep", action="store_true", help="leave the server running afterwards")
    p.add_argument("--no-build", action="store_true", help="use the image as it is")
    p.add_argument("-k", dest="only", help="run only the tests whose name contains this")
    a = p.parse_args()
    if not (a.game / "iw4x.exe").exists():
        sys.exit(f"no IW4x in {a.game} (--game)")
    if not a.no_build:
        print("building the server image from services/ui ...", flush=True)
        sh("docker", "build", "-q", "-t", IMAGE, str(UI))
    s = Server(a.game, a.work, a.gsc.resolve())
    s.check_image()
    s.prepare()
    s.log.mark()  # a game folder kept from an earlier --keep run has its log already
    s.start()
    failed = 0
    try:
        print(f"testing {a.gsc}: waiting for the match ...", flush=True)
        s.wait_for_match()
        # prematch, then 3 s: from the log's start, as it can come before the status shows the match
        s.started, _ = s.log.watch(40, time.monotonic())
        for test in TESTS:
            if a.only and a.only not in test.__name__:
                continue
            for _ in range(3):
                problem = test(s)
                if problem != "RETRY":
                    break
                print(f"  {test.__name__}: a round restarted during the test, again", flush=True)
            ok = not problem
            failed += not ok
            print(f"{'PASS' if ok else 'FAIL'} {test.__name__}: {test.__doc__.splitlines()[0]}", flush=True)
            if not ok:
                print(f"     {problem}", flush=True)
    finally:
        s.stop(a.keep)
    print(f"{failed} failed" if failed else "all passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
