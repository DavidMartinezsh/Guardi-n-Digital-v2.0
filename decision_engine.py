# ==============================================================================
# GUARDIÁN DIGITAL v4.0 - decision_engine.py
# Motor de decisiones basado en valores.
#
# No solo responde preguntas — detecta situaciones y sugiere acciones
# basadas en los valores configurados en values.json.
# ==============================================================================

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ==============================================================================
# Tipos de situaciones detectables
# ==============================================================================

SITUACIONES = {
    "problema_escolar": {
        "keywords": ["colegio", "escuela", "maestra", "maestro", "reprobar", "reprobé",
                     "examen", "tarea", "no entiendo la clase", "me fue mal"],
        "accion":   "apoyo_educativo",
        "prioridad": 3,
    },
    "conflicto_familiar": {
        "keywords": ["pelea", "discutimos", "nos peleamos", "estamos mal", "no se hablan",
                     "problema con mamá", "problema con papá", "separación"],
        "accion":   "mediacion_emocional",
        "prioridad": 4,
    },
    "decision_importante": {
        "keywords": ["no sé si", "qué hago", "me ayudás a decidir", "debería",
                     "tengo que elegir", "es una decisión difícil"],
        "accion":   "consejo_basado_en_valores",
        "prioridad": 3,
    },
    "necesita_motivacion": {
        "keywords": ["no puedo", "es muy difícil", "me rindo", "no sirvo",
                     "no soy capaz", "para qué", "no tiene sentido"],
        "accion":   "motivacion_personalizada",
        "prioridad": 4,
    },
    "logro_personal": {
        "keywords": ["lo logré", "pude", "aprobé", "me aprobaron", "gané",
                     "conseguí el trabajo", "terminé el proyecto"],
        "accion":   "celebrar_logro",
        "prioridad": 2,
    },
    "pide_consejo_vida": {
        "keywords": ["qué harías tú", "qué me aconsejás", "cómo lo harías vos",
                     "qué pensás que debería hacer", "necesito un consejo"],
        "accion":   "consejo_personal",
        "prioridad": 3,
    },
    "problemas_economicos": {
        "keywords": ["no tengo plata", "estoy sin trabajo", "me quedé sin trabajo",
                     "deuda", "no llego a fin de mes", "problemas de dinero"],
        "accion":   "apoyo_practico",
        "prioridad": 4,
    },
    "salud": {
        "keywords": ["me duele", "estoy enfermo", "fui al médico", "diagnóstico",
                     "tratamiento", "operación", "internación"],
        "accion":   "apoyo_salud",
        "prioridad": 5,
    },
}

# Acciones y su descripción para Gemini
ACCIONES = {
    "apoyo_educativo": (
        "El usuario tiene dificultades académicas. Ofrece ayuda concreta: "
        "explica el concepto de forma simple, sugiere técnicas de estudio, "
        "y recuerda que los errores son parte del aprendizaje."
    ),
    "mediacion_emocional": (
        "Hay un conflicto familiar. Escucha sin tomar partido. "
        "Ayuda a ver la perspectiva del otro. Sugiere hablar con calma. "
        "Recuerda el valor de la familia."
    ),
    "consejo_basado_en_valores": (
        "El usuario necesita tomar una decisión. Ayúdalo a evaluar las opciones "
        "desde los valores: ¿qué dice tu instinto? ¿qué es lo correcto a largo plazo? "
        "¿qué decisión podrías sostener con orgullo en el futuro?"
    ),
    "motivacion_personalizada": (
        "El usuario está desmotivado o quiere rendirse. Recuérdale sus capacidades "
        "y logros pasados. Usa el principio: 'la resiliencia es la virtud más importante'. "
        "Ofrece un primer paso pequeño y concreto."
    ),
    "celebrar_logro": (
        "El usuario logró algo importante. Celebra genuinamente. "
        "Conecta el logro con el esfuerzo que lo hizo posible. "
        "Pregunta cómo se siente."
    ),
    "consejo_personal": (
        "El usuario pide consejo personal. Responde como lo haría el dueño: "
        "desde los valores, con honestidad, sin juzgar. "
        "Comparte perspectiva pero deja la decisión al usuario."
    ),
    "apoyo_practico": (
        "Hay un problema económico. Ofrece apoyo emocional primero. "
        "Luego sugiere opciones prácticas concretas si las hay. "
        "No minimices la situación."
    ),
    "apoyo_salud": (
        "Hay una situación de salud. Muestra preocupación genuina. "
        "Pregunta cómo está y qué necesita. "
        "Sugiere hablar con un profesional si el tema es grave."
    ),
}


# ==============================================================================
# Resultado
# ==============================================================================

@dataclass
class ResultadoDecision:
    situacion:      str  = "ninguna"
    accion:         str  = "normal"
    prioridad:      int  = 1
    instruccion_ia: str  = ""
    señales:        List = field(default_factory=list)

    @property
    def requiere_accion_especial(self) -> bool:
        return self.situacion != "ninguna"


# ==============================================================================
# Análisis de situación
# ==============================================================================

def analizar_situacion(texto: str, rol_nombre: str = "desconocido") -> ResultadoDecision:
    """
    Analiza el texto y detecta si hay una situación que requiere
    una respuesta especial basada en valores.
    """
    texto_lower = texto.lower()
    detectadas = []

    for nombre_sit, config in SITUACIONES.items():
        keywords = config["keywords"]
        hits = [k for k in keywords if k in texto_lower]
        if hits:
            detectadas.append({
                "nombre":    nombre_sit,
                "accion":    config["accion"],
                "prioridad": config["prioridad"],
                "hits":      hits,
            })

    if not detectadas:
        return ResultadoDecision()

    # Tomar la situación de mayor prioridad
    principal = max(detectadas, key=lambda x: x["prioridad"])
    accion    = principal["accion"]
    instruccion = ACCIONES.get(accion, "Responde de forma útil y empática.")

    return ResultadoDecision(
        situacion=principal["nombre"],
        accion=accion,
        prioridad=principal["prioridad"],
        instruccion_ia=instruccion,
        señales=principal["hits"],
    )


def enriquecer_con_decision(system_prompt: str, resultado: ResultadoDecision) -> str:
    """Agrega instrucciones de decisión al system prompt si hay una situación detectada."""
    if not resultado.requiere_accion_especial:
        return system_prompt

    bloque = (
        f"\n\nSITUACIÓN DETECTADA: {resultado.situacion.upper().replace('_', ' ')}\n"
        f"ACCIÓN RECOMENDADA: {resultado.instruccion_ia}"
    )
    return system_prompt + bloque
