# ==============================================================================
# GUARDIÁN DIGITAL v4.0 - doc_engine.py
# Motor de procesamiento de documentos (PDF, texto, imágenes de documentos).
#
# Permite analizar documentos enviados por WhatsApp:
#   - Facturas y recibos
#   - Tareas escolares de Alex
#   - Contratos y documentos importantes
#   - Capturas de pantalla con texto
# ==============================================================================

from __future__ import annotations

import base64
import json
import logging
import re
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

try:
    from config import GEMINI_MODEL, GEMINI_API_KEY
    from google import genai
    from google.genai import types
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

# Tipos de documentos y cómo procesarlos
TIPOS_DOCUMENTO = {
    "tarea_escolar": {
        "keywords": ["tarea", "ejercicio", "problema", "actividad", "trabajo práctico"],
        "instruccion": (
            "Este es un documento de tarea escolar. "
            "Ayuda a entenderlo, explica los conceptos involucrados "
            "y da pistas sin dar la respuesta directamente. "
            "El objetivo es que el estudiante aprenda."
        ),
    },
    "factura_recibo": {
        "keywords": ["factura", "recibo", "total", "subtotal", "impuesto", "iva", "precio"],
        "instruccion": (
            "Este es un documento financiero. "
            "Resume los montos principales, fechas y datos relevantes. "
            "Indica si hay algo inusual o que requiera atención."
        ),
    },
    "contrato": {
        "keywords": ["contrato", "acuerdo", "cláusula", "partes", "firma", "vigencia"],
        "instruccion": (
            "Este es un documento legal. "
            "Resume los puntos principales: partes involucradas, obligaciones, fechas, montos. "
            "Señala cláusulas importantes o potencialmente problemáticas. "
            "Recuerda que no eres abogado."
        ),
    },
    "medico": {
        "keywords": ["diagnóstico", "medicamento", "dosis", "médico", "estudio", "análisis"],
        "instruccion": (
            "Este es un documento médico. "
            "Resume los hallazgos principales con claridad. "
            "No diagnostiques ni recomiendes tratamientos. "
            "Sugiere consultar con el médico tratante para cualquier duda."
        ),
    },
    "general": {
        "keywords": [],
        "instruccion": "Analiza este documento y resume su contenido más importante.",
    },
}


# ==============================================================================
# Procesamiento principal
# ==============================================================================

async def procesar_documento(
    contenido_bytes: bytes,
    mime_type:       str = "application/pdf",
    nombre_archivo:  str = "",
    contexto_usuario: str = "",
) -> Dict[str, Any]:
    """
    Procesa un documento y retorna un análisis estructurado.

    Retorna:
        {
            "tipo_documento":  str,
            "resumen":         str,
            "puntos_clave":    list[str],
            "requiere_accion": bool,
            "sugerencia":      str,
            "error":           str | None,
        }
    """
    if not GEMINI_AVAILABLE:
        return _resultado_error("Motor de IA no disponible.")

    tipo   = _detectar_tipo(nombre_archivo, contexto_usuario)
    config_tipo = TIPOS_DOCUMENTO.get(tipo, TIPOS_DOCUMENTO["general"])

    prompt = f"""Analiza el siguiente documento.

Tipo detectado: {tipo}
{config_tipo['instruccion']}

Responde SOLO en JSON con este formato:
{{
  "resumen": "resumen del documento en 2-3 oraciones",
  "puntos_clave": ["punto 1", "punto 2", "punto 3"],
  "requiere_accion": true/false,
  "sugerencia": "qué debería hacer el usuario con este documento",
  "tipo_confirmado": "{tipo}"
}}"""

    try:
        b64 = base64.b64encode(contenido_bytes).decode()
        client = genai.Client(api_key=GEMINI_API_KEY)

        parts = [
            types.Part.from_bytes(data=contenido_bytes, mime_type=mime_type),
            types.Part(text=prompt),
        ]

        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=parts,
        )

        texto = response.text.strip()
        match = re.search(r"\{.*\}", texto, re.DOTALL)
        if match:
            resultado = json.loads(match.group())
            resultado["tipo_documento"] = tipo
            resultado["error"] = None
            return resultado

        return {
            "tipo_documento":  tipo,
            "resumen":         texto[:500],
            "puntos_clave":    [],
            "requiere_accion": False,
            "sugerencia":      "",
            "error":           None,
        }

    except Exception as e:
        logger.error(f"[DOC] Error procesando documento: {e}")
        return _resultado_error(str(e))


def _detectar_tipo(nombre: str, contexto: str) -> str:
    """Detecta el tipo de documento por nombre y contexto."""
    texto = (nombre + " " + contexto).lower()
    for tipo, config in TIPOS_DOCUMENTO.items():
        if tipo == "general":
            continue
        for keyword in config["keywords"]:
            if keyword in texto:
                return tipo
    return "general"


def _resultado_error(mensaje: str) -> Dict[str, Any]:
    return {
        "tipo_documento":  "general",
        "resumen":         "",
        "puntos_clave":    [],
        "requiere_accion": False,
        "sugerencia":      "",
        "error":           mensaje,
    }


def formatear_respuesta_documento(resultado: Dict[str, Any]) -> str:
    """Formatea el resultado del análisis para enviar por WhatsApp."""
    if resultado.get("error"):
        return f"No pude procesar el documento: {resultado['error']}"

    lineas = []
    tipo   = resultado.get("tipo_documento", "documento")

    lineas.append(f"📄 *Documento analizado* ({tipo})")
    lineas.append("")

    if resultado.get("resumen"):
        lineas.append(resultado["resumen"])
        lineas.append("")

    puntos = resultado.get("puntos_clave", [])
    if puntos:
        lineas.append("*Puntos clave:*")
        for p in puntos:
            lineas.append(f"  • {p}")
        lineas.append("")

    if resultado.get("requiere_accion") and resultado.get("sugerencia"):
        lineas.append(f"⚡ *{resultado['sugerencia']}*")

    return "\n".join(lineas)
