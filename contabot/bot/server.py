"""contabot/bot/server.py — Webhook FastAPI para ContaBot.

Recibe eventos de WAHA (WhatsApp HTTP API) y los procesa.

Uso:
    uvicorn contabot.bot.server:app --host 0.0.0.0 --port 8401
"""

from __future__ import annotations

import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path

import httpx
from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import JSONResponse

from .handler import procesar_mensaje
from .migration import run as run_migration

logger = logging.getLogger(__name__)

app = FastAPI(title="ContaBot", version="1.0.0")

# WAHA config — override via environment variables
WAHA_URL = os.getenv("WAHA_URL", "http://localhost:3000")
WAHA_SESSION = os.getenv("WAHA_SESSION", "default")

_MEDIA_DIR = Path(tempfile.gettempdir()) / "contabot_media"
_MEDIA_DIR.mkdir(exist_ok=True)


@app.on_event("startup")
async def startup():
    """Ejecuta migraciones al iniciar."""
    run_migration()
    logger.info("ContaBot server iniciado")


@app.get("/contabot/health")
async def health():
    return {
        "status": "ok",
        "service": "contabot",
        "timestamp": datetime.now().isoformat(),
    }


@app.post("/contabot/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks):
    """Recibe eventos de WAHA."""
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid json"}, status_code=400)

    event = payload.get("event")

    # Solo procesar mensajes entrantes
    if event != "message":
        return {"status": "ignored", "event": event}

    data = payload.get("payload", {})
    body = data.get("body", "")
    from_number = data.get("from", "")

    # Ignorar mensajes de grupo
    if "@g.us" in from_number:
        return {"status": "ignored", "reason": "group"}

    # Ignorar mensajes propios
    if data.get("fromMe", False):
        return {"status": "ignored", "reason": "self"}

    # Extraer teléfono limpio (sin @c.us)
    telefono = from_number.replace("@c.us", "")

    # Determinar tipo de mensaje
    has_media = data.get("hasMedia", False)
    media_type = data.get("type", "chat")  # chat, image, document, etc.

    if has_media and media_type in ("image", "document"):
        tipo = media_type
    else:
        tipo = "text"

    # Procesar en background para responder rápido al webhook
    background_tasks.add_task(
        _procesar_y_responder, telefono, tipo, body, data if has_media else None
    )

    return {"status": "processing"}


async def _procesar_y_responder(
    telefono: str,
    tipo: str,
    contenido: str,
    media_data: dict | None,
) -> None:
    """Procesa mensaje y envía respuesta por WhatsApp."""
    media_path = None

    # Descargar media si hay
    if media_data and tipo in ("image", "document"):
        try:
            media_path = await _descargar_media(media_data)
        except Exception as exc:
            logger.error("Error descargando media: %s", exc)

    try:
        respuesta = await procesar_mensaje(telefono, tipo, contenido, media_path)
    except Exception as exc:
        logger.error("Error procesando mensaje de %s: %s", telefono, exc, exc_info=True)
        respuesta = "Hubo un error procesando tu mensaje. Intenta de nuevo."

    # Enviar respuesta
    await _enviar_whatsapp(telefono, respuesta)

    # Limpiar media temporal
    if media_path and media_path.exists():
        try:
            media_path.unlink()
        except Exception:
            pass


async def _descargar_media(data: dict) -> Path | None:
    """Descarga media de WAHA y guarda localmente."""
    media_url = data.get("mediaUrl")
    if not media_url:
        # Intentar vía API de WAHA
        msg_id = data.get("id", {})
        if isinstance(msg_id, dict):
            msg_id = msg_id.get("id", "")
        if not msg_id:
            return None

        media_url = f"{WAHA_URL}/api/{WAHA_SESSION}/messages/{msg_id}/download"

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(media_url)
        resp.raise_for_status()

    # Determinar extensión
    content_type = resp.headers.get("content-type", "")
    if "pdf" in content_type:
        ext = ".pdf"
    elif "png" in content_type:
        ext = ".png"
    else:
        ext = ".jpg"

    path = _MEDIA_DIR / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}{ext}"
    path.write_bytes(resp.content)
    return path


async def _enviar_whatsapp(telefono: str, mensaje: str) -> bool:
    """Envía mensaje por WhatsApp via WAHA API."""
    try:
        chat_id = f"{telefono}@c.us" if "@" not in telefono else telefono
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{WAHA_URL}/api/sendText",
                json={
                    "session": WAHA_SESSION,
                    "chatId": chat_id,
                    "text": mensaje,
                },
            )
            return resp.status_code == 200 or resp.status_code == 201
    except Exception as exc:
        logger.error("Error enviando WhatsApp a %s: %s", telefono, exc)
        return False
