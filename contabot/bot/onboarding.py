"""contabot/bot/onboarding.py — Registro y lookup de MYPES en ContaBot."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime

from contabot.db.connection import get_conn

logger = logging.getLogger(__name__)

_RUC_RE = re.compile(r"^\d{11}$")


@dataclass
class ContaBotCliente:
    id: int
    telefono: str
    ruc: str
    razon_social: str | None
    ruc_emisor: str | None
    plan: str
    activo: bool
    dia_reporte: int = 1  # 1=lunes


def obtener_cliente(telefono: str) -> ContaBotCliente | None:
    """Busca cliente por número de teléfono."""
    telefono = _normalizar_telefono(telefono)
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM contabot_clientes WHERE telefono = ? AND activo = 1",
            (telefono,),
        ).fetchone()
        if not row:
            return None
        return ContaBotCliente(
            id=row["id"],
            telefono=row["telefono"],
            ruc=row["ruc"],
            razon_social=row["razon_social"],
            ruc_emisor=row["ruc_emisor"],
            plan=row["plan"],
            activo=bool(row["activo"]),
        )
    finally:
        conn.close()


def esta_registrado(telefono: str) -> bool:
    return obtener_cliente(telefono) is not None


def registrar_mype(telefono: str, ruc: str) -> str:
    """Registra nueva MYPE. Retorna mensaje de confirmación o error."""
    telefono = _normalizar_telefono(telefono)

    if not _RUC_RE.match(ruc):
        return "El RUC debe tener exactamente 11 digitos. Intenta de nuevo."

    # Verificar si ya existe
    if esta_registrado(telefono):
        cliente = obtener_cliente(telefono)
        return f"Ya estas registrado con RUC {cliente.ruc} ({cliente.razon_social or 'sin nombre'})."

    # Buscar razón social en clientes existentes o SUNAT
    razon_social = _buscar_razon_social(ruc)

    conn = get_conn()
    try:
        conn.execute(
            """
            INSERT INTO contabot_clientes (telefono, ruc, razon_social)
            VALUES (?, ?, ?)
            """,
            (telefono, ruc, razon_social),
        )
        conn.commit()
        logger.info("MYPE registrada: %s -> %s (%s)", telefono, ruc, razon_social)
    finally:
        conn.close()

    nombre = razon_social or ruc
    return (
        f"Listo! Te registre como *{nombre}*\n\n"
        f"Ahora puedo:\n"
        f"Registrar gastos con foto\n"
        f"Darte tu estado financiero\n"
        f"Calcular tus impuestos SUNAT\n"
        f"Enviarte reporte cada lunes\n\n"
        f"Empieza mandandome una foto de factura o escribe *estado*"
    )


def actualizar_last_message(telefono: str) -> None:
    """Actualiza timestamp del último mensaje."""
    telefono = _normalizar_telefono(telefono)
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE contabot_clientes SET last_message_at = ? WHERE telefono = ?",
            (datetime.now().isoformat(), telefono),
        )
        conn.commit()
    finally:
        conn.close()


def listar_clientes_activos() -> list[ContaBotCliente]:
    """Lista todos los clientes activos para reportes programados."""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM contabot_clientes WHERE activo = 1"
        ).fetchall()
        return [
            ContaBotCliente(
                id=r["id"], telefono=r["telefono"], ruc=r["ruc"],
                razon_social=r["razon_social"], ruc_emisor=r["ruc_emisor"],
                plan=r["plan"], activo=True, dia_reporte=r["dia_reporte"],
            )
            for r in rows
        ]
    finally:
        conn.close()


def _normalizar_telefono(tel: str) -> str:
    """Normaliza a formato 51XXXXXXXXX."""
    tel = re.sub(r"[^\d]", "", tel)
    if tel.startswith("+"):
        tel = tel[1:]
    if len(tel) == 9 and tel.startswith("9"):
        tel = "51" + tel
    return tel


def _buscar_razon_social(ruc: str) -> str | None:
    """Busca razón social en la base de datos de clientes."""
    conn = get_conn()
    try:
        # Primero en tabla clientes
        row = conn.execute(
            "SELECT razon_social FROM clientes WHERE ruc = ?", (ruc,)
        ).fetchone()
        if row and row["razon_social"]:
            return row["razon_social"]

        # Luego en emisores (por si es un emisor)
        row = conn.execute(
            "SELECT nombre FROM emisores WHERE ruc = ?", (ruc,)
        ).fetchone()
        if row and row["nombre"]:
            return row["nombre"]

        return None
    finally:
        conn.close()


MSG_ONBOARDING = (
    "Hola! Soy *ContaBot*, tu contador IA.\n\n"
    "Para empezar, enviame tu *RUC* (11 digitos).\n\n"
    "Despues podre:\n"
    "Registrar tus facturas/boletas con foto\n"
    "Darte tu estado financiero al instante\n"
    "Calcular tus impuestos SUNAT\n"
    "Enviarte reporte semanal cada lunes"
)
