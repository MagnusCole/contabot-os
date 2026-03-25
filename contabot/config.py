"""
Configuracion central de ContaBot.

Lee variables de entorno con valores por defecto sensatos.
Para desarrollo local, copiar .env.example a .env y ajustar.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Cargar .env si existe (no falla si no hay archivo)
load_dotenv()

# --- Rutas ---
BASE_DIR = Path(__file__).resolve().parent.parent
DATABASE_PATH: str = os.getenv("DATABASE_PATH", str(BASE_DIR / "data" / "db" / "contabot.db"))

# --- IA (opcional) ---
XAI_API_KEY: str | None = os.getenv("XAI_API_KEY")

# --- WhatsApp (WAHA) ---
WAHA_URL: str = os.getenv("WAHA_URL", "http://localhost:3000")
WAHA_SESSION: str = os.getenv("WAHA_SESSION", "default")

# --- Bot ---
BOT_COMPANY_NAME: str = os.getenv("BOT_COMPANY_NAME", "Mi Empresa")
ESCALATION_CONTACT: str = os.getenv("ESCALATION_CONTACT", "soporte")
BOT_PHONE: str | None = os.getenv("BOT_PHONE")

# --- Logging ---
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")


def resumen() -> dict[str, str | None]:
    """Retorna un diccionario con la configuracion actual (util para debug)."""
    return {
        "DATABASE_PATH": DATABASE_PATH,
        "XAI_API_KEY": "***" if XAI_API_KEY else None,
        "WAHA_URL": WAHA_URL,
        "WAHA_SESSION": WAHA_SESSION,
        "BOT_COMPANY_NAME": BOT_COMPANY_NAME,
        "ESCALATION_CONTACT": ESCALATION_CONTACT,
        "BOT_PHONE": BOT_PHONE,
        "LOG_LEVEL": LOG_LEVEL,
    }
