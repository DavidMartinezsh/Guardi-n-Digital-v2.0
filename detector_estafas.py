# ==============================================================================
# GUARDIÁN DIGITAL v2.0 - detector_estafas.py
# Detector de estafas entrenado: identifica patrones como "mamá cambié de número",
# "necesito dinero urgente" y suplantaciones familiares usando Gemini + heurísticas.
# ==============================================================================

import re
import logging
from typing import Dict, Any, List, Tuple

logger = logging.getLogger(__name__)


# ==============================================================================
# Patrones de estafa clásica (heurístico de alta precisión)
# ==============================================================================

# Cada tupla: (patrón_regex, peso, categoría, descripción)
PATRONES_ESTAFA: List[Tuple[str, float, str, str]] = [

    # ─── Suplantación familiar ─────────────────────────────────────────────────
    (r"\b(?:soy|es)\s+(?:tu\s+)?(?:hijo|hija|mamá|papá|hermano|hermana|primo|prima)\b",
     3.5, "suplantacion_familiar", "Afirma ser un familiar"),

    (r"\bcambié\s+(?:de\s+)?(?:número|cel|celular|teléfono)\b",
     4.0, "cambio_numero", "Alega haber cambiado de número"),

    (r"\bes(?:te\s+es)\s+mi\s+(?:nuevo|nueva)\s+(?:número|cel)\b",
     3.5, "cambio_numero", "Presenta nuevo número"),

    (r"\bno\s+(?:me\s+)?vayas?\s+a\s+(?:escribir|llamar)\s+al\s+(?:otro|anterior)\b",
     3.0, "desvio_contacto", "Pide no contactar número anterior"),

    (r"\bguarda\s+(?:este|mi)\s+(?:nuevo\s+)?(?:número|cel|contacto)\b",
     3.0, "desvio_contacto", "Pide guardar nuevo contacto"),

    # ─── Pedido de dinero urgente ──────────────────────────────────────────────
    (r"\bnecesito\s+(?:dinero|plata|efectivo|guita)\s+(?:urgente|ya|ahora|rápido)\b",
     4.5, "pedido_dinero_urgente", "Pedido urgente de dinero"),

    (r"\bpuedes?\s+(?:hacer|hacerme)\s+una\s+(?:transferencia|transf)\b",
     3.5, "transferencia", "Solicita transferencia bancaria"),

    (r"\bme\s+(?:prestas?|das?|mandas?)\s+(?:plata|dinero|efectivo)\b",
     3.5, "pedido_dinero", "Solicita dinero directamente"),

    (r"\bte\s+(?:devuelvo|pago)\s+(?:mañana|luego|después|pronto)\b",
     2.5, "promesa_pago", "Promete devolución futura"),

    (r"\bestoy\s+(?:en\s+un\s+)?(?:apuro|aprieto|problema|lío)\b",
     2.5, "situacion_urgente", "Alega estar en un apuro"),

    (r"\bme\s+robaron\b|\bme\s+asaltaron\b|\bperdí\s+(?:el|mi)\s+cel\b",
     3.0, "robo_perdida", "Alega robo o pérdida del teléfono"),

    # ─── Cuenta bancaria sospechosa ────────────────────────────────────────────
    (r"\bte\s+(?:paso|mando|envío)\s+(?:el|mi|la)\s+(?:cbu|cvu|alias|cuenta|iban)\b",
     3.5, "datos_bancarios", "Comparte datos bancarios sin solicitud"),

    (r"\b(?:cbu|cvu|alias)\s*[:=]?\s*[\d\w]+",
     3.0, "datos_bancarios", "Dato bancario en el mensaje"),

    (r"\bdepósit[ao]\s+(?:en|a)\s+(?:esta\s+cuenta|mi\s+cuenta|el\s+alias)\b",
     3.5, "instruccion_pago", "Instrucción de depósito"),

    # ─── Secretismo / presión ──────────────────────────────────────────────────
    (r"\bno\s+(?:le\s+)?(?:cuentes?|digas?|menciones?)\s+a\s+(?:nadie|papá|mamá)\b",
     4.0, "secretismo_familiar", "Pide secreto a la familia"),

    (r"\bsolo\s+(?:tú|vos)\s+(?:puedes?|podés?)\s+(?:ayudarme|salvarme)\b",
     3.5, "presion_emocional", "Presión emocional directa"),

    (r"\bsi\s+(?:me\s+quisieras?|de\s+verdad\s+(?:sos|eres)\s+mi)\b",
     3.0, "manipulacion_afecto", "Manipulación por afecto"),

    # ─── Estafas de premio / inversión ────────────────────────────────────────
    (r"\bganaste?\s+(?:un\s+)?(?:premio|sorteo|rifla)\b",
     3.5, "premio_falso", "Notificación de premio falso"),

    (r"\binversión\s+(?:segura|garantizada)\b",
     3.5, "inversion_fraudulenta", "Propuesta de inversión garantizada"),

    (r"\bdobl(?:a|ar)\s+(?:tu\s+)?(?:dinero|inversión|plata)\b",
     4.0, "esquema_ponzi", "Promesa de duplicar dinero"),

    (r"\bcrypto\s*(?:staking|farming|yield)\b",
     3.0, "cripto_fraude", "Oferta de cripto fraudulenta"),
]

