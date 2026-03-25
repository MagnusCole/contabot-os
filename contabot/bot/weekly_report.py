"""contabot/bot/weekly_report.py — Reporte semanal automático para clientes ContaBot."""

from __future__ import annotations

import logging
import os
from datetime import date

from .onboarding import listar_clientes_activos

logger = logging.getLogger(__name__)

_MESES = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril",
    5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto",
    9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre",
}


def generar_reporte_semanal(ruc: str) -> str:
    """Genera reporte semanal en formato WhatsApp para un RUC."""
    periodo = date.today().strftime("%Y-%m")
    mes_nombre = f"{_MESES.get(date.today().month, '')} {date.today().year}"

    # P&L
    pl_section = ""
    try:
        from contabot.db import get_session
        from contabot.fiscal.financial_report import generar_estado_financiero

        with get_session() as db:
            estado = generar_estado_financiero(db, ruc=ruc, meses=2)

        p = estado.periodo_actual
        if p:
            pl_section = (
                f"*Resultado del mes:*\n"
                f"Ventas: S/ {p.ventas_brutas:,.2f}\n"
                f"Gastos: S/ {p.gastos_operativos:,.2f}\n"
                f"Utilidad neta: S/ {p.utilidad_neta:,.2f}\n"
                f"Margen: {p.margen_neto:.1f}%\n"
            )

            p_ant = estado.periodo_anterior
            if p_ant and p_ant.ventas_brutas > 0:
                var = estado.variacion_ventas()
                if var is not None:
                    direction = "sube" if var >= 0 else "baja"
                    pl_section += f"vs mes anterior: {var:+.1f}% ({direction})\n"
    except Exception as exc:
        logger.warning("No se pudo generar P&L para %s: %s", ruc, exc)

    # Obligaciones tributarias
    tax_section = ""
    try:
        from contabot.db import get_session
        from contabot.fiscal.report import generar_reporte_fiscal

        with get_session() as db:
            resultado = generar_reporte_fiscal(db, ruc_emisor=ruc, periodo=periodo)

        tax_section = (
            f"\n*Obligaciones SUNAT:*\n"
            f"IGV: S/ {resultado.igv_por_pagar:,.2f}\n"
            f"Renta: S/ {resultado.renta_mensual:,.2f}\n"
            f"Total: S/ {resultado.total_obligaciones:,.2f}\n"
        )
        if resultado.dias_para_vencimiento:
            tax_section += f"Vence en {resultado.dias_para_vencimiento} dias\n"
    except Exception as exc:
        logger.warning("No se pudo generar impuestos para %s: %s", ruc, exc)

    # Gastos registrados
    gastos_section = ""
    try:
        from contabot.db import get_session
        from contabot.fiscal.expenses import agregar_compras_periodo

        with get_session() as db:
            acum = agregar_compras_periodo(db, ruc_comprador=ruc, periodo=periodo)

        if acum and acum.get("cantidad", 0) > 0:
            gastos_section = (
                f"\n*Gastos registrados:*\n"
                f"{acum['cantidad']} comprobantes\n"
                f"Total: S/ {acum['monto_total']:,.2f}\n"
                f"IGV credito: S/ {acum.get('igv_credito_fiscal', 0):,.2f}\n"
            )
    except Exception as exc:
        logger.warning("No se pudo generar gastos para %s: %s", ruc, exc)

    # Armar mensaje completo
    msg = f"*Reporte semanal -- {mes_nombre}*\n{'─' * 30}\n\n"

    if pl_section:
        msg += pl_section
    if tax_section:
        msg += tax_section
    if gastos_section:
        msg += gastos_section

    if not pl_section and not tax_section:
        msg += "No encontre datos de facturacion para este mes.\n"

    msg += (
        f"\n{'─' * 30}\n"
        f"_ContaBot -- Tu contador IA_\n"
        f"Manda foto de factura para registrar"
    )

    return msg


async def enviar_reportes_programados() -> int:
    """Envía reportes a todos los clientes activos que les toca hoy.

    Returns:
        Número de reportes enviados.
    """
    today = date.today()
    dia_semana = today.isoweekday()  # 1=lunes

    clientes = listar_clientes_activos()
    enviados = 0

    for cliente in clientes:
        if cliente.dia_reporte != dia_semana:
            continue

        try:
            reporte = generar_reporte_semanal(cliente.ruc)

            # Enviar por WhatsApp — uses the same WAHA send as the server
            try:
                from contabot.bot.server import _enviar_whatsapp
                ok = await _enviar_whatsapp(cliente.telefono, reporte)
                if ok:
                    enviados += 1
                    logger.info("Reporte semanal enviado a %s (%s)", cliente.telefono, cliente.ruc)
                else:
                    logger.warning("Fallo envio a %s", cliente.telefono)
            except ImportError:
                logger.warning("WhatsApp outbound no disponible -- reporte generado pero no enviado")

        except Exception as exc:
            logger.error("Error reporte semanal %s: %s", cliente.ruc, exc)

    return enviados
