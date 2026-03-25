"""contabot.accounting.ltv -- Lifetime Value calculator.

Stateless: each method opens and closes its own connection.
Reads invoices + customers from the database. No data modifications.
"""

from __future__ import annotations

import logging
import statistics
from datetime import date, datetime

from contabot.db.connection import get_conn

from .churn import monthly_churn, retention_curve
from .models import CohortRow, CustomerProfile, LTVSnapshot, SegmentLTV

logger = logging.getLogger(__name__)

_EXCLUDED_STATUS = ("cancelado", "failed")

# A customer is considered active if they invoiced within the last N months
_ACTIVE_WINDOW_MONTHS = 3


class LTVCalculator:
    """LTV calculation engine by customer, segment, and cohort."""

    def customer_profile(self, ruc: str) -> CustomerProfile | None:
        """Revenue profile for an individual customer."""
        conn = get_conn()
        try:
            row = conn.execute(
                """
                SELECT
                    ruc_receptor,
                    MIN(fecha) as primera,
                    MAX(fecha) as ultima,
                    SUM(monto_total) as total_rev,
                    COUNT(*) as n_facturas
                FROM facturas
                WHERE ruc_receptor = ?
                  AND status NOT IN (?, ?)
                GROUP BY ruc_receptor
                """,
                (ruc, *_EXCLUDED_STATUS),
            ).fetchone()

            if not row:
                return None

            # Business name
            cli = conn.execute(
                "SELECT razon_social FROM clientes WHERE ruc = ?", (ruc,)
            ).fetchone()
            razon = cli["razon_social"] if cli else ruc

            primera = row["primera"]
            ultima = row["ultima"]
            total_rev = row["total_rev"] or 0.0
            n_facturas = row["n_facturas"]

            # Lifespan in months
            d_primera = datetime.strptime(primera, "%Y-%m-%d").date()
            d_ultima = datetime.strptime(ultima, "%Y-%m-%d").date()
            lifespan = max(1, (d_ultima.year - d_primera.year) * 12 + d_ultima.month - d_primera.month + 1)

            avg_monthly = total_rev / lifespan

            # Active = last invoice within the last N months
            today = date.today()
            months_since_last = (today.year - d_ultima.year) * 12 + today.month - d_ultima.month
            is_active = months_since_last <= _ACTIVE_WINDOW_MONTHS

            return CustomerProfile(
                ruc=ruc,
                razon_social=razon,
                primera_factura=primera,
                ultima_factura=ultima,
                total_revenue=round(total_rev, 2),
                invoice_count=n_facturas,
                avg_monthly_revenue=round(avg_monthly, 2),
                lifespan_months=lifespan,
                is_active=is_active,
                simple_ltv=round(avg_monthly * lifespan, 2),
            )
        finally:
            conn.close()

    def all_profiles(self) -> list[CustomerProfile]:
        """Profile of all customers with at least one valid invoice."""
        conn = get_conn()
        try:
            rucs = conn.execute(
                """
                SELECT DISTINCT ruc_receptor
                FROM facturas
                WHERE status NOT IN (?, ?)
                """,
                _EXCLUDED_STATUS,
            ).fetchall()
        finally:
            conn.close()

        profiles = []
        for r in rucs:
            p = self.customer_profile(r["ruc_receptor"])
            if p:
                profiles.append(p)
        return profiles

    def cohort_analysis(self, meses_atras: int = 12) -> list[CohortRow]:
        """Cohort analysis: retention by first-invoice month."""
        conn = get_conn()
        try:
            # Get cohorts (first-invoice month per customer)
            rows = conn.execute(
                """
                SELECT strftime('%Y-%m', MIN(fecha)) as cohort_month,
                       COUNT(*) as cohort_size
                FROM facturas
                WHERE status NOT IN (?, ?)
                GROUP BY ruc_receptor
                """,
                _EXCLUDED_STATUS,
            ).fetchall()
        finally:
            conn.close()

        # Group by cohort month
        cohort_sizes: dict[str, int] = {}
        for r in rows:
            cm = r["cohort_month"]
            cohort_sizes[cm] = cohort_sizes.get(cm, 0) + 1

        # Filter to the last N months
        today = date.today()
        cutoff_y = today.year - (meses_atras // 12)
        cutoff_m = today.month - (meses_atras % 12)
        if cutoff_m < 1:
            cutoff_m += 12
            cutoff_y -= 1
        cutoff = f"{cutoff_y}-{cutoff_m:02d}"

        cohorts: list[CohortRow] = []
        for cm in sorted(cohort_sizes.keys()):
            if cm < cutoff:
                continue
            curve = retention_curve(cm, max_months=meses_atras)
            cohorts.append(CohortRow(
                cohort_month=cm,
                cohort_size=cohort_sizes[cm],
                retention=curve,
            ))

        return cohorts

    def segment_ltv(self, by: str = "emisor") -> list[SegmentLTV]:
        """Average LTV by segment.

        Args:
            by: "emisor" (company/ruc_emisor) or "rubro" (issuer industry).
        """
        conn = get_conn()
        try:
            if by == "rubro":
                group_col = "e.rubro"
                join = "JOIN emisores e ON f.ruc_emisor = e.ruc"
            else:
                group_col = "f.ruc_emisor"
                join = ""

            # Revenue per customer per segment
            query = f"""
                SELECT {group_col} as seg,
                       f.ruc_receptor,
                       SUM(f.monto_total) as total_rev,
                       MIN(f.fecha) as primera,
                       MAX(f.fecha) as ultima
                FROM facturas f
                {join}
                WHERE f.status NOT IN (?, ?)
                GROUP BY {group_col}, f.ruc_receptor
            """
            rows = conn.execute(query, _EXCLUDED_STATUS).fetchall()
        finally:
            conn.close()

        # Group by segment
        seg_data: dict[str, list[float]] = {}
        seg_monthly: dict[str, list[float]] = {}

        for r in rows:
            seg = r["seg"] or "sin_clasificar"
            total_rev = r["total_rev"] or 0.0
            primera = r["primera"]
            ultima = r["ultima"]

            d_p = datetime.strptime(primera, "%Y-%m-%d").date()
            d_u = datetime.strptime(ultima, "%Y-%m-%d").date()
            lifespan = max(1, (d_u.year - d_p.year) * 12 + d_u.month - d_p.month + 1)
            ltv = total_rev
            monthly = total_rev / lifespan

            seg_data.setdefault(seg, []).append(ltv)
            seg_monthly.setdefault(seg, []).append(monthly)

        # Readable name for issuer
        if by == "emisor":
            conn2 = get_conn()
            try:
                emi_names = {}
                for r in conn2.execute("SELECT ruc, nombre FROM emisores").fetchall():
                    emi_names[r["ruc"]] = r["nombre"]
            finally:
                conn2.close()
        else:
            emi_names = {}

        segments: list[SegmentLTV] = []
        for seg, ltvs in sorted(seg_data.items(), key=lambda x: -sum(x[1]) / len(x[1])):
            segments.append(SegmentLTV(
                segment_name=emi_names.get(seg, seg),
                segment_key=seg,
                customer_count=len(ltvs),
                avg_ltv=round(statistics.mean(ltvs), 2),
                avg_monthly_revenue=round(statistics.mean(seg_monthly[seg]), 2),
            ))

        return segments

    def predictive_ltv(self, min_cohort_months: int = 6) -> float | None:
        """Predictive LTV: avg_monthly_revenue / monthly_churn_rate.

        Only valid when there are cohorts with >= min_cohort_months of history.
        Returns None if there is not enough data.
        """
        profiles = self.all_profiles()
        if not profiles:
            return None

        # Calculate average churn over the last 3 months
        today = date.today()
        churn_rates: list[float] = []
        for offset in range(1, 4):
            m = today.month - offset
            y = today.year
            if m < 1:
                m += 12
                y -= 1
            cr = monthly_churn(f"{y}-{m:02d}")
            if cr > 0:
                churn_rates.append(cr)

        if not churn_rates:
            return None

        avg_churn = statistics.mean(churn_rates)
        if avg_churn == 0:
            return None

        active = [p for p in profiles if p.is_active]
        if not active:
            return None

        avg_monthly = statistics.mean(p.avg_monthly_revenue for p in active)
        return round(avg_monthly / avg_churn, 2)

    def snapshot(self, periodo: str | None = None) -> LTVSnapshot:
        """Complete LTV snapshot for the business."""
        periodo = periodo or date.today().strftime("%Y-%m")

        profiles = self.all_profiles()
        if not profiles:
            return LTVSnapshot(periodo=periodo)

        ltvs = [p.simple_ltv for p in profiles]
        active = [p for p in profiles if p.is_active]
        lifespans = [p.lifespan_months for p in profiles]

        arpu = 0.0
        if active:
            arpu = statistics.mean(p.avg_monthly_revenue for p in active)

        return LTVSnapshot(
            periodo=periodo,
            avg_ltv=round(statistics.mean(ltvs), 2),
            median_ltv=round(statistics.median(ltvs), 2),
            predictive_ltv=self.predictive_ltv(),
            total_customers=len(profiles),
            active_customers=len(active),
            avg_lifespan_months=round(statistics.mean(lifespans), 1),
            arpu=round(arpu, 2),
            segments=self.segment_ltv(),
            cohorts=self.cohort_analysis(),
        )
