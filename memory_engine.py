# ==============================================================================
# GUARDIÁN DIGITAL v4.0 - memory_engine.py
# Motor de memoria persistente de largo plazo.
#
# Almacena y recupera:
#   - Perfil del usuario (preferencias, rutinas, estado emocional)
#   - Hechos importantes mencionados en conversaciones
#   - Eventos y fechas significativas
#   - Contexto de última sesión
#
# Backends:
#   - ChromaDB para búsqueda semántica (si RAG_ENABLED=true)
#   - MySQL para hechos estructurados
#   - JSON para perfil rápido en caché
# ==============================================================================

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, date
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    from config import GEMINI_API_KEY, GEMINI_MODEL, RAG_ENABLED
except ImportError:
    RAG_ENABLED = False

try:
    from db import get_connection
    DB_AVAILABLE = True
except ImportError:
    DB_AVAILABLE = False

# ── Tablas DDL (ejecutar una vez) ────────────────────────────────────────────

MEMORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS Memorias (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    usuario_id   INT NOT NULL,
    tipo         VARCHAR(50) NOT NULL,
    clave        VARCHAR(200) NOT NULL,
    valor        TEXT NOT NULL,
    importancia  TINYINT DEFAULT 3,
    fecha        DATETIME DEFAULT CURRENT_TIMESTAMP,
    ultima_vez   DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    activa       TINYINT DEFAULT 1,
    KEY idx_mem_usuario (usuario_id),
    KEY idx_mem_tipo    (tipo),
    KEY idx_mem_clave   (clave)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS EventosImportantes (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    usuario_id   INT NOT NULL,
    titulo       VARCHAR(200) NOT NULL,
    descripcion  TEXT,
    fecha_evento DATE,
    recurrente   TINYINT DEFAULT 0,
    tipo         VARCHAR(50) DEFAULT 'personal',
    fecha_creado DATETIME DEFAULT CURRENT_TIMESTAMP,
    KEY idx_ev_usuario (usuario_id),
    KEY idx_ev_fecha   (fecha_evento)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS ContextoSesion (
    usuario_id      INT PRIMARY KEY,
    ultimo_tema     VARCHAR(200),
    estado_emocional VARCHAR(50),
    resumen_sesion  TEXT,
    fecha_sesion    DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


def inicializar_memoria() -> None:
    if not DB_AVAILABLE:
        return
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                for stmt in MEMORY_SCHEMA.strip().split(";"):
                    s = stmt.strip()
                    if s:
                        cur.execute(s)
            conn.commit()
    except Exception as e:
        logger.warning(f"[MEMORY] Schema error: {e}")


# ==============================================================================
# Guardar hechos
# ==============================================================================

def guardar_hecho(
    usuario_id: int,
    tipo: str,
    clave: str,
    valor: str,
    importancia: int = 3,
) -> None:
    """
    Guarda un hecho sobre el usuario en la memoria de largo plazo.

    Tipos predefinidos:
        'preferencia'  → "prefiere WhatsApp a llamadas"
        'rutina'       → "duerme a las 23:00"
        'proyecto'     → "está trabajando en el servidor de juegos"
        'problema'     → "Alex tiene dificultades en matemáticas"
        'relacion'     → "mamá se llama María"
        'fecha'        → "cumpleaños el 15 de agosto"
        'objetivo'     → "quiere aprender inglés"
        'estado'       → "pasó por un momento difícil en marzo"
    """
    if not DB_AVAILABLE:
        return
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO Memorias (usuario_id, tipo, clave, valor, importancia)
                    VALUES (%s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        valor = VALUES(valor),
                        importancia = VALUES(importancia),
                        ultima_vez = NOW()
                """, (usuario_id, tipo, clave[:200], valor[:2000], importancia))
            conn.commit()
        logger.debug(f"[MEMORY] Hecho guardado: user={usuario_id} tipo={tipo} clave={clave[:40]}")
    except Exception as e:
        logger.error(f"[MEMORY] Error guardando hecho: {e}")


def guardar_evento(
    usuario_id: int,
    titulo: str,
    fecha_evento: Optional[date] = None,
    descripcion: str = "",
    recurrente: bool = False,
    tipo: str = "personal",
) -> None:
    """Guarda un evento o fecha importante."""
    if not DB_AVAILABLE:
        return
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO EventosImportantes
                        (usuario_id, titulo, descripcion, fecha_evento, recurrente, tipo)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (usuario_id, titulo[:200], descripcion, fecha_evento,
                      int(recurrente), tipo))
            conn.commit()
    except Exception as e:
        logger.error(f"[MEMORY] Error guardando evento: {e}")


# ==============================================================================
# Recuperar memoria
# ==============================================================================

def obtener_hechos(
    usuario_id: int,
    tipo: Optional[str] = None,
    limite: int = 20,
) -> List[Dict[str, Any]]:
    """Recupera hechos guardados del usuario."""
    if not DB_AVAILABLE:
        return []
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                if tipo:
                    cur.execute("""
                        SELECT tipo, clave, valor, importancia, ultima_vez
                        FROM Memorias
                        WHERE usuario_id = %s AND tipo = %s AND activa = 1
                        ORDER BY importancia DESC, ultima_vez DESC
                        LIMIT %s
                    """, (usuario_id, tipo, limite))
                else:
                    cur.execute("""
                        SELECT tipo, clave, valor, importancia, ultima_vez
                        FROM Memorias
                        WHERE usuario_id = %s AND activa = 1
                        ORDER BY importancia DESC, ultima_vez DESC
                        LIMIT %s
                    """, (usuario_id, limite))
                rows = cur.fetchall()
                return [
                    {"tipo": r[0], "clave": r[1], "valor": r[2],
                     "importancia": r[3], "ultima_vez": str(r[4])}
                    for r in rows
                ]
    except Exception as e:
        logger.error(f"[MEMORY] Error obteniendo hechos: {e}")
        return []


def obtener_eventos_proximos(usuario_id: int, dias: int = 30) -> List[Dict]:
    """Obtiene eventos importantes en los próximos N días."""
    if not DB_AVAILABLE:
        return []
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT titulo, descripcion, fecha_evento, recurrente, tipo
                    FROM EventosImportantes
                    WHERE usuario_id = %s
                      AND (
                        (fecha_evento BETWEEN CURDATE() AND DATE_ADD(CURDATE(), INTERVAL %s DAY))
                        OR recurrente = 1
                      )
                    ORDER BY fecha_evento ASC
                    LIMIT 10
                """, (usuario_id, dias))
                rows = cur.fetchall()
                return [
                    {"titulo": r[0], "descripcion": r[1], "fecha": str(r[2]),
                     "recurrente": bool(r[3]), "tipo": r[4]}
                    for r in rows
                ]
    except Exception as e:
        logger.error(f"[MEMORY] Error obteniendo eventos: {e}")
        return []


def obtener_contexto_sesion(usuario_id: int) -> Dict[str, Any]:
    """Recupera el contexto de la última sesión del usuario."""
    if not DB_AVAILABLE:
        return {}
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT ultimo_tema, estado_emocional, resumen_sesion, fecha_sesion
                    FROM ContextoSesion WHERE usuario_id = %s
                """, (usuario_id,))
                row = cur.fetchone()
                if row:
                    return {
                        "ultimo_tema":      row[0],
                        "estado_emocional": row[1],
                        "resumen_sesion":   row[2],
                        "fecha_sesion":     str(row[3]),
                    }
    except Exception as e:
        logger.error(f"[MEMORY] Error obteniendo contexto sesión: {e}")
    return {}


def actualizar_contexto_sesion(
    usuario_id: int,
    tema: str = "",
    estado_emocional: str = "neutro",
    resumen: str = "",
) -> None:
    """Actualiza el contexto de sesión al final de cada interacción."""
    if not DB_AVAILABLE:
        return
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO ContextoSesion
                        (usuario_id, ultimo_tema, estado_emocional, resumen_sesion)
                    VALUES (%s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        ultimo_tema      = VALUES(ultimo_tema),
                        estado_emocional = VALUES(estado_emocional),
                        resumen_sesion   = VALUES(resumen_sesion),
                        fecha_sesion     = NOW()
                """, (usuario_id, tema[:200], estado_emocional[:50], resumen[:1000]))
            conn.commit()
    except Exception as e:
        logger.error(f"[MEMORY] Error actualizando contexto sesión: {e}")


# ==============================================================================
# Extractor automático de hechos desde mensajes
# ==============================================================================

# Patrones para extraer hechos automáticamente del texto
_PATRONES_HECHOS = [
    # Fechas y cumpleaños
    (r"(mi cumpleaños|mi cumple)\s+(?:es\s+)?(?:el\s+)?(\d{1,2}(?:\s+de\s+\w+)?)",
     "fecha", "cumpleaños_usuario", 5),
    (r"(\w+)\s+cumple\s+(?:años\s+)?(?:el\s+)?(\d{1,2}(?:\s+de\s+\w+)?)",
     "fecha", "cumpleaños_{0}", 4),
    # Nombres de familiares
    (r"mi\s+(mamá|mamá|madre|papá|padre|hermano|hermana|hijo|hija|pareja|novia|novio)\s+se\s+llama\s+(\w+)",
     "relacion", "nombre_{0}", 5),
    # Proyectos
    (r"(?:estoy\s+trabajando\s+en|mi\s+proyecto\s+es)\s+(.+?)(?:\.|$)",
     "proyecto", "proyecto_actual", 3),
    # Problemas
    (r"(?:tengo\s+un\s+problema\s+con|me\s+cuesta\s+mucho)\s+(.+?)(?:\.|$)",
     "problema", "problema_reciente", 3),
    # Preferencias
    (r"(?:me\s+gusta\s+mucho|me\s+encanta)\s+(.+?)(?:\.|$)",
     "preferencia", "gusta_{1}", 2),
]


def extraer_hechos_automatico(usuario_id: int, texto: str) -> List[Dict]:
    """
    Analiza el texto y extrae hechos para guardar automáticamente.
    Retorna lista de hechos extraídos (para logging/debug).
    """
    texto_lower = texto.lower()
    extraidos = []

    for patron, tipo, clave_tmpl, importancia in _PATRONES_HECHOS:
        match = re.search(patron, texto_lower)
        if match:
            grupos = match.groups()
            clave = clave_tmpl.format(*grupos) if "{" in clave_tmpl else clave_tmpl
            valor = " ".join(grupos).strip()
            guardar_hecho(usuario_id, tipo, clave[:200], valor[:500], importancia)
            extraidos.append({"tipo": tipo, "clave": clave, "valor": valor})

    return extraidos


# ==============================================================================
# Construir contexto de memoria para Gemini
# ==============================================================================

def construir_contexto_memoria(usuario_id: int) -> str:
    """
    Genera un bloque de contexto con toda la memoria del usuario
    para incluir en el system prompt de Gemini.
    """
    hechos   = obtener_hechos(usuario_id, limite=15)
    eventos  = obtener_eventos_proximos(usuario_id, dias=30)
    sesion   = obtener_contexto_sesion(usuario_id)
    contexto = []

    if hechos:
        contexto.append("MEMORIA DE LARGO PLAZO:")
        for h in hechos:
            contexto.append(f"  [{h['tipo']}] {h['clave']}: {h['valor']}")

    if eventos:
        contexto.append("\nEVENTOS PRÓXIMOS:")
        for e in eventos:
            contexto.append(f"  {e['fecha']} — {e['titulo']}")

    if sesion:
        contexto.append(f"\nÚLTIMA SESIÓN:")
        if sesion.get("ultimo_tema"):
            contexto.append(f"  Tema: {sesion['ultimo_tema']}")
        if sesion.get("estado_emocional"):
            contexto.append(f"  Estado emocional previo: {sesion['estado_emocional']}")
        if sesion.get("resumen_sesion"):
            contexto.append(f"  Resumen: {sesion['resumen_sesion']}")

    return "\n".join(contexto) if contexto else ""
