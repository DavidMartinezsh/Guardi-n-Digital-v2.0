# ==============================================================================
# GUARDIÁN DIGITAL v2.0 - whatsapp_gateway.py
# Servidor FastAPI: recibe webhooks de Evolution API y despacha respuestas.
# ==============================================================================

import base64
import logging
import httpx
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.responses import JSONResponse
import uvicorn

from config import (
    BOT_PORT,
    EVOLUTION_API_URL,
    EVOLUTION_API_KEY,
    EVOLUTION_INSTANCE,
    VOICE_ENABLED,
    VISION_ENABLED,
    LOG_LEVEL,
    LOG_FILE,
)
from main_guardian import procesar_mensaje

# ==============================================================================
# Logging
# ==============================================================================

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

# ==============================================================================
# App FastAPI
# ==============================================================================

app = FastAPI(
    title="Guardián Digital v2.0",
    description="Bot de WhatsApp con seguridad perimetral biométrica",
    version="2.0.0",
    docs_url="/guardian/docs",
    redoc_url=None,
)


# ==============================================================================
# Helpers de Evolution API
# ==============================================================================

async def enviar_mensaje_whatsapp(telefono: str, mensaje: str) -> bool:
    """
    Envía un mensaje de texto al número indicado via Evolution API.
    """
    url = f"{EVOLUTION_API_URL}/message/sendText/{EVOLUTION_INSTANCE}"
    headers = {
        "apikey":        EVOLUTION_API_KEY,
        "Content-Type":  "application/json",
    }
    payload = {
        "number":  telefono,
        "options": {"delay": 800, "presence": "composing"},
        "textMessage": {"text": mensaje},
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            return True
    except Exception as e:
        logger.error(f"[GATEWAY] Error enviando mensaje a {telefono}: {e}")
        return False


async def descargar_media(message_id: str) -> Optional[bytes]:
    """Descarga el media de un mensaje de WhatsApp."""
    url = f"{EVOLUTION_API_URL}/message/getBase64FromMediaMessage/{EVOLUTION_INSTANCE}"
    headers = {"apikey": EVOLUTION_API_KEY, "Content-Type": "application/json"}
    payload = {"message": {"key": {"id": message_id}}}

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            b64 = data.get("base64", "")
            return base64.b64decode(b64) if b64 else None
    except Exception as e:
        logger.error(f"[GATEWAY] Error descargando media {message_id}: {e}")
        return None


# ==============================================================================
# Parser del payload de Evolution API
# ==============================================================================

def parsear_evento(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Parsea el payload del webhook de Evolution API y extrae los datos relevantes.

    Estructura esperada (Evolution API v2):
    {
        "event": "messages.upsert",
        "instance": "...",
        "data": {
            "key": { "id": "...", "remoteJid": "5491234...@s.whatsapp.net" },
            "message": {
                "conversation": "Texto...",
                "imageMessage": { ... },
                "audioMessage": { ... },
                ...
            },
            "pushName": "Nombre",
            "messageType": "conversation",
            ...
        }
    }
    """
    # Solo procesar eventos de mensajes nuevos
    evento = payload.get("event", "")
    if evento not in ("messages.upsert", "message.created"):
        return None

    data = payload.get("data", {})
    key  = data.get("key", {})

    # Ignorar mensajes propios (fromMe)
    if key.get("fromMe", False):
        return None

    jid         = key.get("remoteJid", "")
    message_id  = key.get("id", "")
    nombre      = data.get("pushName", "Desconocido")
    message     = data.get("message", {})
    msg_type    = data.get("messageType", "")

    # Limpiar el teléfono (remover sufijo @s.whatsapp.net o @g.us)
    telefono = jid.split("@")[0] if "@" in jid else jid

    # Ignorar mensajes grupales (remoteJid termina en @g.us)
    if "@g.us" in jid:
        return None

    # ─── Determinar tipo y contenido ─────────────────────────────────────────
    tipo              = "texto"
    contenido_texto   = None
    mime_type_media   = None

    # Mensaje de texto simple
    if "conversation" in message:
        contenido_texto = message["conversation"]
        tipo = "texto"

    elif "extendedTextMessage" in message:
        contenido_texto = message["extendedTextMessage"].get("text", "")
        tipo = "texto"

    # Mensaje de imagen
    elif "imageMessage" in message:
        img_msg   = message["imageMessage"]
        mime_type_media = img_msg.get("mimetype", "image/jpeg")
        tipo = "imagen"

    # Mensaje de audio/voz
    elif "audioMessage" in message or "voiceNote" in message:
        audio_key  = "audioMessage" if "audioMessage" in message else "voiceNote"
        audio_msg  = message[audio_key]
        mime_type_media = audio_msg.get("mimetype", "audio/ogg; codecs=opus")
        tipo = "voz"

    # Otros tipos (sticker, documento, video, etc.) → ignorar o tratar como texto
    else:
        return None

    return {
        "telefono":       telefono,
        "message_id":     message_id,
        "nombre":         nombre,
        "tipo":           tipo,
        "contenido_texto": contenido_texto,
        "mime_type":      mime_type_media,
    }


# ==============================================================================
# Endpoints
# ==============================================================================

@app.post("/bot-webhook/webhook")
async def webhook_principal(request: Request):
    """
    Endpoint principal que recibe todos los eventos de Evolution API.
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="JSON inválido")

    logger.debug(f"[GATEWAY] Webhook recibido: {str(payload)[:200]}")

    # Parsear evento
    evento = parsear_evento(payload)
    if evento is None:
        return JSONResponse({"status": "ignored"})

    telefono     = evento["telefono"]
    message_id   = evento["message_id"]
    tipo         = evento["tipo"]
    nombre       = evento["nombre"]
    mime_type    = evento.get("mime_type")

    # Descargar media si corresponde
    contenido_binario = None
    if tipo in ("imagen", "voz") and message_id:
        needs_vision = tipo == "imagen" and VISION_ENABLED
        needs_voice  = tipo == "voz"    and VOICE_ENABLED
        if needs_vision or needs_voice:
            contenido_binario = await descargar_media(message_id)

    # Procesar el mensaje
    respuesta = await procesar_mensaje(
        telefono=telefono,
        tipo=tipo,
        contenido_texto=evento.get("contenido_texto"),
        contenido_binario=contenido_binario,
        mime_type=mime_type,
        nombre_remitente=nombre,
    )

    # Enviar respuesta (si no está vacía)
    if respuesta and respuesta.strip():
        enviado = await enviar_mensaje_whatsapp(telefono, respuesta)
        if not enviado:
            logger.error(f"[GATEWAY] No se pudo enviar respuesta a {telefono}")

    return JSONResponse({"status": "ok", "tipo": tipo})


@app.get("/bot-webhook/health")
async def health_check():
    """Health check para monitoreo de uptime."""
    from db import get_connection
    db_ok = False
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                db_ok = True
    except Exception:
        pass

    return {
        "status":        "online",
        "version":       "2.0.0",
        "db":            "ok" if db_ok else "error",
        "vision":        VISION_ENABLED,
        "voice":         VOICE_ENABLED,
    }


@app.get("/bot-webhook/status")
async def status_detallado():
    """Estado detallado del sistema para el administrador."""
    import psutil
    import platform

    return {
        "sistema":   platform.system(),
        "python":    platform.python_version(),
        "cpu_pct":   psutil.cpu_percent(interval=0.5),
        "ram_pct":   psutil.virtual_memory().percent,
        "disco_pct": psutil.disk_usage("/").percent,
        "vision":    VISION_ENABLED,
        "voice":     VOICE_ENABLED,
    }


# ==============================================================================
# Arranque del servidor
# ==============================================================================

if __name__ == "__main__":
    from db import inicializar_schema
    import os

    # Crear schema si no existe
    inicializar_schema()

    logger.info(
        f"🛡️  Guardián Digital v2.0 iniciando en puerto {BOT_PORT}..."
    )
    uvicorn.run(
        "whatsapp_gateway:app",
        host="0.0.0.0",
        port=BOT_PORT,
        reload=False,
        log_level=LOG_LEVEL.lower(),
        access_log=True,
    )
