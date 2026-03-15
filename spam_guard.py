# ==============================================================================
# GUARDIÁN DIGITAL v2.0 - spam_guard.py
# Protección contra spam y flood: rate limiting por usuario con ventana deslizante.
#
# REGLAS DE BLOQUEO (configurables en config.py):
#   - Mensajes totales en ventana de tiempo  → bloqueo temporal
#   - Mensajes idénticos consecutivos        → bloqueo por repetición
#   - Mensajes vacíos o de 1 carácter        → ignorar silencioso
#   - Ráfaga muy rápida (< N ms entre msgs)  → throttle
# ==============================================================================

from __future__ import annotations

import hashlib
import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Dict, Deque, Optional, Tuple

logger = logging.getLogger(__name__)


# ==============================================================================
# Configuración (también importable desde config.py)
# ==============================================================================

try:
    from config import (
        SPAM_VENTANA_SEGUNDOS,
        SPAM_MAX_MENSAJES,
        SPAM_MAX_IDENTICOS,
        SPAM_INTERVALO_MIN_MS,
        SPAM_BLOQUEO_TEMPORAL_SEG,
    )
except ImportError:
    SPAM_VENTANA_SEGUNDOS    = 60     # Ventana de 60 segundos
    SPAM_MAX_MENSAJES        = 30     # Máx. mensajes en la ventana
    SPAM_MAX_IDENTICOS       = 5      # Máx. mensajes idénticos consecutivos
    SPAM_INTERVALO_MIN_MS    = 300    # Intervalo mínimo entre mensajes (ms)
    SPAM_BLOQUEO_TEMPORAL_SEG = 300  # 5 minutos de bloqueo temporal


# ==============================================================================
# Estructuras de datos por usuario (en memoria, sin DB)
# ==============================================================================

@dataclass
class _EstadoUsuario:
    """Estado de rate-limiting por usuario."""
    timestamps:    Deque[float] = field(default_factory=lambda: deque(maxlen=500))
    hashes_recientes: Deque[str] = field(default_factory=lambda: deque(maxlen=20))
    bloqueado_hasta:  float = 0.0       # timestamp UNIX del fin del bloqueo temporal
    motivo_bloqueo:   str   = ""
    total_advertencias: int = 0
    total_bloqueos_spam: int = 0


# Registro global en memoria: { usuario_id: _EstadoUsuario }
_registro: Dict[int, _EstadoUsuario] = defaultdict(_EstadoUsuario)


# ==============================================================================
# Resultado de la evaluación
# ==============================================================================

@dataclass
class ResultadoSpam:
    permitido:        bool  = True
    motivo:           str   = ""
    score_spam:       float = 0.0    # 0–10: contribución al score de riesgo
    es_bloqueo_temp:  bool  = False  # True = bloqueo temporal (no permanente)
    segundos_restantes: int = 0      # Para informar al usuario
    sugerencia_msg:   str   = ""     # Mensaje opcional para devolver al usuario

    @property
    def debe_bloquear(self) -> bool:
        return not self.permitido


# ==============================================================================
# Lógica principal
# ==============================================================================

def evaluar_spam(usuario_id: int, texto: str) -> ResultadoSpam:
    """
    Evalúa si el mensaje debe ser bloqueado por spam.

    Casos que retornan ResultadoSpam.permitido = False:
      1. Usuario en período de bloqueo temporal activo
      2. Superó SPAM_MAX_MENSAJES en los últimos SPAM_VENTANA_SEGUNDOS
      3. Superó SPAM_MAX_IDENTICOS mensajes iguales consecutivos

    Casos que retornan score_spam > 0 pero permitido = True:
      4. Ráfaga rápida (< SPAM_INTERVALO_MIN_MS)
    """
    estado = _registro[usuario_id]
    ahora  = time.monotonic()

    # ─── 1. Bloqueo temporal activo ───────────────────────────────────────────
    if ahora < estado.bloqueado_hasta:
        restantes = int(estado.bloqueado_hasta - ahora)
        return ResultadoSpam(
            permitido=False,
            motivo="bloqueo_temporal_activo",
            score_spam=8.0,
            es_bloqueo_temp=True,
            segundos_restantes=restantes,
            sugerencia_msg=(
                f"Estoy tomando un descanso. "
                f"Podemos seguir en {_formato_tiempo(restantes)}."
            ),
        )

    # ─── 2. Limpiar timestamps fuera de la ventana ────────────────────────────
    ventana_inicio = ahora - SPAM_VENTANA_SEGUNDOS
    while estado.timestamps and estado.timestamps[0] < ventana_inicio:
        estado.timestamps.popleft()

    # ─── 3. Verificar ráfaga de volumen ──────────────────────────────────────
    total_en_ventana = len(estado.timestamps)
    if total_en_ventana >= SPAM_MAX_MENSAJES:
        _aplicar_bloqueo_temporal(estado, usuario_id, "volumen_excesivo")
        return ResultadoSpam(
            permitido=False,
            motivo=f"flood: {total_en_ventana} msgs en {SPAM_VENTANA_SEGUNDOS}s",
            score_spam=9.0,
            es_bloqueo_temp=True,
            segundos_restantes=SPAM_BLOQUEO_TEMPORAL_SEG,
            sugerencia_msg=(
                f"Estoy procesando muchos mensajes. "
                f"Vuelvo en {_formato_tiempo(SPAM_BLOQUEO_TEMPORAL_SEG)}."
            ),
        )

    # ─── 4. Verificar mensajes idénticos consecutivos ─────────────────────────
    hash_texto = _hash(texto)
    identicos_recientes = sum(1 for h in estado.hashes_recientes if h == hash_texto)
    if identicos_recientes >= SPAM_MAX_IDENTICOS:
        _aplicar_bloqueo_temporal(estado, usuario_id, "mensajes_identicos")
        return ResultadoSpam(
            permitido=False,
            motivo=f"repetición: mismo mensaje {identicos_recientes}× seguido",
            score_spam=7.0,
            es_bloqueo_temp=True,
            segundos_restantes=SPAM_BLOQUEO_TEMPORAL_SEG // 2,
            sugerencia_msg="Ya leí ese mensaje. Dame un momento.",
        )

    # ─── 5. Verificar intervalo mínimo (ráfaga rápida) ───────────────────────
    score_spam = 0.0
    if estado.timestamps:
        ultimo_ts  = estado.timestamps[-1]
        elapsed_ms = (ahora - ultimo_ts) * 1000
        if elapsed_ms < SPAM_INTERVALO_MIN_MS:
            # No bloquear, pero sí contribuir al score de riesgo
            factor = 1 - (elapsed_ms / SPAM_INTERVALO_MIN_MS)
            score_spam = round(min(factor * 4.0, 4.0), 2)
            logger.debug(
                f"[SPAM] Ráfaga rápida user={usuario_id} "
                f"elapsed={elapsed_ms:.0f}ms score_spam={score_spam}"
            )

    # ─── Registrar el mensaje ─────────────────────────────────────────────────
    estado.timestamps.append(ahora)
    estado.hashes_recientes.append(hash_texto)

    return ResultadoSpam(
        permitido=True,
        motivo="",
        score_spam=score_spam,
        es_bloqueo_temp=False,
    )


