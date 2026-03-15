# ==============================================================================
# GUARDIÁN DIGITAL v2.0 - manipulacion.py
# Detector de ingeniería social, phishing textual y manipulación emocional.
# ==============================================================================

import re
import logging
from typing import Dict, Any, List, Tuple

logger = logging.getLogger(__name__)


# ==============================================================================
# Diccionario de patrones de riesgo
# ==============================================================================

PATRONES_RIESGO: List[Tuple[str, float, str]] = [
    # (patrón_regex, peso_riesgo, categoría)

    # --- Urgencia artificial ---
    (r"\burgente\b", 1.5, "urgencia"),
    (r"\bahora\s+mismo\b", 1.5, "urgencia"),
    (r"\bno\s+hay\s+tiempo\b", 1.5, "urgencia"),
    (r"\brápido\b", 1.0, "urgencia"),
    (r"\bde\s+inmediato\b", 1.5, "urgencia"),
    (r"\bya\s+mismo\b", 1.0, "urgencia"),
    (r"\bemergencia\b", 2.0, "urgencia"),
    (r"\bcrítico\b", 1.5, "urgencia"),

    # --- Pedido de dinero / recursos ---
    (r"\benvía?me\s+(?:dinero|plata|guita|pesos|dólares|euros)\b", 3.0, "dinero"),
    (r"\bnecesito\s+(?:que\s+me\s+)?(?:prestes?|des?)\b", 2.0, "dinero"),
    (r"\bpréstamo\b", 2.0, "dinero"),
    (r"\btransferencia\b", 1.5, "dinero"),
    (r"\bbizum\b", 1.5, "dinero"),
    (r"\bpaypal\b", 1.5, "dinero"),
    (r"\bcrypto\b", 2.0, "dinero"),
    (r"\bbitcoin\b", 2.0, "dinero"),

    # --- Secretismo / manipulación emocional ---
    (r"\bno\s+(?:le\s+)?(?:digas?|cuentes?|menciones?)\s+a\s+nadie\b", 3.0, "secretismo"),
    (r"\bqueda\s+entre\s+(?:nosotros|tú\s+y\s+yo)\b", 3.0, "secretismo"),
    (r"\bsólo\s+(?:tú|vos)\s+(?:puedes?|podés?)\s+ayudarme\b", 2.5, "manipulacion"),
    (r"\bsi\s+me\s+quisieras?\b", 2.0, "manipulacion"),
    (r"\bsi\s+de\s+verdad\s+(?:eres?|sos)\s+mi\b", 2.0, "manipulacion"),
    (r"\bnadie\s+más\s+(?:me\s+)?(?:ayuda|entiende)\b", 2.0, "manipulacion"),

    # --- Suplantación de identidad ---
    (r"\bsoy\s+(?:tu\s+)?(?:jefe|jefa|supervisor|gerente)\b", 2.5, "suplantacion"),
    (r"\ble\s+habla\s+(?:de\s+parte\s+de|en\s+nombre\s+de)\b", 2.0, "suplantacion"),
    (r"\borden\s+(?:directa|oficial|urgente)\b", 2.0, "suplantacion"),

    # --- Phishing textual ---
    (r"\bverific(?:a|ar|ación)\s+(?:tu\s+)?cuenta\b", 3.0, "phishing"),
    (r"\bingresa?\s+(?:tu\s+)?contraseña\b", 3.5, "phishing"),
    (r"\bclic\s+(?:aquí|acá)\b", 2.5, "phishing"),
    (r"\bacceso\s+suspendido\b", 3.0, "phishing"),
    (r"\bganaste?\s+un\b", 2.5, "phishing"),
    (r"\bpremi(?:o|ado)\b", 2.0, "phishing"),
    (r"\bactualiz(?:a|ar)\s+(?:tus?\s+)?datos\b", 2.5, "phishing"),
    (r"https?://[^\s]+\.(tk|ml|ga|cf|gq|xyz|top|club)\b", 3.0, "phishing_url"),

    # --- Amenazas / coerción ---
    (r"\bsi\s+no\s+(?:lo\s+)?hac(?:es?|és?)\b", 2.0, "coercion"),
    (r"\bvas?\s+a\s+(?:lamentarlo|arrepentirte)\b", 2.5, "coercion"),
    (r"\bte\s+voy?\s+a\b", 1.5, "coercion"),
    (r"\bdenuncia\b", 1.0, "coercion"),

    # --- Información sensible ---
    (r"\bclave\b", 1.5, "datos_sensibles"),
    (r"\bpin\b", 1.5, "datos_sensibles"),
    (r"\btarjeta\s+de\s+crédito\b", 2.5, "datos_sensibles"),
    (r"\bcvv\b", 3.0, "datos_sensibles"),
    (r"\bnúmero\s+de\s+cuenta\b", 2.5, "datos_sensibles"),
    (r"\bdni\b|\bcédula\b|\bpasaporte\b", 1.5, "datos_sensibles"),
]

