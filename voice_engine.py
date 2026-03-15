# ==============================================================================
# GUARDIÁN DIGITAL v2.0 - voice_engine.py
# Motor de procesamiento de voz: transcripción de audios de WhatsApp con
# OpenAI Whisper local para análisis de manipulación en mensajes de voz.
# ==============================================================================

import logging
import os
import tempfile
import base64
from typing import Dict, Any, Optional
from pathlib import Path

from config import (
    VOICE_ENABLED,
    WHISPER_MODEL,
    VOICE_TEMP_DIR,
    EVOLUTION_API_URL,
    EVOLUTION_API_KEY,
    EVOLUTION_INSTANCE,
)

logger = logging.getLogger(__name__)

# Crear directorio temporal para audios
Path(VOICE_TEMP_DIR).mkdir(parents=True, exist_ok=True)

# Cache del modelo Whisper (carga lazy)
_whisper_model = None


# ==============================================================================
# Carga del modelo Whisper
# ==============================================================================

def _cargar_modelo_whisper():
    """Carga el modelo Whisper en memoria (solo la primera vez)."""
    global _whisper_model
    if _whisper_model is not None:
        return _whisper_model

    try:
        import whisper
        logger.info(f"[VOICE] Cargando modelo Whisper '{WHISPER_MODEL}'...")
        _whisper_model = whisper.load_model(WHISPER_MODEL)
        logger.info(f"[VOICE] Modelo Whisper '{WHISPER_MODEL}' cargado.")
        return _whisper_model
    except ImportError:
        logger.warning("[VOICE] openai-whisper no instalado. Voz desactivada.")
        return None
    except Exception as e:
        logger.error(f"[VOICE] Error cargando Whisper: {e}")
        return None


# ==============================================================================
# Descarga y conversión de audio
# ==============================================================================

async def descargar_audio_whatsapp(message_id: str) -> Optional[bytes]:
    """
    Descarga el audio OGG/Opus de WhatsApp via Evolution API.
    """
    import httpx

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
        logger.error(f"[VOICE] Error descargando audio {message_id}: {e}")
    return None


def convertir_ogg_a_wav(audio_bytes: bytes) -> Optional[str]:
    """
    Convierte audio OGG/Opus (formato de WhatsApp) a WAV para Whisper.
    Requiere: ffmpeg instalado en el sistema.
    Retorna: ruta al archivo WAV temporal.
    """
    try:
        import subprocess

        # Guardar OGG en temporal
        with tempfile.NamedTemporaryFile(
            suffix=".ogg", dir=VOICE_TEMP_DIR, delete=False
        ) as f_ogg:
            f_ogg.write(audio_bytes)
            ruta_ogg = f_ogg.name

        # Convertir a WAV con ffmpeg
        ruta_wav = ruta_ogg.replace(".ogg", ".wav")
        resultado = subprocess.run(
            ["ffmpeg", "-y", "-i", ruta_ogg, "-ar", "16000", "-ac", "1", ruta_wav],
            capture_output=True, timeout=30
        )

        # Eliminar OGG temporal
        os.unlink(ruta_ogg)

        if resultado.returncode == 0 and os.path.exists(ruta_wav):
            return ruta_wav
        else:
            logger.error(f"[VOICE] ffmpeg error: {resultado.stderr.decode()}")
            return None

    except FileNotFoundError:
        logger.error("[VOICE] ffmpeg no encontrado. Instalar con: apt install ffmpeg")
        return None
    except Exception as e:
        logger.error(f"[VOICE] Error convirtiendo audio: {e}")
        return None


# ==============================================================================
# Transcripción
# ==============================================================================

