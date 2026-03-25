"""
Reporte Fiscal para Clientes — Diferenciador de retención.

Genera un resumen fiscal personalizado para cada cliente:
- Cuánto le facturamos este período
- Desglose IGV (lo que sus compras a nosotros le dan de crédito fiscal)
- Fecha límite SUNAT
- Proyección vs mes anterior
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from sqlalchemy import extract, func
from sqlalchemy.orm import Session

from contabot.db.models import Invoice, InvoiceStatus
from contabot.fiscal.calendar import get_fecha_vencimiento

logger = logging.getLogger(__name__)


@dataclass
class ReporteCliente:
    """Resumen fiscal personalizado para un cliente."""

    # Identificación
    ruc_cliente: str
    razon_social: str
    periodo: str

    # Lo que le facturamos (sus compras a nosotros = su crédito fiscal)
    cantidad_facturas: int = 0
    monto_subtotal: float = 0.0  # Base imponible
    monto_igv: float = 0.0  # IGV de las facturas
    monto_total: float = 0.0  # Total con IGV

    # Dato útil para el cliente
    credito_fiscal_igv: float = 0.0  # = monto_igv (lo que puede deducir)

    # Contexto temporal
    fecha_vencimiento: date | None = None
    dias_para_vencer: int | None = None

    # Comparativa
    facturas_mes_anterior: int = 0
    monto_mes_anterior: float = 0.0
    variacion_pct: float = 0.0

    # Detalle de facturas
    facturas: list[dict] | None = None

    def __post_init__(self):
        if self.facturas is None:
            self.facturas = []
        self.credito_fiscal_igv = self.monto_igv

    def to_dict(self) -> dict:
        return {
            "ruc_cliente": self.ruc_cliente,
            "razon_social": self.razon_social,
            "periodo": self.periodo,
            "cantidad_facturas": self.cantidad_facturas,
            "monto_subtotal": self.monto_subtotal,
            "monto_igv": self.monto_igv,
            "monto_total": self.monto_total,
            "credito_fiscal_igv": self.credito_fiscal_igv,
            "fecha_vencimiento": (
                self.fecha_vencimiento.isoformat() if self.fecha_vencimiento else None
            ),
            "dias_para_vencer": self.dias_para_vencer,
            "facturas_mes_anterior": self.facturas_mes_anterior,
            "monto_mes_anterior": self.monto_mes_anterior,
            "variacion_pct": self.variacion_pct,
            "facturas": self.facturas,
        }

    def to_texto(self) -> str:
        """Formato legible para email/WhatsApp."""
        lineas = [
            f"=== RESUMEN FISCAL {self.periodo} ===",
            f"{self.razon_social}",
            f"RUC: {self.ruc_cliente}",
            "",
            "COMPRAS A NUESTRAS EMPRESAS",
            f"  Facturas recibidas:   {self.cantidad_facturas}",
            f"  Subtotal:             S/ {self.monto_subtotal:>10,.2f}",
            f"  IGV:                  S/ {self.monto_igv:>10,.2f}",
            f"  Total:                S/ {self.monto_total:>10,.2f}",
            "",
            "TU CREDITO FISCAL (por estas compras)",
            f"  IGV deducible:        S/ {self.credito_fiscal_igv:>10,.2f}",
            "  (Puedes descontar esto de tu IGV por pagar)",
        ]

        if self.fecha_vencimiento:
            urgente = (self.dias_para_vencer or 0) <= 3
            lineas.extend(
                [
                    "",
                    f"{'URGENTE - ' if urgente else ''}Fecha límite SUNAT: {self.fecha_vencimiento.strftime('%d %b %Y')}",
                ]
            )
            if self.dias_para_vencer is not None:
                if self.dias_para_vencer < 0:
                    lineas.append(f"  VENCIDO hace {abs(self.dias_para_vencer)} días")
                elif self.dias_para_vencer == 0:
                    lineas.append("  VENCE HOY")
                else:
                    lineas.append(f"  Faltan {self.dias_para_vencer} días")

        if self.monto_mes_anterior > 0:
            tendencia = "UP" if self.variacion_pct >= 0 else "DOWN"
            lineas.extend(
                [
                    "",
                    f"[{tendencia}] vs mes anterior: {self.variacion_pct:+.1f}%",
                ]
            )

        return "\n".join(lineas)


def generar_reporte_cliente(
    db: Session,
    ruc_cliente: str,
    periodo: str,
    incluir_detalle: bool = False,
) -> ReporteCliente:
    """
    Genera reporte fiscal para un cliente específico.

    Args:
        db: Sesión SQLAlchemy
        ruc_cliente: RUC del cliente receptor
        periodo: Período "YYYY-MM"
        incluir_detalle: Si incluir lista de facturas individuales
    """
    anio, mes = periodo.split("-")
    anio_int, mes_int = int(anio), int(mes)

    # Agregar facturas emitidas al cliente en el período
    result = (
        db.query(
            func.count(Invoice.id).label("cantidad"),
            func.coalesce(func.sum(Invoice.monto_subtotal), 0.0).label("subtotal"),
            func.coalesce(func.sum(Invoice.monto_igv), 0.0).label("igv"),
            func.coalesce(func.sum(Invoice.monto_total), 0.0).label("total"),
        )
        .filter(
            Invoice.ruc_receptor == ruc_cliente,
            Invoice.status == InvoiceStatus.EMITTED.value,
            extract("year", Invoice.fecha_emision) == anio_int,
            extract("month", Invoice.fecha_emision) == mes_int,
        )
        .one()
    )

    # Razón social del cliente
    from contabot.db.models import Client

    razon = (
        db.query(Client.razon_social).filter(Client.ruc == ruc_cliente).scalar()
    ) or ruc_cliente

    reporte = ReporteCliente(
        ruc_cliente=ruc_cliente,
        razon_social=razon,
        periodo=periodo,
        cantidad_facturas=int(result.cantidad),
        monto_subtotal=float(result.subtotal),
        monto_igv=float(result.igv),
        monto_total=float(result.total),
    )

    # Fecha de vencimiento SUNAT para el cliente
    try:
        reporte.fecha_vencimiento = get_fecha_vencimiento(ruc=ruc_cliente, periodo=periodo)
        if reporte.fecha_vencimiento:
            delta = reporte.fecha_vencimiento - date.today()
            reporte.dias_para_vencer = delta.days
    except Exception:
        logger.debug("Silenced exception in %s", __name__)

    # Comparativa con mes anterior
    if mes_int == 1:
        prev_anio, prev_mes = anio_int - 1, 12
    else:
        prev_anio, prev_mes = anio_int, mes_int - 1

    prev = (
        db.query(
            func.count(Invoice.id).label("cantidad"),
            func.coalesce(func.sum(Invoice.monto_total), 0.0).label("total"),
        )
        .filter(
            Invoice.ruc_receptor == ruc_cliente,
            Invoice.status == InvoiceStatus.EMITTED.value,
            extract("year", Invoice.fecha_emision) == prev_anio,
            extract("month", Invoice.fecha_emision) == prev_mes,
        )
        .one()
    )

    reporte.facturas_mes_anterior = int(prev.cantidad)
    reporte.monto_mes_anterior = float(prev.total)
    if reporte.monto_mes_anterior > 0:
        reporte.variacion_pct = round(
            (reporte.monto_total - reporte.monto_mes_anterior) / reporte.monto_mes_anterior * 100,
            1,
        )

    # Detalle de facturas individuales
    if incluir_detalle:
        facturas = (
            db.query(Invoice)
            .filter(
                Invoice.ruc_receptor == ruc_cliente,
                Invoice.status == InvoiceStatus.EMITTED.value,
                extract("year", Invoice.fecha_emision) == anio_int,
                extract("month", Invoice.fecha_emision) == mes_int,
            )
            .order_by(Invoice.fecha_emision, Invoice.id)
            .all()
        )
        reporte.facturas = [
            {
                "serie_numero": f.numero_completo,
                "fecha": f.fecha_emision.isoformat() if f.fecha_emision else None,
                "subtotal": f.monto_subtotal,
                "igv": f.monto_igv,
                "total": f.monto_total,
                "emisor": f.nombre_emisor or f.ruc_emisor,
            }
            for f in facturas
        ]

    return reporte


def generar_reportes_todos_clientes(
    db: Session,
    periodo: str,
) -> list[ReporteCliente]:
    """
    Genera reportes para TODOS los clientes con facturas en el período.

    Returns:
        Lista de ReporteCliente ordenada por monto descendente
    """
    anio, mes = periodo.split("-")
    anio_int, mes_int = int(anio), int(mes)

    # Obtener RUCs únicos de clientes con facturas en el período
    rucs = (
        db.query(Invoice.ruc_receptor)
        .filter(
            Invoice.ruc_receptor.isnot(None),
            Invoice.status == InvoiceStatus.EMITTED.value,
            extract("year", Invoice.fecha_emision) == anio_int,
            extract("month", Invoice.fecha_emision) == mes_int,
        )
        .distinct()
        .all()
    )

    reportes = []
    for (ruc,) in rucs:
        if not ruc:
            continue
        try:
            reporte = generar_reporte_cliente(db, ruc, periodo)
            if reporte.cantidad_facturas > 0:
                reportes.append(reporte)
        except Exception as e:
            logger.warning("Error generando reporte para %s: %s", ruc, e)

    # Ordenar por monto total descendente
    reportes.sort(key=lambda r: r.monto_total, reverse=True)
    return reportes
