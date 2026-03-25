from __future__ import annotations

"""
migration.py — Idempotent DDL migration for ContaBot.

Creates all required tables and indexes. Each operation checks for prior
existence so this script can be executed N times safely.

Usage::

    python -m contabot.db.migration

Or from code::

    from contabot.db.migration import run_migrations
    run_migrations()
"""

import logging
import sqlite3
from pathlib import Path

from contabot.db.connection import DB_PATH as _DB_PATH

logger = logging.getLogger(__name__)

# ── Core table DDL ───────────────────────────────────────────────────────────

_DDL_EMISORES = """
CREATE TABLE IF NOT EXISTS emisores (
    ruc         TEXT PRIMARY KEY,
    nombre      TEXT,
    activo      INTEGER NOT NULL DEFAULT 1,
    updated_at  TEXT,
    empresa     TEXT,
    rubro       TEXT,
    direccion   TEXT
);
"""

_DDL_CLIENTES = """
CREATE TABLE IF NOT EXISTS clientes (
    ruc             TEXT PRIMARY KEY,
    razon_social    TEXT,
    direccion       TEXT,
    updated_at      TEXT
);
"""

_DDL_FACTURAS = """
CREATE TABLE IF NOT EXISTS facturas (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ruc_emisor      TEXT NOT NULL,
    nombre_emisor   TEXT NOT NULL,
    ruc_receptor    TEXT NOT NULL,
    fecha           TEXT NOT NULL,
    monto_subtotal  REAL NOT NULL DEFAULT 0,
    monto_igv       REAL NOT NULL DEFAULT 0,
    monto_total     REAL NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('draft','pending','processing','emitted',
                          'emitted_no_pdf','failed','cancelled','retry',
                          'anulada','pending_validation','completed',
                          'validation_failed')),
    empresa         TEXT,
    pdf_path        TEXT,
    error           TEXT,
    notas           TEXT,
    attempts        INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now','localtime')),
    emitted_at      TEXT,
    revision_manual INTEGER NOT NULL DEFAULT 0,
    notas_revision  TEXT,
    retry_after     TEXT,
    source_file     TEXT,
    trabajo_id      INTEGER
);
"""

_DDL_FACTURAS_ITEMS = """
CREATE TABLE IF NOT EXISTS facturas_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    factura_id      INTEGER NOT NULL REFERENCES facturas(id),
    descripcion     TEXT    NOT NULL,
    unidad_medida   TEXT    DEFAULT 'UNIDAD',
    cantidad        REAL,
    precio_sin_igv  REAL,
    subtotal        REAL    DEFAULT 0.0,
    es_pivot        INTEGER NOT NULL DEFAULT 0
);
"""

_DDL_CLIENT_EMISORES = """
CREATE TABLE IF NOT EXISTS client_emisores (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ruc_cliente TEXT    NOT NULL,
    ruc_emisor  TEXT    NOT NULL,
    orden       INTEGER DEFAULT 0,
    activo      INTEGER DEFAULT 1,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(ruc_cliente, ruc_emisor)
);
"""