def transcribir_audio(ruta_wav: str, idioma: str = "es") -> Dict[str, Any]:
    """
    Transcribe un archivo WAV usando Whisper.

    Retorna:
        {
            "texto":       str,
            "idioma":      str,
            "confianza":   float,
            "duracion":    float,  # segundos
            "exito":       bool,
        }
    """
    modelo = _cargar_modelo_whisper()
    if modelo is None:
        return {
            "texto": "",
            "idioma": idioma,
            "confianza": 0.0,
            "duracion": 0.0,
            "exito": False,
            "error": "Modelo Whisper no disponible.",
        }

    try:
        resultado = modelo.transcribe(
            ruta_wav,
            language=idioma,
            fp16=False,           # CPU-safe
            verbose=False,
        )
        texto = resultado.get("text", "").strip()
        lang  = resultado.get("language", idioma)

        # Calcular confianza promedio de los segmentos
        segmentos = resultado.get("segments", [])
        if segmentos:
            confianza = sum(
                abs(s.get("avg_logprob", -1)) for s in segmentos
            ) / len(segmentos)
            # Convertir logprob a escala 0-1 aproximada
            confianza = max(0.0, min(1.0, 1.0 - confianza))
            duracion  = segmentos[-1].get("end", 0.0)
        else:
            confianza = 0.5
            duracion  = 0.0

        logger.debug(f"[VOICE] Transcripción: '{texto[:80]}...' (conf={confianza:.2f})")

        return {
            "texto":     texto,
            "idioma":    lang,
            "confianza": round(confianza, 3),
            "duracion":  round(duracion, 1),
            "exito":     bool(texto),
        }

    except Exception as e:
        logger.error(f"[VOICE] Error transcribiendo {ruta_wav}: {e}")
        return {
            "texto": "",
            "idioma": idioma,
            "confianza": 0.0,
            "duracion": 0.0,
            "exito": False,
            "error": str(e),
        }
    finally:
        # Limpiar archivo temporal
        try:
            if os.path.exists(ruta_wav):
                os.unlink(ruta_wav)
        except Exception:
            pass


# ==============================================================================
# Pipeline completo de procesamiento de voz
# ==============================================================================

async def procesar_mensaje_voz(
    audio_bytes: bytes,
    usuario_id: int,
) -> Dict[str, Any]:
    """
    Pipeline completo: bytes de audio → transcripción → análisis de manipulación.

    Retorna:
        {
            "procesado":            bool,
            "transcripcion":        str,
            "idioma_detectado":     str,
            "duracion_seg":         float,
            "score_manipulacion":   float,
            "categorias_riesgo":    list[str],
            "detalle":              str,
        }
    """
    if not VOICE_ENABLED:
        return {
            "procesado": False,
            "transcripcion": "",
            "idioma_detectado": "es",
            "duracion_seg": 0.0,
            "score_manipulacion": 0.0,
            "categorias_riesgo": [],
            "detalle": "Procesamiento de voz desactivado.",
        }

    # 1. Convertir OGG a WAV
    ruta_wav = convertir_ogg_a_wav(audio_bytes)
    if not ruta_wav:
        return {
            "procesado": False,
            "transcripcion": "",
            "idioma_detectado": "es",
            "duracion_seg": 0.0,
            "score_manipulacion": 0.0,
            "categorias_riesgo": [],
            "detalle": "Error al convertir el audio.",
        }

    # 2. Transcribir con Whisper
    transcripcion_result = transcribir_audio(ruta_wav)
    if not transcripcion_result["exito"]:
        return {
            "procesado": False,
            "transcripcion": "",
            "idioma_detectado": "es",
            "duracion_seg": 0.0,
            "score_manipulacion": 0.0,
            "categorias_riesgo": [],
            "detalle": transcripcion_result.get("error", "Error en transcripción."),
        }

    texto_transcrito = transcripcion_result["texto"]

    # 3. Analizar manipulación en la transcripción
    from manipulacion import analizar_manipulacion_voz
    analisis_manip = analizar_manipulacion_voz(texto_transcrito)

    logger.info(
        f"[VOICE] user={usuario_id} "
        f"dur={transcripcion_result['duracion']}s "
        f"score_manip={analisis_manip['score_riesgo']}"
    )

    return {
        "procesado": True,
        "transcripcion": texto_transcrito,
        "idioma_detectado": transcripcion_result["idioma"],
        "duracion_seg": transcripcion_result["duracion"],
        "confianza_transcripcion": transcripcion_result["confianza"],
        "score_manipulacion": analisis_manip["score_riesgo"],
        "categorias_riesgo": analisis_manip["categorias"],
        "detalle": analisis_manip["detalle"],
    }


# ==============================================================================
# Utilidades
# ==============================================================================

def limpiar_audios_temporales(max_edad_minutos: int = 30) -> int:
    """
    Elimina archivos de audio temporales más viejos que max_edad_minutos.
    Retorna el número de archivos eliminados.
    """
    import time

    eliminados = 0
    ahora = time.time()
    max_edad_seg = max_edad_minutos * 60

    try:
        for archivo in Path(VOICE_TEMP_DIR).glob("*"):
            if archivo.is_file():
                edad = ahora - archivo.stat().st_mtime
                if edad > max_edad_seg:
                    archivo.unlink()
                    eliminados += 1
    except Exception as e:
        logger.warning(f"[VOICE] Error limpiando temporales: {e}")

    if eliminados:
        logger.info(f"[VOICE] Limpiados {eliminados} archivos temporales.")
    return eliminados
