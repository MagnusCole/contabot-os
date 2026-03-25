"""
Registro y agregación de compras/gastos.

Gestiona el ciclo de vida de comprobantes de compra:
ingreso -> validación -> agregación para crédito fiscal.

Uso:
    from contabot.fiscal.expenses import registrar_compra, agregar_compras_periodo

    compra = registrar_compra(db, datos_compra)
    totales = agregar_compras_periodo(db, ruc_comprador="20100000000", periodo="2026-02")
"""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import extract, func
from sqlalchemy.orm import Session

from contabot.db.constants import IGV_RATE_FLOAT as IGV_RATE
from contabot.db.models import CategoriaGasto, Compra, TipoComprobanteCompra

logger = logging.getLogger(__name__)


# ============================================================================
# REGISTRO
# ============================================================================


def registrar_compra(
    db: Session,
    ruc_comprador: str,
    ruc_proveedor: str,
    razon_social_proveedor: str,
    serie: str,
    numero: str,
    fecha_emision: date,
    monto_subtotal: float,
    monto_igv: float,
    monto_total: float,
    tipo_comprobante: str = TipoComprobanteCompra.FACTURA.value,
    categoria: str = CategoriaGasto.OTROS.value,
    descripcion: str | None = None,
    tiene_credito_fiscal: bool = True,
    moneda: str = "PEN",
    tipo_cambio: float = 1.0,
    monto_no_gravado: float = 0.0,
    archivo_path: str | None = None,
    notas: str | None = None,
) -> Compra:
    """
    Registra un comprobante de compra.

    Valida duplicados por serie-numero-proveedor antes de insertar.

    Returns:
        Compra creada

    Raises:
        ValueError: Si el comprobante ya existe
    """
    # Verificar duplicado
    existente = (
        db.query(Compra)
        .filter(
            Compra.serie == serie.upper(),
            Compra.numero == numero,
            Compra.ruc_proveedor == ruc_proveedor,
        )
        .first()
    )
    if existente:
        raise ValueError(
            f"Comprobante {serie}-{numero} del proveedor {ruc_proveedor} ya existe (id={existente.id})"
        )

    compra = Compra(
        ruc_comprador=ruc_comprador,
        ruc_proveedor=ruc_proveedor,
        razon_social_proveedor=razon_social_proveedor,
        tipo_comprobante=tipo_comprobante,
        serie=serie.upper(),
        numero=numero,
        fecha_emision=fecha_emision,
        monto_subtotal=round(monto_subtotal, 2),
        monto_igv=round(monto_igv, 2),
        monto_no_gravado=round(monto_no_gravado, 2),
        monto_total=round(monto_total, 2),
        moneda=moneda,
        tipo_cambio=tipo_cambio,
        categoria=categoria,
        descripcion=descripcion,
        tiene_credito_fiscal=tiene_credito_fiscal,
        archivo_path=archivo_path,
        notas=notas,
    )

    db.add(compra)
    db.commit()
    db.refresh(compra)

    logger.info(
        "Compra registrada: %s-%s | %s | S/%.2f",
        serie,
        numero,
        razon_social_proveedor,
        monto_total,
    )
    return compra


def registrar_gasto_simple(
    db: Session,
    ruc_comprador: str,
    proveedor: str,
    monto_total: float,
    fecha: date,
    categoria: str = CategoriaGasto.OTROS.value,
    descripcion: str | None = None,
    con_factura: bool = True,
) -> Compra:
    """
    Registra un gasto de forma simplificada (sin serie/número).

    Para gastos menores o recurrentes donde no se tiene el detalle
    completo del comprobante. Genera un número interno.
    """
    # Generar número interno
    count = (
        db.query(func.count(Compra.id))
        .filter(
            Compra.ruc_comprador == ruc_comprador,
            Compra.ruc_proveedor == "00000000000",
        )
        .scalar()
    )
    numero_interno = str(count + 1).zfill(6)

    # Descomponer total
    if con_factura:
        subtotal = round(monto_total / (1 + IGV_RATE), 2)
        igv = round(monto_total - subtotal, 2)
    else:
        subtotal = monto_total
        igv = 0.0

    return registrar_compra(
        db=db,
        ruc_comprador=ruc_comprador,
        ruc_proveedor="00000000000",
        razon_social_proveedor=proveedor,
        serie="INT0",
        numero=numero_interno,
        fecha_emision=fecha,
        monto_subtotal=subtotal,
        monto_igv=igv,
        monto_total=monto_total,
        tipo_comprobante=TipoComprobanteCompra.OTROS.value,
        categoria=categoria,
        descripcion=descripcion,
        tiene_credito_fiscal=con_factura,
    )


