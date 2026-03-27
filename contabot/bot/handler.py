"""contabot/bot/handler.py — Handler principal de ContaBot.

Recibe mensaje -> clasifica intent -> ejecuta pipeline -> retorna respuesta WhatsApp.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path

from contabot.db.connection import get_conn

from .onboarding import (
    MSG_ONBOARDING,
    actualizar_last_message,
    esta_registrado,
    obtener_cliente,
    registrar_mype,
)

logger = logging.getLogger(__name__)

# -- Intent mapping (simple keyword match) ------------------------------------

_INTENT_KEYWORDS: dict[str, list[str]] = {
    "estado_financiero": [
        "estado", "reporte", "cómo voy", "como voy", "resumen",
        "p&l", "situación", "situacion", "balance",
    ],
    "impuestos": [
        "impuesto", "sunat", "igv", "cuánto debo", "cuanto debo",
        "declarar", "pdt", "tributo", "obligacion",
    ],
    "gastos_mes": [
        "gasto", "compra", "qué he gastado", "que he gastado",
        "egresos", "cuánto llevo", "cuanto llevo",
    ],
    "ayuda": [
        "ayuda", "help", "qué puedes", "que puedes", "comando",
        "menu", "menú", "opciones",
    ],
}

_RUC_RE = re.compile(r"^\d{11}$")


def _clasificar_intent(texto: str) -> str:
    """Clasifica el intent del mensaje por keywords."""
    texto_lower = texto.lower().strip()
    for intent, keywords in _INTENT_KEYWORDS.items():
        for kw in keywords:
            if kw in texto_lower:
                return intent
    return "otro"


async def procesar_mensaje(
    telefono: str,
    tipo: str,
    contenido: str,
    media_path: Path | None = None,
) -> str:
    """Procesa un mensaje entrante y retorna la respuesta.

    Args:
        telefono: Numero del remitente (51XXXXXXXXX).
        tipo: "text", "image", "document".
        contenido: Texto del mensaje (o caption de media).
        media_path: Ruta local al archivo descargado (fotos/docs).

    Returns:
        Texto de respuesta para enviar por WhatsApp.
    """
    # Actualizar timestamp
    if esta_registrado(telefono):
        actualizar_last_message(telefono)

    # -- Flujo de onboarding --------------------------------------------------
    if not esta_registrado(telefono):
        # Si manda un RUC, registrar
        texto_limpio = re.sub(r"[^\d]", "", contenido.strip())
        if _RUC_RE.match(texto_limpio):
            return registrar_mype(telefono, texto_limpio)
        return MSG_ONBOARDING

    cliente = obtener_cliente(telefono)

    # -- Foto/documento -> registrar gasto ------------------------------------
    if tipo in ("image", "document"):
        if not media_path or not media_path.exists():
            return (
                "Recibi tu imagen pero no pude descargarla.\n"
                "Intenta enviarla de nuevo como foto (no como archivo)."
            )
        return await _procesar_gasto_foto(cliente.ruc, media_path, contenido)

    # -- Texto -> clasificar intent -------------------------------------------
    intent = _clasificar_intent(contenido)

    if intent == "estado_financiero":
        return _generar_estado(cliente.ruc)
    elif intent == "impuestos":
        return _generar_impuestos(cliente.ruc)
    elif intent == "gastos_mes":
        return _generar_resumen_gastos(cliente.ruc)
    elif intent == "ayuda":
        return _msg_ayuda(cliente.razon_social or cliente.ruc)
    else:
        # Intent no reconocido -- dar ayuda contextual
        return (
            "No entendi tu mensaje. Puedes:\n\n"
            "*Mandar foto* de factura/boleta\n"
            "Escribir *estado* para ver tu P&L\n"
            "Escribir *impuestos* para ver obligaciones\n"
            "Escribir *gastos* para ver egresos del mes\n"
            "Escribir *ayuda* para mas opciones"
        )


# -- Handlers por intent ------------------------------------------------------


async def _procesar_gasto_foto(ruc: str, media_path: Path, contexto: str) -> str:
    """Procesa foto de factura/boleta y registra en DB."""
    try:
        from contabot.fiscal.expense_intake import ExpenseIntakeService

        service = ExpenseIntakeService()
        image_bytes = media_path.read_bytes()
        resultado = service.procesar_foto(image_bytes, contexto=contexto or "")

        if not resultado.gastos:
            return (
                "No pude leer la factura/boleta en esa imagen.\n"
                "Asegurate de que se vea bien el monto, RUC y serie.\n"
                "Intenta con otra foto mas clara."
            )

        # Registrar en DB
        from contabot.db import get_session
        with get_session() as db:
            resultado_db = service.registrar_en_db(resultado, db, ruc_comprador=ruc)

        # Formatear respuesta
        _TIPOS = {"01": "Factura", "02": "Recibo Honorarios", "03": "Boleta",
                  "07": "Nota Credito", "08": "Nota Debito", "14": "Serv. Publico"}

        lines = []
        for g in resultado.gastos:
            tipo_nombre = _TIPOS.get(g.tipo_comprobante, "Comprobante")
            lines.append(
                f"*Registrado:* {tipo_nombre} {g.serie}-{g.numero}\n"
                f"Proveedor: {g.razon_social_proveedor}\n"
                f"Total: S/ {g.monto_total:,.2f} (IGV: S/ {g.monto_igv:,.2f})\n"
                f"Categoria: {g.categoria}\n"
                f"Credito fiscal: {'Si' if g.tiene_credito_fiscal else 'No'}"
            )

        # Acumulado del mes
        periodo = date.today().strftime("%Y-%m")
        acumulado = _acumulado_gastos(ruc, periodo)
        if acumulado:
            lines.append(
                f"\n*Acumulado {_mes_nombre(periodo)}:*\n"
                f"  Gastos: S/ {acumulado['total']:,.2f}\n"
                f"  IGV credito: S/ {acumulado['igv_credito']:,.2f}"
            )

        if resultado.errores:
            lines.append(f"\n{len(resultado.errores)} items no se pudieron leer")

        return "\n".join(lines)

    except Exception as exc:
        logger.error("Error procesando foto gasto: %s", exc, exc_info=True)
        return "Hubo un error procesando la imagen. Intenta de nuevo o manda otra foto."


def _generar_estado(ruc: str) -> str:
    """Genera estado financiero del mes actual."""
    try:
        from contabot.db import get_session
        from contabot.fiscal.financial_report import generar_estado_financiero

        with get_session() as db:
            try:
                estado = generar_estado_financiero(db, ruc=ruc, meses=2)
            except Exception:
                # Si falla como emisor, intentar generar resumen manual
                return _generar_estado_como_receptor(ruc)

        p = estado.periodo_actual
        if not p or (p.ventas_brutas == 0 and p.gastos_operativos == 0):
            return _generar_estado_como_receptor(ruc)

        periodo_str = _mes_nombre(p.periodo)
        msg = (
            f"*Tu negocio -- {periodo_str}*\n\n"
            f"Ventas: S/ {p.ventas_brutas:,.2f}\n"
            f"Gastos: S/ {p.gastos_operativos:,.2f}\n"
            f"IGV por pagar: S/ {p.igv_por_pagar:,.2f}\n"
            f"Renta mensual: S/ {p.renta_mensual:,.2f}\n"
            f"Obligaciones: S/ {p.total_obligaciones:,.2f}\n\n"
            f"*Utilidad neta: S/ {p.utilidad_neta:,.2f}*\n"
            f"Margen: {p.margen_neto:.1f}%"
        )

        # Comparación con mes anterior
        p_ant = estado.periodo_anterior
        if p_ant and p_ant.ventas_brutas > 0:
            var = estado.variacion_ventas()
            if var is not None:
                direction = "sube" if var >= 0 else "baja"
                msg += f"\nvs mes anterior: {var:+.1f}% ({direction})"

        return msg

    except Exception as exc:
        logger.error("Error generando estado: %s", exc, exc_info=True)
        return "No pude generar el estado financiero. Verifica que tengas facturas registradas."


def _generar_impuestos(ruc: str) -> str:
    """Calcula obligaciones tributarias del mes."""
    periodo = date.today().strftime("%Y-%m")

    # Intentar como emisor (tiene reporte fiscal completo)
    try:
        from contabot.db import get_session
        from contabot.fiscal.report import generar_reporte_fiscal

        with get_session() as db:
            resultado = generar_reporte_fiscal(db, ruc_emisor=ruc, periodo=periodo)

        return (
            f"*Obligaciones SUNAT -- {_mes_nombre(periodo)}*\n\n"
            f"Ventas brutas: S/ {resultado.ventas_brutas:,.2f}\n"
            f"Ventas netas: S/ {resultado.ventas_netas:,.2f}\n\n"
            f"IGV por pagar: S/ {resultado.igv_por_pagar:,.2f}\n"
            f"Renta mensual: S/ {resultado.renta_mensual:,.2f}\n"
            f"{'─' * 30}\n"
            f"*Total a pagar: S/ {resultado.total_obligaciones:,.2f}*\n\n"
            f"Saldo disponible: S/ {resultado.saldo_real:,.2f}\n"
            f"% obligaciones: {resultado.porcentaje_obligaciones:.1f}%"
            + (
                f"\nVence en {resultado.dias_para_vencimiento} dias"
                if resultado.dias_para_vencimiento
                else ""
            )
        )
    except (ValueError, Exception):
        pass

    # Fallback: calcular manualmente como receptor
    try:
        from contabot.fiscal.calculator import FiscalCalculator, RegimenTributario

        conn = get_conn()
        try:
            row = conn.execute(
                "SELECT COALESCE(SUM(monto_total), 0) as ventas, "
                "COALESCE(SUM(monto_igv), 0) as igv "
                "FROM facturas WHERE ruc_receptor = ? "
                "AND strftime('%Y-%m', fecha) = ? "
                "AND status NOT IN ('cancelado', 'failed')",
                (ruc, periodo),
            ).fetchone()
        finally:
            conn.close()

        ventas = row["ventas"] if row else 0
        igv = row["igv"] if row else 0

        if ventas == 0:
            return (
                f"No encontre ventas para tu RUC en {_mes_nombre(periodo)}.\n"
                f"Cuando tengas facturas registradas, podre calcular tus impuestos."
            )

        calc = FiscalCalculator(regimen=RegimenTributario.MYPE)
        resultado = calc.calcular(
            periodo=periodo,
            ventas_brutas=ventas,
            igv_ventas=igv,
        )

        return (
            f"*Obligaciones SUNAT -- {_mes_nombre(periodo)}*\n\n"
            f"Ventas brutas: S/ {ventas:,.2f}\n"
            f"IGV por pagar: S/ {resultado.igv_por_pagar:,.2f}\n"
            f"Renta mensual: S/ {resultado.renta_mensual:,.2f}\n"
            f"{'─' * 30}\n"
            f"*Total a pagar: S/ {resultado.total_obligaciones:,.2f}*\n\n"
            f"Estimado con regimen MYPE. Envia tus gastos para ajustar."
        )
    except Exception as exc:
        logger.error("Error calculando impuestos: %s", exc, exc_info=True)
        return "No pude calcular tus impuestos. Verifica que tu RUC tenga facturas registradas."


def _generar_resumen_gastos(ruc: str) -> str:
    """Resumen de gastos del mes actual."""
    periodo = date.today().strftime("%Y-%m")
    acumulado = _acumulado_gastos(ruc, periodo)

    if not acumulado or acumulado["cantidad"] == 0:
        return (
            f"No tienes gastos registrados en {_mes_nombre(periodo)}.\n\n"
            f"Manda foto de una factura/boleta para empezar."
        )

    lines = [
        f"*Gastos -- {_mes_nombre(periodo)}*\n",
        f"Total: S/ {acumulado['total']:,.2f}",
        f"Facturas: {acumulado['cantidad']}",
        f"IGV credito: S/ {acumulado['igv_credito']:,.2f}",
    ]

    if acumulado.get("por_categoria"):
        lines.append("\n*Por categoria:*")
        for cat, monto in sorted(acumulado["por_categoria"].items(), key=lambda x: -x[1]):
            lines.append(f"  {cat}: S/ {monto:,.2f}")

    return "\n".join(lines)


def _msg_ayuda(nombre: str) -> str:
    return (
        f"Hola {nombre}!\n\n"
        f"Soy ContaBot, tu contador IA. Esto puedo hacer:\n\n"
        f"*Foto de factura/boleta* -> La registro automaticamente\n"
        f"*estado* -> Tu P&L del mes (ventas, gastos, utilidad)\n"
        f"*impuestos* -> Cuanto debes a SUNAT\n"
        f"*gastos* -> Resumen de egresos del mes\n"
        f"*ayuda* -> Este menu\n\n"
        f"Tambien te mando reporte cada lunes a las 8am."
    )


# -- Helpers ------------------------------------------------------------------


def _generar_estado_como_receptor(ruc: str) -> str:
    """Estado financiero simplificado usando facturas recibidas (como cliente)."""
    periodo = date.today().strftime("%Y-%m")
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT COUNT(*) as n, COALESCE(SUM(monto_total), 0) as total, "
            "COALESCE(SUM(monto_igv), 0) as igv "
            "FROM facturas WHERE ruc_receptor = ? "
            "AND strftime('%Y-%m', fecha) = ? "
            "AND status NOT IN ('cancelado', 'failed')",
            (ruc, periodo),
        ).fetchone()

        if not row or row["n"] == 0:
            return (
                f"No encontre facturas para tu RUC en {_mes_nombre(periodo)}.\n"
                f"Si eres nuevo, los datos apareceran cuando proceses facturas."
            )

        # Gastos registrados
        gastos = conn.execute(
            "SELECT COUNT(*) as n, COALESCE(SUM(monto_total), 0) as total "
            "FROM compras WHERE ruc_comprador = ? "
            "AND strftime('%Y-%m', fecha_emision) = ?",
            (ruc, periodo),
        ).fetchone()

        gastos_total = gastos["total"] if gastos else 0
        utilidad = row["total"] - gastos_total

        return (
            f"*Tu negocio -- {_mes_nombre(periodo)}*\n\n"
            f"Facturado: S/ {row['total']:,.2f} ({row['n']} facturas)\n"
            f"IGV en ventas: S/ {row['igv']:,.2f}\n"
            f"Gastos registrados: S/ {gastos_total:,.2f}\n\n"
            f"*Resultado: S/ {utilidad:,.2f}*\n\n"
            f"Manda fotos de gastos para mejorar tu reporte"
        )
    finally:
        conn.close()


def _acumulado_gastos(ruc: str, periodo: str) -> dict | None:
    """Obtiene acumulado de gastos del periodo."""
    try:
        from contabot.db import get_session
        from contabot.fiscal.expenses import agregar_compras_periodo

        with get_session() as db:
            return agregar_compras_periodo(db, ruc_comprador=ruc, periodo=periodo)
    except Exception:
        return None


_MESES = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril",
    5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto",
    9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre",
}


def _mes_nombre(periodo: str) -> str:
    """YYYY-MM -> 'Marzo 2026'."""
    y, m = int(periodo[:4]), int(periodo[5:7])
    return f"{_MESES.get(m, periodo)} {y}"
