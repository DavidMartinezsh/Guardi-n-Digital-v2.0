# ==============================================================================
# GUARDIÁN DIGITAL v2.0 - memoria.py
# Gestión de memoria conversacional: corto plazo (DB) y largo plazo (RAG/Chroma).
# ==============================================================================

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

import pymysql

from config import (
    MEMORIA_VENTANA_CORTO,
    MEMORIA_VENTANA_LARGO,
    RAG_ENABLED,
    RAG_COLLECTION_NAME,
    RAG_TOP_K,
    RAG_EMBED_MODEL,
    CHROMA_PERSIST_DIR,
    GEMINI_API_KEY,
)
from db import get_connection

logger = logging.getLogger(__name__)


# ==============================================================================
# MEMORIA DE CORTO PLAZO  (MySQL)
# ==============================================================================

def guardar_mensaje(usuario_id: int, rol: str, contenido: str) -> None:
    """
    Persiste un turno de conversación.
    rol: 'user' | 'assistant'
    """
    sql = """
        INSERT INTO MemoriaConversacion (usuario_id, rol, contenido, fecha)
        VALUES (%s, %s, %s, NOW())
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (usuario_id, rol, contenido))
            conn.commit()

    # Si RAG activo, también indexar en vector store
    if RAG_ENABLED:
        _indexar_en_rag(usuario_id, rol, contenido)


def obtener_contexto_reciente(
    usuario_id: int,
    ventana: int = MEMORIA_VENTANA_CORTO,
) -> List[Dict[str, str]]:
    """
    Retorna los últimos `ventana` mensajes en formato Gemini:
    [{"role": "user"|"model", "parts": [{"text": "..."}]}]
    """
    sql = """
        SELECT rol, contenido FROM MemoriaConversacion
        WHERE usuario_id = %s
        ORDER BY fecha DESC
        LIMIT %s
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (usuario_id, ventana))
            rows = cur.fetchall()

    # Revertir para orden cronológico
    rows = list(reversed(rows))
    historial = []
    for row in rows:
        # Gemini usa "model" en lugar de "assistant"
        gemini_rol = "model" if row["rol"] == "assistant" else "user"
        historial.append({
            "role": gemini_rol,
            "parts": [{"text": row["contenido"]}],
        })
    return historial


def obtener_mensajes_raw(
    usuario_id: int,
    ventana: int = MEMORIA_VENTANA_LARGO,
) -> List[Dict[str, Any]]:
    """
    Retorna mensajes en formato raw (dict con claves: rol, contenido, fecha).
    Usado por biometria.py para construir el perfil histórico.
    """
    sql = """
        SELECT rol, contenido, fecha FROM MemoriaConversacion
        WHERE usuario_id = %s AND rol = 'user'
        ORDER BY fecha DESC
        LIMIT %s
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (usuario_id, ventana))
            return cur.fetchall()


def contar_mensajes(usuario_id: int) -> int:
    sql = "SELECT COUNT(*) AS total FROM MemoriaConversacion WHERE usuario_id = %s"
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (usuario_id,))
            row = cur.fetchone()
            return row["total"] if row else 0


def limpiar_memoria_antigua(usuario_id: int, mantener: int = 200) -> None:
    """Elimina mensajes más viejos conservando los últimos `mantener`."""
    sql = """
        DELETE FROM MemoriaConversacion
        WHERE usuario_id = %s
          AND id NOT IN (
              SELECT id FROM (
                  SELECT id FROM MemoriaConversacion
                  WHERE usuario_id = %s
                  ORDER BY fecha DESC
                  LIMIT %s
              ) AS sub
          )
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (usuario_id, usuario_id, mantener))
            conn.commit()


# ==============================================================================
# MEMORIA DE LARGO PLAZO  (RAG con ChromaDB + Google Embeddings)
# ==============================================================================

_chroma_client = None
_chroma_collection = None


def _init_rag():
    """Inicializa ChromaDB y la colección de vectores (lazy)."""
    global _chroma_client, _chroma_collection
    if _chroma_client is not None:
        return

    try:
        import chromadb
        import google.generativeai as genai

        genai.configure(api_key=GEMINI_API_KEY)

        _chroma_client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
        _chroma_collection = _chroma_client.get_or_create_collection(
            name=RAG_COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info("[RAG] ChromaDB inicializado correctamente.")
    except ImportError as e:
        logger.warning(f"[RAG] Dependencias no instaladas: {e}. RAG desactivado.")
    except Exception as e:
        logger.error(f"[RAG] Error al inicializar: {e}")


def _obtener_embedding(texto: str) -> Optional[List[float]]:
    """Genera un embedding usando Google Generative AI."""
    try:
        import google.generativeai as genai
        resultado = genai.embed_content(
            model=RAG_EMBED_MODEL,
            content=texto,
            task_type="retrieval_document",
        )
        return resultado["embedding"]
    except Exception as e:
        logger.error(f"[RAG] Error generando embedding: {e}")
        return None


def _indexar_en_rag(usuario_id: int, rol: str, contenido: str) -> None:
    """Indexa un mensaje en ChromaDB para búsqueda semántica futura."""
    if not RAG_ENABLED:
        return
    _init_rag()
    if _chroma_collection is None:
        return

    embedding = _obtener_embedding(contenido)
    if embedding is None:
        return

    doc_id = f"{usuario_id}_{datetime.utcnow().timestamp()}"
    try:
        _chroma_collection.add(
            ids=[doc_id],
            embeddings=[embedding],
            documents=[contenido],
            metadatas=[{
                "usuario_id": str(usuario_id),
                "rol": rol,
                "timestamp": datetime.utcnow().isoformat(),
            }],
        )
    except Exception as e:
        logger.error(f"[RAG] Error indexando: {e}")


def buscar_memoria_semantica(
    usuario_id: int,
    query: str,
    top_k: int = RAG_TOP_K,
) -> List[str]:
    """
    Busca los fragmentos más relevantes del historial a largo plazo.
    Retorna lista de textos ordenados por relevancia.
    """
    if not RAG_ENABLED:
        return []
    _init_rag()
    if _chroma_collection is None:
        return []

    embedding = _obtener_embedding(query)
    if embedding is None:
        return []

    try:
        resultados = _chroma_collection.query(
            query_embeddings=[embedding],
            n_results=top_k,
            where={"usuario_id": str(usuario_id)},
        )
        documentos = resultados.get("documents", [[]])[0]
        return documentos
    except Exception as e:
        logger.error(f"[RAG] Error en búsqueda semántica: {e}")
        return []


def construir_contexto_aumentado(usuario_id: int, mensaje_actual: str) -> str:
    """
    Combina memoria semántica con el mensaje actual para enriquecer el prompt.
    Retorna un bloque de texto para inyectar en el System Prompt de Gemini.
    """
    fragmentos = buscar_memoria_semantica(usuario_id, mensaje_actual)
    if not fragmentos:
        return ""

    bloque = "\n\n--- Contexto relevante de conversaciones anteriores ---\n"
    for i, frag in enumerate(fragmentos, 1):
        bloque += f"{i}. {frag[:300]}\n"
    bloque += "--- Fin del contexto histórico ---\n"
    return bloque
