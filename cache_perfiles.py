# ==============================================================================
# GUARDIÁN DIGITAL v2.0 - cache_perfiles.py
# Caché de perfiles lingüísticos con dos backends:
#   - Memoria (default, sin dependencias extra)
#   - Redis   (opcional, para persistencia entre reinicios y multi-proceso)
#
# La selección del backend es automática: si Redis está disponible y
# REDIS_ENABLED=true en el .env, se usa Redis. Si no, cae a memoria.
# ==============================================================================

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# ==============================================================================
# Configuración
# ==============================================================================

try:
    from config import REDIS_URL, REDIS_ENABLED, CACHE_TTL_SEGUNDOS
except ImportError:
    REDIS_URL            = "redis://localhost:6379/0"
    REDIS_ENABLED        = False
    CACHE_TTL_SEGUNDOS   = 3600   # 1 hora de TTL por defecto


# ==============================================================================
# Backend en memoria (siempre disponible)
# ==============================================================================

class _CacheMemoria:
    """
    Caché en memoria con TTL.
    Thread-safe para uso con asyncio (no comparte estado entre procesos).
    """

    def __init__(self, ttl: int = CACHE_TTL_SEGUNDOS):
        self._ttl    = ttl
        self._store: Dict[str, Dict[str, Any]] = {}  # {clave: {"v": valor, "exp": timestamp}}
        self._hits   = 0
        self._misses = 0

    def get(self, clave: str) -> Optional[Any]:
        entrada = self._store.get(clave)
        if entrada is None:
            self._misses += 1
            return None
        if time.monotonic() > entrada["exp"]:
            del self._store[clave]
            self._misses += 1
            return None
        self._hits += 1
        return entrada["v"]

    def set(self, clave: str, valor: Any, ttl: Optional[int] = None) -> None:
        exp = time.monotonic() + (ttl or self._ttl)
        self._store[clave] = {"v": valor, "exp": exp}

    def delete(self, clave: str) -> None:
        self._store.pop(clave, None)

    def flush(self) -> None:
        """Elimina todas las entradas (útil en tests)."""
        self._store.clear()

    def purge_expired(self) -> int:
        """Elimina entradas caducadas. Llamar periódicamente."""
        ahora = time.monotonic()
        caducadas = [k for k, v in self._store.items() if ahora > v["exp"]]
        for k in caducadas:
            del self._store[k]
        return len(caducadas)

    def stats(self) -> Dict[str, Any]:
        return {
            "backend":  "memoria",
            "entradas": len(self._store),
            "hits":     self._hits,
            "misses":   self._misses,
            "hit_rate": round(
                self._hits / max(self._hits + self._misses, 1) * 100, 1
            ),
        }


# ==============================================================================
# Backend Redis (opcional)
# ==============================================================================

class _CacheRedis:
    """
    Caché Redis con serialización JSON.
    Requiere: pip install redis
    """

    def __init__(self, url: str, ttl: int = CACHE_TTL_SEGUNDOS):
        import redis
        self._ttl    = ttl
        self._hits   = 0
        self._misses = 0
        self._r      = redis.from_url(url, decode_responses=True, socket_timeout=2)
        self._r.ping()   # Falla rápido si Redis no está disponible
        logger.info(f"[CACHE] Redis conectado en {url}")

    def _k(self, clave: str) -> str:
        return f"guardian:perfil:{clave}"

    def get(self, clave: str) -> Optional[Any]:
        try:
            raw = self._r.get(self._k(clave))
            if raw is None:
                self._misses += 1
                return None
            self._hits += 1
            return json.loads(raw)
        except Exception as e:
            logger.warning(f"[CACHE] Redis GET error: {e}")
            self._misses += 1
            return None

    def set(self, clave: str, valor: Any, ttl: Optional[int] = None) -> None:
        try:
            self._r.setex(self._k(clave), ttl or self._ttl, json.dumps(valor))
        except Exception as e:
            logger.warning(f"[CACHE] Redis SET error: {e}")

    def delete(self, clave: str) -> None:
        try:
            self._r.delete(self._k(clave))
        except Exception as e:
            logger.warning(f"[CACHE] Redis DELETE error: {e}")

    def flush(self) -> None:
        try:
            keys = self._r.keys("guardian:perfil:*")
            if keys:
                self._r.delete(*keys)
        except Exception as e:
            logger.warning(f"[CACHE] Redis FLUSH error: {e}")

    def stats(self) -> Dict[str, Any]:
        try:
            info  = self._r.info("stats")
            keys  = len(self._r.keys("guardian:perfil:*"))
        except Exception:
            info, keys = {}, 0
        return {
            "backend":       "redis",
            "entradas":      keys,
            "hits":          self._hits,
            "misses":        self._misses,
            "hit_rate":      round(self._hits / max(self._hits + self._misses, 1) * 100, 1),
            "redis_hits":    info.get("keyspace_hits", "?"),
            "redis_misses":  info.get("keyspace_misses", "?"),
        }


