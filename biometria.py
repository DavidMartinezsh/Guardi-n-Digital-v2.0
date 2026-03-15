# ==============================================================================
# GUARDIÁN DIGITAL v2.0 - biometria.py
# Análisis de "huella digital" conductual del texto para detectar impostores.
# ==============================================================================

import re
import math
import logging
from typing import Dict, Any, List, Optional
from difflib import SequenceMatcher

from config import (
    BIOMETRIA_VENTANA_MENSAJES,
    BIOMETRIA_UMBRAL_SIMILITUD,
    BIOMETRIA_PESO_EMOJI,
    BIOMETRIA_PESO_LONGITUD,
    BIOMETRIA_PESO_ESTILO,
)
from memoria import obtener_mensajes_raw

logger = logging.getLogger(__name__)

# Regex de emojis (rango Unicode de emojis comunes)
EMOJI_PATTERN = re.compile(
    "[\U0001F600-\U0001F64F"
    "\U0001F300-\U0001F5FF"
    "\U0001F680-\U0001F6FF"
    "\U0001F1E0-\U0001F1FF"
    "\U00002500-\U00002BEF"
    "\U00002702-\U000027B0"
    "\U000024C2-\U0001F251"
    "\U0001f926-\U0001f937"
    "\u200d\u2640\u2642"
    "\u2600-\u2B55"
    "\u23cf\u23e9\u231a\ufe0f\u3030"
    "]+",
    flags=re.UNICODE,
)


# ==============================================================================
# Extracción de características
# ==============================================================================

def extraer_caracteristicas(texto: str) -> Dict[str, Any]:
    """
    Extrae métricas conductuales de un mensaje de texto.
    """
    palabras = texto.split()
    oraciones = re.split(r"[.!?]+", texto)
    oraciones = [o.strip() for o in oraciones if o.strip()]

    emojis = EMOJI_PATTERN.findall(texto)
    num_emojis = len(emojis)

    # Ratio de signos de exclamación / interrogación
    exclamaciones = texto.count("!")
    interrogaciones = texto.count("?")

    # Longitud promedio de palabras
    long_palabras = (
        sum(len(p) for p in palabras) / len(palabras) if palabras else 0
    )

    # Mayúsculas al inicio de oraciones (estilo formal)
    inicia_mayuscula = sum(
        1 for o in oraciones if o and o[0].isupper()
    ) / max(len(oraciones), 1)

    # Uso de diminutivos / coloquialismos en español
    coloquialismos = sum(
        1 for p in palabras
        if p.lower().endswith(("ito", "ita", "illo", "illa", "ón", "azo"))
    )

    return {
        "longitud_total": len(texto),
        "num_palabras": len(palabras),
        "longitud_media_palabras": round(long_palabras, 2),
        "num_emojis": num_emojis,
        "ratio_emojis": round(num_emojis / max(len(palabras), 1), 3),
        "exclamaciones": exclamaciones,
        "interrogaciones": interrogaciones,
        "inicia_mayuscula_ratio": round(inicia_mayuscula, 2),
        "coloquialismos": coloquialismos,
        "num_oraciones": len(oraciones),
        "long_media_oracion": round(
            sum(len(o.split()) for o in oraciones) / max(len(oraciones), 1), 2
        ),
    }


def calcular_perfil_historico(mensajes: List[Dict]) -> Optional[Dict[str, Any]]:
    """
    Calcula el perfil biométrico promedio a partir de una lista de mensajes.
    """
    if not mensajes:
        return None

    perfiles = [extraer_caracteristicas(m["contenido"]) for m in mensajes]

    claves = perfiles[0].keys()
    perfil_promedio = {}
    for clave in claves:
        valores = [p[clave] for p in perfiles]
        perfil_promedio[clave] = round(sum(valores) / len(valores), 3)

    # Agregar desviación estándar como medida de consistencia
    perfil_promedio["_num_muestras"] = len(mensajes)
    for clave in list(claves):
        valores = [p[clave] for p in perfiles]
        media = perfil_promedio[clave]
        varianza = sum((v - media) ** 2 for v in valores) / max(len(valores), 1)
        perfil_promedio[f"_{clave}_std"] = round(math.sqrt(varianza), 3)

    return perfil_promedio


# ==============================================================================
# Comparación de similitud
# ==============================================================================

def similitud_longitud(actual: Dict, perfil: Dict) -> float:
    """Compara la longitud media de mensajes."""
    val_actual = actual.get("longitud_total", 0)
    val_hist   = perfil.get("longitud_total", 1)
    if val_hist == 0:
        return 0.5
    ratio = val_actual / val_hist
    # Penalizar si la diferencia supera el 200%
    if ratio > 2.0 or ratio < 0.1:
        return 0.0
    return 1.0 - abs(ratio - 1.0)


