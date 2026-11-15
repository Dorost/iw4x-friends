import sqlite3
import time

from control.db import OFF, Server, connect


def test_reads_go_on_while_another_connection_writes(tmp_path):
    """The web UI's threads and the orchestrator write at the same time: a read must not fail
    with "database is locked" (a boot that hit it failed, Istanbul)."""
    path = tmp_path / "control.db"
    db = connect(path)
    with db.begin() as s:
        s.add(Server(name="ist", status=OFF))
    writer = sqlite3.connect(path, isolation_level=None)
    writer.execute("BEGIN EXCLUSIVE")
    writer.execute("UPDATE servers SET step = 'busy' WHERE name = 'ist'")
    started = time.monotonic()
    try:
        with db.begin() as s:
            assert s.get(Server, "ist").step == ""  # the last committed state
    finally:
        writer.execute("ROLLBACK")
        writer.close()
    assert time.monotonic() - started < 1


def test_wal_and_busy_timeout(tmp_path):
    db = connect(tmp_path / "control.db")
    with db.begin() as s:
        conn = s.connection().connection.dbapi_connection
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 30000
