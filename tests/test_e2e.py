"""Tests end-to-end de ContaBot.

Verifica el flujo completo: DB -> onboarding -> mensaje -> respuesta.
"""
from __future__ import annotations

import os
import tempfile

import pytest


@pytest.fixture(autouse=True)
def temp_db(monkeypatch, tmp_path):
    """Usa una DB temporal para cada test.

    get_conn() lee DATABASE_PATH en cada llamada, asi que
    basta con setear el env var antes de correr las migraciones.
    """
    db_path = str(tmp_path / "test.db")
    monkeypatch.setenv("DATABASE_PATH", db_path)

    from contabot.db.migration import run_migrations
    run_migrations(db_path=tmp_path / "test.db")

    yield db_path


class TestOnboarding:
    """Tests del flujo de registro."""

    def test_nuevo_usuario_recibe_bienvenida(self):
        from contabot.bot.onboarding import esta_registrado, MSG_ONBOARDING
        assert not esta_registrado("51999888777")

    def test_registro_con_ruc(self):
        from contabot.bot.onboarding import registrar_mype, esta_registrado, obtener_cliente
        resultado = registrar_mype("51999888777", "20100000001")
        assert "Listo" in resultado
        assert esta_registrado("51999888777")
        cliente = obtener_cliente("51999888777")
        assert cliente is not None
        assert cliente.ruc == "20100000001"

    def test_registro_duplicado(self):
        from contabot.bot.onboarding import registrar_mype
        registrar_mype("51999888777", "20100000001")
        resultado = registrar_mype("51999888777", "20100000001")
        assert "Ya esta" in resultado.lower() or "ya est" in resultado.lower()

    def test_ruc_invalido(self):
        from contabot.bot.onboarding import registrar_mype
        resultado = registrar_mype("51999888777", "123")
        assert "11 d" in resultado.lower()

    def test_listar_clientes_activos(self):
        from contabot.bot.onboarding import registrar_mype, listar_clientes_activos
        registrar_mype("51999888777", "20100000001")
        registrar_mype("51999888666", "20100000002")
        activos = listar_clientes_activos()
        assert len(activos) == 2


class TestHandler:
    """Tests del handler de mensajes."""

    @pytest.mark.asyncio
    async def test_mensaje_sin_registro_da_onboarding(self):
        from contabot.bot.handler import procesar_mensaje
        resp = await procesar_mensaje("51999000111", "text", "hola")
        assert "RUC" in resp

    @pytest.mark.asyncio
    async def test_mensaje_ruc_registra(self):
        from contabot.bot.handler import procesar_mensaje
        resp = await procesar_mensaje("51999000111", "text", "20100000001")
        assert "Listo" in resp

    @pytest.mark.asyncio
    async def test_ayuda(self):
        from contabot.bot.handler import procesar_mensaje
        from contabot.bot.onboarding import registrar_mype
        registrar_mype("51999000111", "20100000001")
        resp = await procesar_mensaje("51999000111", "text", "ayuda")
        assert "ContaBot" in resp

    @pytest.mark.asyncio
    async def test_intent_gastos(self):
        from contabot.bot.handler import procesar_mensaje
        from contabot.bot.onboarding import registrar_mype
        registrar_mype("51999000111", "20100000001")
        resp = await procesar_mensaje("51999000111", "text", "gastos")
        assert "gasto" in resp.lower() or "registrado" in resp.lower()

    @pytest.mark.asyncio
    async def test_intent_impuestos(self):
        from contabot.bot.handler import procesar_mensaje
        from contabot.bot.onboarding import registrar_mype
        registrar_mype("51999000111", "20100000001")
        resp = await procesar_mensaje("51999000111", "text", "cuanto debo a sunat")
        # Debe responder algo sobre impuestos (aunque no haya data)
        assert resp is not None and len(resp) > 10

    @pytest.mark.asyncio
    async def test_intent_estado(self):
        from contabot.bot.handler import procesar_mensaje
        from contabot.bot.onboarding import registrar_mype
        registrar_mype("51999000111", "20100000001")
        resp = await procesar_mensaje("51999000111", "text", "como voy")
        assert resp is not None and len(resp) > 10


class TestFiscalCalculator:
    """Tests del calculador fiscal."""

    def test_calculo_mype_basico(self):
        from contabot.fiscal.calculator import FiscalCalculator, RegimenTributario
        calc = FiscalCalculator(regimen=RegimenTributario.MYPE)
        resultado = calc.calcular(
            periodo="2026-03",
            ventas_brutas=11800.0,
            igv_ventas=1800.0,
        )
        assert resultado.ventas_netas == 10000.0
        assert resultado.igv_por_pagar == 1800.0
        assert resultado.renta_mensual == 100.0  # 1% de 10000
        assert resultado.total_obligaciones == 1900.0

    def test_calculo_con_credito_fiscal(self):
        from contabot.fiscal.calculator import FiscalCalculator, RegimenTributario
        calc = FiscalCalculator(regimen=RegimenTributario.MYPE)
        resultado = calc.calcular(
            periodo="2026-03",
            ventas_brutas=11800.0,
            igv_ventas=1800.0,
            compras_netas=5000.0,
            igv_compras=900.0,
        )
        assert resultado.igv_por_pagar == 900.0  # 1800 - 900
        assert resultado.renta_mensual == 100.0


class TestCalendar:
    """Tests del calendario SUNAT."""

    def test_vencimiento_conocido(self):
        from contabot.fiscal.calendar import get_fecha_vencimiento
        from datetime import date
        fecha = get_fecha_vencimiento("20100000001", "2026-01")
        assert fecha == date(2026, 2, 14)  # digito 1 -> dia 14

    def test_vencimiento_ruc_invalido(self):
        from contabot.fiscal.calendar import get_fecha_vencimiento
        assert get_fecha_vencimiento("123", "2026-01") is None

    def test_estimacion_periodo_futuro(self):
        from contabot.fiscal.calendar import get_fecha_vencimiento
        fecha = get_fecha_vencimiento("20100000001", "2027-06")
        # Debe estimar (no hay cronograma 2027)
        assert fecha is not None


class TestWebhookServer:
    """Tests del servidor FastAPI."""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from contabot.bot.server import app
        return TestClient(app)

    def test_health(self, client):
        resp = client.get("/contabot/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_webhook_ignora_grupos(self, client):
        resp = client.post("/contabot/webhook", json={
            "event": "message",
            "payload": {"from": "grupo@g.us", "body": "hola"},
        })
        assert resp.json()["status"] == "ignored"

    def test_webhook_ignora_propios(self, client):
        resp = client.post("/contabot/webhook", json={
            "event": "message",
            "payload": {"from": "51999@c.us", "body": "hola", "fromMe": True},
        })
        assert resp.json()["status"] == "ignored"

    def test_webhook_procesa_mensaje(self, client):
        resp = client.post("/contabot/webhook", json={
            "event": "message",
            "payload": {"from": "51999888777@c.us", "body": "hola", "fromMe": False},
        })
        assert resp.json()["status"] == "processing"

    def test_webhook_ignora_no_message(self, client):
        resp = client.post("/contabot/webhook", json={"event": "ack", "payload": {}})
        assert resp.json()["status"] == "ignored"
