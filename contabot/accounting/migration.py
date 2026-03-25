"""contabot.accounting.migration -- DDL for unit economics (LTV/CAC).

Adds acquisition columns to compras and creates the monthly spend table.
Idempotent -- safe to run multiple times.
"""

from __future__ import annotations

import logging
import sqlite3

from contabot.db.connection import DB_PATH

logger = logging.getLogger(__name__)

_DDL_GASTO_ADQUISICION = """
CREATE TABLE IF NOT EXISTS gasto_adquisicion_mensual (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    periodo     TEXT    NOT NULL,
    canal       TEXT    NOT NULL DEFAULT 'total',
    monto       REAL    NOT NULL DEFAULT 0.0,
    ruc_emisor  TEXT,
    notas       TEXT,
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(periodo, canal, ruc_emisor)
);
"""

_DDL_GASTO_IDX = """
CREATE INDEX IF NOT EXISTS ix_gasto_adq_periodo
    ON gasto_adquisicion_mensual(periodo);
"""


def _table_exists(cur: sqlite3.Cursor, name: str) -> bool:
    """Check if a table exists in the database."""
    cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    )
    return cur.fetchone() is not None


def _add_column_if_missing(
    cur: sqlite3.Cursor, table: str, column: str, col_def: str
) -> None:
    """Add a column to a table if it doesn't already exist."""
    cur.execute(f"PRAGMA table_info({table})")
    existing = {row[1] for row in cur.fetchall()}
    if column not in existing:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")
        logger.info("Added column %s.%s", table, column)


def run(db_path: str | None = None) -> None:
    """Execute accounting migrations. Idempotent."""
    path = db_path or str(DB_PATH)
    conn = sqlite3.connect(path)
    cur = conn.cursor()

    try:
        # 1. New columns on compras
        _add_column_if_missing(cur, "compras", "es_adquisicion", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(cur, "compras", "canal_adquisicion", "TEXT")

        # 2. Monthly acquisition spend table
        if not _table_exists(cur, "gasto_adquisicion_mensual"):
            cur.executescript(_DDL_GASTO_ADQUISICION + _DDL_GASTO_IDX)
            logger.info("Table gasto_adquisicion_mensual created")
        else:
            logger.debug("Table gasto_adquisicion_mensual already exists -- skip")

        conn.commit()
        logger.info("Accounting migrations completed")
    finally:
        conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