_DDL_COMPRAS = """
CREATE TABLE IF NOT EXISTS compras (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    ruc_comprador               TEXT    NOT NULL,
    tipo_documento_proveedor    TEXT    NOT NULL DEFAULT '6',
    ruc_proveedor               TEXT    NOT NULL,
    razon_social_proveedor      TEXT    NOT NULL,
    tipo_comprobante            TEXT    NOT NULL DEFAULT '01',
    serie                       TEXT    NOT NULL,
    numero                      TEXT    NOT NULL,
    fecha_emision               DATE    NOT NULL,
    fecha_vencimiento           DATE,
    monto_subtotal              REAL    NOT NULL DEFAULT 0.0,
    monto_igv                   REAL    NOT NULL DEFAULT 0.0,
    monto_no_gravado            REAL    NOT NULL DEFAULT 0.0,
    monto_total                 REAL    NOT NULL DEFAULT 0.0,
    moneda                      TEXT    NOT NULL DEFAULT 'PEN',
    tipo_cambio                 REAL    NOT NULL DEFAULT 1.0,
    categoria                   TEXT    NOT NULL DEFAULT 'otros',
    descripcion                 TEXT,
    tiene_credito_fiscal        INTEGER NOT NULL DEFAULT 1,
    pagado                      INTEGER NOT NULL DEFAULT 0,
    fecha_pago                  DATE,
    archivo_path                TEXT,
    notas                       TEXT,
    created_at                  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at                  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

_DDL_CONTABOT_CLIENTES = """
CREATE TABLE IF NOT EXISTS contabot_clientes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    telefono        TEXT    NOT NULL UNIQUE,
    ruc             TEXT    NOT NULL,
    razon_social    TEXT,
    ruc_emisor      TEXT,
    plan            TEXT    NOT NULL DEFAULT 'basico',
    activo          INTEGER NOT NULL DEFAULT 1,
    dia_reporte     INTEGER NOT NULL DEFAULT 1,
    hora_reporte    TEXT    NOT NULL DEFAULT '08:00',
    onboarded_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_message_at DATETIME
);
"""

_DDL_TRABAJOS = """
CREATE TABLE IF NOT EXISTS trabajos (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id                   INTEGER,
    ruc_cliente                 TEXT    NOT NULL,
    ruc_emisor                  TEXT,
    mes                         TEXT    NOT NULL,
    descripcion                 TEXT,
    monto_total_contrato        REAL    NOT NULL DEFAULT 0.0,
    monto_emitido_actual        REAL    NOT NULL DEFAULT 0.0,
    monto_pendiente             REAL    NOT NULL DEFAULT 0.0,
    fecha_inicio                DATE,
    fecha_fin_proyectada        DATE,
    pdf_folder                  TEXT,
    pdf_count                   INTEGER NOT NULL DEFAULT 0,
    ultima_actualizacion_pdf    DATETIME,
    estado                      TEXT    NOT NULL DEFAULT 'activo',
    created_at                  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at                  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

_DDL_ITEMS_CATALOGO = """
CREATE TABLE IF NOT EXISTS items_catalogo (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    ruc_cliente             TEXT,
    descripcion             TEXT    NOT NULL,
    unidad                  TEXT    NOT NULL DEFAULT 'UNIDAD',
    categoria               TEXT,
    precio_unitario_base    REAL    NOT NULL DEFAULT 0.0,
    precio_min              REAL    NOT NULL DEFAULT 0.0,
    precio_max              REAL    NOT NULL DEFAULT 0.0,
    cantidad_tipica         REAL    NOT NULL DEFAULT 1.0,
    frecuencia              INTEGER NOT NULL DEFAULT 1,
    ultima_variacion        DATETIME,
    activo                  INTEGER NOT NULL DEFAULT 1,
    created_at              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

# ── Indexes ──────────────────────────────────────────────────────────────────

_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_facturas_status     ON facturas(status)",
    "CREATE INDEX IF NOT EXISTS idx_facturas_emisor     ON facturas(ruc_emisor)",
    "CREATE INDEX IF NOT EXISTS idx_facturas_receptor   ON facturas(ruc_receptor)",
    "CREATE INDEX IF NOT EXISTS idx_facturas_fecha      ON facturas(fecha)",
    "CREATE INDEX IF NOT EXISTS idx_facturas_empresa    ON facturas(empresa)",
    "CREATE INDEX IF NOT EXISTS ix_client_emisores_ruc  ON client_emisores(ruc_cliente)",
    "CREATE INDEX IF NOT EXISTS ix_compras_periodo      ON compras(ruc_comprador, fecha_emision)",
    "CREATE INDEX IF NOT EXISTS ix_compras_proveedor    ON compras(ruc_proveedor)",
    "CREATE INDEX IF NOT EXISTS ix_compras_comprobante  ON compras(serie, numero, ruc_proveedor)",
    "CREATE INDEX IF NOT EXISTS ix_contabot_ruc         ON contabot_clientes(ruc)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_trabajo_cliente_mes ON trabajos(ruc_cliente, mes)",
    "CREATE INDEX IF NOT EXISTS ix_trabajos_mes         ON trabajos(mes)",
    "CREATE INDEX IF NOT EXISTS ix_items_catalogo_desc_cliente ON items_catalogo(descripcion, ruc_cliente)",
    "CREATE INDEX IF NOT EXISTS ix_items_catalogo_categoria    ON items_catalogo(categoria)",
]

# ── Helpers ──────────────────────────────────────────────────────────────────


def _table_exists(cur: sqlite3.Cursor, table: str) -> bool:
    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    )
    return cur.fetchone() is not None


def _add_column_if_missing(
    cur: sqlite3.Cursor,
    table: str,
    column: str,
    definition: str,
) -> bool:
    """Add a column to a table if it does not already exist.

    Returns:
        True if the column was added, False if it already existed.
    """
    cur.execute(f"PRAGMA table_info({table})")
    cols = {row[1] for row in cur.fetchall()}
    if column in cols:
        logger.debug("Column %s.%s already exists — skip", table, column)
        return False

    cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    logger.info("Column %s.%s added", table, column)
    return True


# ── Main runner ──────────────────────────────────────────────────────────────


def run_migrations(db_path: Path | None = None) -> dict:
    """Execute all migrations idempotently.

    Args:
        db_path: Path to the SQLite file. Default: ``data/db/contabot.db``

    Returns:
        Dict summarising operations performed.
    """
    db_path = db_path or _DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)

    results: dict[str, str] = {}

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    cur = conn.cursor()

    try:
        # 1. Create tables
        tables = [
            ("emisores", _DDL_EMISORES),
            ("clientes", _DDL_CLIENTES),
            ("facturas", _DDL_FACTURAS),
            ("facturas_items", _DDL_FACTURAS_ITEMS),
            ("client_emisores", _DDL_CLIENT_EMISORES),
            ("compras", _DDL_COMPRAS),
            ("contabot_clientes", _DDL_CONTABOT_CLIENTES),
            ("trabajos", _DDL_TRABAJOS),
            ("items_catalogo", _DDL_ITEMS_CATALOGO),
        ]
        for name, ddl in tables:
            before = _table_exists(cur, name)
            cur.executescript(ddl)
            results[f"table_{name}"] = "already_existed" if before else "created"
            logger.info("Table %s: %s", name, results[f"table_{name}"])

        # 2. Create indexes
        for idx_ddl in _INDEXES:
            try:
                cur.execute(idx_ddl)
            except Exception as exc:
                logger.warning("Index skipped: %s", exc)

        conn.commit()

    except Exception as exc:
        conn.rollback()
        logger.error("Migration error: %s", exc)
        results["error"] = str(exc)
        raise
    finally:
        conn.close()

    return results


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    print(f"\nRunning migrations on: {_DB_PATH}")
    print("-" * 60)

    results = run_migrations()

    for key, val in results.items():
        icon = "+" if "error" not in key else "!"
        print(f"  [{icon}] {key}: {val}")

    print("-" * 60)
    if "error" not in results:
        print("Migration completed successfully.\n")
    else:
        print(f"ERROR: {results.get('error')}\n")


if __name__ == "__main__":
    main()