# ============================================================================
# AGREGACIÓN
# ============================================================================


def agregar_compras_periodo(
    db: Session,
    ruc_comprador: str,
    periodo: str,
) -> dict:
    """
    Agrega compras de un período tributario.

    Returns:
        dict con totales: monto_subtotal, monto_igv, monto_total,
        igv_credito_fiscal, cantidad, por_categoria
    """
    anio, mes = periodo.split("-")
    anio_int, mes_int = int(anio), int(mes)

    # Totales generales
    result = (
        db.query(
            func.coalesce(func.sum(Compra.monto_subtotal), 0.0).label("subtotal"),
            func.coalesce(func.sum(Compra.monto_igv), 0.0).label("igv"),
            func.coalesce(func.sum(Compra.monto_total), 0.0).label("total"),
            func.count(Compra.id).label("cantidad"),
        )
        .filter(
            Compra.ruc_comprador == ruc_comprador,
            extract("year", Compra.fecha_emision) == anio_int,
            extract("month", Compra.fecha_emision) == mes_int,
        )
        .one()
    )

    # Subtotal e IGV solo de compras con crédito fiscal
    credito = (
        db.query(
            func.coalesce(func.sum(Compra.monto_subtotal), 0.0).label("subtotal_credito"),
            func.coalesce(func.sum(Compra.monto_igv), 0.0).label("igv_credito"),
        )
        .filter(
            Compra.ruc_comprador == ruc_comprador,
            Compra.tiene_credito_fiscal == True,  # noqa: E712
            extract("year", Compra.fecha_emision) == anio_int,
            extract("month", Compra.fecha_emision) == mes_int,
        )
        .one()
    )

    # Desglose por categoría
    categorias = (
        db.query(
            Compra.categoria,
            func.sum(Compra.monto_total).label("total"),
            func.count(Compra.id).label("cantidad"),
        )
        .filter(
            Compra.ruc_comprador == ruc_comprador,
            extract("year", Compra.fecha_emision) == anio_int,
            extract("month", Compra.fecha_emision) == mes_int,
        )
        .group_by(Compra.categoria)
        .all()
    )

    por_categoria = {
        cat.categoria: {"total": float(cat.total), "cantidad": int(cat.cantidad)}
        for cat in categorias
    }

    return {
        "monto_subtotal": float(result.subtotal),
        "monto_igv": float(result.igv),
        "monto_total": float(result.total),
        "subtotal_con_credito": float(credito.subtotal_credito),
        "subtotal_sin_credito": float(result.subtotal) - float(credito.subtotal_credito),
        "igv_credito_fiscal": float(credito.igv_credito),
        "cantidad": int(result.cantidad),
        "por_categoria": por_categoria,
    }


def listar_compras_periodo(
    db: Session,
    ruc_comprador: str,
    periodo: str,
) -> list[Compra]:
    """Lista todas las compras de un período, ordenadas por fecha."""
    anio, mes = periodo.split("-")
    return (
        db.query(Compra)
        .filter(
            Compra.ruc_comprador == ruc_comprador,
            extract("year", Compra.fecha_emision) == int(anio),
            extract("month", Compra.fecha_emision) == int(mes),
        )
        .order_by(Compra.fecha_emision, Compra.id)
        .all()
    )
