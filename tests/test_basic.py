"""Tests basicos de ContaBot."""
from __future__ import annotations

import os


def test_import_contabot():
    """Verificar que el paquete se importa correctamente."""
    import contabot
    assert hasattr(contabot, "__version__")


def test_config_defaults():
    """Verificar valores por defecto de configuracion."""
    from contabot import config
    assert config.BOT_COMPANY_NAME == os.getenv("BOT_COMPANY_NAME", "Mi Empresa")
    assert config.WAHA_URL == os.getenv("WAHA_URL", "http://localhost:3000")


def test_db_models_importable():
    """Verificar que los modelos de DB se importan."""
    from contabot.db.models import Base
    assert Base is not None


def test_fiscal_calculator_importable():
    """Verificar que el calculador fiscal se importa."""
    from contabot.fiscal import calculator
    assert calculator is not None