# Patrones en inglés
PATRONES_ESTAFA_EN: List[Tuple[str, float, str, str]] = [
    (r"\bi\s+changed\s+my\s+number\b",            4.0, "cambio_numero",   "Changed number (EN)"),
    (r"\bsend\s+me\s+money\s+urgently?\b",         4.5, "pedido_dinero_urgente", "Urgent money request (EN)"),
    (r"\bthis\s+is\s+(?:mom|dad|son|daughter)\b",  3.5, "suplantacion_familiar", "Family impersonation (EN)"),
    (r"\bdont\s+tell\s+anyone\b",                  4.0, "secretismo",     "Don't tell anyone (EN)"),
    (r"\byou\s+won\s+a\s+prize\b",                 3.5, "premio_falso",   "You won a prize (EN)"),
    (r"\bdouble\s+your\s+(?:money|investment)\b",  4.0, "esquema_ponzi",  "Double money (EN)"),
]


# ==============================================================================
# Detector heurístico
# ==============================================================================

def detectar_estafa_heuristico(texto: str) -> Dict[str, Any]:
    """
    Analiza patrones de estafa en el texto mediante regex.
    """
    texto_lower = texto.lower()
    score = 0.0
    categorias = set()
    disparadores = []

    todos_patrones = PATRONES_ESTAFA + PATRONES_ESTAFA_EN
    for patron, peso, categoria, descripcion in todos_patrones:
        if re.search(patron, texto_lower):
            score += peso
            categorias.add(categoria)
            disparadores.append({"categoria": categoria, "descripcion": descripcion, "peso": peso})

    # Bonus por combinación peligrosa: cambio_numero + pedido_dinero
    if "cambio_numero" in categorias and any(
        c in categorias for c in ["pedido_dinero", "pedido_dinero_urgente", "transferencia"]
    ):
        score += 3.0
        disparadores.append({
            "categoria": "combo_peligroso",
            "descripcion": "COMBO: Cambio de número + pedido de dinero",
            "peso": 3.0,
        })

    score = round(min(score, 10.0), 2)
    return {
        "score": score,
        "categorias": sorted(categorias),
        "disparadores": disparadores,
        "es_estafa": score >= 4.5,
    }


# ==============================================================================
# Análisis profundo con Gemini
# ==============================================================================

async def analizar_estafa_con_gemini(texto: str, contexto_usuario: str = "") -> Dict[str, Any]:
    """
    Usa Gemini para analizar si el mensaje es una estafa, con razonamiento.
    Solo se invoca cuando el score heurístico supera 3.0 (para ahorrar tokens).
    """
    import google.generativeai as genai
    from config import GEMINI_API_KEY, GEMINI_MODEL
    import json, re as re_module

    genai.configure(api_key=GEMINI_API_KEY)

    prompt = f"""
Eres un experto en ciberseguridad y estafas por WhatsApp en Latinoamérica.

Analiza el siguiente mensaje y determina si es un intento de estafa.
Contexto del usuario: {contexto_usuario or 'Sin contexto previo'}

Mensaje a analizar:
\"\"\"
{texto[:1000]}
\"\"\"

Responde ÚNICAMENTE con este JSON (sin markdown, sin explicaciones):
{{
  "es_estafa": true/false,
  "tipo_estafa": "suplantacion_familiar|pedido_dinero|cambio_numero|premio|inversion|otro|ninguno",
  "confianza": 0-100,
  "razonamiento": "explicación breve en español (máx 100 palabras)",
  "señales_detectadas": ["señal1", "señal2"],
  "score_riesgo": 0-10
}}
"""

    try:
        model = genai.GenerativeModel(GEMINI_MODEL)
        response = model.generate_content(prompt)
        texto_resp = response.text.strip()

        # Limpiar posibles backticks de markdown
        texto_resp = re_module.sub(r"```json|```", "", texto_resp).strip()
        resultado = json.loads(texto_resp)
        resultado["fuente"] = "gemini"
        return resultado

    except Exception as e:
        logger.error(f"[DETECTOR_ESTAFA] Error Gemini: {e}")
        return {
            "es_estafa":         False,
            "tipo_estafa":       "desconocido",
            "confianza":         0,
            "razonamiento":      "Error al analizar con IA.",
            "señales_detectadas": [],
            "score_riesgo":      0.0,
            "fuente":            "error",
        }


