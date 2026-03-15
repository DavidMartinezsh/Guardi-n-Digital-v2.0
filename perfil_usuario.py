# ==============================================================================
# GUARDIÁN DIGITAL v2.0 - perfil_usuario.py
# Sistema de aprendizaje: construye y actualiza el perfil lingüístico real
# de cada usuario para mejorar la detección de impostores con el tiempo.
# ==============================================================================

import re
import math
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime

from db import get_connection
from memoria import obtener_mensajes_raw

logger = logging.getLogger(__name__)

# ==============================================================================
# Extracción de estadísticas lingüísticas avanzadas
# ==============================================================================

EMOJI_RE = re.compile(
    "[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF"
    "\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF"
    "\u2600-\u2B55\u23cf\u23e9\u231a\ufe0f\u3030]+",
    flags=re.UNICODE,
)

# Palabras coloquiales / jerga hispanohablante común
SLANG_WORDS = {
    "re", "igual", "oka", "okas", "dale", "anda", "joya", "copado",
    "grosso", "buena", "buen", "yeite", "pa", "wey", "güey", "chido",
    "neta", "órale", "chévere", "bacano", "parcero", "marica", "vaina",
    "pana", "chamo", "coño", "tío", "tía", "mola", "guay", "genial",
    "venga", "ostia", "joer", "chaval", "nano", "cachondo",
}

# Errores ortográficos típicos en WhatsApp (abreviaciones intencionales)
ABREVIACIONES = {
    "q", "xq", "x", "d", "tb", "tmb", "tmbn", "mñn", "hsta", "kiero",
    "stas", "sta", "ntp", "nds", "bn", "bss", "msj", "mns", "grax",
    "grasias", "k", "xfa", "pls", "ok", "oki", "oks",
}


def extraer_estadisticas(textos: List[str]) -> Dict[str, float]:
    """
    Calcula el perfil lingüístico completo a partir de una lista de mensajes.

    Métricas calculadas:
        avg_words          → promedio de palabras por mensaje
        avg_chars          → promedio de caracteres por mensaje
        emoji_rate         → emojis por palabra
        typo_rate          → abreviaciones / total palabras
        slang_rate         → palabras de jerga / total palabras
        exclamation_rate   → signos ! por mensaje
        question_rate      → signos ? por mensaje
        caps_ratio         → ratio de palabras en MAYÚSCULAS
        sentence_length    → promedio de palabras por oración
        avg_hour           → hora promedio de escritura (0-23)
        punctuation_rate   → signos de puntuación por palabra
        multiline_ratio    → ratio de mensajes con saltos de línea
    """
    if not textos:
        return {}

    totals = {k: 0.0 for k in [
        "words", "chars", "emojis", "typos", "slangs",
        "exclamations", "questions", "caps_words", "sentences",
        "sentence_words", "punct", "multiline",
    ]}
    total_words_global = 0

    for texto in textos:
        palabras  = texto.split()
        oraciones = re.split(r"[.!?\n]+", texto)
        oraciones = [o.strip() for o in oraciones if o.strip()]

        emojis_found = EMOJI_RE.findall(texto)
        totals["words"]       += len(palabras)
        totals["chars"]       += len(texto)
        totals["emojis"]      += len(emojis_found)
        totals["exclamations"]+= texto.count("!")
        totals["questions"]   += texto.count("?")
        totals["punct"]       += len(re.findall(r"[.,;:\"'()\[\]{}]", texto))
        totals["multiline"]   += 1 if "\n" in texto else 0
        totals["sentences"]   += max(len(oraciones), 1)
        totals["sentence_words"] += sum(len(o.split()) for o in oraciones)

        for p in palabras:
            p_lower = p.lower().strip(".,!?;:")
            if p_lower in ABREVIACIONES:
                totals["typos"] += 1
            if p_lower in SLANG_WORDS:
                totals["slangs"] += 1
            if p.isupper() and len(p) > 1:
                totals["caps_words"] += 1

        total_words_global += max(len(palabras), 1)

    n = len(textos)
    w = max(total_words_global, 1)

    return {
        "avg_words":        round(totals["words"] / n, 2),
        "avg_chars":        round(totals["chars"] / n, 2),
        "emoji_rate":       round(totals["emojis"] / w, 4),
        "typo_rate":        round(totals["typos"] / w, 4),
        "slang_rate":       round(totals["slangs"] / w, 4),
        "exclamation_rate": round(totals["exclamations"] / n, 3),
        "question_rate":    round(totals["questions"] / n, 3),
        "caps_ratio":       round(totals["caps_words"] / w, 4),
        "sentence_length":  round(totals["sentence_words"] / max(totals["sentences"], 1), 2),
        "punctuation_rate": round(totals["punct"] / w, 4),
        "multiline_ratio":  round(totals["multiline"] / n, 3),
        "sample_size":      n,
    }


# ==============================================================================
# Horario de escritura
# ==============================================================================

