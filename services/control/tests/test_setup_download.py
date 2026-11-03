"""scripts/linux/setup.sh's parallel download (a game server's first boot): its own functions, run
against a local server that answers ranges, drops some connections and is slow on others."""

import os
import re
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SETUP = Path(__file__).resolve().parents[3] / "scripts/linux/setup.sh"
DATA = bytes(i % 251 for i in range(160_000))  # 16 parts of 10 000 bytes
PART = len(DATA) // 16


def functions(tries: int = 30) -> str:
    """size_of, fetch_part, fetch_parallel and parts_size, as setup.sh has them."""
    script = SETUP.read_text().replace("PART_TRIES=30", f"PART_TRIES={tries}")
    size_of = re.search(r"^size_of\(\) \{.*\}$", script, re.MULTILINE)[0]
    start = script.index("# Download $1 ($2 bytes)")
    end = script.index("\n}\n", script.index("parts_size() {")) + 3
    return size_of + "\n" + script[start:end]


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, fail_first=(), slow=None, fail_always=()):
        self.fail_first, self.slow, self.fail_always = set(fail_first), slow or {}, set(fail_always)
        self.log: list[tuple[float, int, str]] = []  # (time, part, what)
        self.lock = threading.Lock()
        super().__init__(("127.0.0.1", 0), Handler)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        server: Server = self.server
        first, last = map(int, re.match(r"bytes=(\d+)-(\d+)", self.headers["Range"]).groups())
        part = first // PART
        with server.lock:
            failing = part in server.fail_first or part in server.fail_always
            server.fail_first.discard(part)
            server.log.append((time.monotonic(), part, "fail" if failing else "start"))
        if failing:  # the connection drops: what Istanbul's network does to some of them
            self.send_response(503)
            self.end_headers()
            return
        body = DATA[first : last + 1]
        self.send_response(206)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        time.sleep(server.slow.get(part, 0))
        self.wfile.write(body)
        with server.lock:
            server.log.append((time.monotonic(), part, "done"))


def download(tmp_path: Path, server: Server, tries: int = 30) -> subprocess.CompletedProcess:
    url = f"http://127.0.0.1:{server.server_address[1]}/mw.zip"
    harness = f"""set -euo pipefail
{functions(tries)}
fetch_parallel '{url}' {len(DATA)} '{tmp_path}/mw.zip'
"""
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        env = {**os.environ, "LC_ALL": "C"}
        return subprocess.run(["bash", "-c", harness], capture_output=True, timeout=60, env=env)
    finally:
        server.shutdown()


def test_a_dropped_part_tries_again_without_waiting_for_a_slow_one(tmp_path):
    server = Server(fail_first={3, 7}, slow={12: 6.0})
    run = download(tmp_path, server)
    assert run.returncode == 0, run.stderr.decode()
    assert (tmp_path / "mw.zip").read_bytes() == DATA
    assert not (tmp_path / "mw.zip.parts").exists()
    slow_done = next(t for t, part, what in server.log if part == 12 and what == "done")
    for dropped in (3, 7):
        retried = [t for t, part, what in server.log if part == dropped and what == "start"]
        # the old rounds waited for every part (the slow one too) before trying any again
        assert retried and retried[0] < slow_done


def test_a_part_that_never_comes_fails_the_download(tmp_path):
    run = download(tmp_path, Server(fail_always={5}), tries=2)
    assert run.returncode != 0
    assert (tmp_path / "mw.zip.parts").exists()  # kept: a re-run resumes the parts
