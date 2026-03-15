# ==============================================================================
# GUARDIÁN DIGITAL v4.0 - diary_engine.py
# Diario familiar automático.
#
# Construye una historia familiar digital a partir de las conversaciones.
# Guarda entradas diarias con los momentos más relevantes.
# ==============================================================================

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, date
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DIARY_DIR = Path(os.getenv("DIARY_DIR", "/var/guardian/diary"))
DIARY_DIR.mkdir(parents=True, exist_ok=True)


# ==============================================================================
# Estructura de una entrada de diario
# ==============================================================================

def _nueva_entrada(fecha: str) -> Dict[str, Any]:
    return {
        "fecha":     fecha,
        "momentos":  [],    # Lista de momentos del día
        "emociones": {},    # {telefono: estado_emocional}
        "logros":    [],    # Logros del día
        "problemas": [],    # Problemas del día
        "resumen":   "",    # Resumen generado por IA (opcional)
        "creado":    datetime.now().isoformat(),
    }


# ==============================================================================
# Guardar y cargar entradas
# ==============================================================================

def _ruta_entrada(fecha: str) -> Path:
    return DIARY_DIR / f"{fecha}.json"


def cargar_entrada(fecha: Optional[str] = None) -> Dict[str, Any]:
    """Carga la entrada del diario para una fecha. Default: hoy."""
    if fecha is None:
        fecha = date.today().isoformat()
    ruta = _ruta_entrada(fecha)
    if ruta.exists():
        try:
            with open(ruta, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"[DIARY] Error cargando entrada {fecha}: {e}")
    return _nueva_entrada(fecha)


def guardar_entrada(entrada: Dict[str, Any]) -> None:
    """Guarda una entrada del diario."""
    fecha = entrada.get("fecha", date.today().isoformat())
    ruta  = _ruta_entrada(fecha)
    try:
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(entrada, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"[DIARY] Error guardando entrada {fecha}: {e}")


# ==============================================================================
# Registrar momentos
# ==============================================================================

def registrar_momento(
    telefono:         str,
    nombre:           str,
    contenido:        str,
    tipo:             str = "conversacion",
    estado_emocional: str = "neutro",
) -> None:
    """
    Registra un momento en el diario del día actual.

    Tipos: 'conversacion' | 'logro' | 'problema' | 'decision' | 'evento'
    """
    entrada = cargar_entrada()
    hora    = datetime.now().strftime("%H:%M")

    momento = {
        "hora":             hora,
        "telefono":         telefono,
        "nombre":           nombre,
        "tipo":             tipo,
        "contenido":        contenido[:500],
        "estado_emocional": estado_emocional,
    }

    entrada["momentos"].append(momento)
    entrada["emociones"][telefono] = estado_emocional

    if tipo == "logro":
        entrada["logros"].append({"nombre": nombre, "logro": contenido[:200]})
    elif tipo == "problema":
        entrada["problemas"].append({"nombre": nombre, "problema": contenido[:200]})

    guardar_entrada(entrada)
    logger.debug(f"[DIARY] Momento registrado: {nombre} — {tipo}")


def registrar_evento_especial(titulo: str, descripcion: str = "") -> None:
    """Registra un evento especial en el diario."""
    entrada = cargar_entrada()
    entrada["momentos"].append({
        "hora":     datetime.now().strftime("%H:%M"),
        "tipo":     "evento_especial",
        "titulo":   titulo,
        "contenido": descripcion[:300],
    })
    guardar_entrada(entrada)


# ==============================================================================
# Leer el diario
# ==============================================================================

def obtener_entradas_recientes(dias: int = 7) -> List[Dict[str, Any]]:
    """Obtiene las entradas del diario de los últimos N días."""
    from datetime import timedelta
    entradas = []
    hoy = date.today()
    for i in range(dias):
        fecha = (hoy - timedelta(days=i)).isoformat()
        ruta  = _ruta_entrada(fecha)
        if ruta.exists():
            try:
                with open(ruta, "r", encoding="utf-8") as f:
                    entradas.append(json.load(f))
            except Exception:
                pass
    return entradas


def generar_resumen_dia(fecha: Optional[str] = None) -> str:
    """
    Genera un resumen legible del día en formato de diario.
    Ejemplo de salida:
        2026-03-13
        Alex estuvo contento — habló sobre videojuegos
        Daniel trabajó en el servidor y resolvió el problema de Evolution API
    """
    entrada  = cargar_entrada(fecha)
    fecha_str = entrada.get("fecha", "hoy")
    momentos = entrada.get("momentos", [])

    if not momentos:
        return f"{fecha_str}\n(Sin registros este día)"

    lineas = [fecha_str]
    for m in momentos:
        nombre = m.get("nombre", "Alguien")
        tipo   = m.get("tipo", "conversacion")
        contenido = m.get("contenido", "")
        estado = m.get("estado_emocional", "neutro")

        if tipo == "logro":
            lineas.append(f"{nombre} logró: {contenido}")
        elif tipo == "problema":
            lineas.append(f"{nombre} tuvo dificultades: {contenido}")
        elif tipo == "evento_especial":
            lineas.append(f"✦ {m.get('titulo', '')}: {contenido}")
        elif estado != "neutro":
            lineas.append(f"{nombre} estuvo {estado} — {contenido[:80]}")

    logros    = entrada.get("logros", [])
    problemas = entrada.get("problemas", [])

    if logros:
        lineas.append(f"Logros del día: {', '.join(l['logro'][:40] for l in logros)}")
    if problemas:
        lineas.append(f"Dificultades: {', '.join(p['problema'][:40] for p in problemas)}")

    return "\n".join(lineas)


def construir_contexto_diario(dias: int = 3) -> str:
    """
    Genera un bloque de contexto con el diario reciente
    para incluir en el system prompt de Gemini.
    """
    entradas = obtener_entradas_recientes(dias)
    if not entradas:
        return ""

    lineas = ["DIARIO FAMILIAR RECIENTE:"]
    for entrada in entradas:
        resumen = generar_resumen_dia(entrada.get("fecha"))
        for linea in resumen.split("\n")[:4]:  # Máx 4 líneas por día
            lineas.append(f"  {linea}")

    return "\n".join(lineas)