# Patrones en inglés (para mensajes multilingüe)
PATRONES_INGLES: List[Tuple[str, float, str]] = [
    (r"\burgent\b", 1.5, "urgencia"),
    (r"\bsend\s+money\b", 3.0, "dinero"),
    (r"\bwire\s+transfer\b", 2.5, "dinero"),
    (r"\bpassword\b", 2.0, "datos_sensibles"),
    (r"\bverify\s+your\s+account\b", 3.0, "phishing"),
    (r"\bclick\s+here\b", 2.5, "phishing"),
    (r"\baccount\s+suspended\b", 3.0, "phishing"),
    (r"\byou\s+won\b", 2.5, "phishing"),
    (r"\bdon.t\s+tell\s+anyone\b", 3.0, "secretismo"),
    (r"\bonlyyou\s+can\s+help\b", 2.5, "manipulacion"),
]

TODOS_PATRONES = PATRONES_RIESGO + PATRONES_INGLES


# ==============================================================================
# Analizador principal
# ==============================================================================

def analizar_manipulacion(texto: str) -> Dict[str, Any]:
    """
    Analiza un texto en busca de patrones de ingeniería social.

    Retorna:
        {
            "score_riesgo":     float (0-10),
            "categorias":       list[str],   # Categorías de riesgo detectadas
            "patrones_activos": list[str],   # Patrones que dispararon
            "detalle":          str,
            "es_peligroso":     bool,        # score >= 5.0
        }
    """
    texto_lower = texto.lower()
    score_acumulado = 0.0
    categorias_detectadas = set()
    patrones_activos = []

    for patron, peso, categoria in TODOS_PATRONES:
        if re.search(patron, texto_lower):
            score_acumulado += peso
            categorias_detectadas.add(categoria)
            patrones_activos.append(f"{categoria}:{patron[:30]}")

    # Bonus por acumulación: múltiples categorías = riesgo exponencial
    num_categorias = len(categorias_detectadas)
    if num_categorias >= 3:
        score_acumulado *= 1.5
    elif num_categorias == 2:
        score_acumulado *= 1.2

    # Normalizar a escala 0-10
    score_riesgo = round(min(score_acumulado, 10.0), 2)
    es_peligroso = score_riesgo >= 5.0

    detalle = (
        f"Score={score_riesgo} | "
        f"Categorías={','.join(sorted(categorias_detectadas)) or 'ninguna'} | "
        f"Patrones={len(patrones_activos)}"
    )
    if es_peligroso:
        detalle += " ⚠️ ALERTA MANIPULACIÓN"

    logger.debug(f"[MANIPULACION] {detalle}")

    return {
        "score_riesgo": score_riesgo,
        "categorias": sorted(categorias_detectadas),
        "patrones_activos": patrones_activos,
        "detalle": detalle,
        "es_peligroso": es_peligroso,
    }


# ==============================================================================
# Analizador de voz (post-transcripción)
# ==============================================================================

def analizar_manipulacion_voz(transcripcion: str) -> Dict[str, Any]:
    """
    Análisis de manipulación sobre texto transcrito de audio.
    Agrega un factor de confianza reducida al ser transcripción.
    """
    resultado = analizar_manipulacion(transcripcion)
    # La voz tiene mayor peso porque implica presión directa
    resultado["score_riesgo"] = round(
        min(resultado["score_riesgo"] * 1.2, 10.0), 2
    )
    resultado["fuente"] = "voz_transcrita"
    resultado["es_peligroso"] = resultado["score_riesgo"] >= 5.0
    return resultado


# ==============================================================================
# Utilidades de resumen
# ==============================================================================

def resumen_riesgo(resultado: Dict[str, Any]) -> str:
    """Genera un resumen legible del análisis para incluir en logs."""
    if not resultado["categorias"]:
        return "✅ Sin patrones de manipulación detectados."

    nivel = "🔴 ALTO" if resultado["score_riesgo"] >= 8 else (
            "🟡 MEDIO" if resultado["score_riesgo"] >= 5 else "🟢 BAJO"
    )
    return (
        f"{nivel} | Score: {resultado['score_riesgo']}/10 | "
        f"Categorías: {', '.join(resultado['categorias'])}"
    )
