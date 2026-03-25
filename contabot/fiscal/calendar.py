"""Cronograma de vencimientos SUNAT.

Calcula fecha limite de declaracion mensual segun el ultimo digito del RUC
y el cronograma oficial publicado por SUNAT cada anio.

Uso:
    from contabot.fiscal.calendar import get_fecha_vencimiento

    fecha = get_fecha_vencimiento(ruc="20100000000", periodo="2026-02")
"""

from __future__ import annotations

import logging
from datetime import date

logger = logging.getLogger(__name__)


# ============================================================================
# CRONOGRAMA SUNAT 2026
# Fuente: Resolucion de Superintendencia SUNAT (publicada dic 2025)
# Formato: {periodo: {ultimo_digito_ruc: dia_vencimiento_mes_siguiente}}
# NOTA: Actualizar esto cada anio con la resolucion oficial.
# ============================================================================

CRONOGRAMA_2026: dict[str, dict[str, int]] = {
    "2026-01": {"0": 13, "1": 14, "2": 17, "3": 17, "4": 18, "5": 18, "6": 19, "7": 19, "8": 20, "9": 20},
    "2026-02": {"0": 13, "1": 16, "2": 16, "3": 17, "4": 17, "5": 18, "6": 18, "7": 19, "8": 19, "9": 20},
    "2026-03": {"0": 15, "1": 15, "2": 16, "3": 16, "4": 17, "5": 17, "6": 20, "7": 20, "8": 21, "9": 21},
    "2026-04": {"0": 14, "1": 14, "2": 15, "3": 15, "4": 18, "5": 18, "6": 19, "7": 19, "8": 20, "9": 20},
    "2026-05": {"0": 12, "1": 15, "2": 15, "3": 16, "4": 16, "5": 17, "6": 17, "7": 18, "8": 18, "9": 19},
    "2026-06": {"0": 14, "1": 14, "2": 15, "3": 15, "4": 16, "5": 16, "6": 17, "7": 17, "8": 20, "9": 20},
    "2026-07": {"0": 13, "1": 13, "2": 14, "3": 14, "4": 17, "5": 17, "6": 18, "7": 18, "8": 19, "9": 19},
    "2026-08": {"0": 14, "1": 14, "2": 15, "3": 15, "4": 16, "5": 16, "6": 17, "7": 17, "8": 18, "9": 18},
    "2026-09": {"0": 15, "1": 15, "2": 16, "3": 16, "4": 19, "5": 19, "6": 20, "7": 20, "8": 21, "9": 21},
    "2026-10": {"0": 13, "1": 16, "2": 16, "3": 17, "4": 17, "5": 18, "6": 18, "7": 19, "8": 19, "9": 20},
    "2026-11": {"0": 15, "1": 15, "2": 16, "3": 16, "4": 17, "5": 17, "6": 18, "7": 18, "8": 21, "9": 21},
    "2026-12": {"0": 15, "1": 18, "2": 18, "3": 19, "4": 19, "5": 20, "6": 20, "7": 21, "8": 21, "9": 22},
}


def get_fecha_vencimiento(ruc: str, periodo: str) -> date | None:
    """Calcula la fecha de vencimiento para declarar el periodo tributario.

    Args:
        ruc: RUC del contribuyente (11 digitos)
        periodo: Periodo tributario "YYYY-MM"

    Returns:
        date con la fecha de vencimiento, o None si no se puede calcular
    """
    if not ruc or len(ruc) != 11:
        logger.warning("RUC invalido para calculo de vencimiento: %s", ruc)
        return None

    ultimo_digito = ruc[-1]

    cronograma_periodo = CRONOGRAMA_2026.get(periodo)
    if cronograma_periodo is None:
        logger.warning("No hay cronograma para periodo %s, usando estimacion", periodo)
        return _estimar_vencimiento(periodo, ultimo_digito)

    dia = cronograma_periodo.get(ultimo_digito)
    if dia is None:
        return None

    anio, mes = periodo.split("-")
    mes_venc = int(mes) + 1
    anio_venc = int(anio)
    if mes_venc > 12:
        mes_venc = 1
        anio_venc += 1

    try:
        return date(anio_venc, mes_venc, dia)
    except ValueError:
        logger.error("Fecha invalida: %d-%d-%d", anio_venc, mes_venc, dia)
        return None


def _estimar_vencimiento(periodo: str, ultimo_digito: str) -> date | None:
    """Estimacion conservadora cuando no hay cronograma oficial."""
    base_dia = 13 + int(ultimo_digito)

    anio, mes = periodo.split("-")
    mes_venc = int(mes) + 1
    anio_venc = int(anio)
    if mes_venc > 12:
        mes_venc = 1
        anio_venc += 1

    try:
        return date(anio_venc, mes_venc, min(base_dia, 28))
    except ValueError:
        return None


def dias_para_vencimiento(ruc: str, periodo: str) -> int | None:
    """Dias restantes hasta el vencimiento (negativo si ya vencio)."""
    fecha = get_fecha_vencimiento(ruc, periodo)
    if fecha is None:
        return None
    return (fecha - date.today()).days
