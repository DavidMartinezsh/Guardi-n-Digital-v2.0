# ==============================================================================
# GUARDIÁN DIGITAL v2.0 - vision_engine.py
# Motor de análisis visual: detecta phishing en capturas de pantalla enviadas
# por WhatsApp usando Gemini Vision + análisis de texto OCR local.
# ==============================================================================

import base64
import logging
import os
import re
import tempfile
from typing import Dict, Any, Optional, List

import httpx

from config import (
    VISION_ENABLED,
    VISION_MAX_FILE_MB,
    VISION_PHISHING_KEYWORDS,
    EVOLUTION_API_URL,
    EVOLUTION_API_KEY,
    EVOLUTION_INSTANCE,
)

logger = logging.getLogger(__name__)


# ==============================================================================
# Descarga de medios desde Evolution API
# ==============================================================================

async def descargar_media_whatsapp(
    message_id: str,
    mime_type: str = "image/jpeg",
) -> Optional[bytes]:
    """
    Descarga el contenido binario de una imagen/audio enviada por WhatsApp
    usando la Evolution API.
    """
    url = f"{EVOLUTION_API_URL}/message/getBase64FromMediaMessage/{EVOLUTION_INSTANCE}"
    headers = {"apikey": EVOLUTION_API_KEY, "Content-Type": "application/json"}
    payload = {"message": {"key": {"id": message_id}}}

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            b64 = data.get("base64", "")
            if b64:
                return base64.b64decode(b64)
    except Exception as e:
        logger.error(f"[VISION] Error descargando media {message_id}: {e}")
    return None


def bytes_a_base64(datos: bytes) -> str:
    """Convierte bytes a string base64."""
    return base64.b64encode(datos).decode("utf-8")


# ==============================================================================
# Análisis rápido de texto en imagen (heurístico sin OCR externo)
# ==============================================================================

