"""contabot.accounting.dashboard -- Formatted unit economics reports."""

from __future__ import annotations

import logging
import os

from .cac import CACCalculator
from .churn import monthly_churn, mrr_recurring, net_revenue_retention
from .ltv import LTVCalculator
from .models import LTVSnapshot, UnitEconomics

logger = logging.getLogger(__name__)

_W = 58  # report width


def _signal_emoji(signal: str) -> str:
    return {"green": "[OK]", "yellow": "[!!]", "red": "[XX]"}.get(signal, "[--]")


def _signal_label(signal: str) -> str:
    return {"green": "SALUDABLE", "yellow": "ATENCION", "red": "CRITICO"}.get(signal, "SIN DATOS")


def reporte_texto(periodo: str) -> str:
    """Full unit economics report in plain text."""
    ltv_calc = LTVCalculator()
    cac_calc = CACCalculator()

    ltv_snap = ltv_calc.snapshot(periodo)
    cac_snap = cac_calc.simple_cac(periodo)
    ue = cac_calc.ltv_cac_ratio(periodo)
    churn = monthly_churn(periodo)
    nrr = net_revenue_retention(periodo)
    mrr = mrr_recurring(periodo)

    lines = [
        "=" * _W,
        f"UNIT ECONOMICS -- {periodo}",
        f"Generated: {ue.generado_en}",
        "=" * _W,
        "",
        f"  SIGNAL: [{_signal_label(ue.signal)}]",
        "",
        "KEY METRICS:",
        f"  Avg LTV:               S/ {ltv_snap.avg_ltv:>10,.2f}",
        f"  Median LTV:            S/ {ltv_snap.median_ltv:>10,.2f}",
    ]

    if ltv_snap.predictive_ltv is not None:
        lines.append(f"  Predictive LTV:        S/ {ltv_snap.predictive_ltv:>10,.2f}")

    lines += [
        f"  CAC:                   S/ {cac_snap.cac:>10,.2f}",
        f"  LTV:CAC ratio:         {ue.ltv_cac_ratio:>13.1f}x",
        f"  Payback:               {ue.payback_months:>11.1f} months",
        "",
        "CUSTOMERS:",
        f"  Total historic:        {ltv_snap.total_customers:>12,}",
        f"  Active (3 months):     {ltv_snap.active_customers:>12,}",
        f"  New this month:        {cac_snap.new_customers:>12,}",
        f"  Monthly ARPU:          S/ {ltv_snap.arpu:>10,.2f}",
        f"  Avg lifespan:          {ltv_snap.avg_lifespan_months:>10.1f} months",
        "",
        "RETENTION:",
        f"  Monthly churn:         {churn * 100:>12.1f}%",
        f"  Net Revenue Retention: {nrr * 100:>12.1f}%",
        f"  Recurring MRR:         S/ {mrr:>10,.2f}",
    ]

    # Spend by channel
    if cac_snap.total_spend > 0:
        channels = cac_calc.channel_cac(periodo)
        if channels:
            lines += ["", "ACQUISITION SPEND:"]
            for ch in channels:
                lines.append(
                    f"  {ch.canal:<22} S/ {ch.spend:>8,.2f}  "
                    f"({ch.new_customers} customers, CAC S/{ch.cac:,.2f})"
                )

    # LTV Segments
    if ltv_snap.segments:
        lines += ["", "LTV BY SEGMENT:"]
        for seg in ltv_snap.segments[:5]:
            lines.append(
                f"  {seg.segment_name[:22]:<22} LTV S/ {seg.avg_ltv:>8,.2f}  "
                f"({seg.customer_count} customers)"
            )

    # Cohorts
    if ltv_snap.cohorts:
        lines += ["", "COHORTS (retention %):"]
        lines.append(f"  {'Cohort':<10} {'Size':>4}  M0   M1   M2   M3   M4   M5")
        for c in ltv_snap.cohorts[-6:]:  # last 6
            ret_str = "  ".join(f"{r:4.0f}" for r in c.retention[:6])
            lines.append(f"  {c.cohort_month:<10} {c.cohort_size:>4}  {ret_str}")

    lines.append("=" * _W)
    return "\n".join(lines)


def reporte_telegram(periodo: str) -> str:
    """Unit economics report in HTML for Telegram."""
    ltv_calc = LTVCalculator()
    cac_calc = CACCalculator()

    ltv_snap = ltv_calc.snapshot(periodo)
    ue = cac_calc.ltv_cac_ratio(periodo)
    churn = monthly_churn(periodo)
    nrr = net_revenue_retention(periodo)

    signal_icon = _signal_emoji(ue.signal)

    msg = (
        f"<b>Unit Economics -- {periodo}</b>\n\n"
        f"{signal_icon} <b>LTV:CAC = {ue.ltv_cac_ratio:.1f}x</b> ({_signal_label(ue.signal)})\n\n"
        f"<b>LTV:</b> S/ {ltv_snap.avg_ltv:,.2f} (median S/ {ltv_snap.median_ltv:,.2f})\n"
        f"<b>CAC:</b> S/ {ue.cac:,.2f}\n"
        f"<b>Payback:</b> {ue.payback_months:.1f} months\n"
        f"<b>ARPU:</b> S/ {ltv_snap.arpu:,.2f}/month\n\n"
        f"<b>Customers:</b> {ltv_snap.active_customers} active / {ltv_snap.total_customers} total\n"
        f"<b>Churn:</b> {churn * 100:.1f}%\n"
        f"<b>NRR:</b> {nrr * 100:.1f}%\n"
    )

    if ue.commentary:
        msg += f"\n<i>{ue.commentary}</i>"

    return msg


async def ai_commentary(ue: UnitEconomics, ltv_snap: LTVSnapshot) -> str:
    """Generate executive commentary via an LLM API.

    Requires LLM_API_KEY and LLM_API_URL environment variables.

    Returns:
        Text of 2-4 sentences. Empty string on failure.
    """
    api_key = os.getenv("LLM_API_KEY", "")
    api_url = os.getenv("LLM_API_URL", "")
    model = os.getenv("LLM_MODEL", "")

    if not api_key or not api_url or not model:
        return ""

    prompt = (
        f"Analyze these unit economics for an accounting services SME:\n"
        f"- Avg LTV: S/ {ltv_snap.avg_ltv:,.2f}\n"
        f"- CAC: S/ {ue.cac:,.2f}\n"
        f"- LTV:CAC ratio: {ue.ltv_cac_ratio:.1f}x (signal: {ue.signal})\n"
        f"- Payback: {ue.payback_months:.1f} months\n"
        f"- ARPU: S/ {ltv_snap.arpu:,.2f}/month\n"
        f"- Monthly churn: {ue.monthly_churn_rate * 100:.1f}%\n"
        f"- Active customers: {ltv_snap.active_customers} of {ltv_snap.total_customers}\n"
        f"- NRR: {ue.monthly_churn_rate}\n\n"
        f"Respond in 3 sentences max. Be direct like a CFO. "
        f"Include one actionable recommendation."
    )

    try:
        import httpx

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                api_url,
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 200,
                    "temperature": 0.3,
                },
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        logger.warning("AI commentary failed: %s", exc)
        return ""
