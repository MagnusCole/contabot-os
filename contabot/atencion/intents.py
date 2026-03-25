"""
contabot/atencion/intents.py — Clasificación de intents de mensajes de clientes.

Pipeline:
  1. Regex rápido (microsegundos, sin API)
  2. Grok fallback si el regex no es concluyente

Retorna: (intent: str, confianza: float, contexto: dict)
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Patrones regex por intent (orden de precedencia)
_PATTERNS: list[tuple[str, list[str]]] = [
    (
        "urgente",
        [
            r"\burgente\b",
            r"\bpara hoy\b",
            r"\bantes de las\b",
            r"\bplazo\b",
            r"\bsunat\b.*\bhoy\b",
            r"\bhoy mismo\b",
            r"\bfecha.{0,10}límite\b",
        ],
    ),
    (
        "solicitar_anulacion",
        [
            r"\banular\b",
            r"\banulaci[oó]n\b",
            r"\bcancelar.{0,15}factura\b",
            r"\bvoid\b",
            r"\bequivocad[ao]\b",
            r"\bmal emitid[ao]\b",
        ],
    ),
    (
        "queja",
        [
            r"\berror\b",
            r"\bproblema\b",
            r"\bmal\b.{0,20}\bfactura\b",
            r"\bno est[aá] bien\b",
            r"\bfalta\b.{0,15}\bfactura\b",
            r"\bse demor[oó]\b",
            r"\bno lleg[oó]\b",
            r"\bno recib[íi]\b",
            r"\bqueja\b",
            r"\breclamaci[oó]n\b",
        ],
    ),
    (
        "solicitar_reporte",
        [
            r"\breporte\b",
            r"\binforme\b",
            r"\bresumen\b",
            r"\bexcel\b",
            r"\bconsolidado\b",
            r"\bestado de cuenta\b",
            r"\bcuadro\b",
        ],
    ),
    (
        "estado_facturas",
        [
            r"\bcuántas\b.{0,20}\bfactura[s]?\b",
            r"\bcuánto van\b",
            r"\bestado\b.{0,20}(trabajo|factura|emisi[oó]n)",
            r"\bfactura[s]?\b.{0,20}\b(pendiente|emitid|lista)\b",
            r"\bcu[aá]nto lleva[n]?\b",
            r"\bprogreso\b",
        ],
    ),
    (
        "adjuntar_documento",
        [
            r"\bword\b",
            r"\bdocx\b",
            r"\bexcel\b.{0,10}\badjunt\b",
            r"\bles mando\b",
            r"\bte env[íi]o\b",
            r"\badjunto\b",
            r"\baquí.{0,10}\b(el|la|los)\b.{0,10}\b(archivo|documento|lista)\b",
        ],
    ),
    (
        "consulta_precio",
        [
            r"\bcu[aá]nto (me cobran|cuesta|vale|es)\b",
            r"\btarifa\b",
            r"\bprecio\b.{0,20}\bservicio\b",
            r"\bhonorario\b",
            r"\bfactura de servicios\b",
        ],
    ),
    (
        "saludo",
        [
            r"^(hola|buenas|buenos d[íi]as|buenas tardes|buenas noches|hi|hey)[!.,]?\s*$",
            r"^(hola|buenas).{0,30}$",
        ],
    ),
    (
        "gracias",
        [
            r"\bgracias\b",
            r"\bmuchas gracias\b",
            r"\bperfecto\b",
            r"\bexcelente\b",
            r"^(ok|listo|entendido|de acuerdo)[!.,]?\s*$",
        ],
    ),
]


def clasificar_regex(texto: str) -> tuple[str, float]:
    """Clasificación rápida por regex. Retorna (intent, confianza)."""
    t = texto.lower().strip()
    for intent, patterns in _PATTERNS:
        for pat in patterns:
            if re.search(pat, t, re.IGNORECASE):
                return intent, 0.85
    return "otro", 0.3


def clasificar_con_grok(texto: str, cliente: str = "") -> tuple[str, float, dict[str, Any]]:
    """
    Clasificación con Grok. Extrae intent + entidades relevantes.
    Retorna (intent, confianza, extras).
    """
    import json
    import os

    import httpx

    api_key = os.getenv("XAI_API_KEY") or os.getenv("GROK_API_KEY")
    if not api_key:
        intent, conf = clasificar_regex(texto)
        return intent, conf, {}

    intents_list = "\n".join(
        f"- {k}: {v}"
        for k, v in {
            "estado_facturas": "consulta cuántas facturas van o estado del trabajo",
            "solicitar_reporte": "pide Excel o reporte del mes",
            "solicitar_anulacion": "quiere anular una factura",
            "consulta_precio": "pregunta por precio o tarifa del servicio",
            "adjuntar_documento": "envía o anuncia un archivo Word/Excel",
            "urgente": "necesita atención inmediata hoy",
            "queja": "reporta error, problema o demora",
            "saludo": "saludo inicial",
            "gracias": "agradecimiento o cierre positivo",
            "otro": "no encaja en ninguna categoría",
        }.items()
    )

    prompt = (
        f"Clasifica este mensaje de un cliente ({cliente}) de una empresa de facturación.\n"
        f"Intents disponibles:\n{intents_list}\n\n"
        f'Mensaje: "{texto}"\n\n'
        f'Responde SOLO JSON: {{"intent": "...", "confianza": 0.0-1.0, '
        f'"numero_factura": null_o_string, "mes": null_o_string, "urgencia": "baja|normal|alta"}}'
    )

    try:
        r = httpx.post(
            "https://api.x.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": "grok-4-1-fast-non-reasoning",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 150,
                "temperature": 0,
            },
            timeout=8,
        )
        data = json.loads(r.json()["choices"][0]["message"]["content"])
        intent = data.get("intent", "otro")
        if intent not in {k for k, _ in _PATTERNS} | {"otro"}:
            intent = "otro"
        return intent, float(data.get("confianza", 0.7)), data
    except Exception as e:
        logger.warning("Grok classify error: %s", e)
        intent, conf = clasificar_regex(texto)
        return intent, conf, {}


def clasificar(
    texto: str, cliente: str = "", usar_grok: bool = True
) -> tuple[str, float, dict[str, Any]]:
    """
    Punto de entrada principal.
    Usa regex primero. Si confianza < 0.7 y hay API key, llama a Grok.
    """
    intent_r, conf_r = clasificar_regex(texto)
    if conf_r >= 0.75 or not usar_grok:
        return intent_r, conf_r, {}
    return clasificar_con_grok(texto, cliente=cliente)
