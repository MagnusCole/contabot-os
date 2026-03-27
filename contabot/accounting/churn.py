"""contabot.accounting.churn -- Churn, retention, and revenue retention.

Utility functions that read directly from the database (facturas table).
Read-only -- no data modifications.
"""

from __future__ import annotations

import logging
from datetime import date

from contabot.db.connection import get_conn

logger = logging.getLogger(__name__)

_EXCLUDED_STATUS = ("cancelado", "failed")


def _prev_periodo(periodo: str) -> str:
    """YYYY-MM -> previous month."""
    y, m = int(periodo[:4]), int(periodo[5:7])
    m -= 1
    if m < 1:
        m = 12
        y -= 1
    return f"{y}-{m:02d}"


def _active_customers(conn, periodo: str) -> set[str]:
    """RUCs with at least one valid invoice in the period."""
    rows = conn.execute(
        "SELECT DISTINCT ruc_receptor FROM facturas "
        "WHERE strftime('%Y-%m', fecha) = ? AND status NOT IN (?, ?)",
        (periodo, *_EXCLUDED_STATUS),
    ).fetchall()
    return {r["ruc_receptor"] for r in rows}


def _revenue_by_customer(conn, periodo: str) -> dict[str, float]:
    """{ruc: total_revenue} for the period."""
    rows = conn.execute(
        "SELECT ruc_receptor, SUM(monto_total) as rev FROM facturas "
        "WHERE strftime('%Y-%m', fecha) = ? AND status NOT IN (?, ?) "
        "GROUP BY ruc_receptor",
        (periodo, *_EXCLUDED_STATUS),
    ).fetchall()
    return {r["ruc_receptor"]: r["rev"] for r in rows}


def monthly_churn(periodo: str) -> float:
    """Monthly churn rate: active customers last month who didn't invoice this month.

    Returns:
        Float between 0.0 and 1.0. 0.0 if no data.
    """
    prev = _prev_periodo(periodo)
    conn = get_conn()
    try:
        prev_active = _active_customers(conn, prev)
        curr_active = _active_customers(conn, periodo)

        if not prev_active:
            return 0.0

        churned = prev_active - curr_active
        return len(churned) / len(prev_active)
    finally:
        conn.close()


def retention_curve(cohort_month: str, max_months: int = 12) -> list[float]:
    """Retention curve for a cohort (first-invoice month).

    Args:
        cohort_month: YYYY-MM of the cohort.
        max_months: Maximum months to track.

    Returns:
        List of percentages [100.0, 80.0, 65.0, ...] where index=months since cohort.
    """
    conn = get_conn()
    try:
        # Customers whose first invoice is in cohort_month
        cohort_customers = conn.execute(
            """
            SELECT ruc_receptor
            FROM facturas
            WHERE status NOT IN (?, ?)
            GROUP BY ruc_receptor
            HAVING strftime('%Y-%m', MIN(fecha)) = ?
            """,
            (*_EXCLUDED_STATUS, cohort_month),
        ).fetchall()

        cohort_rucs = {r["ruc_receptor"] for r in cohort_customers}
        cohort_size = len(cohort_rucs)

        if cohort_size == 0:
            return []

        # Activity per month for these customers
        rows = conn.execute(
            f"""
            SELECT ruc_receptor, strftime('%Y-%m', fecha) as mes
            FROM facturas
            WHERE ruc_receptor IN ({','.join('?' * len(cohort_rucs))})
              AND status NOT IN (?, ?)
            GROUP BY ruc_receptor, mes
            """,
            (*cohort_rucs, *_EXCLUDED_STATUS),
        ).fetchall()

        # Map month -> set of active rucs
        activity: dict[str, set[str]] = {}
        for r in rows:
            activity.setdefault(r["mes"], set()).add(r["ruc_receptor"])

        # Generate curve
        curve: list[float] = []
        cy, cm = int(cohort_month[:4]), int(cohort_month[5:7])

        for offset in range(max_months + 1):
            m = cm + offset
            y = cy + (m - 1) // 12
            m = ((m - 1) % 12) + 1
            key = f"{y}-{m:02d}"

            # Don't go beyond today
            today = date.today()
            if y > today.year or (y == today.year and m > today.month):
                break

            active_in_month = activity.get(key, set())
            retained = len(cohort_rucs & active_in_month)
            curve.append(round(retained / cohort_size * 100, 1))

        return curve
    finally:
        conn.close()


def net_revenue_retention(periodo: str) -> float:
    """Net Revenue Retention: existing customer revenue vs previous period.

    >1.0 = expansion (upsell / more invoicing per customer).
    <1.0 = contraction.

    Returns:
        Float ratio. 0.0 if no data.
    """
    prev = _prev_periodo(periodo)
    conn = get_conn()
    try:
        prev_rev = _revenue_by_customer(conn, prev)
        curr_rev = _revenue_by_customer(conn, periodo)

        if not prev_rev:
            return 0.0

        # Only customers that existed in the previous period
        existing_customers = set(prev_rev.keys())
        prev_total = sum(prev_rev[ruc] for ruc in existing_customers)
        curr_total = sum(curr_rev.get(ruc, 0.0) for ruc in existing_customers)

        if prev_total == 0:
            return 0.0

        return round(curr_total / prev_total, 4)
    finally:
        conn.close()


def mrr_recurring(periodo: str) -> float:
    """MRR from recurring customers (who also invoiced the previous month).

    Returns:
        Total amount.
    """
    prev = _prev_periodo(periodo)
    conn = get_conn()
    try:
        prev_active = _active_customers(conn, prev)
        curr_rev = _revenue_by_customer(conn, periodo)

        return sum(
            rev for ruc, rev in curr_rev.items() if ruc in prev_active
        )
    finally:
        conn.close()
