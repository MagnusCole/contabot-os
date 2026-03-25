"""contabot.accounting -- Unit economics: LTV, CAC, churn, retention.

Usage:
    from contabot.accounting import LTVCalculator, CACCalculator
    from contabot.accounting.dashboard import reporte_texto, reporte_telegram

    # LTV
    ltv = LTVCalculator()
    print(ltv.snapshot("2026-03"))
    print(ltv.customer_profile("20100000000"))

    # CAC
    cac = CACCalculator()
    cac.register_spend("2026-03", "youtube", 500.0)
    print(cac.ltv_cac_ratio("2026-03"))

    # Dashboard
    print(reporte_texto("2026-03"))
"""

from __future__ import annotations

from .cac import CACCalculator
from .churn import monthly_churn, mrr_recurring, net_revenue_retention, retention_curve
from .ltv import LTVCalculator
from .models import (
    CACSnapshot,
    ChannelCAC,
    ChurnMetrics,
    CohortRow,
    CustomerProfile,
    LTVSnapshot,
    SegmentLTV,
    UnitEconomics,
)

__all__ = [
    "CACCalculator",
    "CACSnapshot",
    "ChannelCAC",
    "ChurnMetrics",
    "CohortRow",
    "CustomerProfile",
    "LTVCalculator",
    "LTVSnapshot",
    "SegmentLTV",
    "UnitEconomics",
    "monthly_churn",
    "mrr_recurring",
    "net_revenue_retention",
    "retention_curve",
]