# ==============================================================================
# Helpers
# ==============================================================================

def _aplicar_bloqueo_temporal(estado: _EstadoUsuario, usuario_id: int, motivo: str) -> None:
    ahora = time.monotonic()
    estado.bloqueado_hasta   = ahora + SPAM_BLOQUEO_TEMPORAL_SEG
    estado.motivo_bloqueo    = motivo
    estado.total_bloqueos_spam += 1
    logger.warning(
        f"[SPAM] 🚫 Bloqueo temporal user={usuario_id} | "
        f"motivo={motivo} | duración={SPAM_BLOQUEO_TEMPORAL_SEG}s"
    )


def _hash(texto: str) -> str:
    """Hash corto del texto para comparar mensajes idénticos."""
    return hashlib.md5(texto.strip().lower().encode()).hexdigest()[:12]


def _formato_tiempo(segundos: int) -> str:
    """Convierte segundos a string legible."""
    if segundos < 60:
        return f"{segundos} segundos"
    mins = segundos // 60
    segs = segundos % 60
    return f"{mins} min{' ' + str(segs) + 's' if segs else ''}"


# ==============================================================================
# Reset y administración
# ==============================================================================

def resetear_spam_usuario(usuario_id: int) -> None:
    """Elimina el estado de spam de un usuario (útil al desbloquearlo manualmente)."""
    if usuario_id in _registro:
        del _registro[usuario_id]
        logger.info(f"[SPAM] Estado reseteado para user={usuario_id}")


def obtener_stats_spam(usuario_id: int) -> Dict:
    """Estadísticas del usuario para monitoreo."""
    if usuario_id not in _registro:
        return {"usuario_id": usuario_id, "sin_historial": True}
    estado = _registro[usuario_id]
    ahora  = time.monotonic()
    return {
        "usuario_id":         usuario_id,
        "msgs_en_ventana":    len(estado.timestamps),
        "bloqueado_temp":     ahora < estado.bloqueado_hasta,
        "segundos_restantes": max(0, int(estado.bloqueado_hasta - ahora)),
        "total_bloqueos":     estado.total_bloqueos_spam,
        "total_advertencias": estado.total_advertencias,
    }


def obtener_stats_globales() -> Dict:
    """Resumen del estado de spam de todos los usuarios activos."""
    ahora = time.monotonic()
    bloqueados = [
        uid for uid, e in _registro.items()
        if ahora < e.bloqueado_hasta
    ]
    return {
        "usuarios_monitoreados": len(_registro),
        "usuarios_bloqueados_temp": len(bloqueados),
        "ids_bloqueados": bloqueados,
    }


def purge_inactivos(inactividad_segundos: int = 3600) -> int:
    """
    Elimina entradas de usuarios inactivos para liberar memoria.
    Llamar periódicamente (ej. cada hora).
    """
    ahora = time.monotonic()
    a_eliminar = [
        uid for uid, e in _registro.items()
        if (not e.timestamps or ahora - e.timestamps[-1] > inactividad_segundos)
        and ahora >= e.bloqueado_hasta
    ]
    for uid in a_eliminar:
        del _registro[uid]
    if a_eliminar:
        logger.info(f"[SPAM] Purge: {len(a_eliminar)} usuarios inactivos eliminados.")
    return len(a_eliminar)