def analisis_heuristico_phishing(texto_ocr: str) -> Dict[str, Any]:
    """
    Análisis rápido basado en palabras clave de phishing sobre texto OCR.
    """
    texto_lower = texto_ocr.lower()
    encontrados = []

    for keyword in VISION_PHISHING_KEYWORDS:
        if keyword.lower() in texto_lower:
            encontrados.append(keyword)

    # Buscar URLs sospechosas
    urls = re.findall(r"https?://[^\s]+", texto_ocr)
    urls_sospechosas = [
        u for u in urls
        if re.search(r"\.(tk|ml|ga|cf|gq|xyz|top|club|ru|cn)\b", u)
        or re.search(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", u)  # IP directa
    ]

    score = len(encontrados) * 2.0 + len(urls_sospechosas) * 3.0
    score = min(score, 10.0)

    return {
        "score_riesgo": round(score, 2),
        "keywords_detectadas": encontrados,
        "urls_sospechosas": urls_sospechosas,
        "es_phishing": score >= 5.0,
    }


# ==============================================================================
# Pipeline completo de análisis de imagen
# ==============================================================================

async def analizar_imagen(
    imagen_bytes: bytes,
    mime_type: str = "image/jpeg",
    usar_gemini_vision: bool = True,
) -> Dict[str, Any]:
    """
    Analiza una imagen en busca de contenido de phishing.

    Pipeline:
    1. Validar tamaño del archivo.
    2. OCR con pytesseract (si disponible) para extracción de texto.
    3. Análisis heurístico de texto.
    4. Análisis con Gemini Vision (si está habilitado).
    5. Combinar scores y retornar resultado final.

    Retorna:
        {
            "procesado":        bool,
            "es_phishing":      bool,
            "score_riesgo":     float (0-10),
            "descripcion":      str,
            "elementos_riesgo": list[str],
            "texto_ocr":        str,
            "fuente_analisis":  str,  # "gemini" | "heuristico" | "combinado"
        }
    """
    if not VISION_ENABLED:
        return {
            "procesado": False,
            "es_phishing": False,
            "score_riesgo": 0.0,
            "descripcion": "Análisis de visión desactivado.",
            "elementos_riesgo": [],
            "texto_ocr": "",
            "fuente_analisis": "desactivado",
        }

    # Validar tamaño
    max_bytes = VISION_MAX_FILE_MB * 1024 * 1024
    if len(imagen_bytes) > max_bytes:
        logger.warning(f"[VISION] Imagen demasiado grande: {len(imagen_bytes)} bytes")
        return {
            "procesado": False,
            "es_phishing": False,
            "score_riesgo": 0.0,
            "descripcion": f"Imagen supera el límite de {VISION_MAX_FILE_MB}MB.",
            "elementos_riesgo": [],
            "texto_ocr": "",
            "fuente_analisis": "rechazado",
        }

    imagen_b64 = bytes_a_base64(imagen_bytes)
    texto_ocr  = ""

    # ─── OCR con Tesseract (opcional) ─────────────────────────────────────────
    try:
        import pytesseract
        from PIL import Image
        import io

        img_pil = Image.open(io.BytesIO(imagen_bytes))
        texto_ocr = pytesseract.image_to_string(img_pil, lang="spa+eng")
        logger.debug(f"[VISION] OCR extrajo {len(texto_ocr)} caracteres.")
    except ImportError:
        logger.debug("[VISION] pytesseract no disponible, usando solo Gemini Vision.")
    except Exception as e:
        logger.warning(f"[VISION] OCR falló: {e}")

    # ─── Análisis heurístico ──────────────────────────────────────────────────
    resultado_heuristico = {"score_riesgo": 0.0, "elementos_riesgo": []}
    if texto_ocr:
        resultado_heuristico = analisis_heuristico_phishing(texto_ocr)

    # ─── Análisis con Gemini Vision ───────────────────────────────────────────
    resultado_gemini = {"es_phishing": False, "score_riesgo": 0.0, "descripcion": "", "elementos_riesgo": []}
    if usar_gemini_vision:
        from ia_engine import analizar_imagen_phishing
        resultado_gemini = analizar_imagen_phishing(imagen_b64, mime_type)

    # ─── Combinar resultados ──────────────────────────────────────────────────
    score_combinado = max(
        resultado_heuristico["score_riesgo"],
        resultado_gemini.get("score_riesgo", 0.0),
    )
    # Si ambos detectan algo, elevar el score
    if resultado_heuristico["score_riesgo"] > 3 and resultado_gemini.get("score_riesgo", 0) > 3:
        score_combinado = min(score_combinado * 1.3, 10.0)

    elementos = list(set(
        resultado_heuristico.get("keywords_detectadas", [])
        + resultado_gemini.get("elementos_riesgo", [])
    ))

    return {
        "procesado": True,
        "es_phishing": score_combinado >= 5.0,
        "score_riesgo": round(score_combinado, 2),
        "descripcion": resultado_gemini.get("descripcion", "Análisis completado."),
        "elementos_riesgo": elementos,
        "texto_ocr": texto_ocr[:1000],
        "fuente_analisis": "combinado" if texto_ocr else "gemini",
    }


# ==============================================================================
# Respuesta al usuario sobre la imagen analizada
# ==============================================================================

def generar_alerta_imagen(resultado: Dict[str, Any]) -> str:
    """Genera el texto de alerta para el usuario tras analizar una imagen."""
    if not resultado.get("procesado"):
        return "No pude analizar la imagen en este momento."

    if resultado["es_phishing"]:
        elementos = resultado.get("elementos_riesgo", [])
        lista_elem = "\n".join(f"  • {e}" for e in elementos[:5]) if elementos else "  • Contenido visual sospechoso"
        return (
            f"⚠️ *ALERTA DE SEGURIDAD* ⚠️\n\n"
            f"Detecté indicadores de *phishing* en esta imagen "
            f"(score: {resultado['score_riesgo']:.1f}/10).\n\n"
            f"*Elementos sospechosos:*\n{lista_elem}\n\n"
            f"*No hagas clic* en ningún enlace ni proporciones datos personales. "
            f"Si recibiste esto de alguien, podría ser un intento de fraude."
        )
    else:
        return (
            f"✅ La imagen no parece contener contenido de phishing "
            f"(score: {resultado['score_riesgo']:.1f}/10)."
        )