def similitud_emojis(actual: Dict, perfil: Dict) -> float:
    """Compara el patrón de uso de emojis."""
    ratio_actual = actual.get("ratio_emojis", 0)
    ratio_hist   = perfil.get("ratio_emojis", 0)
    diff = abs(ratio_actual - ratio_hist)
    # Si ambos usan 0 emojis → similitud perfecta
    if ratio_actual == 0 and ratio_hist == 0:
        return 1.0
    return max(0.0, 1.0 - diff * 10)  # Cada 0.1 de diferencia resta 1.0


def similitud_estilo(texto_actual: str, mensajes_historicos: List[Dict]) -> float:
    """
    Compara la similitud lingüística usando SequenceMatcher sobre el vocabulario.
    """
    if not mensajes_historicos:
        return 0.5  # Sin historial, no penalizar

    # Construir "vocabulario" del historial
    corpus_hist = " ".join(m["contenido"] for m in mensajes_historicos[:10])
    palabras_hist = set(corpus_hist.lower().split())
    palabras_actual = set(texto_actual.lower().split())

    if not palabras_hist or not palabras_actual:
        return 0.5

    # Jaccard similarity entre vocabularios
    interseccion = palabras_hist & palabras_actual
    union = palabras_hist | palabras_actual
    jaccard = len(interseccion) / max(len(union), 1)

    # SequenceMatcher sobre texto completo (más costoso pero más preciso)
    muestra_hist = corpus_hist[:500]
    seq_sim = SequenceMatcher(None, texto_actual[:500], muestra_hist).ratio()

    return round((jaccard * 0.6 + seq_sim * 0.4), 3)


# ==============================================================================
# Score final de biometría
# ==============================================================================

def analizar_biometria(
    usuario_id: int,
    texto_actual: str,
) -> Dict[str, Any]:
    """
    Orquesta el análisis biométrico completo.

    Retorna:
        {
            "score_similitud": float (0-1),  # 1 = idéntico al perfil histórico
            "score_riesgo":    float (0-10), # 0 = sin riesgo, 10 = impostor
            "perfil_actual":   dict,
            "perfil_historico": dict | None,
            "detalle":         str,
            "tiene_historial": bool,
        }
    """
    mensajes_hist = obtener_mensajes_raw(usuario_id, BIOMETRIA_VENTANA_MENSAJES)
    tiene_historial = len(mensajes_hist) >= 5  # Mínimo para ser confiable

    perfil_actual = extraer_caracteristicas(texto_actual)

    if not tiene_historial:
        return {
            "score_similitud": 0.5,
            "score_riesgo": 0.0,
            "perfil_actual": perfil_actual,
            "perfil_historico": None,
            "detalle": "Historial insuficiente para análisis biométrico.",
            "tiene_historial": False,
        }

    perfil_historico = calcular_perfil_historico(mensajes_hist)

    # Calcular componentes de similitud
    sim_longitud = similitud_longitud(perfil_actual, perfil_historico)
    sim_emojis   = similitud_emojis(perfil_actual, perfil_historico)
    sim_estilo   = similitud_estilo(texto_actual, mensajes_hist)

    # Score ponderado final (0-1)
    score_similitud = (
        sim_longitud * BIOMETRIA_PESO_LONGITUD
        + sim_emojis   * BIOMETRIA_PESO_EMOJI
        + sim_estilo   * BIOMETRIA_PESO_ESTILO
    )
    score_similitud = round(max(0.0, min(1.0, score_similitud)), 3)

    # Convertir a score de riesgo (0-10): mayor similitud = menor riesgo
    score_riesgo = round((1.0 - score_similitud) * 10, 2)

    # Verificar si el umbral mínimo supera el límite configurado
    alerta = score_similitud < BIOMETRIA_UMBRAL_SIMILITUD

    detalle = (
        f"Similitud={score_similitud:.2f} | "
        f"Longitud={sim_longitud:.2f} | "
        f"Emojis={sim_emojis:.2f} | "
        f"Estilo={sim_estilo:.2f} | "
        f"Muestras={len(mensajes_hist)}"
    )
    if alerta:
        detalle += " ⚠️ POSIBLE IMPOSTOR"

    logger.debug(f"[BIOMETRIA] user={usuario_id} {detalle}")

    return {
        "score_similitud": score_similitud,
        "score_riesgo": score_riesgo,
        "perfil_actual": perfil_actual,
        "perfil_historico": perfil_historico,
        "detalle": detalle,
        "tiene_historial": True,
        "alerta": alerta,
    }
