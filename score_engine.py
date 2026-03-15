# ==============================================================================
# GUARDIÁN DIGITAL v2.0 - score_engine.py
# Motor de Score Central: única fuente de verdad para el cálculo de riesgo.
#
# ARQUITECTURA DEL SCORE (escala 0–10 por dimensión, pesos configurables)
# ─────────────────────────────────────────────────────────────────────────
#   DIMENSIÓN        PESO DEFAULT   DESCRIPCIÓN
#   Biometría          40 %         ¿El texto suena como el usuario real?
#   Manipulación       30 %         Ingeniería social, phishing textual
#   Estafa             20 %         Patrones de estafa específicos (IA + heurístico)
#   Improvisación      10 %         Rol, historial de incidentes, contexto situacional
# ─────────────────────────────────────────────────────────────────────────
#   TOTAL             100 %  →  score_final en escala 0–10
# ==============================================================================

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, Optional

from config import (
    UMBRAL_BLOQUEO, UMBRAL_DESAFIO, UMBRAL_ALERTA,
    SCORE_PESO_BIOMETRIA, SCORE_PESO_MANIPULACION,
    SCORE_PESO_ESTAFA, SCORE_PESO_IMPROVISACION,
)

logger = logging.getLogger(__name__)


# ==============================================================================
# Pesos cargados desde config.py (ajustables vía .env sin tocar código)
# ==============================================================================

PESOS_SCORE: Dict[str, float] = {
    "biometria":     SCORE_PESO_BIOMETRIA,     # 40 % default
    "manipulacion":  SCORE_PESO_MANIPULACION,  # 30 % default
    "estafa":        SCORE_PESO_ESTAFA,        # 20 % default
    "improvisacion": SCORE_PESO_IMPROVISACION, # 10 % default
}

# Invariante: la suma debe ser 1.0
_suma_pesos = sum(PESOS_SCORE.values())
assert abs(_suma_pesos - 1.0) < 1e-6, f"Los pesos deben sumar 1.0 (actual: {_suma_pesos:.3f})"


# ==============================================================================
# Dataclass del resultado — único objeto que circula por el sistema
# ==============================================================================

@dataclass
class ResultadoScore:
    """
    Resultado del cálculo de score. Es el único objeto que el firewall,
    el gateway y el logger necesitan conocer.
    """
    # Scores parciales (0–10 cada uno)
    biometria:     float = 0.0
    manipulacion:  float = 0.0
    estafa:        float = 0.0
    improvisacion: float = 0.0

    # Score final ponderado (0–10)
    total: float = 0.0

    # Metadatos
    usuario_id:    int   = 0
    rol_nivel:     int   = 1
    tipo_estafa:   str   = "ninguno"
    categorias:    list  = field(default_factory=list)
    señales:       list  = field(default_factory=list)
    detalle:       str   = ""

    # Decisión recomendada (la toma firewall.py, no este módulo)
    nivel_riesgo: str = "bajo"  # "ninguno" | "bajo" | "medio" | "alto" | "critico"

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def resumen(self) -> str:
        return (
            f"bio={self.biometria:.1f}×40% + "
            f"manip={self.manipulacion:.1f}×30% + "
            f"estafa={self.estafa:.1f}×20% + "
            f"improv={self.improvisacion:.1f}×10% "
            f"→ {self.total:.2f}/10 [{self.nivel_riesgo.upper()}]"
        )


# ==============================================================================
# Cálculo de la dimensión "Improvisación"
# (todo lo que no es biometría, manipulación ni estafa directa)
# ==============================================================================

def _calcular_improvisacion(
    texto:            str,
    rol_nivel:        int,
    score_historial:  float,
    hora_actual:      Optional[int] = None,
    franja_habitual:  Optional[str] = None,
) -> float:
    """
    Dimensión de improvisación / contexto situacional (0–10).

    Factores:
    ─ Penalización base por rol (desconocido = mayor desconfianza)
    ─ Historial de incidentes previos
    ─ Escritura fuera del horario habitual del usuario
    ─ Indicadores léxicos de urgencia no cubiertos por manipulación
    """
    score = 0.0

    # Penalización por rol
    penalizacion_rol = {5: 0.0, 4: 0.5, 3: 1.0, 2: 2.0, 1: 3.5}
    score += penalizacion_rol.get(rol_nivel, 3.5)

    # Historial (ya normalizado a 0–10 por el caller)
    score += min(score_historial * 0.3, 3.0)

    # Escritura fuera del horario habitual
    if hora_actual is not None and franja_habitual:
        franjas = {
            "madrugada": range(0, 6),
            "mañana":    range(6, 12),
            "tarde":     range(12, 20),
            "noche":     range(20, 24),
        }
        franja_actual = next(
            (k for k, r in franjas.items() if hora_actual in r), "tarde"
        )
        if franja_actual != franja_habitual:
            score += 1.5   # Escribe en horario inusual

    # Urgencia léxica residual
    urgencias = [
        r"\burgente\b", r"\bya\s+mismo\b", r"\bahora\s+mismo\b",
        r"\bemergencia\b", r"\bno\s+hay\s+tiempo\b",
    ]
    hits = sum(1 for u in urgencias if re.search(u, texto.lower()))
    score += min(hits * 0.6, 2.0)

    return round(min(score, 10.0), 2)


