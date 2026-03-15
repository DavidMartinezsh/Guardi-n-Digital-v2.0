# ==============================================================================
# GUARDIÁN DIGITAL v2.0 - firewall.py
# Motor de decisión con Score Unificado de 4 dimensiones (total 100 puntos).
# ==============================================================================

import logging
import random
from typing import Any, Dict, Optional
from enum import Enum

from config import UMBRAL_BLOQUEO, UMBRAL_DESAFIO, UMBRAL_ALERTA
from db import (
    registrar_log_seguridad,
    obtener_preguntas_desafio,
    bloquear_usuario,
    obtener_logs_recientes,
)

logger = logging.getLogger(__name__)


# ==============================================================================
# Enums
# ==============================================================================

class AccionFirewall(str, Enum):
    PERMITIR    = "permitir"
    DESAFIO_2FA = "desafio_2fa"
    BLOQUEAR    = "bloquear"
    ALERTA      = "alerta"


MENSAJES_BLOQUEO = [
    "Lo siento, en este momento no puedo continuar la conversación.",
    "Estoy ocupado ahora mismo. Intentemos más tarde.",
    "No es un buen momento. Hablamos después.",
]

MENSAJES_ERROR_DESAFIO = [
    "Eso no coincide con lo que recuerdo. Voy a pausar la conversación.",
    "No estoy seguro de que seas quien creo. Hablamos pronto.",
]


# ==============================================================================
# Score Unificado — 4 Dimensiones (escala 0-10 por dimensión)
# ==============================================================================
#
#   DIMENSIÓN         PESO    DESCRIPCIÓN
#   ──────────────────────────────────────────────────────────────────
#   Biometría          35%    ¿El texto suena como el usuario real?
#   Manipulación       35%    ¿Hay patrones de ingeniería social?
#   Urgencia/Contexto  20%    Rol, detector de estafas, palabras urgentes
#   Historial          10%    Incidentes y bloqueos previos
#   ──────────────────────────────────────────────────────────────────

PESOS = {
    "biometria":    0.35,
    "manipulacion": 0.35,
    "urgencia":     0.20,
    "historial":    0.10,
}


def calcular_score_urgencia(texto: str, rol_nivel: int, score_estafa: float = 0.0) -> float:
    """Calcula el componente de urgencia/contexto (0–10)."""
    import re

    score = 0.0

    # Penalización base por rol
    if rol_nivel <= 1:
        score += 4.0
    elif rol_nivel == 2:
        score += 2.0

    # Aportar el detector de estafas (hasta 4 pts)
    score += min(score_estafa * 0.4, 4.0)

    # Palabras de urgencia explícita
    for patron in [
        r"\burgente\b", r"\bya\s+mismo\b", r"\bahora\s+mismo\b",
        r"\bemergencia\b", r"\bno\s+hay\s+tiempo\b", r"\brápido\b",
    ]:
        if re.search(patron, texto.lower()):
            score += 0.8

    return round(min(score, 10.0), 2)


def calcular_score_historial(usuario_id: int) -> float:
    """Calcula el componente de historial (0–10)."""
    logs = obtener_logs_recientes(usuario_id, 20)
    eventos     = sum(1 for l in logs if l.get("score_riesgo", 0) >= UMBRAL_ALERTA)
    bloqueos    = sum(1 for l in logs if "BLOQUEO" in l.get("evento", "") or "FALLIDO" in l.get("evento", ""))
    return round(min(eventos * 0.5 + bloqueos * 2.0, 10.0), 2)


