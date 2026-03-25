"""
Ingesta de gastos vía Telegram — Fotos, PDFs y texto.

Procesa comprobantes de compra desde múltiples formatos:
1. Foto/Screenshot -> Grok Vision extrae datos
2. PDF de compra -> pdfplumber extrae texto -> Grok parsea
3. Texto libre -> Grok extrae datos estructurados

Resultado: Compra registrada en DB vía expenses.py

Uso:
    from contabot.fiscal.expense_intake import ExpenseIntakeService

    service = ExpenseIntakeService()
    resultado = service.procesar_foto(image_bytes, "factura del almuerzo")
    resultado = service.procesar_pdf(pdf_bytes, "factura hosting")
    resultado = service.procesar_texto("Pagué 150 soles a Claro por internet, F001-00892")
"""

from __future__ import annotations

import base64
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Prompt de sistema para extracción de gastos
SYSTEM_PROMPT = """Eres un asistente contable peruano. Extraes datos de comprobantes de compra/gasto.

REGLAS:
- Moneda por defecto: PEN (soles)
- IGV estándar: 18% (si no se indica, calcúlalo del total)
- Fechas en formato YYYY-MM-DD
- RUC tiene 11 dígitos, DNI tiene 8
- Serie de factura: F001, E001 (electrónica), B001 (boleta)
- Recibo por honorarios: serie E001, tipo "02"
- Recibo de servicios públicos (luz, agua, teléfono): tipo "14"
- Si no puedes determinar un campo, pon null

CATEGORÍAS VÁLIDAS:
mercaderia, materia_prima, servicios, alquiler, servicios_publicos,
combustible, planilla, honorarios, suministros, mantenimiento, seguros, bancarios, otros

TIPOS DE COMPROBANTE:
01 = Factura
02 = Recibo por honorarios
03 = Boleta de venta
07 = Nota de crédito
08 = Nota de débito
14 = Recibo servicios públicos
00 = Otros

Responde SIEMPRE con JSON válido (sin markdown), con esta estructura exacta:
{
  "ruc_proveedor": "20100000000",
  "razon_social_proveedor": "PROVEEDOR S.A.C.",
  "tipo_comprobante": "01",
  "serie": "F001",
  "numero": "0042891",
  "fecha_emision": "2026-01-15",
  "monto_subtotal": 254.24,
  "monto_igv": 45.76,
  "monto_total": 300.00,
  "monto_no_gravado": 0.00,
  "moneda": "PEN",
  "categoria": "servicios_publicos",
  "descripcion": "Servicio eléctrico enero 2026",
  "tiene_credito_fiscal": true,
  "confianza": 0.95
}

Si hay MÚLTIPLES comprobantes en la imagen/texto, devuelve un JSON array.
Si la confianza es menor a 0.5, indica qué campos son inciertos en "notas".
"""


@dataclass
class GastoExtraido:
    """Resultado de la extracción de un gasto."""

    ruc_proveedor: str = ""
    razon_social_proveedor: str = ""
    tipo_comprobante: str = "01"
    serie: str = ""
    numero: str = ""
    fecha_emision: date | None = None
    monto_subtotal: float = 0.0
    monto_igv: float = 0.0
    monto_total: float = 0.0
    monto_no_gravado: float = 0.0
    moneda: str = "PEN"
    categoria: str = "otros"
    descripcion: str = ""
    tiene_credito_fiscal: bool = True
    confianza: float = 0.0
    notas: str = ""


@dataclass
class ResultadoIngesta:
    """Resultado completo de la ingesta."""

    gastos: list[GastoExtraido] = field(default_factory=list)
    registrados: int = 0
    errores: list[str] = field(default_factory=list)
    tokens_usados: int = 0

    @property
    def exito(self) -> bool:
        return self.registrados > 0

    def resumen_telegram(self) -> str:
        """Genera resumen formateado para Telegram."""
        if not self.gastos:
            return "No se pudo extraer ningún gasto."

        lines = []
        if self.registrados > 0:
            lines.append(f"<b>{self.registrados} gasto(s) registrado(s)</b>\n")
        for g in self.gastos:
            estado = "OK" if g.confianza >= 0.7 else "WARN"
            lines.append(
                f"[{estado}] {g.serie}-{g.numero} | {g.razon_social_proveedor}\n"
                f"   S/ {g.monto_total:,.2f} | {g.categoria} | {g.confianza:.0%}"
            )
        if self.errores:
            lines.append("")
            for e in self.errores:
                lines.append(f"ERROR: {e}")
        return "\n".join(lines)


