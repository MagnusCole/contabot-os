"""Vercel serverless function — chat endpoint para el demo web.

POST /api/chat
Body: {"message": "...", "session_id": "..."}
Response: {"response": "..."}
"""

from __future__ import annotations

import json
import re
import sqlite3
import tempfile
from datetime import date
from http.server import BaseHTTPRequestHandler
from pathlib import Path

# -- DB en /tmp (efímera pero persiste entre invocaciones del mismo container) --

_DB_PATH = Path(tempfile.gettempdir()) / "contabot_demo.db"


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _ensure_tables():
    conn = _get_conn()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS demo_sessions (
                session_id TEXT PRIMARY KEY,
                ruc TEXT,
                razon_social TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );
        """)
        conn.commit()
    finally:
        conn.close()


# -- Lógica del bot (simplificada para demo) --

_RUC_RE = re.compile(r"^\d{11}$")

_INTENT_KEYWORDS = {
    "estado": ["estado", "reporte", "cómo voy", "como voy", "resumen", "p&l", "balance"],
    "impuestos": ["impuesto", "sunat", "igv", "cuánto debo", "cuanto debo", "declarar", "pdt"],
    "gastos": ["gasto", "compra", "qué he gastado", "que he gastado", "egresos"],
    "ayuda": ["ayuda", "help", "qué puedes", "que puedes", "comando", "menu", "menú", "opciones"],
}

_MESES = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril",
    5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto",
    9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre",
}

# Datos demo para simular un negocio real
_DEMO_DATA = {
    "ventas": 45800.00,
    "gastos_op": 18200.00,
    "igv_ventas": 6986.78,
    "igv_compras": 2776.27,
    "cantidad_facturas": 23,
    "cantidad_gastos": 14,
}


def _clasificar(texto: str) -> str:
    t = texto.lower().strip()
    for intent, kws in _INTENT_KEYWORDS.items():
        for kw in kws:
            if kw in t:
                return intent
    return "otro"


def _procesar(session_id: str, mensaje: str) -> str:
    _ensure_tables()
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM demo_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()

        # -- Onboarding --
        if row is None:
            texto_limpio = re.sub(r"[^\d]", "", mensaje.strip())
            if _RUC_RE.match(texto_limpio):
                # Simular lookup de razón social
                nombres_demo = {
                    "0": "DISTRIBUIDORA EL SOL SAC",
                    "1": "INVERSIONES LIMA NORTE EIRL",
                    "2": "TRANSPORTES RAPIDO SRL",
                    "3": "CONFECCIONES MARIA SAC",
                    "4": "FERRETERIA EL CONSTRUCTOR",
                    "5": "ALIMENTOS DEL SUR SAC",
                    "6": "TECNOLOGIA ANDINA EIRL",
                    "7": "SERVICIOS GENERALES PERU SAC",
                    "8": "COMERCIAL HUANCAYO SRL",
                    "9": "AGROINDUSTRIAL NORTE SAC",
                }
                ultimo = texto_limpio[-1]
                razon = nombres_demo.get(ultimo, "MI EMPRESA SAC")

                conn.execute(
                    "INSERT OR REPLACE INTO demo_sessions (session_id, ruc, razon_social) VALUES (?, ?, ?)",
                    (session_id, texto_limpio, razon),
                )
                conn.commit()

                return (
                    f"Listo! Te registré como *{razon}*\n\n"
                    f"Ahora puedo:\n"
                    f"- Registrar gastos con foto\n"
                    f"- Darte tu estado financiero\n"
                    f"- Calcular tus impuestos SUNAT\n"
                    f"- Enviarte reporte cada lunes\n\n"
                    f"Prueba escribiendo *estado*, *impuestos* o *gastos*"
                )

            return (
                "Hola! Soy *ContaBot*, tu contador IA.\n\n"
                "Para empezar, envíame un *RUC* (11 dígitos).\n\n"
                "Ejemplo: 20612345678\n\n"
                "Después podré:\n"
                "- Darte tu estado financiero\n"
                "- Calcular tus impuestos SUNAT\n"
                "- Registrar gastos\n"
                "- Enviarte reportes semanales"
            )

        # -- Usuario registrado --
        razon = row["razon_social"] or row["ruc"]
        ruc = row["ruc"]
        intent = _clasificar(mensaje)
        hoy = date.today()
        mes = f"{_MESES[hoy.month]} {hoy.year}"
        d = _DEMO_DATA

        if intent == "estado":
            utilidad = d["ventas"] - d["gastos_op"] - (d["igv_ventas"] - d["igv_compras"]) - (d["ventas"] / 1.18 * 0.01)
            margen = utilidad / d["ventas"] * 100
            return (
                f"*Tu negocio — {mes}*\n\n"
                f"Ventas: S/ {d['ventas']:,.2f}\n"
                f"Gastos: S/ {d['gastos_op']:,.2f}\n"
                f"IGV por pagar: S/ {d['igv_ventas'] - d['igv_compras']:,.2f}\n"
                f"Renta mensual: S/ {d['ventas'] / 1.18 * 0.01:,.2f}\n\n"
                f"*Utilidad neta: S/ {utilidad:,.2f}*\n"
                f"Margen: {margen:.1f}%"
            )

        elif intent == "impuestos":
            igv_pagar = d["igv_ventas"] - d["igv_compras"]
            renta = d["ventas"] / 1.18 * 0.01
            total = igv_pagar + renta
            return (
                f"*Obligaciones SUNAT — {mes}*\n\n"
                f"Ventas brutas: S/ {d['ventas']:,.2f}\n"
                f"IGV por pagar: S/ {igv_pagar:,.2f}\n"
                f"Renta mensual: S/ {renta:,.2f}\n"
                f"{'─' * 28}\n"
                f"*Total a pagar: S/ {total:,.2f}*\n\n"
                f"Régimen MYPE Tributario (1%)\n"
                f"Vence el 17 del próximo mes"
            )

        elif intent == "gastos":
            return (
                f"*Gastos — {mes}*\n\n"
                f"Total: S/ {d['gastos_op']:,.2f}\n"
                f"Comprobantes: {d['cantidad_gastos']}\n"
                f"IGV crédito: S/ {d['igv_compras']:,.2f}\n\n"
                f"*Por categoría:*\n"
                f"  Materiales: S/ 8,400.00\n"
                f"  Servicios: S/ 4,200.00\n"
                f"  Combustible: S/ 3,100.00\n"
                f"  Otros: S/ 2,500.00\n\n"
                f"_Manda foto de factura para registrar más_"
            )

        elif intent == "ayuda":
            return (
                f"Hola {razon}!\n\n"
                f"Soy ContaBot, tu contador IA. Esto puedo hacer:\n\n"
                f"*estado* — Tu P&L del mes\n"
                f"*impuestos* — Cuánto debes a SUNAT\n"
                f"*gastos* — Resumen de egresos\n"
                f"*ayuda* — Este menú\n\n"
                f"En la versión completa también puedo:\n"
                f"- Registrar gastos con foto\n"
                f"- Enviar reporte semanal automático\n"
                f"- Conectar por WhatsApp"
            )

        else:
            return (
                "No entendí tu mensaje. Prueba:\n\n"
                "*estado* — Ver tu P&L\n"
                "*impuestos* — Obligaciones SUNAT\n"
                "*gastos* — Egresos del mes\n"
                "*ayuda* — Más opciones"
            )

    finally:
        conn.close()


# -- Handler HTTP --

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        try:
            data = json.loads(body)
            message = data.get("message", "").strip()
            session_id = data.get("session_id", "anonymous")

            if not message:
                self._json(400, {"error": "message required"})
                return

            response = _procesar(session_id, message)
            self._json(200, {"response": response})

        except json.JSONDecodeError:
            self._json(400, {"error": "invalid json"})
        except Exception as e:
            self._json(500, {"error": str(e)})

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors_headers()
        self.end_headers()

    def _json(self, status: int, data: dict):
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._cors_headers()
        self.end_headers()
        self.wfile.write(payload)

    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
