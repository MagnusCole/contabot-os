"""
financial_report.py — Estado financiero mensual para gestión.

Reemplaza al analista financiero que antes pasaba horas en Excel:
- P&L mensual: ventas -> gastos -> utilidad neta real
- Tendencia 6 meses: detecta caídas y alzas automáticamente
- Comparación vs período anterior
- Commentary en lenguaje natural (vía Grok si disponible)
- Entregable por Telegram

Uso:
    from contabot.fiscal.financial_report import generar_estado_financiero

    with get_session() as db:
        estado = generar_estado_financiero(db, ruc="20100000000", meses=6)
        print(estado.resumen_texto())
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session

from contabot.fiscal.calculator import RegimenTributario
from contabot.fiscal.expenses import agregar_compras_periodo

logger = logging.getLogger(__name__)

MESES_ES = {
    1: "Ene",
    2: "Feb",
    3: "Mar",
    4: "Abr",
    5: "May",
    6: "Jun",
    7: "Jul",
    8: "Ago",
    9: "Sep",
    10: "Oct",
    11: "Nov",
    12: "Dic",
}


# -- Modelos -------------------------------------------------------------------


@dataclass
class PeriodoFinanciero:
    """P&L de un período."""

    periodo: str  # YYYY-MM
    ventas_brutas: float  # Total facturado con IGV
    ventas_netas: float  # Base imponible
    igv_ventas: float
    gastos_operativos: float  # Compras + insumos (sin planilla)
    igv_credito: float
    costo_planilla: float  # Neto pagado a trabajadores (si disponible)
    aporte_essalud: float  # Costo empleador adicional
    igv_por_pagar: float
    renta_mensual: float
    total_obligaciones: float  # Impuestos SUNAT
    utilidad_bruta: float  # Ventas netas - gastos operativos
    utilidad_neta: float  # Después de impuestos y planilla
    cantidad_facturas: int

    @property
    def mes_label(self) -> str:
        mes = int(self.periodo.split("-")[1])
        anio = self.periodo.split("-")[0][2:]  # últimos 2 dígitos
        return f"{MESES_ES[mes]}/{anio}"

    @property
    def margen_neto(self) -> float:
        if self.ventas_brutas == 0:
            return 0.0
        return round(self.utilidad_neta / self.ventas_brutas * 100, 1)


@dataclass
class EstadoFinanciero:
    """Estado financiero multi-período."""

    ruc: str
    razon_social: str
    generado_en: datetime
    periodos: list[PeriodoFinanciero] = field(default_factory=list)
    commentary: str = ""  # Generado por IA si disponible

    @property
    def periodo_actual(self) -> PeriodoFinanciero | None:
        return self.periodos[-1] if self.periodos else None

    @property
    def periodo_anterior(self) -> PeriodoFinanciero | None:
        return self.periodos[-2] if len(self.periodos) >= 2 else None

    def variacion_ventas(self) -> float | None:
        """% de cambio ventas vs período anterior."""
        if not self.periodo_actual or not self.periodo_anterior:
            return None
        if self.periodo_anterior.ventas_brutas == 0:
            return None
        return round(
            (self.periodo_actual.ventas_brutas - self.periodo_anterior.ventas_brutas)
            / self.periodo_anterior.ventas_brutas
            * 100,
            1,
        )

    def mejor_mes(self) -> PeriodoFinanciero | None:
        return max(self.periodos, key=lambda p: p.ventas_brutas) if self.periodos else None

    def peor_mes(self) -> PeriodoFinanciero | None:
        return min(self.periodos, key=lambda p: p.ventas_brutas) if self.periodos else None

    def promedio_ventas(self) -> float:
        if not self.periodos:
            return 0.0
        return sum(p.ventas_brutas for p in self.periodos) / len(self.periodos)

    def resumen_texto(self) -> str:
        return _formatear_estado(self)

    def resumen_telegram(self) -> str:
        return _formatear_telegram(self)


# -- Core ---------------------------------------------------------------------


def generar_estado_financiero(
    db: Session,
    ruc: str,
    meses: int = 6,
    regimen: RegimenTributario = RegimenTributario.MYPE,
    incluir_planilla: bool = True,
) -> EstadoFinanciero:
    """
    Genera estado financiero multi-período.

    Args:
        db: Sesión SQLAlchemy
        ruc: RUC del emisor
        meses: Cuántos meses hacia atrás incluir (default 6)
        regimen: Régimen tributario
        incluir_planilla: Si leer datos de planilla del JSON local

    Returns:
        EstadoFinanciero con todos los períodos calculados
    """
    from dateutil.relativedelta import relativedelta

    from contabot.db.models import Emisor
    from contabot.fiscal.report import _agregar_facturas_periodo, generar_reporte_fiscal

    # Razón social
    emisor = db.query(Emisor).filter(Emisor.ruc == ruc).first()
    razon_social = emisor.nombre if emisor else ruc

    hoy = datetime.now()
    periodos_calculados: list[PeriodoFinanciero] = []

    for i in range(meses - 1, -1, -1):  # De más antiguo a más reciente
        fecha = (hoy - relativedelta(months=i)).replace(day=1)
        periodo = fecha.strftime("%Y-%m")
        anio_int, mes_int = int(fecha.year), int(fecha.month)

        try:
            # Ventas del período
            ventas = _agregar_facturas_periodo(db, ruc, anio_int, mes_int)
            ventas_brutas = ventas["monto_total"]
            ventas_netas = ventas["monto_subtotal"]
            igv_ventas = ventas["monto_igv"]
            cantidad = ventas["cantidad"]

            # Compras / gastos operativos
            compras = agregar_compras_periodo(db, ruc_comprador=ruc, periodo=periodo)
            gastos_op = compras.get("subtotal_con_credito", 0.0) + compras.get(
                "subtotal_sin_credito", 0.0
            )
            igv_credito = compras.get("igv_credito_fiscal", 0.0)

            # Planilla (desde JSON local si disponible)
            costo_planilla = 0.0
            aporte_essalud = 0.0
            if incluir_planilla:
                costo_planilla, aporte_essalud = _leer_costo_planilla(ruc, periodo)

            # Obligaciones fiscales
            reporte_fiscal = generar_reporte_fiscal(db, ruc, periodo, regimen)
            igv_pagar = reporte_fiscal.igv_por_pagar
            renta = reporte_fiscal.renta_mensual
            total_obligaciones = igv_pagar + renta

            # P&L
            utilidad_bruta = ventas_netas - gastos_op
            utilidad_neta = (
                ventas_brutas - gastos_op - costo_planilla - aporte_essalud - total_obligaciones
            )

            periodos_calculados.append(
                PeriodoFinanciero(
                    periodo=periodo,
                    ventas_brutas=round(ventas_brutas, 2),
                    ventas_netas=round(ventas_netas, 2),
                    igv_ventas=round(igv_ventas, 2),
                    gastos_operativos=round(gastos_op, 2),
                    igv_credito=round(igv_credito, 2),
                    costo_planilla=round(costo_planilla, 2),
                    aporte_essalud=round(aporte_essalud, 2),
                    igv_por_pagar=round(igv_pagar, 2),
                    renta_mensual=round(renta, 2),
                    total_obligaciones=round(total_obligaciones, 2),
                    utilidad_bruta=round(utilidad_bruta, 2),
                    utilidad_neta=round(utilidad_neta, 2),
                    cantidad_facturas=cantidad,
                )
            )

        except Exception as e:
            logger.warning("Error calculando período %s: %s", periodo, e)
            continue

    estado = EstadoFinanciero(
        ruc=ruc,
        razon_social=razon_social,
        generado_en=hoy,
        periodos=periodos_calculados,
    )

    # Commentary con Grok si hay API key
    try:
        estado.commentary = _generar_commentary(estado)
    except Exception as e:
        logger.debug("Commentary IA no disponible: %s", e)

    return estado


def _leer_costo_planilla(ruc: str, periodo: str) -> tuple[float, float]:
    """Lee costo de planilla del JSON local. Retorna (neto_trabajadores, essalud)."""
    try:
        from contabot.planilla.service import calcular_planilla_periodo, generar_resumen_planilla

        conceptos = calcular_planilla_periodo(ruc, periodo)
        if not conceptos:
            return 0.0, 0.0
        resumen = generar_resumen_planilla(conceptos)
        return float(resumen["total_neto"]), float(resumen["total_aportes_essalud"])
    except Exception:
        return 0.0, 0.0


def _generar_commentary(estado: EstadoFinanciero) -> str:
    """Genera análisis en lenguaje natural usando Grok."""
    if not estado.periodos:
        return ""

    actual = estado.periodo_actual
    variacion = estado.variacion_ventas()
    promedio = estado.promedio_ventas()

    # Construir prompt con los datos reales
    datos_texto = "\n".join(
        f"  {p.mes_label}: ventas S/{p.ventas_brutas:,.0f}, "
        f"utilidad neta S/{p.utilidad_neta:,.0f}, margen {p.margen_neto}%"
        for p in estado.periodos
    )

    prompt = (
        f"Eres un analista financiero para una PYME peruana. "
        f"Analiza estos datos de {estado.razon_social} (RUC {estado.ruc}):\n\n"
        f"{datos_texto}\n\n"
        f"En máximo 3 oraciones: identifica la tendencia principal, "
        f"un riesgo concreto y una oportunidad. Sin formalismos, directo al punto."
    )

    try:
        import httpx

        api_key = os.getenv("XAI_API_KEY")
        if not api_key:
            return ""

        r = httpx.post(
            "https://api.x.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": "grok-4-1-fast-non-reasoning",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 200,
                "temperature": 0.3,
            },
            timeout=15,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.debug("Grok commentary error: %s", e)
        return ""


# -- Formateo ------------------------------------------------------------------


def _formatear_estado(estado: EstadoFinanciero) -> str:
    actual = estado.periodo_actual
    if not actual:
        return "Sin datos"

    variacion = estado.variacion_ventas()
    flecha = ""
    if variacion is not None:
        flecha = f" ({'▲' if variacion >= 0 else '▼'}{abs(variacion):.1f}% vs mes ant.)"

    lines = [
        f"{'=' * 58}",
        f"ESTADO FINANCIERO — {estado.razon_social}",
        f"RUC: {estado.ruc}  |  Generado: {estado.generado_en.strftime('%d/%m/%Y %H:%M')}",
        f"{'=' * 58}",
        "",
        f"PERIODO ACTUAL: {actual.mes_label}{flecha}",
        f"  Facturas emitidas:      {actual.cantidad_facturas}",
        f"  Ventas totales:         S/ {actual.ventas_brutas:>12,.2f}",
        f"  Base imponible:         S/ {actual.ventas_netas:>12,.2f}",
        f"  Gastos operativos:      S/ {actual.gastos_operativos:>12,.2f}",
    ]

    if actual.costo_planilla > 0:
        lines += [
            f"  Planilla (neto):        S/ {actual.costo_planilla:>12,.2f}",
            f"  EsSalud:                S/ {actual.aporte_essalud:>12,.2f}",
        ]

    lines += [
        f"  Impuestos SUNAT:        S/ {actual.total_obligaciones:>12,.2f}",
        f"    IGV por pagar:          S/ {actual.igv_por_pagar:>12,.2f}",
        f"    Renta mensual:          S/ {actual.renta_mensual:>12,.2f}",
        f"  {'-' * 42}",
        f"  Utilidad bruta:         S/ {actual.utilidad_bruta:>12,.2f}",
        f"  UTILIDAD NETA:          S/ {actual.utilidad_neta:>12,.2f}  ({actual.margen_neto}%)",
        "",
    ]

    # Tendencia
    if len(estado.periodos) > 1:
        lines.append(f"TENDENCIA ({len(estado.periodos)} meses):")
        max_ventas = max(p.ventas_brutas for p in estado.periodos) or 1
        for p in estado.periodos:
            bar_len = int(p.ventas_brutas / max_ventas * 20)
            bar = "#" * bar_len
            marker = " <" if p == actual else ""
            lines.append(
                f"  {p.mes_label:>7}  {bar:<20}  S/ {p.ventas_brutas:>10,.0f}"
                f"  neto S/ {p.utilidad_neta:>8,.0f}{marker}"
            )
        lines.append(f"  Promedio ventas: S/ {estado.promedio_ventas():,.0f}")

    if estado.commentary:
        lines += ["", "ANALISIS IA:", f"  {estado.commentary}"]

    lines.append(f"{'=' * 58}")
    return "\n".join(lines)


def _formatear_telegram(estado: EstadoFinanciero) -> str:
    actual = estado.periodo_actual
    if not actual:
        return "Sin datos"

    variacion = estado.variacion_ventas()
    var_text = ""
    if variacion is not None:
        var_text = f" ({'+' if variacion >= 0 else ''}{variacion:.1f}%)"

    lines = [
        f"<b>Estado Financiero {actual.mes_label}</b>",
        f"<b>{estado.razon_social}</b>",
        "",
        f"Ventas: S/ {actual.ventas_brutas:,.0f}{var_text}",
        f"Impuestos: S/ {actual.total_obligaciones:,.0f}",
    ]

    if actual.costo_planilla > 0:
        lines.append(f"Planilla: S/ {actual.costo_planilla + actual.aporte_essalud:,.0f}")

    lines += [
        f"<b>Utilidad neta: S/ {actual.utilidad_neta:,.0f} ({actual.margen_neto}%)</b>",
    ]

    if len(estado.periodos) > 1:
        lines.append("")
        trend = "  ".join(
            f"{p.mes_label} S/{p.ventas_brutas / 1000:.0f}K" for p in estado.periodos[-3:]
        )
        lines.append(f"Ultimos meses: {trend}")

    if estado.commentary:
        lines += ["", estado.commentary]

    return "\n".join(lines)
