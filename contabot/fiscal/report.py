"""Generador de reportes fiscales.

Consulta facturas emitidas de la base de datos, agrega por periodo,
y calcula obligaciones tributarias usando FiscalCalculator.

Uso:
    from contabot.fiscal.report import generar_reporte_fiscal

    with get_session() as db:
        resultado = generar_reporte_fiscal(db, ruc_emisor="20100000000", periodo="2026-02")
        print(resultado.saldo_real)
"""

from __future__ import annotations

import logging

from sqlalchemy import extract, func
from sqlalchemy.orm import Session

from contabot.db.models import Emisor, Invoice, InvoiceStatus
from contabot.fiscal.calculator import (
    FiscalCalculator,
    RegimenTributario,
    ResultadoFiscal,
)
from contabot.fiscal.calendar import get_fecha_vencimiento

logger = logging.getLogger(__name__)


def generar_reporte_fiscal(
    db: Session,
    ruc_emisor: str,
    periodo: str,
    regimen: RegimenTributario | None = None,
) -> ResultadoFiscal:
    """Genera reporte fiscal para un emisor en un periodo.

    Args:
        db: Sesion SQLAlchemy activa
        ruc_emisor: RUC del emisor (11 digitos)
        periodo: Periodo tributario "YYYY-MM"
        regimen: Regimen tributario (si None, usa MYPE por defecto)

    Returns:
        ResultadoFiscal con calculos completos

    Raises:
        ValueError: Si el RUC no existe o el periodo es invalido
    """
    # Validar periodo
    try:
        anio, mes = periodo.split("-")
        anio_int, mes_int = int(anio), int(mes)
        if not (1 <= mes_int <= 12):
            raise ValueError
    except (ValueError, AttributeError) as e:
        raise ValueError(f"Periodo invalido: '{periodo}'. Formato esperado: YYYY-MM") from e

    # Verificar emisor existe
    emisor = db.query(Emisor).filter(Emisor.ruc == ruc_emisor).first()
    if emisor is None:
        raise ValueError(f"Emisor con RUC {ruc_emisor} no encontrado en la base de datos")

    if regimen is None:
        regimen = RegimenTributario.MYPE

    # Agregar facturas emitidas del periodo
    totales = _agregar_facturas_periodo(db, ruc_emisor, anio_int, mes_int)
    ventas_brutas = totales["monto_total"]
    igv_ventas = totales["monto_igv"]

    # Agregar compras del periodo (credito fiscal)
    from contabot.fiscal.expenses import agregar_compras_periodo

    compras = agregar_compras_periodo(db, ruc_emisor, periodo)
    compras_netas = compras["monto_subtotal"]
    igv_compras = compras["igv_credito_fiscal"]

    # Acumulado anual (para tramo MYPE)
    acumulado_anual = _calcular_acumulado_anual(db, ruc_emisor, anio_int, mes_int)

    # Fecha de vencimiento SUNAT
    fecha_venc = get_fecha_vencimiento(ruc=ruc_emisor, periodo=periodo)

    # Calcular
    calculadora = FiscalCalculator(regimen=regimen)
    resultado = calculadora.calcular(
        periodo=periodo,
        ventas_brutas=ventas_brutas,
        igv_ventas=igv_ventas,
        compras_netas=compras_netas,
        igv_compras=igv_compras,
        ingresos_netos_acumulados_anual=acumulado_anual,
        fecha_vencimiento=fecha_venc,
    )

    logger.info(
        "Reporte fiscal generado — %s periodo, S/%.2f bruto, S/%.2f obligaciones",
        periodo,
        ventas_brutas,
        resultado.total_obligaciones,
    )

    return resultado