# ==============================================================================
# Pipeline completo
# ==============================================================================

async def analizar_mensaje_completo(
    texto: str,
    contexto_usuario: str = "",
    usar_gemini: bool = True,
) -> Dict[str, Any]:
    """
    Combina análisis heurístico + Gemini para máxima precisión.

    Retorna:
        {
            "score_final":        float (0-10),
            "es_estafa":          bool,
            "tipo_estafa":        str,
            "categorias":         list,
            "razonamiento":       str,
            "señales":            list,
            "nivel_alerta":       str,  # "critico" | "alto" | "medio" | "bajo" | "ninguno"
            "mensaje_alerta":     str,  # Para mostrar al propietario del bot
        }
    """
    # 1. Análisis rápido heurístico
    heuristico = detectar_estafa_heuristico(texto)

    # 2. Análisis Gemini solo si supera umbral (economizar tokens)
    gemini_result = {"score_riesgo": 0.0, "es_estafa": False, "razonamiento": "", "señales_detectadas": [], "tipo_estafa": "ninguno"}
    if usar_gemini and heuristico["score"] >= 3.0:
        gemini_result = await analizar_estafa_con_gemini(texto, contexto_usuario)

    # 3. Combinar scores
    score_heuristico = heuristico["score"]
    score_gemini     = gemini_result.get("score_riesgo", 0.0)

    # Peso: Gemini 60%, heurístico 40% (si Gemini está disponible)
    if gemini_result.get("fuente") == "gemini":
        score_final = round(score_gemini * 0.6 + score_heuristico * 0.4, 2)
    else:
        score_final = score_heuristico

    score_final = min(score_final, 10.0)

    # 4. Determinar nivel de alerta
    if score_final >= 7.0:
        nivel = "critico"
    elif score_final >= 5.0:
        nivel = "alto"
    elif score_final >= 3.0:
        nivel = "medio"
    elif score_final >= 1.5:
        nivel = "bajo"
    else:
        nivel = "ninguno"

    # 5. Generar mensaje de alerta para el dueño
    tipo = gemini_result.get("tipo_estafa") or (heuristico["categorias"][0] if heuristico["categorias"] else "desconocido")
    mensaje_alerta = _generar_mensaje_alerta(nivel, tipo, score_final)

    return {
        "score_final":    score_final,
        "es_estafa":      score_final >= 5.0,
        "tipo_estafa":    tipo,
        "categorias":     heuristico["categorias"],
        "razonamiento":   gemini_result.get("razonamiento", ""),
        "señales":        list(set(
            [d["descripcion"] for d in heuristico["disparadores"]]
            + gemini_result.get("señales_detectadas", [])
        ))[:8],
        "nivel_alerta":   nivel,
        "mensaje_alerta": mensaje_alerta,
    }


def _generar_mensaje_alerta(nivel: str, tipo: str, score: float) -> str:
    """Genera un mensaje de alerta claro para el dueño del bot."""
    tipo_legible = {
        "suplantacion_familiar": "suplantación de familiar",
        "cambio_numero":         "cambio de número sospechoso",
        "pedido_dinero_urgente": "pedido de dinero urgente",
        "pedido_dinero":         "pedido de dinero",
        "transferencia":         "solicitud de transferencia",
        "premio_falso":          "premio/sorteo falso",
        "inversion_fraudulenta": "inversión fraudulenta",
        "esquema_ponzi":         "esquema Ponzi / duplicador",
        "secretismo_familiar":   "secretismo familiar",
        "combo_peligroso":       "combinación de señales críticas",
    }.get(tipo, tipo.replace("_", " "))

    iconos = {"critico": "🚨", "alto": "⛔", "medio": "⚠️", "bajo": "🔔", "ninguno": ""}
    icono = iconos.get(nivel, "⚠️")

    if nivel == "ninguno":
        return ""

    return (
        f"{icono} *ALERTA DE ESTAFA [{nivel.upper()}]* {icono}\n"
        f"Tipo detectado: *{tipo_legible}*\n"
        f"Score de riesgo: {score:.1f}/10\n\n"
        f"Este mensaje presenta características de una estafa. "
        f"Se recomienda verificar la identidad del remitente antes de responder."
    )