# ==============================================================================
# Inicialización del backend (selección automática)
# ==============================================================================

_cache_instance: Optional[_CacheMemoria | _CacheRedis] = None


def _get_cache() -> _CacheMemoria | _CacheRedis:
    """Singleton: devuelve el backend activo, inicializándolo si es necesario."""
    global _cache_instance
    if _cache_instance is not None:
        return _cache_instance

    if REDIS_ENABLED:
        try:
            _cache_instance = _CacheRedis(REDIS_URL, CACHE_TTL_SEGUNDOS)
            return _cache_instance
        except Exception as e:
            logger.warning(f"[CACHE] Redis no disponible ({e}). Usando memoria.")

    _cache_instance = _CacheMemoria(CACHE_TTL_SEGUNDOS)
    logger.info("[CACHE] Backend en memoria inicializado.")
    return _cache_instance


# ==============================================================================
# API pública del módulo
# ==============================================================================

def _clave_perfil(usuario_id: int) -> str:
    return f"perfil:{usuario_id}"


def get_perfil_cacheado(usuario_id: int) -> Optional[Dict[str, Any]]:
    """
    Obtiene el perfil lingüístico del caché.
    Retorna None si no está en caché o si caducó.
    """
    return _get_cache().get(_clave_perfil(usuario_id))


def set_perfil_cacheado(usuario_id: int, perfil: Dict[str, Any], ttl: Optional[int] = None) -> None:
    """Guarda el perfil en caché."""
    _get_cache().set(_clave_perfil(usuario_id), perfil, ttl)


def invalidar_perfil(usuario_id: int) -> None:
    """Invalida el perfil de un usuario (forzará recalculo en próxima lectura)."""
    _get_cache().delete(_clave_perfil(usuario_id))
    logger.debug(f"[CACHE] Perfil invalidado para user={usuario_id}")


def get_perfil_con_fallback(usuario_id: int) -> Optional[Dict[str, Any]]:
    """
    Obtiene el perfil del caché. Si no está, lo busca en DB y lo cachea.
    Este es el método que deben usar el resto de los módulos.
    """
    perfil = get_perfil_cacheado(usuario_id)
    if perfil is not None:
        logger.debug(f"[CACHE] HIT perfil user={usuario_id}")
        return perfil

    # Caché miss → buscar en DB
    logger.debug(f"[CACHE] MISS perfil user={usuario_id} → consultando DB")
    try:
        from perfil_usuario import obtener_perfil
        perfil = obtener_perfil(usuario_id)
        if perfil:
            set_perfil_cacheado(usuario_id, perfil)
    except Exception as e:
        logger.warning(f"[CACHE] Error al cargar perfil desde DB: {e}")

    return perfil


def actualizar_y_cachear_perfil(usuario_id: int, ventana: int = 100) -> Optional[Dict[str, Any]]:
    """
    Recalcula el perfil lingüístico desde DB, lo guarda en DB y lo pone en caché.
    Usar cuando se cumple el tick de aprendizaje.
    """
    try:
        from perfil_usuario import actualizar_perfil_usuario
        perfil = actualizar_perfil_usuario(usuario_id, ventana)
        if perfil:
            set_perfil_cacheado(usuario_id, perfil)
            logger.debug(f"[CACHE] Perfil actualizado y cacheado para user={usuario_id}")
        return perfil
    except Exception as e:
        logger.error(f"[CACHE] Error al actualizar perfil user={usuario_id}: {e}")
        return None


def stats_cache() -> Dict[str, Any]:
    """Devuelve estadísticas del backend de caché activo."""
    return _get_cache().stats()


def flush_cache() -> None:
    """Vacía toda la caché. Útil para tests o reinicio manual."""
    _get_cache().flush()
    logger.info("[CACHE] Caché vaciado.")


def purge_expirados() -> int:
    """
    Elimina entradas caducadas (solo relevante para backend en memoria).
    Llamar periódicamente (ej. cada 30 min desde un scheduler).
    """
    c = _get_cache()
    if hasattr(c, "purge_expired"):
        eliminados = c.purge_expired()
        if eliminados:
            logger.info(f"[CACHE] Purge: {eliminados} entradas caducadas eliminadas.")
        return eliminados
    return 0
