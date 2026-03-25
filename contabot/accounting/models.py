"""contabot.accounting.models -- Data models for unit economics: LTV, CAC, churn."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class CustomerProfile:
    """Revenue timeline for an individual customer."""

    ruc: str
    razon_social: str
    primera_factura: str  # YYYY-MM-DD
    ultima_factura: str
    total_revenue: float
    invoice_count: int
    avg_monthly_revenue: float
    lifespan_months: int
    is_active: bool  # last invoice within the last 3 months
    simple_ltv: float  # avg_monthly_revenue * lifespan_months


@dataclass
class CohortRow:
    """Retention of a customer cohort grouped by first-invoice month."""

    cohort_month: str  # YYYY-MM
    cohort_size: int
    retention: list[float] = field(default_factory=list)  # [100.0, 80.0, ...]


@dataclass
class ChurnMetrics:
    """Churn and retention metrics for a period."""

    periodo: str
    active_previous: int
    churned: int
    monthly_churn_rate: float  # 0.0 - 1.0
    retention_rate: float
    net_revenue_retention: float  # >1.0 = expansion
    mrr_recurring: float


@dataclass
class SegmentLTV:
    """Average LTV for a segment (by issuer, industry, etc.)."""

    segment_name: str
    segment_key: str
    customer_count: int
    avg_ltv: float
    avg_monthly_revenue: float


@dataclass
class LTVSnapshot:
    """Aggregated LTV snapshot for the business."""

    periodo: str
    generado_en: str = field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M")
    )
    avg_ltv: float = 0.0
    median_ltv: float = 0.0
    predictive_ltv: float | None = None
    total_customers: int = 0
    active_customers: int = 0
    avg_lifespan_months: float = 0.0
    arpu: float = 0.0  # avg revenue per user (monthly)
    segments: list[SegmentLTV] = field(default_factory=list)
    cohorts: list[CohortRow] = field(default_factory=list)


@dataclass
class ChannelCAC:
    """CAC breakdown by acquisition channel."""

    canal: str
    spend: float
    new_customers: int
    cac: float


@dataclass
class CACSnapshot:
    """Acquisition cost snapshot for a period."""

    periodo: str
    generado_en: str = field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M")
    )
    total_spend: float = 0.0
    new_customers: int = 0
    cac: float = 0.0
    channels: list[ChannelCAC] = field(default_factory=list)


@dataclass
class UnitEconomics:
    """Executive summary: the LTV/CAC ratio and derived metrics."""

    periodo: str
    generado_en: str = field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M")
    )
    avg_ltv: float = 0.0
    cac: float = 0.0
    ltv_cac_ratio: float = 0.0
    payback_months: float = 0.0
    monthly_churn_rate: float = 0.0
    arpu: float = 0.0
    signal: str = "red"  # green | yellow | red
    commentary: str = ""