def calcular_score_compuesto(
    score_biometria:    float,
    score_manipulacion: float,
    score_urgencia:     float,
    score_historial:    float,
    usuario_bloqueado:  bool = False,
) -> Dict[str, Any]:
    """Combina las 4 dimensiones en un score final unificado (0–10)."""
    if usuario_bloqueado:
        return {
            "total": 10.0,
            "biometria":    score_biometria,
            "manipulacion": score_manipulacion,
            "urgencia":     score_urgencia,
            "historial":    score_historial,
            "detalle":      "Usuario bloqueado → score máximo automático",
        }

    total = (
        score_biometria    * PESOS["biometria"]
        + score_manipulacion * PESOS["manipulacion"]
        + score_urgencia     * PESOS["urgencia"]
        + score_historial    * PESOS["historial"]
    )
    total = round(min(total, 10.0), 2)

    detalle = (
        f"bio={score_biometria:.1f}×{int(PESOS['biometria']*100)}% + "
        f"manip={score_manipulacion:.1f}×{int(PESOS['manipulacion']*100)}% + "
        f"urgencia={score_urgencia:.1f}×{int(PESOS['urgencia']*100)}% + "
        f"hist={score_historial:.1f}×{int(PESOS['historial']*100)}% "
        f"→ {total:.2f}/10"
    )

    return {
        "total":        total,
        "biometria":    score_biometria,
        "manipulacion": score_manipulacion,
        "urgencia":     score_urgencia,
        "historial":    score_historial,
        "detalle":      detalle,
    }


# ==============================================================================
# Motor de Decisión Principal
# ==============================================================================

def evaluar_firewall(
    usuario:            Dict[str, Any],
    score_biometria:    float,
    score_manipulacion: float,
    texto_original:     str,
    score_estafa:       float = 0.0,
    score_result:       Any   = None,
) -> Dict[str, Any]:
    """
    Evalúa el score unificado y decide la acción.
    Si se pasa score_result (ResultadoScore de score_engine), lo usa directamente.
    Si no, calcula el score internamente como fallback.
    """
    usuario_id = usuario["id"]
    rol_nivel  = usuario.get("rol_nivel", 1)
    bloqueado  = bool(usuario.get("bloqueado", 0))

    if score_result is not None:
        scores = {
            "total":        score_result.total,
            "biometria":    score_result.biometria,
            "manipulacion": score_result.manipulacion,
            "urgencia":     score_result.improvisacion,
            "historial":    0.0,
            "detalle":      score_result.detalle,
        }
        score_total = score_result.total
    else:
        score_urgencia  = calcular_score_urgencia(texto_original, rol_nivel, score_estafa)
        score_historial = calcular_score_historial(usuario_id)
        scores = calcular_score_compuesto(
            score_biometria, score_manipulacion,
            score_urgencia, score_historial, bloqueado,
        )
        score_total = scores["total"]

    # ─── BLOQUEO ─────────────────────────────────────────────────────────────
    if score_total >= UMBRAL_BLOQUEO or bloqueado:
        if not bloqueado:
            bloquear_usuario(usuario_id, f"Score crítico: {score_total:.2f} | {scores['detalle']}")
        _log(usuario_id, "BLOQUEO_AUTOMATICO", score_total, scores["detalle"], "bloquear")
        logger.warning(f"[FIREWALL] 🔴 BLOQUEO user={usuario_id} | {scores['detalle']}")
        return _res(AccionFirewall.BLOQUEAR, scores, random.choice(MENSAJES_BLOQUEO))

    # ─── DESAFÍO 2FA ─────────────────────────────────────────────────────────
    if score_total >= UMBRAL_DESAFIO:
        _log(usuario_id, "DESAFIO_2FA_LANZADO", score_total, scores["detalle"], "desafio_2fa")
        logger.warning(f"[FIREWALL] 🟡 DESAFÍO user={usuario_id} | {scores['detalle']}")

        preguntas = obtener_preguntas_desafio(usuario_id)
        pregunta  = preguntas[0] if preguntas else None

        # Nivel de sospecha para el desafío avanzado
        nivel = "critico" if score_total >= 8.0 else ("alto" if score_total >= 6.5 else "medio")
        msg   = generar_desafio_avanzado(usuario, nivel) if not pregunta else pregunta["pregunta"]

        return _res(AccionFirewall.DESAFIO_2FA, scores, msg, pregunta)

    # ─── ALERTA SUAVE ─────────────────────────────────────────────────────────
    if score_total >= UMBRAL_ALERTA:
        _log(usuario_id, "ALERTA_RIESGO_BAJO", score_total, scores["detalle"], "permitir_con_alerta")
        logger.info(f"[FIREWALL] 🟢⚠ ALERTA user={usuario_id} | {scores['detalle']}")
        return _res(AccionFirewall.ALERTA, scores)

    logger.debug(f"[FIREWALL] ✅ PERMITIDO user={usuario_id} | {scores['detalle']}")
    return _res(AccionFirewall.PERMITIR, scores)


