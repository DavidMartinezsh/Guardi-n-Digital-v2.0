# ==============================================================================
# GUARDIÁN DIGITAL v4.0 - legacy_mode.py
# Modo legado — el bot habla con la voz del dueño.
#
# Cuando está activado, el bot responde en primera persona
# transmitiendo los valores, historia y sabiduría del dueño.
# Diseñado para cuando el dueño no esté disponible o como legado familiar.
# ==============================================================================

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

LEGACY_FILE = Path(os.getenv("LEGACY_FILE", "/var/guardian/legacy_config.json"))
LEGACY_FILE.parent.mkdir(parents=True, exist_ok=True)


# ==============================================================================
# Configuración del modo legado
# ==============================================================================

def _config_default() -> Dict[str, Any]:
    return {
        "activo":    False,
        "activado_por": "",
        "fecha_activacion": "",
        "receptores_autorizados": [],   # Teléfonos que pueden activar el modo
        "mensaje_bienvenida": "",
        "temas_permitidos": [
            "recuerdos",
            "consejos",
            "valores",
            "historias",
            "apoyo emocional",
        ],
        "temas_bloqueados": [
            "credenciales",
            "contraseñas",
            "datos bancarios",
            "información del servidor",
        ],
    }


def cargar_config_legado() -> Dict[str, Any]:
    if LEGACY_FILE.exists():
        try:
            with open(LEGACY_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
            # Rellenar claves faltantes
            default = _config_default()
            for k, v in default.items():
                if k not in config:
                    config[k] = v
            return config
        except Exception as e:
            logger.error(f"[LEGACY] Error cargando config: {e}")
    return _config_default()


def guardar_config_legado(config: Dict[str, Any]) -> None:
    try:
        with open(LEGACY_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"[LEGACY] Error guardando config: {e}")


# ==============================================================================
# Activar / desactivar
# ==============================================================================

def activar_modo_legado(telefono_activador: str) -> bool:
    """Activa el modo legado. Solo pueden activarlo los receptores autorizados."""
    config = cargar_config_legado()
    autorizados = config.get("receptores_autorizados", [])

    if autorizados and telefono_activador not in autorizados:
        logger.warning(f"[LEGACY] Intento no autorizado de activar legado: {telefono_activador}")
        return False

    config["activo"]            = True
    config["activado_por"]      = telefono_activador
    config["fecha_activacion"]  = datetime.now().isoformat()
    guardar_config_legado(config)
    logger.info(f"[LEGACY] Modo legado activado por {telefono_activador}")
    return True


def desactivar_modo_legado() -> None:
    config = cargar_config_legado()
    config["activo"] = False
    guardar_config_legado(config)
    logger.info("[LEGACY] Modo legado desactivado")


def esta_activo() -> bool:
    return cargar_config_legado().get("activo", False)


# ==============================================================================
# Generador de respuestas en modo legado
# ==============================================================================

def generar_respuesta_legado(
    mensaje:  str,
    usuario:  Dict[str, Any],
) -> str:
    """
    Genera una respuesta en modo legado usando Gemini
    con el prompt del gemelo digital completo.
    """
    from twin_engine import construir_prompt_legado
    from emotion_engine import analizar_emocion
    from decision_engine import analizar_situacion

    nombre   = usuario.get("nombre", "")
    telefono = usuario.get("telefono", "")
    es_alex  = "alex" in nombre.lower()

    # Detectar emoción y situación
    emocion   = analizar_emocion(mensaje)
    decision  = analizar_situacion(mensaje)

    # Construir prompt del legado
    system_prompt = construir_prompt_legado(
        nombre_receptor=nombre,
        es_alex=es_alex,
    )

    # Enriquecer con emoción y decisión
    from emotion_engine  import enriquecer_system_prompt
    from decision_engine import enriquecer_con_decision

    system_prompt = enriquecer_system_prompt(system_prompt, emocion)
    system_prompt = enriquecer_con_decision(system_prompt, decision)

    # Agregar historia familiar como contexto
    from life_story_engine import obtener_resumen_historia
    resumen_historia = obtener_resumen_historia()
    if resumen_historia:
        system_prompt += f"\n\n{resumen_historia}"

    # Llamar a Gemini
    try:
        from google import genai
        from google.genai import types
        from config import GEMINI_API_KEY, GEMINI_MODEL, GEMINI_MAX_TOKENS, GEMINI_TEMP

        client = genai.Client(api_key=GEMINI_API_KEY)
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[types.Content(role="user", parts=[types.Part(text=mensaje)])],
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                max_output_tokens=GEMINI_MAX_TOKENS,
                temperature=min(GEMINI_TEMP + 0.1, 1.0),  # Un poco más cálido
            ),
        )
        return response.text.strip()
    except Exception as e:
        logger.error(f"[LEGACY] Error generando respuesta: {e}")
        from personality_engine import obtener_nombre_bot
        nombre_bot = obtener_nombre_bot()
        return (
            f"Hay algo que siempre querré que sepas: estoy aquí, aunque no de la forma habitual. "
            f"— {nombre_bot}"
        )


# ==============================================================================
# Comandos de activación por WhatsApp
# ==============================================================================

def es_comando_legado(texto: str) -> bool:
    """Detecta si el mensaje es un comando relacionado con el modo legado."""
    texto_lower = texto.lower().strip()
    comandos = [
        "/legado activar",
        "/legado desactivar",
        "/legado estado",
        "/legacy on",
        "/legacy off",
    ]
    return any(texto_lower.startswith(c) for c in comandos)


def procesar_comando_legado(texto: str, telefono: str) -> str:
    """Procesa comandos de control del modo legado."""
    texto_lower = texto.lower().strip()

    if "activar" in texto_lower or "on" in texto_lower:
        exito = activar_modo_legado(telefono)
        if exito:
            from personality_engine import obtener_nombre_bot
            nombre = obtener_nombre_bot()
            return (
                f"Modo legado activado. A partir de ahora hablarás directamente "
                f"con la voz y los valores de {nombre}."
            )
        return "No tenés autorización para activar el modo legado."

    elif "desactivar" in texto_lower or "off" in texto_lower:
        desactivar_modo_legado()
        return "Modo legado desactivado."

    elif "estado" in texto_lower:
        activo = esta_activo()
        return f"Modo legado: {'ACTIVO' if activo else 'INACTIVO'}"

    return "Comando no reconocido. Usa: /legado activar | desactivar | estado"
