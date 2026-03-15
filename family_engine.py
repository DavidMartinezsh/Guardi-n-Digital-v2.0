# ==============================================================================
# GUARDIÁN DIGITAL v4.0 - family_engine.py
# Motor de perfiles familiares.
#
# Cada persona tiene un perfil completo con:
#   - Datos básicos (nombre, edad, relación)
#   - Intereses y proyectos actuales
#   - Problemas conocidos
#   - Objetivos
#   - Estado emocional reciente
#   - Cómo comunicarse con ella
# ==============================================================================

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Directorio donde se guardan los perfiles
FAMILY_DIR = Path(os.getenv("FAMILY_PROFILES_DIR", "/var/guardian/family"))
FAMILY_DIR.mkdir(parents=True, exist_ok=True)

# Perfil vacío base
_PERFIL_BASE = {
    "version": "4.0",
    "telefono": "",
    "nombre": "",
    "apodo": "",
    "relacion": "desconocido",
    "edad": None,
    "intereses": [],
    "proyectos_actuales": [],
    "problemas": [],
    "objetivos": [],
    "miedos": [],
    "logros": [],
    "estado_emocional": "neutro",
    "ultima_conversacion": "",
    "resumen_relacion": "",
    "como_comunicarse": "",
    "fechas_importantes": {},
    "notas": [],
    "actualizado": "",
}


# ==============================================================================
# Cargar y guardar perfiles
# ==============================================================================

def _ruta_perfil(telefono: str) -> Path:
    return FAMILY_DIR / f"{telefono.replace('+', '')}.json"


def cargar_perfil(telefono: str) -> Dict[str, Any]:
    """Carga el perfil familiar de un número. Crea uno vacío si no existe."""
    ruta = _ruta_perfil(telefono)
    if ruta.exists():
        try:
            with open(ruta, "r", encoding="utf-8") as f:
                perfil = json.load(f)
            # Rellenar claves faltantes con base
            for k, v in _PERFIL_BASE.items():
                if k not in perfil:
                    perfil[k] = v
            return perfil
        except Exception as e:
            logger.error(f"[FAMILY] Error cargando perfil {telefono}: {e}")

    # Crear perfil vacío
    perfil = dict(_PERFIL_BASE)
    perfil["telefono"] = telefono
    perfil["actualizado"] = datetime.now().isoformat()
    return perfil


def guardar_perfil(perfil: Dict[str, Any]) -> None:
    """Guarda el perfil familiar a disco."""
    telefono = perfil.get("telefono", "")
    if not telefono:
        return
    perfil["actualizado"] = datetime.now().isoformat()
    ruta = _ruta_perfil(telefono)
    try:
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(perfil, f, ensure_ascii=False, indent=2)
        logger.debug(f"[FAMILY] Perfil guardado: {telefono}")
    except Exception as e:
        logger.error(f"[FAMILY] Error guardando perfil {telefono}: {e}")


def listar_familia() -> List[Dict[str, Any]]:
    """Lista todos los perfiles familiares guardados."""
    perfiles = []
    for ruta in FAMILY_DIR.glob("*.json"):
        try:
            with open(ruta, "r", encoding="utf-8") as f:
                p = json.load(f)
            perfiles.append({
                "telefono":        p.get("telefono", ""),
                "nombre":          p.get("nombre", ""),
                "relacion":        p.get("relacion", ""),
                "edad":            p.get("edad"),
                "estado_emocional": p.get("estado_emocional", ""),
                "actualizado":     p.get("actualizado", ""),
            })
        except Exception:
            pass
    return sorted(perfiles, key=lambda x: x.get("nombre", ""))


# ==============================================================================
# Actualizar campos específicos
# ==============================================================================

def actualizar_estado_emocional(telefono: str, estado: str) -> None:
    """Actualiza el estado emocional registrado de un familiar."""
    perfil = cargar_perfil(telefono)
    perfil["estado_emocional"] = estado
    guardar_perfil(perfil)


def agregar_problema(telefono: str, problema: str) -> None:
    """Registra un problema o preocupación de un familiar."""
    perfil = cargar_perfil(telefono)
    if problema not in perfil["problemas"]:
        perfil["problemas"].append(problema)
        if len(perfil["problemas"]) > 20:
            perfil["problemas"] = perfil["problemas"][-20:]
    guardar_perfil(perfil)


def agregar_logro(telefono: str, logro: str) -> None:
    """Registra un logro o momento positivo de un familiar."""
    perfil = cargar_perfil(telefono)
    entrada = {"logro": logro, "fecha": datetime.now().strftime("%Y-%m-%d")}
    perfil["logros"].append(entrada)
    guardar_perfil(perfil)


def agregar_nota(telefono: str, nota: str) -> None:
    """Agrega una nota libre al perfil del familiar."""
    perfil = cargar_perfil(telefono)
    entrada = {"nota": nota, "fecha": datetime.now().strftime("%Y-%m-%d")}
    perfil["notas"].append(entrada)
    if len(perfil["notas"]) > 50:
        perfil["notas"] = perfil["notas"][-50:]
    guardar_perfil(perfil)


def registrar_conversacion(telefono: str, resumen: str) -> None:
    """Registra el resumen de la última conversación."""
    perfil = cargar_perfil(telefono)
    perfil["ultima_conversacion"] = resumen[:500]
    guardar_perfil(perfil)


# ==============================================================================
# Construir contexto familiar para Gemini
# ==============================================================================

def construir_contexto_familiar(telefono: str) -> str:
    """
    Genera un bloque de texto con el perfil familiar
    para incluir en el system prompt de Gemini.
    """
    perfil = cargar_perfil(telefono)
    if not perfil.get("nombre"):
        return ""

    lineas = [f"PERFIL FAMILIAR — {perfil['nombre']}:"]

    if perfil.get("edad"):
        lineas.append(f"  Edad: {perfil['edad']} años")
    if perfil.get("relacion"):
        lineas.append(f"  Relación: {perfil['relacion']}")
    if perfil.get("estado_emocional") and perfil["estado_emocional"] != "neutro":
        lineas.append(f"  Estado emocional reciente: {perfil['estado_emocional']}")
    if perfil.get("intereses"):
        lineas.append(f"  Intereses: {', '.join(perfil['intereses'][:5])}")
    if perfil.get("proyectos_actuales"):
        lineas.append(f"  Proyectos actuales: {', '.join(perfil['proyectos_actuales'][:3])}")
    if perfil.get("problemas"):
        lineas.append(f"  Situaciones actuales: {', '.join(perfil['problemas'][-3:])}")
    if perfil.get("como_comunicarse"):
        lineas.append(f"  Cómo comunicarse: {perfil['como_comunicarse']}")
    if perfil.get("ultima_conversacion"):
        lineas.append(f"  Última conversación: {perfil['ultima_conversacion']}")

    return "\n".join(lineas)


def obtener_perfil_resumido(telefono: str) -> str:
    """Resumen de una línea del perfil para logs y debug."""
    p = cargar_perfil(telefono)
    nombre = p.get("nombre", "?")
    relacion = p.get("relacion", "?")
    estado = p.get("estado_emocional", "?")
    return f"{nombre} ({relacion}) — estado: {estado}"