class ExpenseIntakeService:
    """Servicio de ingesta de gastos desde múltiples fuentes."""

    def __init__(self, api_key: str | None = None):
        self._api_key = api_key or os.getenv("XAI_API_KEY")
        self._disponible = bool(self._api_key)
        if not self._disponible:
            logger.warning("Grok API key no disponible — intake deshabilitado")

    def _call_grok(
        self,
        messages: list[dict],
        max_tokens: int = 2000,
    ) -> dict | None:
        """Llamada a Grok API (OpenAI-compatible)."""
        try:
            import httpx

            response = httpx.post(
                "https://api.x.ai/v1/chat/completions",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self._api_key}",
                },
                json={
                    "model": "grok-4-1-fast-non-reasoning",
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": 0.1,
                },
                timeout=30,
            )
            if response.status_code != 200:
                logger.error("Grok API error %d: %s", response.status_code, response.text[:200])
                return None
            data = response.json()
            return data
        except Exception as e:
            logger.error("Error llamando Grok: %s", e)
            return None

    def _call_grok_vision(
        self,
        image_bytes: bytes,
        prompt: str,
        mime_type: str = "image/jpeg",
    ) -> dict | None:
        """Llamada a Grok Vision con imagen."""
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{b64}",
                        },
                    },
                ],
            },
        ]
        return self._call_grok(messages, max_tokens=3000)  # type: ignore[arg-type]

    def _parse_response(self, data: dict) -> tuple[list[GastoExtraido], int]:
        """Parsea respuesta de Grok a lista de GastoExtraido."""
        tokens = data.get("usage", {}).get("total_tokens", 0)
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")

        # Limpiar markdown fences
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1] if "\n" in content else content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            logger.error("Grok devolvió JSON inválido: %s", content[:200])
            return [], tokens

        # Normalizar a lista
        if isinstance(parsed, dict):
            parsed = [parsed]

        gastos = []
        for item in parsed:
            try:
                fecha_str = item.get("fecha_emision")
                fecha = None
                if fecha_str:
                    try:
                        fecha = datetime.strptime(fecha_str, "%Y-%m-%d").date()
                    except ValueError:
                        fecha = date.today()

                g = GastoExtraido(
                    ruc_proveedor=str(item.get("ruc_proveedor", "")).strip(),
                    razon_social_proveedor=str(item.get("razon_social_proveedor", "")).strip(),
                    tipo_comprobante=str(item.get("tipo_comprobante", "01")).strip(),
                    serie=str(item.get("serie", "")).strip().upper(),
                    numero=str(item.get("numero", "")).strip(),
                    fecha_emision=fecha,
                    monto_subtotal=float(item.get("monto_subtotal", 0)),
                    monto_igv=float(item.get("monto_igv", 0)),
                    monto_total=float(item.get("monto_total", 0)),
                    monto_no_gravado=float(item.get("monto_no_gravado", 0)),
                    moneda=str(item.get("moneda", "PEN")).strip(),
                    categoria=str(item.get("categoria", "otros")).strip(),
                    descripcion=str(item.get("descripcion", "")).strip(),
                    tiene_credito_fiscal=bool(item.get("tiene_credito_fiscal", True)),
                    confianza=float(item.get("confianza", 0.5)),
                    notas=str(item.get("notas", "")),
                )

                # Autocompletar montos si faltan
                if g.monto_total > 0 and g.monto_subtotal == 0 and g.monto_igv == 0:
                    if g.tiene_credito_fiscal:
                        g.monto_subtotal = round(g.monto_total / 1.18, 2)
                        g.monto_igv = round(g.monto_total - g.monto_subtotal, 2)
                    else:
                        g.monto_subtotal = g.monto_total

                gastos.append(g)
            except (ValueError, TypeError) as e:
                logger.warning("Error parseando gasto: %s", e)

        return gastos, tokens

    # ========================================================================
    # MÉTODOS PÚBLICOS
    # ========================================================================

    def procesar_foto(
        self,
        image_bytes: bytes,
        contexto: str = "",
        mime_type: str = "image/jpeg",
    ) -> ResultadoIngesta:
        """
        Procesa una foto/screenshot de comprobante.

        Args:
            image_bytes: Bytes de la imagen
            contexto: Texto adicional del usuario
            mime_type: Tipo MIME de la imagen

        Returns:
            ResultadoIngesta con gastos extraídos
        """
        if not self._disponible:
            return ResultadoIngesta(errores=["API key no configurada"])

        prompt = "Extrae los datos del comprobante de compra en esta imagen."
        if contexto:
            prompt += f"\n\nContexto adicional del usuario: {contexto}"

        data = self._call_grok_vision(image_bytes, prompt, mime_type)
        if not data:
            return ResultadoIngesta(errores=["Error comunicándose con Grok Vision"])

        gastos, tokens = self._parse_response(data)
        return ResultadoIngesta(gastos=gastos, tokens_usados=tokens)

    def procesar_pdf(
        self,
        pdf_bytes: bytes,
        contexto: str = "",
    ) -> ResultadoIngesta:
        """
        Procesa un PDF de comprobante de compra.

        Extrae texto con pdfplumber y lo envía a Grok para parseo.
        """
        if not self._disponible:
            return ResultadoIngesta(errores=["API key no configurada"])

        # Extraer texto del PDF
        try:
            from io import BytesIO

            import pdfplumber

            texto = ""
            with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
                for page in pdf.pages:
                    texto += (page.extract_text() or "") + "\n"
        except Exception as e:
            return ResultadoIngesta(errores=[f"Error leyendo PDF: {e}"])

        if not texto.strip():
            return ResultadoIngesta(errores=["PDF sin texto extraíble"])

        prompt = f"Extrae los datos del comprobante de compra de este texto:\n\n{texto[:4000]}"
        if contexto:
            prompt += f"\n\nContexto adicional: {contexto}"

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        data = self._call_grok(messages)
        if not data:
            return ResultadoIngesta(errores=["Error comunicándose con Grok"])

        gastos, tokens = self._parse_response(data)
        return ResultadoIngesta(gastos=gastos, tokens_usados=tokens)

    def procesar_texto(self, texto: str) -> ResultadoIngesta:
        """
        Procesa un mensaje de texto libre describiendo una compra.

        Ejemplos válidos:
            "Pagué 150 soles a Claro, factura F001-00892, RUC 20100000000"
            "Almuerzo 35 soles restaurante El Rincón"
            "Alquiler oficina 1000 soles, factura del coworking"
        """
        if not self._disponible:
            return ResultadoIngesta(errores=["API key no configurada"])

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Extrae los datos de gasto de este mensaje:\n\n{texto}"},
        ]
        data = self._call_grok(messages)
        if not data:
            return ResultadoIngesta(errores=["Error comunicándose con Grok"])

        gastos, tokens = self._parse_response(data)
        return ResultadoIngesta(gastos=gastos, tokens_usados=tokens)

    def registrar_en_db(
        self,
        resultado: ResultadoIngesta,
        db: Session,
        ruc_comprador: str,
    ) -> ResultadoIngesta:
        """
        Registra los gastos extraídos en la base de datos.

        Filtra gastos con confianza < 0.5 y los marca como error.
        """
        from contabot.fiscal.expenses import registrar_compra

        for g in resultado.gastos:
            if g.confianza < 0.5:
                resultado.errores.append(
                    f"Confianza muy baja ({g.confianza:.0%}): {g.descripcion or g.razon_social_proveedor}"
                )
                continue

            if not g.serie or not g.numero:
                # Generar número interno para gastos sin comprobante formal
                g.serie = "INT0"
                g.numero = datetime.now().strftime("%Y%m%d%H%M%S")

            if not g.fecha_emision:
                g.fecha_emision = date.today()

            try:
                registrar_compra(
                    db=db,
                    ruc_comprador=ruc_comprador,
                    ruc_proveedor=g.ruc_proveedor or "00000000000",
                    razon_social_proveedor=g.razon_social_proveedor or "SIN RAZÓN SOCIAL",
                    serie=g.serie,
                    numero=g.numero,
                    fecha_emision=g.fecha_emision,
                    monto_subtotal=g.monto_subtotal,
                    monto_igv=g.monto_igv,
                    monto_total=g.monto_total,
                    tipo_comprobante=g.tipo_comprobante,
                    categoria=g.categoria,
                    descripcion=g.descripcion,
                    tiene_credito_fiscal=g.tiene_credito_fiscal,
                    moneda=g.moneda,
                    monto_no_gravado=g.monto_no_gravado,
                )
                resultado.registrados += 1
                logger.info(
                    "Gasto registrado: %s %s-%s S/%.2f",
                    g.razon_social_proveedor,
                    g.serie,
                    g.numero,
                    g.monto_total,
                )
            except ValueError as e:
                resultado.errores.append(str(e))

        return resultado