def _agregar_facturas_periodo(
    db: Session,
    ruc_emisor: str,
    anio: int,
    mes: int,
) -> dict:
    """Suma montos de facturas emitidas en el periodo (status EMITTED)."""
    result = (
        db.query(
            func.coalesce(func.sum(Invoice.monto_total), 0.0).label("total"),
            func.coalesce(func.sum(Invoice.monto_igv), 0.0).label("igv"),
            func.coalesce(func.sum(Invoice.monto_subtotal), 0.0).label("subtotal"),
            func.count(Invoice.id).label("cantidad"),
        )
        .filter(
            Invoice.ruc_emisor == ruc_emisor,
            Invoice.status == InvoiceStatus.EMITTED.value,
            extract("year", Invoice.fecha_emision) == anio,
            extract("month", Invoice.fecha_emision) == mes,
        )
        .one()
    )

    return {
        "monto_total": float(result.total),
        "monto_igv": float(result.igv),
        "monto_subtotal": float(result.subtotal),
        "cantidad": int(result.cantidad),
    }


def _calcular_acumulado_anual(
    db: Session,
    ruc_emisor: str,
    anio: int,
    mes_actual: int,
) -> float:
    """Calcula ingresos netos acumulados del anio hasta el mes anterior.

    Necesario para determinar si aplica tramo 1 o tramo 2 en MYPE.
    """
    if mes_actual <= 1:
        return 0.0

    result = (
        db.query(
            func.coalesce(func.sum(Invoice.monto_subtotal), 0.0).label("acumulado"),
        )
        .filter(
            Invoice.ruc_emisor == ruc_emisor,
            Invoice.status == InvoiceStatus.EMITTED.value,
            extract("year", Invoice.fecha_emision) == anio,
            extract("month", Invoice.fecha_emision) < mes_actual,
        )
        .one()
    )

    return float(result.acumulado)


def resumen_fiscal_texto(resultado: ResultadoFiscal) -> str:
    """Genera resumen fiscal legible."""
    lineas = [
        f"=== REPORTE FISCAL {resultado.periodo} ===",
        f"Regimen: {resultado.regimen.label}",
        "",
        "VENTAS",
        f"  Facturado (con IGV):  S/ {resultado.ventas_brutas:>12,.2f}",
        f"  Base imponible:       S/ {resultado.ventas_netas:>12,.2f}",
        f"  IGV cobrado:          S/ {resultado.igv_ventas:>12,.2f}",
    ]

    if resultado.compras_netas > 0 or resultado.igv_compras > 0:
        lineas += [
            "",
            "COMPRAS (Credito Fiscal)",
            f"  Base imponible:       S/ {resultado.compras_netas:>12,.2f}",
            f"  IGV deducible:        S/ {resultado.igv_compras:>12,.2f}",
        ]

    lineas += [
        "",
        "OBLIGACIONES TRIBUTARIAS",
        f"  IGV por pagar:        S/ {resultado.igv_por_pagar:>12,.2f}",
        f"  Renta mensual ({resultado.tasa_renta_aplicada:.1%}): S/ {resultado.renta_mensual:>12,.2f}",
        f"  {'─' * 40}",
        f"  TOTAL a pagar SUNAT:  S/ {resultado.total_obligaciones:>12,.2f}",
        f"  ({resultado.porcentaje_obligaciones}% de ventas)",
        "",
        "SALDO REAL DISPONIBLE",
        f"  S/ {resultado.saldo_real:>12,.2f}",
    ]

    if resultado.fecha_vencimiento:
        lineas.append("")
        lineas.append(
            f"Fecha limite SUNAT: {resultado.fecha_vencimiento.strftime('%d %b %Y')}"
        )
        if resultado.dias_para_vencimiento is not None:
            if resultado.dias_para_vencimiento < 0:
                lineas.append(f"  VENCIDO hace {abs(resultado.dias_para_vencimiento)} dias")
            elif resultado.dias_para_vencimiento == 0:
                lineas.append("  VENCE HOY")
            else:
                lineas.append(f"  Faltan {resultado.dias_para_vencimiento} dias")

    return "\n".join(lineas)
