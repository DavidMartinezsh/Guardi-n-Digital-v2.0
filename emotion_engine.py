# ==============================================================================
# GUARDIÁN DIGITAL v4.0 - emotion_engine.py
# Motor de inteligencia emocional.
#
# Detecta el estado emocional del mensaje y adapta la respuesta.
# También registra el estado emocional en el perfil familiar.
# ==============================================================================

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ==============================================================================
# Definición de estados emocionales
# ==============================================================================

ESTADOS = {
    "triste":     ["triste", "llorar", "llorando", "solo", "sola", "deprimido", "mal", "horrible",
                   "no puedo más", "no aguanto", "extraño", "extraña", "echo de menos", "duele",
                   "dolor", "pena", "angustia", "vacío", "perdido"],
    "enojado":    ["enojado", "furioso", "odio", "rabia", "bronca", "harto", "fastidiado", "molesto",
                   "me da asco", "no lo soporto", "insoportable", "injusto", "qué bronca"],
    "ansioso":    ["nervioso", "ansiosa", "ansioso", "preocupado", "asustado", "miedo", "pánico",
                   "no sé qué hacer", "qué hago", "me agobio", "agobiado", "estresado", "estrés"],
    "feliz":      ["feliz", "contento", "bien", "genial", "excelente", "perfecto", "alegre",
                   "lo logré", "pude", "pasó algo bueno", "buenas noticias"],
    "orgulloso":  ["lo logré", "aprobé", "gané", "me aprobaron", "conseguí", "lo hice",
                   "estoy orgulloso", "qué logro"],
    "cansado":    ["cansado", "agotado", "sin energía", "no dormí", "sin dormir", "rendido",
                   "no me da el cuerpo"],
    "confundido": ["no entiendo", "no sé", "perdido", "confundido", "no me queda claro",
                   "cómo hago", "me perdí"],
    "urgente":    ["urgente", "emergencia", "ayuda", "por favor", "rápido", "necesito ya",
                   "es grave"],
}

# Cómo responder según el estado emocional
ESTRATEGIAS_RESPUESTA = {
    "triste": {
        "prioridad":    "contener",
        "instruccion":  "Primero valida el sentimiento. Escucha antes de dar soluciones. Usa un tono cálido y empático. No minimices lo que siente.",
        "apertura":     ["¿Querés contarme qué pasó?", "Estoy acá.", "Te escucho."],
    },
    "enojado": {
        "prioridad":    "validar",
        "instruccion":  "Valida la rabia sin avivarla. No des la razón ni la quites. Ayuda a procesar la emoción antes de buscar soluciones.",
        "apertura":     ["Entiendo que estás enojado.", "Tiene sentido que te sientas así.", "Contame qué pasó."],
    },
    "ansioso": {
        "prioridad":    "calmar",
        "instruccion":  "Responde con calma y claridad. Da pasos concretos. Evita información abrumadora. Ayuda a enfocar en lo que sí puede controlar.",
        "apertura":     ["Tranquilo, lo resolvemos.", "Un paso a la vez.", "Vamos por partes."],
    },
    "feliz": {
        "prioridad":    "celebrar",
        "instruccion":  "Comparte la alegría genuinamente. Pregunta por los detalles. Refuerza el logro.",
        "apertura":     ["¡Qué buenas noticias!", "Me alegra mucho escuchar eso.", "Cuéntame más."],
    },
    "orgulloso": {
        "prioridad":    "reconocer",
        "instruccion":  "Reconoce el logro con entusiasmo. Conecta el logro con el esfuerzo previo. Pregunta cómo se siente.",
        "apertura":     ["¡Lo lograste!", "Sabía que podías.", "Estoy orgulloso de vos."],
    },
    "cansado": {
        "prioridad":    "sostener",
        "instruccion":  "Sé breve y claro. No agobies con información. Sugiere descanso si es posible.",
        "apertura":     ["Entiendo que estás agotado.", "¿Querés que lo dejemos para después?"],
    },
    "confundido": {
        "prioridad":    "clarificar",
        "instruccion":  "Explica paso a paso. Usa ejemplos simples. Pregunta qué parte no quedó clara.",
        "apertura":     ["Te lo explico con calma.", "Empecemos por el principio."],
    },
    "urgente": {
        "prioridad":    "actuar",
        "instruccion":  "Responde directo y rápido. Da la información más importante primero. Sé conciso.",
        "apertura":     ["Estoy acá.", "¿Qué necesitás?"],
    },
    "neutro": {
        "prioridad":    "normal",
        "instruccion":  "Conversación normal. Adapta el tono al contexto.",
        "apertura":     [],
    },
}