# ==============================================================================
# Función principal: calcular_score
# ==============================================================================

def calcular_score(
    usuario_id:         int,
    rol_nivel:          int,
    texto:              str,
    score_biometria:    float,
    score_manipulacion: float,
    score_estafa:       float,
    score_historial:    float       = 0.0,
    tipo_estafa:        str         = "ninguno",
    categorias:         list        = None,
    señales:            list        = None,
    hora_actual:        Optional[int] = None,
    franja_habitual:    Optional[str] = None,
    usuario_bloqueado:  bool        = False,
) -> ResultadoScore:
    """
    Calcula el score de riesgo unificado.

    Parámetros:
        usuario_id          ID del usuario en la DB
        rol_nivel           Nivel del rol (1–5)
        texto               Texto original del mensaje
        score_biometria     Resultado de biometria.py  (0–10)
        score_manipulacion  Resultado de manipulacion.py (0–10)
        score_estafa        Resultado de detector_estafas.py (0–10)
        score_historial     Incidentes previos normalizados (0–10)
        hora_actual         Hora del mensaje (0–23), opcional
        franja_habitual     Franja habitual del usuario, opcional
        usuario_bloqueado   Si True → score = 10 automáticamente

    Retorna:
        ResultadoScore con el desglose completo y el score final.
    """
    if usuario_bloqueado:
        return ResultadoScore(
            biometria=score_biometria,
            manipulacion=score_manipulacion,
            estafa=score_estafa,
            improvisacion=10.0,
            total=10.0,
            usuario_id=usuario_id,
            rol_nivel=rol_nivel,
            tipo_estafa=tipo_estafa,
            categorias=categorias or [],
            señales=señales or [],
            nivel_riesgo="critico",
            detalle="Usuario bloqueado → score máximo automático",
        )

    # Calcular dimensión propia
    score_improv = _calcular_improvisacion(
        texto, rol_nivel, score_historial, hora_actual, franja_habitual
    )

    # Score ponderado
    total = (
        score_biometria    * PESOS_SCORE["biometria"]
        + score_manipulacion * PESOS_SCORE["manipulacion"]
        + score_estafa       * PESOS_SCORE["estafa"]
        + score_improv       * PESOS_SCORE["improvisacion"]
    )
    total = round(min(total, 10.0), 2)

    # Nivel de riesgo semántico
    if total >= UMBRAL_BLOQUEO:
        nivel = "critico"
    elif total >= UMBRAL_DESAFIO:
        nivel = "alto"
    elif total >= UMBRAL_ALERTA:
        nivel = "medio"
    elif total >= 1.5:
        nivel = "bajo"
    else:
        nivel = "ninguno"

    resultado = ResultadoScore(
        biometria=round(score_biometria,    2),
        manipulacion=round(score_manipulacion, 2),
        estafa=round(score_estafa,          2),
        improvisacion=round(score_improv,   2),
        total=total,
        usuario_id=usuario_id,
        rol_nivel=rol_nivel,
        tipo_estafa=tipo_estafa,
        categorias=categorias or [],
        señales=señales or [],
        nivel_riesgo=nivel,
        detalle="",  # Se llena justo abajo
    )
    resultado.detalle = resultado.resumen()

    logger.debug(f"[SCORE] {resultado.detalle}")
    return resultado


# ==============================================================================
# Helpers de presentación
# ==============================================================================

def barra_score(total: float, ancho: int = 20) -> str:
    """Genera una barra de progreso ASCII para el score."""
    relleno  = int((total / 10.0) * ancho)
    vacio    = ancho - relleno
    color    = "🔴" if total >= 8 else ("🟠" if total >= 5.5 else ("🟡" if total >= 3.5 else "🟢"))
    return f"{color} [{'█' * relleno}{'░' * vacio}] {total:.1f}/10"


def reporte_score(r: ResultadoScore) -> str:
    """Genera un reporte legible del score para logs y debug."""
    lineas = [
        "┌─── SCORE DE RIESGO ───────────────────┐",
        f"│  Biometría      {r.biometria:>4.1f} × 40% = {r.biometria * 0.40:>4.2f}  │",
        f"│  Manipulación   {r.manipulacion:>4.1f} × 30% = {r.manipulacion * 0.30:>4.2f}  │",
        f"│  Estafa         {r.estafa:>4.1f} × 20% = {r.estafa * 0.20:>4.2f}  │",
        f"│  Improvisación  {r.improvisacion:>4.1f} × 10% = {r.improvisacion * 0.10:>4.2f}  │",
        f"│  {'─' * 36}│",
        f"│  TOTAL          {barra_score(r.total, 15)}  │",
        f"│  Nivel: {r.nivel_riesgo.upper():<30}│",
        "└───────────────────────────────────────┘",
    ]
    return "\n".join(lineas)
