from __future__ import annotations

"""
SQLAlchemy models for the ContaBot invoicing system.

Single source of truth for all database models.
SQLite-only. Override the database path via DATABASE_PATH env var.
"""

import enum
import os
from collections.abc import Generator
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    create_engine,
    event,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
    sessionmaker,
)
from sqlalchemy.sql import func

# ============================================================================
# DATABASE CONFIGURATION
# ============================================================================

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATABASE_PATH = Path(
    os.getenv("DATABASE_PATH", str(_PROJECT_ROOT / "data" / "db" / "contabot.db"))
)

# Ensure directory exists
DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

DATABASE_URL = f"sqlite:///{DATABASE_PATH}"

engine = create_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False},
    pool_pre_ping=True,
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    """Configure SQLite with WAL for better concurrent performance."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """Dependency for obtaining a database session.

    Yields:
        Session: Configured SQLAlchemy session.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ============================================================================
# DECLARATIVE BASE
# ============================================================================


class Base(DeclarativeBase):
    """Declarative base for all models."""

    pass


# ============================================================================
# ENUMS
# ============================================================================


class InvoiceStatus(str, enum.Enum):
    """Invoice lifecycle states.

    Typical flow: PENDING -> PROCESSING -> EMITTED
    Error flow:   PENDING -> PROCESSING -> FAILED
    Cancellation: EMITTED -> CANCELLED
    """

    PENDING = "pending"
    PROCESSING = "processing"
    EMITTED = "emitted"
    EMITTED_NO_PDF = "emitted_no_pdf"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRY = "retry"
    ANULADA = "anulada"
    PENDING_VALIDATION = "pending_validation"
    COMPLETED = "completed"
    VALIDATION_FAILED = "validation_failed"

    @classmethod
    def from_spanish(cls, value: str) -> InvoiceStatus:
        """Convert a Spanish status label to enum."""
        _MAP = {
            "PENDIENTE": cls.PENDING,
            "PROCESANDO": cls.PROCESSING,
            "EMITIDO": cls.EMITTED,
            "EMITIDO_SIN_PDF": cls.EMITTED_NO_PDF,
            "ERROR": cls.FAILED,
            "ANULADO": cls.ANULADA,
        }
        return _MAP.get(value.upper().strip(), cls.PENDING)

    @property
    def label_es(self) -> str:
        """Human-readable label in Spanish."""
        _LABELS = {
            "pending": "PENDIENTE",
            "processing": "PROCESANDO",
            "emitted": "EMITIDO",
            "emitted_no_pdf": "EMITIDO SIN PDF",
            "failed": "ERROR",
            "cancelled": "CANCELADO",
            "retry": "REINTENTO",
            "anulada": "ANULADO",
            "pending_validation": "VALIDACION PENDIENTE",
            "completed": "COMPLETADO",
            "validation_failed": "VALIDACION FALLIDA",
        }
        return _LABELS.get(self.value, self.value.upper())


