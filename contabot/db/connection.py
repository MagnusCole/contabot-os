from __future__ import annotations

"""
connection.py — Single source of truth for database path and raw SQLite connections.

Every module that needs a raw sqlite3 connection imports from here:

    from contabot.db.connection import get_conn, DB_PATH

Override via the DATABASE_PATH environment variable:
    DATABASE_PATH=/tmp/test.db python -m contabot ...
"""

import os
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = Path(os.getenv("DATABASE_PATH", str(_PROJECT_ROOT / "data" / "db" / "contabot.db")))


def get_conn(
    db_path: Path | str | None = None,
    *,
    wal: bool = True,
    fk: bool = True,
    row_factory: bool = True,
) -> sqlite3.Connection:
    """Open a sqlite3 connection with production-safe defaults.

    - journal_mode = WAL  (safe concurrency, default ON)
    - foreign_keys = ON   (referential integrity, default ON)
    - row_factory  = sqlite3.Row (access by column name, default ON)
    - busy_timeout = 5000 ms (wait before SQLITE_BUSY)

    Example::

        con = get_conn()
        rows = con.execute("SELECT * FROM facturas WHERE status='pending'").fetchall()
        con.close()
    """
    path = str(db_path or DB_PATH)
    con = sqlite3.connect(path, timeout=10.0)
    con.execute("PRAGMA busy_timeout = 5000")
    if wal:
        con.execute("PRAGMA journal_mode = WAL")
    if fk:
        con.execute("PRAGMA foreign_keys = ON")
    if row_factory:
        con.row_factory = sqlite3.Row
    return con


@contextmanager
def db_conn(
    db_path: Path | str | None = None,
    *,
    wal: bool = True,
    fk: bool = True,
    row_factory: bool = True,
) -> Generator[sqlite3.Connection, None, None]:
    """Context manager for a safe connection — always closes.

    Example::

        with db_conn() as con:
            con.execute("UPDATE facturas SET status='emitted' WHERE id=?", (fid,))
            con.commit()
    """
    con = get_conn(db_path, wal=wal, fk=fk, row_factory=row_factory)
    try:
        yield con
    finally:
        con.close()
