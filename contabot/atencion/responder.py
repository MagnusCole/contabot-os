"""
contabot/atencion/responder.py — Generación de respuestas automáticas.

Cada intent tiene un handler que pull de billing.db datos reales y
retorna texto HTML para Telegram.

Garantía: SIEMPRE retorna algo — nunca None ni excepción al caller.
"""

from __future__ import annotations

import logging
import os
from datetime import date
from typing import Any

logger = logging.getLogger(__name__)

_COMPANY_NAME = os.getenv("BOT_COMPANY_NAME", "Mi Empresa")
_ESCALATION_CONTACT = os.getenv("ESCALATION_CONTACT", "soporte")


# -- helpers de billing.db ----------------------------------------------------


def _get_billing_db():
    """Conexión de solo lectura a billing.db."""
    import sqlite3
    from pathlib import Path

    db_path = Path(__file__).resolve().parents[2] / "data" / "db" / "billing.db"
    if not db_path.exists():
        return None
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    return con


def _estado_facturas_cliente(ruc: str, mes: str | None = None) -> dict[str, Any]:
    """Estadísticas reales del cliente desde billing.db."""
    db = _get_billing_db()
    if not db:
        return {"error": "sin_db"}

    mes = mes or date.today().strftime("%Y-%m")
    try:
        rows = db.execute(
            """SELECT status AS estado, COUNT(*) AS n, SUM(monto_total) AS total
               FROM facturas
               WHERE ruc_receptor = ? AND strftime('%Y-%m', fecha) = ?
               GROUP BY status""",
            (ruc, mes),
        ).fetchall()

        if not rows:
            # Buscar por ruc_emisor también (emisores propios)
            rows = db.execute(
                """SELECT status AS estado, COUNT(*) AS n, SUM(monto_total) AS total
                   FROM facturas
                   WHERE ruc_emisor = ? AND strftime('%Y-%m', fecha) = ?
                   GROUP BY status""",
                (ruc, mes),
            ).fetchall()

        result: dict[str, Any] = {"mes": mes, "por_estado": {}, "total_n": 0, "total_monto": 0.0}
        for r in rows:
            result["por_estado"][r["estado"]] = {"n": r["n"], "monto": round(r["total"] or 0, 2)}
            result["total_n"] += r["n"]
            result["total_monto"] += r["total"] or 0
        result["total_monto"] = round(result["total_monto"], 2)
        return result
    except Exception as e:
        logger.warning("billing query error: %s", e)
        return {"error": str(e)}
    finally:
        db.close()


# -- handlers por intent ------------------------------------------------------


def _resp_saludo(cliente: str, **_: Any) -> str:
    return (
        f"Hola{', ' + cliente if cliente else ''}!\n\n"
        f"Soy el asistente de {_COMPANY_NAME}. En que le ayudo?\n\n"
        f"Puede preguntarme sobre:\n"
        f"- Estado de sus facturas del mes\n"
        f"- Solicitar el reporte/Excel\n"
        f"- Reportar algun problema\n"
        f"- Consultar tarifas\n\n"
        f"Tambien puede enviarnos su lista de trabajo directamente."
    )


def _resp_gracias(**_: Any) -> str:
    return "Con gusto! Estamos para servirle.\nSi necesita algo mas, escribanos."


def _resp_estado_facturas(cliente: str, ruc: str, extras: dict[str, Any], **_: Any) -> str:
    mes = extras.get("mes") or date.today().strftime("%Y-%m")
    if not ruc:
        return (
            "Para consultarle el estado de sus facturas necesito su RUC.\n"
            "Me puede confirmar su numero de RUC?"
        )

    datos = _estado_facturas_cliente(ruc, mes)
    if "error" in datos:
        return (
            "Disculpe, en este momento no puedo consultar el estado online.\n"
            "Le confirmare en breve."
        )

    if datos["total_n"] == 0:
        return (
            f"No encuentro facturas registradas para el periodo <b>{mes}</b>.\n"
            f"El trabajo ya fue enviado para procesar?"
        )

    lineas = [f"<b>Estado facturas {mes}</b> -- {cliente}:\n"]
    etiquetas = {
        "emitted": "Emitidas",
        "pending": "Pendientes",
        "failed": "Con error",
        "cancelled": "Anuladas",
        "retry": "Reintentando",
    }
    for estado, info in sorted(datos["por_estado"].items()):
        label = etiquetas.get(estado, estado.title())
        lineas.append(f"  {label}: <b>{info['n']}</b>  (S/{info['monto']:,.2f})")

    lineas.append(f"\n  <b>Total: {datos['total_n']} facturas -- S/{datos['total_monto']:,.2f}</b>")
    return "\n".join(lineas)


def _resp_solicitar_reporte(cliente: str, **_: Any) -> str:
    mes = date.today().strftime("%Y-%m")
    return (
        f"Perfecto, {cliente}. Generamos el reporte de <b>{mes}</b> y se lo enviamos en breve.\n\n"
        f"Incluye: facturas emitidas, montos, estado, resumen por serie.\n"
        f"Tiempo estimado: 5-10 minutos.\n\n"
        f"Si necesita un mes diferente, indiquenos el periodo (ej: 2026-01)."
    )


