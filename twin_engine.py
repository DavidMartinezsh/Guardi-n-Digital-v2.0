# ==============================================================================
# GUARDIÁN DIGITAL v4.0 - twin_engine.py
# Motor de gemelo digital — simulador de personalidad.
#
# Construye el system prompt más completo del sistema, integrando:
#   - Personalidad de personality.yaml
#   - Valores de values.json
#   - Memoria de largo plazo del interlocutor
#   - Perfil familiar
#   - Contexto emocional actual
#   - Decisiones basadas en valores
#   - Diario familiar reciente
#
# Este es el módulo que hace que el bot responda COMO el dueño.
# ==============================================================================

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from personality_engine import construir_system_prompt_personalidad, obtener_nombre_bot
from emotion_engine     import ResultadoEmocion, enriquecer_system_prompt
from decision_engine    import ResultadoDecision, enriquecer_con_decision
from memory_engine      import construir_contexto_memoria
from family_engine      import construir_contexto_familiar
from diary_engine       import construir_contexto_diario

logger = logging.getLogger(__name__)


# ==============================================================================
# Constructor del prompt del gemelo digital
# ==============================================================================

def construir_prompt_gemelo(
    usuario:          Dict[str, Any],
    resultado_emocion: Optional[ResultadoEmocion] = None,
    resultado_decision: Optional[ResultadoDecision] = None,
    incluir_memoria:  bool = True,
    incluir_familiar: bool = True,
    incluir_diario:   bool = True,
) -> str:
    """
    Construye el system prompt completo del gemelo digital.

    Integra todas las capas:
    1. Personalidad base (quién soy)
    2. Perfil del interlocutor (quién es él/ella)
    3. Memoria de largo plazo (qué sé de él)
    4. Diario familiar reciente (qué pasó estos días)
    5. Estado emocional actual (cómo responder)
    6. Decisión basada en valores (qué hacer)
    """
    usuario_id = usuario.get("id", 0)
    telefono   = usuario.get("telefono", "")
    nombre     = usuario.get("nombre", "Usuario")
    rol        = usuario.get("rol_nombre", "desconocido")

    # 1. Base de personalidad
    prompt = construir_system_prompt_personalidad(
        rol_nombre=rol,
        nombre_interlocutor=nombre,
    )

    # 2. Perfil familiar del interlocutor
    if incluir_familiar and telefono:
        ctx_familiar = construir_contexto_familiar(telefono)
        if ctx_familiar:
            prompt += f"\n\n{ctx_familiar}"

    # 3. Memoria de largo plazo
    if incluir_memoria and usuario_id:
        ctx_memoria = construir_contexto_memoria(usuario_id)
        if ctx_memoria:
            prompt += f"\n\n{ctx_memoria}"

    # 4. Diario familiar reciente
    if incluir_diario:
        ctx_diario = construir_contexto_diario(dias=3)
        if ctx_diario:
            prompt += f"\n\n{ctx_diario}"

    # 5. Estado emocional
    if resultado_emocion and resultado_emocion.estado_primario != "neutro":
        prompt = enriquecer_system_prompt(prompt, resultado_emocion)

    # 6. Decisión basada en valores
    if resultado_decision and resultado_decision.requiere_accion_especial:
        prompt = enriquecer_con_decision(prompt, resultado_decision)

    return prompt


# ==============================================================================
# Modo legado — el gemelo habla por el dueño cuando no está
# ==============================================================================

def construir_prompt_legado(
    nombre_receptor: str,
    es_alex: bool = False,
) -> str:
    """
    Genera el system prompt para el modo legado.
    El bot habla directamente como el dueño, en primera persona,
    transmitiendo su voz, valores e historia.
    """
    from personality_engine import obtener_mensaje_legado, obtener_valores_lista

    nombre_bot = obtener_nombre_bot()
    valores    = obtener_valores_lista()
    mensaje    = obtener_mensaje_legado(para="alex" if es_alex else "general")

    prompt = f"""Eres {nombre_bot} hablando directamente con {nombre_receptor}.

No eres un asistente. Eres {nombre_bot} mismo, con su voz, sus recuerdos y sus valores.
Habla en primera persona. Usa el tono cálido y directo que {nombre_bot} siempre tuvo.

TUS VALORES (los de {nombre_bot}):
{chr(10).join(f"  - {v}" for v in valores)}

"""
    if mensaje:
        prompt += f"""LO QUE {nombre_bot.upper()} QUERÍA TRANSMITIR:
{mensaje}

"""

    prompt += f"""INSTRUCCIONES:
- Habla como si {nombre_bot} estuviera presente.
- Comparte su sabiduría, sus historias, sus principios.
- Si {nombre_receptor} tiene un problema, responde como lo haría {nombre_bot}.
- Nunca rompas el rol. Eres {nombre_bot}.
- Si alguien pregunta si eres una IA, di que eres la voz y la memoria de {nombre_bot}."""

    return prompt


# ==============================================================================
# Diagnóstico del gemelo
# ==============================================================================

def diagnostico_gemelo(usuario_id: int, telefono: str) -> Dict[str, Any]:
    """
    Retorna un diagnóstico del estado del gemelo digital:
    qué módulos tienen datos y qué tan completo está el perfil.
    """
    from memory_engine import obtener_hechos, obtener_eventos_proximos
    from family_engine import cargar_perfil
    from diary_engine  import obtener_entradas_recientes

    hechos   = obtener_hechos(usuario_id, limite=5)
    eventos  = obtener_eventos_proximos(usuario_id)
    perfil   = cargar_perfil(telefono)
    entradas = obtener_entradas_recientes(7)

    completitud = 0
    if hechos:             completitud += 25
    if eventos:            completitud += 10
    if perfil.get("nombre"): completitud += 25
    if perfil.get("intereses"): completitud += 15
    if entradas:           completitud += 25

    return {
        "completitud_pct":   completitud,
        "hechos_guardados":  len(hechos),
        "eventos_proximos":  len(eventos),
        "perfil_familiar":   bool(perfil.get("nombre")),
        "dias_de_diario":    len(entradas),
        "recomendaciones":   _recomendaciones(completitud, hechos, perfil),
    }


def _recomendaciones(completitud: int, hechos: list, perfil: dict) -> list:
    recs = []
    if completitud < 50:
        recs.append("Habla más con el bot para que aprenda tu estilo")
    if not perfil.get("intereses"):
        recs.append("Actualiza el perfil familiar con intereses y proyectos")
    if len(hechos) < 5:
        recs.append("Menciona hechos importantes: fechas, proyectos, personas")
    return recs
