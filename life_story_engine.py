# ==============================================================================
# GUARDIÁN DIGITAL v4.0 - life_story_engine.py
# Motor de historia familiar — construye capítulos de vida.
#
# Genera automáticamente una narrativa de la historia familiar
# a partir del diario, los perfiles y la memoria acumulada.
# ==============================================================================

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, date
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

STORY_DIR = Path(os.getenv("STORY_DIR", "/var/guardian/story"))
STORY_DIR.mkdir(parents=True, exist_ok=True)

STORY_FILE = STORY_DIR / "historia_familiar.json"


# ==============================================================================
# Estructura de la historia
# ==============================================================================

def _historia_vacia() -> Dict[str, Any]:
    return {
        "version": "4.0",
        "titulo":  "Historia de Nuestra Familia",
        "autor":   "",
        "capitulos": [],
        "hitos":   [],
        "creado":  datetime.now().isoformat(),
        "actualizado": datetime.now().isoformat(),
    }


def _capitulo_vacio(numero: int, titulo: str) -> Dict[str, Any]:
    return {
        "numero":   numero,
        "titulo":   titulo,
        "periodo":  "",
        "entradas": [],
        "resumen":  "",
        "personas": [],
        "creado":   datetime.now().isoformat(),
    }


# ==============================================================================
# Cargar y guardar historia
# ==============================================================================

def cargar_historia() -> Dict[str, Any]:
    if STORY_FILE.exists():
        try:
            with open(STORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"[STORY] Error cargando historia: {e}")
    historia = _historia_vacia()
    from personality_engine import obtener_nombre_bot
    historia["autor"] = obtener_nombre_bot()
    return historia


def guardar_historia(historia: Dict[str, Any]) -> None:
    historia["actualizado"] = datetime.now().isoformat()
    try:
        with open(STORY_FILE, "w", encoding="utf-8") as f:
            json.dump(historia, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"[STORY] Error guardando historia: {e}")


# ==============================================================================
# Gestión de capítulos
# ==============================================================================

def crear_capitulo(titulo: str, periodo: str = "") -> int:
    """Crea un nuevo capítulo. Retorna el número de capítulo."""
    historia = cargar_historia()
    numero   = len(historia["capitulos"]) + 1
    capitulo = _capitulo_vacio(numero, titulo)
    capitulo["periodo"] = periodo
    historia["capitulos"].append(capitulo)
    guardar_historia(historia)
    logger.info(f"[STORY] Capítulo {numero} creado: {titulo}")
    return numero


def agregar_entrada_capitulo(
    numero_capitulo: int,
    fecha:           str,
    contenido:       str,
    autor:           str = "",
    tipo:            str = "momento",
) -> None:
    """Agrega una entrada a un capítulo existente."""
    historia = cargar_historia()
    for cap in historia["capitulos"]:
        if cap["numero"] == numero_capitulo:
            entrada = {
                "fecha":    fecha,
                "autor":    autor,
                "tipo":     tipo,
                "contenido": contenido[:1000],
            }
            cap["entradas"].append(entrada)
            if autor and autor not in cap["personas"]:
                cap["personas"].append(autor)
            guardar_historia(historia)
            return
    logger.warning(f"[STORY] Capítulo {numero_capitulo} no encontrado")


def agregar_hito(titulo: str, fecha: str, descripcion: str = "") -> None:
    """Agrega un hito importante a la historia familiar."""
    historia = cargar_historia()
    historia["hitos"].append({
        "titulo":      titulo,
        "fecha":       fecha,
        "descripcion": descripcion[:500],
    })
    guardar_historia(historia)
    logger.info(f"[STORY] Hito agregado: {titulo}")


# ==============================================================================
# Generación automática desde el diario
# ==============================================================================