def _resp_solicitar_anulacion(cliente: str, extras: dict[str, Any], **_: Any) -> str:
    nro = extras.get("numero_factura")
    if nro:
        return (
            f"Recibido, {cliente}. Procesaremos la anulacion de <b>{nro}</b>.\n\n"
            f"Recuerde que SUNAT solo permite anular dentro de los 7 dias corridos.\n"
            f"Le confirmaremos cuando este lista."
        )
    return (
        f"Entendido, {cliente}. Para procesar la anulacion necesitamos:\n\n"
        f"1. Numero de factura (ej: E001-123)\n"
        f"2. Motivo de la anulacion\n\n"
        f"SUNAT solo permite anular dentro de los 7 dias corridos de emision."
    )


def _resp_urgente(cliente: str, texto: str, **_: Any) -> str:
    return (
        f"Entendido, {cliente} -- lo atendemos con <b>prioridad URGENTE</b>.\n\n"
        f"Su solicitud ha sido escalada a nuestro equipo.\n"
        f"Recibira respuesta en maximo <b>1 hora</b>.\n\n"
        f'<i>Mensaje recibido: "{texto[:120]}{"..." if len(texto) > 120 else ""}"</i>'
    )


def _resp_queja(cliente: str, texto: str, **_: Any) -> str:
    return (
        f"Lamentamos el inconveniente, {cliente}.\n\n"
        f"Su reporte ha sido registrado con <b>prioridad alta</b> y nuestro equipo lo revisara de inmediato.\n\n"
        f"Le contactaremos en maximo <b>2 horas</b> con una solucion.\n\n"
        f'<i>Detalle registrado: "{texto[:150]}{"..." if len(texto) > 150 else ""}"</i>'
    )


def _resp_consulta_precio(cliente: str, **_: Any) -> str:
    return (
        f"Hola {cliente}. Para consultarle nuestra estructura de tarifas,\n"
        f"favor contactenos directamente con {_ESCALATION_CONTACT}:\n\n"
        f"Le indicaremos precio segun volumen y tipo de comprobantes.\n\n"
        f"Le puedo ayudar en algo mas?"
    )


def _resp_adjuntar_documento(cliente: str, **_: Any) -> str:
    return (
        f"Recibido, {cliente}.\n\n"
        f"Por favor envie el archivo directamente aqui (Word .docx, Excel .xlsx o PDF).\n"
        f"Procesaremos su lista de trabajo en cuanto lo recibamos.\n\n"
        f"Tiempo de procesamiento estimado segun volumen."
    )


def _resp_otro(cliente: str, texto: str, **_: Any) -> str:
    return (
        f"Gracias por escribirnos, {cliente}.\n\n"
        f"Su mensaje fue registrado y nuestro equipo le respondera pronto.\n\n"
        f"Si su consulta es urgente, puede indicarnoslo y la atendemos con prioridad."
    )


# -- dispatcher ---------------------------------------------------------------

_HANDLERS = {
    "saludo": _resp_saludo,
    "gracias": _resp_gracias,
    "estado_facturas": _resp_estado_facturas,
    "solicitar_reporte": _resp_solicitar_reporte,
    "solicitar_anulacion": _resp_solicitar_anulacion,
    "urgente": _resp_urgente,
    "queja": _resp_queja,
    "consulta_precio": _resp_consulta_precio,
    "adjuntar_documento": _resp_adjuntar_documento,
    "otro": _resp_otro,
}


def generar_respuesta(
    intent: str,
    texto: str,
    cliente: str = "",
    ruc: str = "",
    extras: dict[str, Any] | None = None,
) -> str:
    """
    Genera respuesta HTML para Telegram dado un intent clasificado.
    Nunca falla -- siempre retorna texto.
    """
    handler = _HANDLERS.get(intent, _resp_otro)
    try:
        return handler(
            cliente=cliente,
            ruc=ruc,
            texto=texto,
            extras=extras or {},
        )
    except Exception as e:
        logger.exception("Error en handler %s: %s", intent, e)
        return f"Gracias {cliente}. Su consulta fue recibida y le responderemos pronto."


def es_auto_resoluble(intent: str) -> bool:
    """True si el bot puede resolver sin intervención humana."""
    return intent in {
        "saludo",
        "gracias",
        "estado_facturas",
        "consulta_precio",
        "solicitar_reporte",
        "adjuntar_documento",
    }


def prioridad_por_intent(intent: str) -> str:
    """Prioridad inicial del ticket según el intent."""
    return {
        "urgente": "urgente",
        "queja": "alta",
        "solicitar_anulacion": "alta",
        "estado_facturas": "normal",
        "solicitar_reporte": "normal",
        "adjuntar_documento": "normal",
        "consulta_precio": "baja",
        "saludo": "baja",
        "gracias": "baja",
        "otro": "normal",
    }.get(intent, "normal")