def _log(usuario_id, evento, score, detalle, accion):
    registrar_log_seguridad(usuario_id, evento, score, detalle, accion)


def _res(
    accion:   AccionFirewall,
    scores:   Dict[str, Any],
    mensaje:  Optional[str] = None,
    pregunta: Optional[Dict] = None,
) -> Dict[str, Any]:
    return {
        "accion":            accion,
        "scores":            scores,
        "score_compuesto":   scores["total"],
        "mensaje_respuesta": mensaje,
        "pregunta_desafio":  pregunta,
        "detalle_log":       scores.get("detalle", ""),
    }


# ==============================================================================
# Modo Desafío Avanzado
# ==============================================================================

_PREGUNTAS_GENERICAS = [
    "¿Cuál es el nombre de nuestra mascota de siempre?",
    "¿En qué ciudad vivíamos cuando nos conocimos?",
    "¿Qué plato typical preparaba mamá los domingos?",
    "¿Cómo se llama el colegio al que fuiste?",
    "¿Con qué apodo te llamo de siempre?",
    "¿Qué canción escuchábamos juntos todo el tiempo?",
]


def generar_desafio_avanzado(usuario: Dict[str, Any], nivel: str = "medio") -> str:
    """Genera un desafío contextual adaptado al nivel de sospecha."""
    import random

    if nivel == "critico":
        intro = (
            "⚠️ *Verificación de seguridad requerida*\n\n"
            "Antes de continuar necesito confirmar que eres quien dices ser.\n\n"
            "*Pregunta de verificación:*\n"
        )
    elif nivel == "alto":
        intro = "Para seguir hablando necesito hacerte una pregunta:\n\n"
    else:
        intro = "Solo para confirmar que eres tú, dime:\n\n"

    preguntas_db = obtener_preguntas_desafio(usuario["id"])
    if preguntas_db:
        return intro + preguntas_db[0]["pregunta"]
    return intro + random.choice(_PREGUNTAS_GENERICAS)


# ==============================================================================
# Validación del desafío
# ==============================================================================

def validar_respuesta_desafio(usuario_id: int, pregunta: Dict, respuesta_usuario: str) -> bool:
    from difflib import SequenceMatcher
    esperada = pregunta.get("respuesta", "").lower().strip()
    dada     = respuesta_usuario.lower().strip()
    if dada == esperada:
        return True
    return SequenceMatcher(None, dada, esperada).ratio() >= 0.82


def procesar_resultado_desafio(
    usuario: Dict[str, Any],
    pregunta: Dict[str, Any],
    respuesta_dada: str,
) -> Dict[str, Any]:
    from db import registrar_intento_desafio

    usuario_id = usuario["id"]
    correcto   = validar_respuesta_desafio(usuario_id, pregunta, respuesta_dada)
    registrar_intento_desafio(usuario_id, pregunta["id"], respuesta_dada, correcto)

    if correcto:
        _log(usuario_id, "DESAFIO_2FA_SUPERADO", 0.0, "Respuesta correcta.", "permitir")
        return {"verificado": True, "mensaje": "✅ Identidad verificada. Podemos continuar."}
    else:
        _log(usuario_id, "DESAFIO_2FA_FALLIDO", 7.0, f"Resp. incorrecta: '{respuesta_dada[:50]}'", "bloquear")
        bloquear_usuario(usuario_id, "Desafío 2FA fallido.")
        return {"verificado": False, "mensaje": random.choice(MENSAJES_ERROR_DESAFIO)}
