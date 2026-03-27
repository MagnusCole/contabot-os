"""contabot.accounting.cac -- Customer Acquisition Cost calculator.

Reads from the database (compras, facturas, gasto_adquisicion_mensual) and crm.db (leads).
Writes only to gasto_adquisicion_mensual (manual spend registration).
"""

from __future__ import annotations

import logging
import sqlite3

from contabot.db.connection import DB_PATH, get_conn

from .churn import monthly_churn
from .ltv import LTVCalculator
from .models import CACSnapshot, ChannelCAC, UnitEconomics

logger = logging.getLogger(__name__)

_EXCLUDED_STATUS = ("cancelado", "failed")
_CRM_DB = DB_PATH.parent / "crm.db"


class CACCalculator:
    """CAC and unit economics calculation engine."""

    def _new_customers(self, conn: sqlite3.Connection, periodo: str) -> int:
        """Customers whose first invoice is in this period."""
        row = conn.execute(
            """
            SELECT COUNT(*) as n
            FROM (
                SELECT ruc_receptor
                FROM facturas
                WHERE status NOT IN (?, ?)
                GROUP BY ruc_receptor
                HAVING strftime('%Y-%m', MIN(fecha)) = ?
            )
            """,
            (*_EXCLUDED_STATUS, periodo),
        ).fetchone()
        return row["n"] if row else 0

    def _new_customer_rucs(self, conn: sqlite3.Connection, periodo: str) -> set[str]:
        """RUCs of customers whose first invoice is in this period."""
        rows = conn.execute(
            """
            SELECT ruc_receptor
            FROM facturas
            WHERE status NOT IN (?, ?)
            GROUP BY ruc_receptor
            HAVING strftime('%Y-%m', MIN(fecha)) = ?
            """,
            (*_EXCLUDED_STATUS, periodo),
        ).fetchall()
        return {r["ruc_receptor"] for r in rows}

    def _total_spend(self, conn: sqlite3.Connection, periodo: str) -> float:
        """Total acquisition spend for the period.

        Priority: gasto_adquisicion_mensual > compras.es_adquisicion.
        """
        # 1. Dedicated table
        row = conn.execute(
            "SELECT SUM(monto) as total FROM gasto_adquisicion_mensual WHERE periodo = ?",
            (periodo,),
        ).fetchone()
        if row and row["total"]:
            return row["total"]

        # 2. Fallback: tagged purchases
        row = conn.execute(
            """
            SELECT SUM(monto_total) as total
            FROM compras
            WHERE es_adquisicion = 1
              AND strftime('%Y-%m', fecha_emision) = ?
            """,
            (periodo,),
        ).fetchone()
        return row["total"] if row and row["total"] else 0.0

    def simple_cac(self, periodo: str) -> CACSnapshot:
        """Simple CAC: total_spend / new_customers."""
        conn = get_conn()
        try:
            spend = self._total_spend(conn, periodo)
            new_cust = self._new_customers(conn, periodo)
            cac = round(spend / new_cust, 2) if new_cust > 0 else 0.0

            return CACSnapshot(
                periodo=periodo,
                total_spend=round(spend, 2),
                new_customers=new_cust,
                cac=cac,
            )
        finally:
            conn.close()

    def channel_cac(self, periodo: str) -> list[ChannelCAC]:
        """CAC breakdown by acquisition channel.

        Attribution: join spend by channel with leads.fuente from crm.db.
        """
        conn = get_conn()
        try:
            # Spend by channel
            spend_rows = conn.execute(
                "SELECT canal, SUM(monto) as total FROM gasto_adquisicion_mensual "
                "WHERE periodo = ? GROUP BY canal",
                (periodo,),
            ).fetchall()
            spend_by_channel = {r["canal"]: r["total"] for r in spend_rows}

            # New customers this period
            new_rucs = self._new_customer_rucs(conn, periodo)
        finally:
            conn.close()

        # Attribution via crm.db (leads.fuente -> ruc)
        channel_customers: dict[str, int] = {}
        if _CRM_DB.exists() and new_rucs:
            try:
                crm_conn = sqlite3.connect(str(_CRM_DB))
                crm_conn.row_factory = sqlite3.Row
                leads = crm_conn.execute(
                    f"""
                    SELECT ruc, fuente FROM leads
                    WHERE ruc IN ({','.join('?' * len(new_rucs))})
                    """,
                    tuple(new_rucs),
                ).fetchall()
                crm_conn.close()

                for lead in leads:
                    canal = lead["fuente"] or "desconocido"
                    channel_customers[canal] = channel_customers.get(canal, 0) + 1
            except Exception as exc:
                logger.warning("Could not read crm.db for attribution: %s", exc)

        # Customers without a lead -> unknown
        attributed = sum(channel_customers.values())
        unattributed = len(new_rucs) - attributed
        if unattributed > 0:
            channel_customers["desconocido"] = channel_customers.get("desconocido", 0) + unattributed

        # Combine spend + customers
        all_channels = set(spend_by_channel.keys()) | set(channel_customers.keys())
        all_channels.discard("total")  # exclude the aggregate

        results: list[ChannelCAC] = []
        for canal in sorted(all_channels):
            sp = spend_by_channel.get(canal, 0.0)
            nc = channel_customers.get(canal, 0)
            results.append(ChannelCAC(
                canal=canal,
                spend=round(sp, 2),
                new_customers=nc,
                cac=round(sp / nc, 2) if nc > 0 else 0.0,
            ))

        return results

    def ltv_cac_ratio(self, periodo: str) -> UnitEconomics:
        """Full unit economics: LTV, CAC, ratio, payback, signal."""
        ltv_calc = LTVCalculator()
        ltv_snap = ltv_calc.snapshot(periodo)
        cac_snap = self.simple_cac(periodo)
        churn = monthly_churn(periodo)

        ratio = 0.0
        if cac_snap.cac > 0:
            ratio = round(ltv_snap.avg_ltv / cac_snap.cac, 2)

        payback = 0.0
        if ltv_snap.arpu > 0 and cac_snap.cac > 0:
            payback = round(cac_snap.cac / ltv_snap.arpu, 1)

        # Traffic light signal
        if ratio >= 3:
            signal = "green"
        elif ratio >= 1.5:
            signal = "yellow"
        else:
            signal = "red"

        return UnitEconomics(
            periodo=periodo,
            avg_ltv=ltv_snap.avg_ltv,
            cac=cac_snap.cac,
            ltv_cac_ratio=ratio,
            payback_months=payback,
            monthly_churn_rate=round(churn, 4),
            arpu=ltv_snap.arpu,
            signal=signal,
        )

    def register_spend(
        self,
        periodo: str,
        canal: str,
        monto: float,
        ruc_emisor: str | None = None,
        notas: str | None = None,
    ) -> None:
        """Register acquisition spend manually.

        INSERT or UPDATE (upsert) into gasto_adquisicion_mensual.
        """
        conn = get_conn()
        try:
            conn.execute(
                """
                INSERT INTO gasto_adquisicion_mensual (periodo, canal, monto, ruc_emisor, notas)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(periodo, canal, ruc_emisor) DO UPDATE SET
                    monto = excluded.monto,
                    notas = excluded.notas
                """,
                (periodo, canal, monto, ruc_emisor, notas),
            )
            conn.commit()
            logger.info("Spend registered: %s / %s = %.2f", periodo, canal, monto)
        finally:
            conn.close()

    def sync_from_compras(self, periodo: str) -> int:
        """Sync purchases tagged as acquisition to the cache table.

        Returns:
            Number of records synced.
        """
        conn = get_conn()
        try:
            rows = conn.execute(
                """
                SELECT COALESCE(canal_adquisicion, 'otro') as canal,
                       SUM(monto_total) as total
                FROM compras
                WHERE es_adquisicion = 1
                  AND strftime('%Y-%m', fecha_emision) = ?
                GROUP BY canal
                """,
                (periodo,),
            ).fetchall()

            count = 0
            for r in rows:
                conn.execute(
                    """
                    INSERT INTO gasto_adquisicion_mensual (periodo, canal, monto)
                    VALUES (?, ?, ?)
                    ON CONFLICT(periodo, canal, ruc_emisor) DO UPDATE SET
                        monto = excluded.monto
                    """,
                    (periodo, r["canal"], r["total"]),
                )
                count += 1

            conn.commit()
            logger.info("Synced %d acquisition channels for %s", count, periodo)
            return count
        finally:
            conn.close()