# ==============================================================================
# Resultado del análisis
# ==============================================================================

@dataclass
class ResultadoEmocion:
    estado_primario:   str   = "neutro"
    estado_secundario: str   = ""
    intensidad:        float = 0.0      # 0.0 a 1.0
    estrategia:        Dict  = field(default_factory=dict)
    señales:           List  = field(default_factory=list)
    instruccion_ia:    str   = ""

    def es_critico(self) -> bool:
        return self.estado_primario in ("triste", "ansioso") and self.intensidad > 0.7


# ==============================================================================
# Análisis emocional
# ==============================================================================

def analizar_emocion(texto: str) -> ResultadoEmocion:
    """
    Analiza el estado emocional del mensaje.
    Retorna un ResultadoEmocion con el estado y la estrategia de respuesta.
    """
    texto_lower = texto.lower()
    scores: Dict[str, float] = {}
    señales_encontradas = []

    for estado, palabras in ESTADOS.items():
        hits = []
        for palabra in palabras:
            if palabra in texto_lower:
                hits.append(palabra)
        if hits:
            # Score base: proporción de palabras encontradas
            scores[estado] = len(hits) / len(palabras)
            señales_encontradas.extend(hits)

    if not scores:
        return ResultadoEmocion(
            estado_primario="neutro",
            intensidad=0.0,
            estrategia=ESTRATEGIAS_RESPUESTA["neutro"],
            instruccion_ia=ESTRATEGIAS_RESPUESTA["neutro"]["instruccion"],
        )

    # Estado principal y secundario
    ordenados = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    estado_1 = ordenados[0][0]
    estado_2 = ordenados[1][0] if len(ordenados) > 1 else ""
    intensidad = min(ordenados[0][1] * 5, 1.0)  # Normalizar a 0-1

    # Ajuste por signos de puntuación de énfasis
    if "!" in texto or texto.isupper():
        intensidad = min(intensidad + 0.2, 1.0)

    estrategia = ESTRATEGIAS_RESPUESTA.get(estado_1, ESTRATEGIAS_RESPUESTA["neutro"])

    return ResultadoEmocion(
        estado_primario=estado_1,
        estado_secundario=estado_2,
        intensidad=round(intensidad, 2),
        estrategia=estrategia,
        señales=señales_encontradas,
        instruccion_ia=estrategia["instruccion"],
    )


def enriquecer_system_prompt(system_prompt: str, resultado: ResultadoEmocion) -> str:
    """
    Enriquece el system prompt de Gemini con instrucciones emocionales.
    """
    if resultado.estado_primario == "neutro":
        return system_prompt

    bloque = f"""
ESTADO EMOCIONAL DETECTADO: {resultado.estado_primario.upper()}
Intensidad: {resultado.intensidad:.0%}
Estrategia: {resultado.instruccion_ia}
"""
    if resultado.estado_secundario:
        bloque += f"Emoción secundaria: {resultado.estado_secundario}\n"

    return system_prompt + "\n\n" + bloque


def detectar_necesidad_apoyo_profesional(resultado: ResultadoEmocion) -> bool:
    """
    Detecta si el estado emocional podría requerir apoyo profesional.
    No ofrece crisis resources directamente — solo señala la necesidad al sistema.
    """
    criticos = {"triste", "ansioso"}
    return resultado.estado_primario in criticos and resultado.intensidad > 0.8


def emoji_estado(estado: str) -> str:
    """Devuelve un emoji representativo del estado (para logs, no para respuestas)."""
    mapa = {
        "triste":     "😢",
        "enojado":    "😤",
        "ansioso":    "😰",
        "feliz":      "😊",
        "orgulloso":  "💪",
        "cansado":    "😴",
        "confundido": "🤔",
        "urgente":    "⚡",
        "neutro":     "😐",
    }
    return mapa.get(estado, "😐")