def calcular_patron_horario(mensajes_raw: List[Dict]) -> Dict[str, Any]:
    """
    Analiza las horas en que el usuario suele escribir.
    Retorna hora promedio y distribución por franja.
    """
    horas = []
    for m in mensajes_raw:
        fecha = m.get("fecha")
        if isinstance(fecha, datetime):
            horas.append(fecha.hour)
        elif isinstance(fecha, str):
            try:
                dt = datetime.fromisoformat(fecha)
                horas.append(dt.hour)
            except Exception:
                pass

    if not horas:
        return {"avg_hour": 12.0, "active_slots": []}

    avg_hour = round(sum(horas) / len(horas), 1)

    # Franjas horarias (mañana/tarde/noche/madrugada)
    franjas = {"madrugada": 0, "mañana": 0, "tarde": 0, "noche": 0}
    for h in horas:
        if 0 <= h < 6:
            franjas["madrugada"] += 1
        elif 6 <= h < 12:
            franjas["mañana"] += 1
        elif 12 <= h < 20:
            franjas["tarde"] += 1
        else:
            franjas["noche"] += 1

    franja_dominante = max(franjas, key=franjas.get)
    return {
        "avg_hour":         avg_hour,
        "franja_dominante": franja_dominante,
        "distribucion":     franjas,
    }


# ==============================================================================
# Persistencia del perfil en DB
# ==============================================================================

def guardar_perfil(usuario_id: int, estadisticas: Dict[str, float]) -> None:
    """
    Guarda o actualiza el perfil lingüístico del usuario en la base de datos.
    Usa un JSON column para flexibilidad.
    """
    import json
    sql = """
        INSERT INTO PerfilLinguistico (usuario_id, estadisticas, actualizado)
        VALUES (%s, %s, NOW())
        ON DUPLICATE KEY UPDATE
            estadisticas = VALUES(estadisticas),
            actualizado  = NOW()
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (usuario_id, json.dumps(estadisticas)))
            conn.commit()


def obtener_perfil(usuario_id: int) -> Optional[Dict[str, Any]]:
    """Recupera el perfil lingüístico guardado del usuario."""
    import json
    sql = """
        SELECT estadisticas, actualizado FROM PerfilLinguistico
        WHERE usuario_id = %s LIMIT 1
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (usuario_id,))
            row = cur.fetchone()
            if row:
                try:
                    stats = json.loads(row["estadisticas"])
                    stats["_actualizado"] = str(row["actualizado"])
                    return stats
                except Exception:
                    pass
    return None


# ==============================================================================
# DDL para la nueva tabla
# ==============================================================================

PERFIL_DDL = """
CREATE TABLE IF NOT EXISTS PerfilLinguistico (
    usuario_id   INT PRIMARY KEY,
    estadisticas JSON NOT NULL,
    actualizado  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (usuario_id) REFERENCES Usuarios(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


def inicializar_tabla_perfil() -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(PERFIL_DDL)
            conn.commit()


# ==============================================================================
# Actualización incremental del perfil
# ==============================================================================

def actualizar_perfil_usuario(usuario_id: int, ventana: int = 100) -> Dict[str, Any]:
    """
    Recalcula y guarda el perfil lingüístico usando los últimos `ventana` mensajes.
    Llamar después de cada N mensajes para aprendizaje continuo.
    """
    mensajes_raw = obtener_mensajes_raw(usuario_id, ventana)
    if len(mensajes_raw) < 5:
        return {}

    textos = [m["contenido"] for m in mensajes_raw]
    stats  = extraer_estadisticas(textos)

    # Agregar patrón horario
    patron_horario = calcular_patron_horario(mensajes_raw)
    stats.update({
        "avg_hour":         patron_horario["avg_hour"],
        "franja_dominante": patron_horario["franja_dominante"],
    })

    guardar_perfil(usuario_id, stats)
    logger.debug(f"[PERFIL] Actualizado para user={usuario_id} ({len(textos)} muestras)")
    return stats


# ==============================================================================
# Comparación entre mensaje actual y perfil histórico
# ==============================================================================

def comparar_con_perfil(
    texto_actual: str,
    perfil_guardado: Dict[str, float],
) -> Dict[str, Any]:
    """
    Compara las estadísticas del mensaje actual con el perfil histórico.

    Retorna un score de desviación normalizado (0 = idéntico, 10 = muy diferente).
    """
    stats_actual = extraer_estadisticas([texto_actual])
    if not stats_actual or not perfil_guardado:
        return {"score_desviacion": 0.0, "desviaciones": {}}

    claves_comparar = [
        "avg_words", "emoji_rate", "typo_rate", "slang_rate",
        "exclamation_rate", "caps_ratio", "sentence_length",
    ]

    desviaciones = {}
    score_total  = 0.0

    for clave in claves_comparar:
        val_actual = stats_actual.get(clave, 0)
        val_hist   = perfil_guardado.get(clave, 0)

        if val_hist == 0 and val_actual == 0:
            desviaciones[clave] = 0.0
            continue

        denominador = max(abs(val_hist), 0.001)
        desv = abs(val_actual - val_hist) / denominador
        desv = min(desv, 2.0)  # Capping en 200% de diferencia
        desviaciones[clave] = round(desv, 3)
        score_total += desv

    # Normalizar a 0-10
    score_normalizado = round(min((score_total / len(claves_comparar)) * 5, 10.0), 2)

    return {
        "score_desviacion": score_normalizado,
        "desviaciones":     desviaciones,
        "stats_actuales":   stats_actual,
    }
