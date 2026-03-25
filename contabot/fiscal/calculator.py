"""
Calculadora fiscal para empresas peruanas.

Calcula obligaciones tributarias (IGV, Renta) basado en las facturas
emitidas del período. Diseñado para Régimen MYPE Tributario y RER.

Uso:
    from contabot.fiscal.calculator import FiscalCalculator, RegimenTributario

    calc = FiscalCalculator(regimen=RegimenTributario.MYPE)
    resultado = calc.calcular(ventas_brutas=45_000, igv_ventas=8_100)
    print(resultado.saldo_real)  # Lo que realmente puedes gastar
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass
from datetime import date

logger = logging.getLogger(__name__)


# ============================================================================
# CONSTANTES FISCALES PERÚ 2026
# ============================================================================

UIT_2026 = 5_350  # Verificar con SUNAT al inicio de cada año
IGV_TASA = 0.18
RENTA_MYPE_TRAMO1_TASA = 0.01  # Hasta 300 UIT de ingresos netos anuales
RENTA_MYPE_TRAMO2_TASA = 0.015  # Más de 300 UIT
RENTA_MYPE_UMBRAL_UIT = 300  # Umbral en UIT para cambio de tasa
RENTA_RER_TASA = 0.015  # RER siempre 1.5%
RENTA_GENERAL_COEFICIENTE = 0.015  # Coeficiente mínimo Régimen General


class RegimenTributario(str, enum.Enum):
    """Regímenes tributarios disponibles en Perú."""

    NRUS = "nrus"  # Nuevo RUS (cuota fija, no emite facturas)
    RER = "rer"  # Régimen Especial de Renta
    MYPE = "mype"  # Régimen MYPE Tributario
    GENERAL = "general"  # Régimen General

    @property
    def label(self) -> str:
        labels = {
            "nrus": "Nuevo RUS",
            "rer": "Régimen Especial (RER)",
            "mype": "MYPE Tributario",
            "general": "Régimen General",
        }
        return labels[self.value]


@dataclass(frozen=True)
class ResultadoFiscal:
    """Resultado del cálculo fiscal de un período."""

    # Inputs
    periodo: str  # "2026-02"
    regimen: RegimenTributario
    ventas_brutas: float  # Total facturado (con IGV)
    ventas_netas: float  # Base imponible (sin IGV)
    igv_ventas: float  # IGV cobrado en ventas

    # Compras
    compras_netas: float = 0.0
    igv_compras: float = 0.0

    # Cálculos
    igv_por_pagar: float = 0.0  # IGV ventas - IGV compras
    renta_mensual: float = 0.0  # Pago a cuenta de renta
    total_obligaciones: float = 0.0  # IGV + Renta
    saldo_real: float = 0.0  # Ventas brutas - obligaciones

    # Metadata
    tasa_renta_aplicada: float = 0.0
    dias_para_vencimiento: int | None = None
    fecha_vencimiento: date | None = None

    @property
    def porcentaje_obligaciones(self) -> float:
        """Qué porcentaje de tus ventas se va en impuestos."""
        if self.ventas_brutas == 0:
            return 0.0
        return round(self.total_obligaciones / self.ventas_brutas * 100, 1)


# ============================================================================
# CALCULADORA
# ============================================================================


class FiscalCalculator:
    """
    Calcula obligaciones tributarias mensuales.

    Soporta:
    - MYPE Tributario (tramos de 1% y 1.5%)
    - RER (1.5% fijo)
    - Régimen General (coeficiente o 1.5% mínimo)
    """

    def __init__(
        self,
        regimen: RegimenTributario = RegimenTributario.MYPE,
        uit: float = UIT_2026,
    ):
        self.regimen = regimen
        self.uit = uit

    def calcular(
        self,
        periodo: str,
        ventas_brutas: float,
        igv_ventas: float,
        compras_netas: float = 0.0,
        igv_compras: float = 0.0,
        ingresos_netos_acumulados_anual: float = 0.0,
        fecha_vencimiento: date | None = None,
    ) -> ResultadoFiscal:
        """
        Calcula obligaciones fiscales del período.

        Args:
            periodo: Período en formato "YYYY-MM"
            ventas_brutas: Total facturado (incluye IGV)
            igv_ventas: IGV total de las ventas
            compras_netas: Base imponible de compras
            igv_compras: IGV de compras deducible
            ingresos_netos_acumulados_anual: Acumulado del año para tramo MYPE
            fecha_vencimiento: Fecha límite de declaración

        Returns:
            ResultadoFiscal con todos los cálculos
        """
        ventas_netas = ventas_brutas - igv_ventas

        # IGV por pagar = IGV cobrado - IGV pagado (crédito fiscal)
        igv_por_pagar = max(0.0, igv_ventas - igv_compras)

        # Renta mensual según régimen
        tasa_renta, renta_mensual = self._calcular_renta(
            ventas_netas=ventas_netas,
            ingresos_acumulados=ingresos_netos_acumulados_anual,
        )

        total_obligaciones = igv_por_pagar + renta_mensual
        saldo_real = ventas_brutas - total_obligaciones

        # Días para vencimiento
        dias = None
        if fecha_vencimiento:
            dias = (fecha_vencimiento - date.today()).days

        resultado = ResultadoFiscal(
            periodo=periodo,
            regimen=self.regimen,
            ventas_brutas=round(ventas_brutas, 2),
            ventas_netas=round(ventas_netas, 2),
            igv_ventas=round(igv_ventas, 2),
            compras_netas=round(compras_netas, 2),
            igv_compras=round(igv_compras, 2),
            igv_por_pagar=round(igv_por_pagar, 2),
            renta_mensual=round(renta_mensual, 2),
            total_obligaciones=round(total_obligaciones, 2),
            saldo_real=round(saldo_real, 2),
            tasa_renta_aplicada=tasa_renta,
            dias_para_vencimiento=dias,
            fecha_vencimiento=fecha_vencimiento,
        )

        logger.info(
            "Cálculo fiscal completado",
            extra={
                "periodo": periodo,
                "regimen": self.regimen.value,
                "ventas_brutas": ventas_brutas,
                "obligaciones": total_obligaciones,
                "saldo_real": saldo_real,
            },
        )

        return resultado

    def _calcular_renta(
        self,
        ventas_netas: float,
        ingresos_acumulados: float = 0.0,
    ) -> tuple[float, float]:
        """
        Calcula pago a cuenta de renta según régimen.

        Returns:
            (tasa_aplicada, monto_renta)
        """
        if self.regimen == RegimenTributario.NRUS:
            # NRUS paga cuota fija, no calcula renta mensual
            return 0.0, 0.0

        if self.regimen == RegimenTributario.RER:
            tasa = RENTA_RER_TASA
            return tasa, round(ventas_netas * tasa, 2)

        if self.regimen == RegimenTributario.MYPE:
            umbral = self.uit * RENTA_MYPE_UMBRAL_UIT
            if ingresos_acumulados <= umbral:
                tasa = RENTA_MYPE_TRAMO1_TASA
            else:
                tasa = RENTA_MYPE_TRAMO2_TASA
            return tasa, round(ventas_netas * tasa, 2)

        if self.regimen == RegimenTributario.GENERAL:
            tasa = RENTA_GENERAL_COEFICIENTE
            return tasa, round(ventas_netas * tasa, 2)

        return 0.0, 0.0