def generar_capitulo_automatico(mes: Optional[str] = None) -> Optional[int]:
    """
    Genera automáticamente un capítulo del mes actual
    a partir de las entradas del diario.
    Retorna el número de capítulo creado o None si no hay datos.
    """
    from diary_engine import obtener_entradas_recientes, generar_resumen_dia

    if mes is None:
        ahora = datetime.now()
        mes   = ahora.strftime("%Y-%m")
        titulo_cap = ahora.strftime("Capítulo: %B %Y")
    else:
        titulo_cap = f"Capítulo: {mes}"

    # Verificar si ya existe un capítulo para este mes
    historia = cargar_historia()
    for cap in historia["capitulos"]:
        if mes in cap.get("titulo", ""):
            logger.debug(f"[STORY] Capítulo para {mes} ya existe")
            return cap["numero"]

    entradas = obtener_entradas_recientes(31)
    entradas_mes = [e for e in entradas if e.get("fecha", "").startswith(mes)]

    if not entradas_mes:
        return None

    numero = crear_capitulo(titulo_cap, periodo=mes)

    for entrada in entradas_mes:
        fecha   = entrada.get("fecha", "")
        momentos = entrada.get("momentos", [])
        for m in momentos:
            if m.get("tipo") in ("logro", "problema", "evento_especial"):
                agregar_entrada_capitulo(
                    numero_capitulo=numero,
                    fecha=fecha,
                    contenido=m.get("contenido", ""),
                    autor=m.get("nombre", ""),
                    tipo=m.get("tipo", "momento"),
                )

    logger.info(f"[STORY] Capítulo {numero} generado automáticamente para {mes}")
    return numero


# ==============================================================================
# Renderizado de la historia
# ==============================================================================

def renderizar_historia_texto(max_capitulos: int = 5) -> str:
    """
    Renderiza la historia familiar como texto narrativo.
    """
    historia  = cargar_historia()
    titulo    = historia.get("titulo", "Historia Familiar")
    autor     = historia.get("autor", "")
    capitulos = historia.get("capitulos", [])
    hitos     = historia.get("hitos", [])

    lineas = [
        f"═══════════════════════════════════",
        f"  {titulo}",
        f"  Por {autor}" if autor else "",
        f"═══════════════════════════════════",
        "",
    ]

    if hitos:
        lineas.append("HITOS IMPORTANTES:")
        for h in hitos[-5:]:
            lineas.append(f"  ✦ {h['fecha']} — {h['titulo']}")
            if h.get("descripcion"):
                lineas.append(f"    {h['descripcion'][:100]}")
        lineas.append("")

    for cap in capitulos[-max_capitulos:]:
        lineas.append(f"--- {cap['titulo']} ---")
        if cap.get("periodo"):
            lineas.append(f"Período: {cap['periodo']}")
        if cap.get("personas"):
            lineas.append(f"Personas: {', '.join(cap['personas'])}")
        if cap.get("resumen"):
            lineas.append(cap["resumen"])
        for entrada in cap.get("entradas", [])[-5:]:
            lineas.append(f"  [{entrada['fecha']}] {entrada.get('autor','')}: {entrada['contenido'][:120]}")
        lineas.append("")

    return "\n".join(l for l in lineas if l is not None)


def obtener_resumen_historia() -> str:
    """Resumen breve de la historia para incluir en el contexto de Gemini."""
    historia  = cargar_historia()
    capitulos = historia.get("capitulos", [])
    hitos     = historia.get("hitos", [])

    if not capitulos and not hitos:
        return ""

    lineas = ["HISTORIA FAMILIAR (resumen):"]
    if hitos:
        for h in hitos[-3:]:
            lineas.append(f"  ✦ {h['titulo']} ({h['fecha']})")
    if capitulos:
        ultimo = capitulos[-1]
        lineas.append(f"  Último capítulo: {ultimo['titulo']}")
        entradas = ultimo.get("entradas", [])
        if entradas:
            ult_entrada = entradas[-1]
            lineas.append(f"    {ult_entrada.get('contenido', '')[:100]}")

    return "\n".join(lineas)
