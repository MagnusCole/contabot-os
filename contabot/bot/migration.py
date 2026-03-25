"""contabot.bot.migration — Tablas para ContaBot clientes."""

from __future__ import annotations

import logging

from contabot.db.connection import get_conn

logger = logging.getLogger(__name__)


def run() -> None:
    """Crea tabla contabot_clientes si no existe."""
    conn = get_conn()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS contabot_clientes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telefono TEXT NOT NULL UNIQUE,
                ruc TEXT NOT NULL,
                razon_social TEXT,
                ruc_emisor TEXT,
                plan TEXT DEFAULT 'free',
                activo INTEGER DEFAULT 1,
                dia_reporte INTEGER DEFAULT 1,
                last_message_at TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_contabot_telefono
                ON contabot_clientes(telefono);

            CREATE INDEX IF NOT EXISTS idx_contabot_ruc
                ON contabot_clientes(ruc);
        """)
        conn.commit()
        logger.info("Tabla contabot_clientes verificada")
    finally:
        conn.close()