class JobStatus(str, enum.Enum):
    """Batch job states."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TipoComprobanteCompra(str, enum.Enum):
    """Purchase receipt types accepted by SUNAT."""

    FACTURA = "01"
    RECIBO_HONORARIOS = "02"
    BOLETA = "03"
    NOTA_CREDITO = "07"
    NOTA_DEBITO = "08"
    RECIBO_SERVICIOS = "14"
    OTROS = "00"


class CategoriaGasto(str, enum.Enum):
    """Expense categories for internal classification."""

    MERCADERIA = "mercaderia"
    MATERIA_PRIMA = "materia_prima"
    SERVICIOS = "servicios"
    ALQUILER = "alquiler"
    SERVICIOS_PUBLICOS = "servicios_publicos"
    COMBUSTIBLE = "combustible"
    PLANILLA = "planilla"
    HONORARIOS = "honorarios"
    SUMINISTROS = "suministros"
    MANTENIMIENTO = "mantenimiento"
    SEGUROS = "seguros"
    BANCARIOS = "bancarios"
    OTROS = "otros"


class TrabajoEstado(str, enum.Enum):
    """Monthly work order states."""

    ACTIVO = "activo"
    COMPLETADO = "completado"
    PAUSADO = "pausado"
    CANCELADO = "cancelado"


# ============================================================================
# MODELS
# ============================================================================


class Emisor(Base):
    """Invoice issuer (facturador).

    Represents an entity that issues invoices via SUNAT.
    Example RUC: 20100000000
    """

    __tablename__ = "emisores"

    ruc: Mapped[str] = mapped_column(String(11), primary_key=True)
    nombre: Mapped[str | None] = mapped_column(String(255), nullable=True)
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    empresa: Mapped[str | None] = mapped_column(String(50), nullable=True)
    rubro: Mapped[str | None] = mapped_column(Text, nullable=True)
    direccion: Mapped[str | None] = mapped_column(String(500), nullable=True)

    def __repr__(self) -> str:
        return f"<Emisor(ruc='{self.ruc}', nombre='{self.nombre}')>"


class Client(Base):
    """Client / company that receives invoices.

    Example RUC: 20100000000
    """

    __tablename__ = "clientes"

    ruc: Mapped[str] = mapped_column(String(11), primary_key=True)
    razon_social: Mapped[str | None] = mapped_column(String(255), nullable=True)
    direccion: Mapped[str | None] = mapped_column(String(500), nullable=True)
    updated_at: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<Client(ruc='{self.ruc}', razon_social='{self.razon_social}')>"


# Spanish alias for compatibility
Cliente = Client


class ClientEmisor(Base):
    """Emisor assignments per client."""

    __tablename__ = "client_emisores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ruc_cliente: Mapped[str] = mapped_column(String(11), nullable=False, index=True)
    ruc_emisor: Mapped[str] = mapped_column(String(11), nullable=False)
    orden: Mapped[int] = mapped_column(Integer, default=0)
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    __table_args__ = (Index("uq_client_emisor", "ruc_cliente", "ruc_emisor", unique=True),)

    def __repr__(self) -> str:
        return f"<ClientEmisor(ruc_cliente={self.ruc_cliente}, ruc_emisor={self.ruc_emisor})>"


class Invoice(Base):
    """Electronic invoice (factura electronica).

    Core table: ``facturas``
    """

    __tablename__ = "facturas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    ruc_emisor: Mapped[str | None] = mapped_column(Text, nullable=True)
    nombre_emisor: Mapped[str | None] = mapped_column(Text, nullable=True)
    ruc_receptor: Mapped[str | None] = mapped_column(Text, nullable=True)

    fecha_emision: Mapped[str | None] = mapped_column(
        "fecha", Text, nullable=True, comment="Issue date (YYYY-MM-DD)"
    )

    monto_subtotal: Mapped[float] = mapped_column(Float, nullable=True, default=0.0)
    monto_igv: Mapped[float] = mapped_column(Float, nullable=True, default=0.0)
    monto_total: Mapped[float] = mapped_column(Float, nullable=True, default=0.0)

    status: Mapped[str] = mapped_column(
        Text, nullable=True, default=InvoiceStatus.PENDING.value
    )
    pdf_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column("error", Text, nullable=True)
    notas: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=True, default=0)

    created_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    emitted_at: Mapped[str | None] = mapped_column(Text, nullable=True)

    facturador: Mapped[str | None] = mapped_column("empresa", Text, nullable=True)

    items: Mapped[list[InvoiceItem]] = relationship(
        "InvoiceItem", back_populates="invoice", cascade="all, delete-orphan", lazy="selectin"
    )

    def __repr__(self) -> str:
        return (
            f"<Invoice(id={self.id}, ruc_emisor='{self.ruc_emisor}', "
            f"ruc_receptor='{self.ruc_receptor}', status='{self.status}')>"
        )

    @property
    def numero_completo(self) -> str:
        return f"#{self.id}"

    @property
    def status_enum(self) -> InvoiceStatus:
        try:
            return InvoiceStatus(self.status)
        except ValueError:
            return InvoiceStatus.PENDING


class InvoiceItem(Base):
    """Invoice line item.

    Core table: ``facturas_items``
    """

    __tablename__ = "facturas_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    invoice_id: Mapped[int] = mapped_column(
        "factura_id", Integer, ForeignKey("facturas.id"), nullable=False
    )
    descripcion: Mapped[str] = mapped_column(Text, nullable=False)
    unidad_medida: Mapped[str] = mapped_column(Text, nullable=True, default="UNIDAD")
    cantidad: Mapped[float] = mapped_column(Float, nullable=True)
    precio_unitario: Mapped[float] = mapped_column("precio_sin_igv", Float, nullable=True)
    subtotal: Mapped[float] = mapped_column(Float, nullable=True, default=0.0)

    invoice: Mapped[Invoice] = relationship("Invoice", back_populates="items")

    def __repr__(self) -> str:
        desc = self.descripcion[:30] if self.descripcion else "?"
        return f"<InvoiceItem(id={self.id}, descripcion='{desc}...', cantidad={self.cantidad})>"


class Compra(Base):
    """Purchase receipt / expense record.

    Tracks purchases with invoices for:
    - IGV tax credit (deducts IGV from sales)
    - Purchase registry (SIRE)
    - Expense control and cash flow
    """

    __tablename__ = "compras"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    ruc_comprador: Mapped[str] = mapped_column(
        String(11), nullable=False, index=True, comment="Buyer RUC"
    )
    tipo_documento_proveedor: Mapped[str] = mapped_column(
        String(2), nullable=False, default="6", comment="Provider ID type (6=RUC, 1=DNI)"
    )
    ruc_proveedor: Mapped[str] = mapped_column(
        String(11), nullable=False, index=True, comment="Provider RUC/DNI"
    )
    razon_social_proveedor: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="Provider legal name"
    )

    tipo_comprobante: Mapped[str] = mapped_column(
        String(2), nullable=False, default=TipoComprobanteCompra.FACTURA.value
    )
    serie: Mapped[str] = mapped_column(String(4), nullable=False)
    numero: Mapped[str] = mapped_column(String(20), nullable=False)
    fecha_emision: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    fecha_vencimiento: Mapped[date | None] = mapped_column(Date, nullable=True)

    monto_subtotal: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    monto_igv: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    monto_no_gravado: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    monto_total: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    moneda: Mapped[str] = mapped_column(String(3), nullable=False, default="PEN")
    tipo_cambio: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)

    categoria: Mapped[str] = mapped_column(
        String(30), nullable=False, default=CategoriaGasto.OTROS.value
    )
    descripcion: Mapped[str | None] = mapped_column(Text, nullable=True)

    tiene_credito_fiscal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    pagado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    fecha_pago: Mapped[date | None] = mapped_column(Date, nullable=True)

    archivo_path: Mapped[str | None] = mapped_column(String(500), nullable=True)

    notas: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now, onupdate=datetime.now
    )

    __table_args__ = (
        Index("ix_compras_periodo", "ruc_comprador", "fecha_emision"),
        Index("ix_compras_proveedor", "ruc_proveedor"),
        Index("ix_compras_comprobante", "serie", "numero", "ruc_proveedor"),
    )

    def __repr__(self) -> str:
        return f"<Compra(id={self.id}, {self.serie}-{self.numero}, S/{self.monto_total:.2f})>"

    @property
    def numero_completo(self) -> str:
        return f"{self.serie}-{self.numero}"

    @property
    def periodo(self) -> str:
        """Tax period YYYY-MM."""
        return f"{self.fecha_emision.year}-{self.fecha_emision.month:02d}"

    @property
    def igv_credito_fiscal(self) -> float:
        """IGV usable as tax credit."""
        return self.monto_igv if self.tiene_credito_fiscal else 0.0


class ContabotCliente(Base):
    """ContaBot WhatsApp client.

    Represents an end-user subscribed to the ContaBot service.
    """

    __tablename__ = "contabot_clientes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telefono: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    ruc: Mapped[str] = mapped_column(Text, nullable=False)
    razon_social: Mapped[str | None] = mapped_column(Text, nullable=True)
    ruc_emisor: Mapped[str | None] = mapped_column(Text, nullable=True)
    plan: Mapped[str] = mapped_column(Text, nullable=False, default="basico")
    activo: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    dia_reporte: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    hora_reporte: Mapped[str] = mapped_column(Text, nullable=False, default="08:00")
    onboarded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return f"<ContabotCliente(tel='{self.telefono}', ruc='{self.ruc}')>"


# ============================================================================
# INITIALIZATION
# ============================================================================


def init_db() -> None:
    """Initialize the database, creating all tables.

    Idempotent — can be called multiple times without recreating existing tables.

    Example::

        >>> from contabot.db import init_db
        >>> init_db()
    """
    Base.metadata.create_all(bind=engine)
    print(f"[OK] Database initialized at: {DATABASE_PATH}")


def get_or_create_client(db: Session, ruc: str, razon_social: str, **kwargs) -> tuple[Client, bool]:
    """Get or create a client by RUC.

    Args:
        db: Database session.
        ruc: Client RUC (e.g. ``20100000000``).
        razon_social: Legal name.
        **kwargs: Additional fields.

    Returns:
        Tuple of (client, created) where created is True if newly created.
    """
    client = db.query(Client).filter(Client.ruc == ruc).first()
    if client:
        return client, False

    client = Client(ruc=ruc, razon_social=razon_social, **kwargs)
    db.add(client)
    db.commit()
    db.refresh(client)
    return client, True
