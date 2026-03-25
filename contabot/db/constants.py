"""Constantes del sistema de facturacion peruano.

Verdad Unica (DRY): Todas las constantes van aqui.
Si necesitas cambiar IGV o un codigo, este es el unico lugar.
"""

from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Final

# ============================================================================
# IMPUESTOS - PERU
# ============================================================================

IGV_RATE: Final[Decimal] = Decimal("0.18")
"""Tasa del IGV (18%) en Peru."""

IGV_RATE_FLOAT: Final[float] = 0.18
"""Tasa del IGV como float para calculos rapidos."""

IGV_MULTIPLIER: Final[Decimal] = Decimal("1.18")
"""Multiplicador IGV (1 + tasa). Para convertir monto sin IGV a con IGV."""

IGV_MULTIPLIER_FLOAT: Final[float] = 1.18
"""Multiplicador IGV como float."""


# ============================================================================
# MONEDAS
# ============================================================================


class Moneda(str, Enum):
    """Codigos de moneda ISO 4217 soportados."""

    PEN = "PEN"
    USD = "USD"


DEFAULT_MONEDA: Final[str] = Moneda.PEN.value


# ============================================================================
# UNIDADES DE MEDIDA - SUNAT (Catalogo N 03)
# ============================================================================


class UnidadMedida(str, Enum):
    """Codigos oficiales SUNAT — Catalogo N 03."""

    BOBINAS = "4A"
    BALDE = "BJ"
    BARRILES = "BLL"
    BOLSA = "BG"
    BOTELLAS = "BO"
    CAJA = "BX"
    CARTONES = "CT"
    CMT = "CMT"
    MTR = "MTR"
    MTK = "MTK"
    MTQ = "MTQ"
    KGM = "KGM"
    GRM = "GRM"
    TNE = "TNE"
    LBR = "LBR"
    LTR = "LTR"
    MLT = "MLT"
    GLL = "GLL"
    KWH = "KWH"
    HUR = "HUR"
    DAY = "DAY"
    MON = "MON"
    NIU = "NIU"  # Unidad (bienes)
    ZZ = "ZZ"  # Unidad (servicios)
    DZN = "DZN"
    MLL = "MLL"
    C62 = "C62"  # Piezas
    PR = "PR"  # Par
    SET = "SET"
    KT = "KT"  # Kit
    PK = "PK"  # Paquete


DEFAULT_UNIDAD_MEDIDA: Final[str] = UnidadMedida.NIU.value

_UNIDAD_NORMALIZER: dict[str, str] = {
    "NIU": "NIU", "UNIDAD": "NIU", "UND": "NIU", "UNI": "NIU",
    "ZZ": "ZZ", "SERVICIO": "ZZ", "SERVICIOS": "ZZ",
    "MTR": "MTR", "METRO": "MTR", "METROS": "MTR",
    "KGM": "KGM", "KILOGRAMO": "KGM", "KG": "KGM",
    "LTR": "LTR", "LITRO": "LTR", "LT": "LTR",
    "BG": "BG", "BOLSA": "BG", "BX": "BX", "CAJA": "BX",
    "DZN": "DZN", "DOCENA": "DZN", "PR": "PR", "PAR": "PR",
    "SET": "SET", "JUEGO": "SET", "KT": "KT", "KIT": "KT",
    "PK": "PK", "PAQUETE": "PK", "C62": "C62", "PIEZA": "C62",
    "HUR": "HUR", "HORA": "HUR", "DAY": "DAY", "DIA": "DAY",
    "MON": "MON", "MES": "MON",
}

_CODE_TO_DESCRIPCION: dict[str, str] = {
    "4A": "BOBINAS", "BJ": "BALDE", "BLL": "BARRILES", "BG": "BOLSA",
    "BO": "BOTELLAS", "BX": "CAJA", "CT": "CARTONES", "CMT": "CENTIMETRO",
    "MTR": "METRO", "MTK": "METRO CUADRADO", "MTQ": "METRO CUBICO",
    "KGM": "KILOGRAMO", "GRM": "GRAMO", "TNE": "TONELADAS", "LBR": "LIBRAS",
    "LTR": "LITRO", "MLT": "MILILITRO", "GLL": "US GALON", "KWH": "KILOVATIO HORA",
    "HUR": "HORA", "DAY": "DIA", "MON": "MES",
    "NIU": "UNIDAD", "ZZ": "UNIDAD", "DZN": "DOCENA", "MLL": "MILLARES",
    "C62": "PIEZAS", "PR": "PAR", "SET": "JUEGO", "KT": "KIT", "PK": "PAQUETE",
}

DEFAULT_UNIDAD_DESCRIPCION: Final[str] = _CODE_TO_DESCRIPCION["NIU"]


def normalize_unidad(value: str | None) -> str:
    """Convierte texto de unidad a descripcion oficial SUNAT (Catalogo N 03)."""
    if not value:
        return DEFAULT_UNIDAD_DESCRIPCION
    key = value.strip().upper()
    codigo = _UNIDAD_NORMALIZER.get(key)
    if codigo:
        return _CODE_TO_DESCRIPCION.get(codigo, DEFAULT_UNIDAD_DESCRIPCION)
    for desc in _CODE_TO_DESCRIPCION.values():
        if key == desc.upper():
            return desc
    return DEFAULT_UNIDAD_DESCRIPCION


# ============================================================================
# TIPOS DE DOCUMENTO
# ============================================================================


class TipoDocumento(str, Enum):
    """Tipos de documento de identidad SUNAT (Catalogo N 06)."""

    DNI = "1"
    CARNET_EXT = "4"
    RUC = "6"
    PASAPORTE = "7"
    OTROS = "0"


class TipoComprobante(str, Enum):
    """Tipos de comprobante de pago SUNAT (Catalogo N 01)."""

    FACTURA = "01"
    BOLETA = "03"
    NOTA_CREDITO = "07"
    NOTA_DEBITO = "08"
    GUIA_REMISION = "09"


# ============================================================================
# VALIDACION
# ============================================================================

RUC_LENGTH: Final[int] = 11
DNI_LENGTH: Final[int] = 8
MAX_ITEMS_PER_INVOICE: Final[int] = 99
MIN_MONTO: Final[Decimal] = Decimal("0.01")

DEFAULT_SERIE_FACTURA: Final[str] = "E001"
DEFAULT_SERIE_BOLETA: Final[str] = "B001"

RUC_MULTIPLIERS: Final[tuple[int, ...]] = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)
VALID_RUC_PREFIXES: Final[tuple[str, ...]] = ("10", "15", "17", "20")
