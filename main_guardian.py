# ==============================================================================
# GUARDIÁN DIGITAL v2.0 - main_guardian.py
# Orquestador principal — integra todos los sistemas:
#
#   WhatsApp → Gateway → [spam_guard] → [biometría + manipulación + estafas]
#              → [score_engine] → [firewall] → [ia_engine] → Respuesta
#
# Nuevos sistemas integrados:
#   ✅ score_engine.py    → Score central con 4 dimensiones (40/30/20/10)
#   ✅ cache_perfiles.py  → Caché de perfiles lingüísticos (mem/Redis)
#   ✅ spam_guard.py      → Rate limiting y protección anti-flood
# ==============================================================================

import asyncio
import logging
from datetime import datetime
from typing import Dict, Any, Optional

from config import VOICE_ENABLED, VISION_ENABLED, ADMIN_PREFIX
from db import (
    obtener_usuario,
    crear_usuario_desconocido,
    actualizar_ultimo_contacto,
    registrar_log_seguridad,
)
from biometria       import analizar_biometria
from manipulacion    import analizar_manipulacion
from firewall        import evaluar_firewall, AccionFirewall, procesar_resultado_desafio
from sysadmin_engine import es_comando_admin, procesar_comando_admin
from ia_engine       import generar_respuesta
from score_engine    import calcular_score, ResultadoScore, reporte_score
from cache_perfiles  import get_perfil_con_fallback, actualizar_y_cachear_perfil
from spam_guard      import evaluar_spam, resetear_spam_usuario

logger = logging.getLogger(__name__)


# ==============================================================================
# Constantes internas
# ==============================================================================

_ACTUALIZAR_PERFIL_CADA = 10   # Recalcular perfil lingüístico cada N mensajes
_contadores: Dict[int, int] = {}
_sesiones_desafio: Dict[int, Dict] = {}   # { usuario_id: {"pregunta": dict, "intentos": int} }


# ==============================================================================
# Análisis individuales con fallback  (cada módulo falla de forma independiente)
# ==============================================================================

async def _bio(usuario_id: int, texto: str) -> Dict[str, Any]:
    try:
        return await asyncio.to_thread(analizar_biometria, usuario_id, texto)
    except Exception as e:
        logger.error(f"[GUARDIAN] Biometría error user={usuario_id}: {e}")
        return {"score_riesgo": 0.0, "detalle": f"error: {e}", "alerta": False, "tiene_historial": False}


async def _manip(texto: str) -> Dict[str, Any]:
    try:
        return await asyncio.to_thread(analizar_manipulacion, texto)
    except Exception as e:
        logger.error(f"[GUARDIAN] Manipulación error: {e}")
        return {"score_riesgo": 0.0, "categorias": [], "detalle": f"error: {e}", "es_peligroso": False}


async def _estafa(texto: str, contexto: str) -> Dict[str, Any]:
    try:
        from detector_estafas import analizar_mensaje_completo
        return await analizar_mensaje_completo(texto, contexto)
    except Exception as e:
        logger.error(f"[GUARDIAN] Detector estafas error: {e}")
        return {"score_final": 0.0, "es_estafa": False, "tipo_estafa": "ninguno",
                "categorias": [], "nivel_alerta": "ninguno", "mensaje_alerta": ""}


async def _historial_score(usuario_id: int) -> float:
    """Calcula el score de historial de incidentes de forma segura."""
    try:
        from db import obtener_logs_recientes
        from config import UMBRAL_ALERTA
        logs = obtener_logs_recientes(usuario_id, 20)
        eventos  = sum(1 for l in logs if l.get("score_riesgo", 0) >= UMBRAL_ALERTA)
        bloqueos = sum(1 for l in logs if "BLOQUEO" in l.get("evento", "") or "FALLIDO" in l.get("evento", ""))
        return round(min(eventos * 0.5 + bloqueos * 2.0, 10.0), 2)
    except Exception:
        return 0.0


# ==============================================================================
# Enriquecimiento de biometría con perfil cacheado
# ==============================================================================

def _enriquecer_bio_con_perfil(usuario_id: int, score_bio_base: float, texto: str) -> float:
    """
    Consulta el perfil cacheado y eleva el score biométrico si hay
    una desviación alta del estilo habitual del usuario.
    El perfil NO se recalcula aquí; solo se lee del caché.
    """
    try:
        perfil = get_perfil_con_fallback(usuario_id)
        if not perfil:
            return score_bio_base

        from perfil_usuario import comparar_con_perfil
        comp = comparar_con_perfil(texto, perfil)
        desv = comp.get("score_desviacion", 0.0)

        if desv > 5.0:
            incremento = min((desv - 5.0) * 0.4, 2.5)
            nuevo = round(min(score_bio_base + incremento, 10.0), 2)
            logger.debug(
                f"[GUARDIAN] Perfil cacheado → bio ajustada "
                f"{score_bio_base:.1f} → {nuevo:.1f} (desv={desv:.1f})"
            )
            return nuevo
    except Exception as e:
        logger.debug(f"[GUARDIAN] Enriquecimiento de perfil falló: {e}")
    return score_bio_base


# ==============================================================================
# Tick de aprendizaje (actualiza caché + DB cada N mensajes)
# ==============================================================================

def _tick_aprendizaje(usuario_id: int) -> None:
    _contadores[usuario_id] = _contadores.get(usuario_id, 0) + 1
    if _contadores[usuario_id] >= _ACTUALIZAR_PERFIL_CADA:
        _contadores[usuario_id] = 0
        # Ejecutar en background — no bloquear la respuesta al usuario
        asyncio.get_event_loop().run_in_executor(
            None, actualizar_y_cachear_perfil, usuario_id
        )


# ==============================================================================
# Procesador de texto
# ==============================================================================

async def _procesar_texto(usuario: Dict[str, Any], texto: str) -> str:
    usuario_id = usuario["id"]

    # ─── Desafío 2FA pendiente ────────────────────────────────────────────────
    if usuario_id in _sesiones_desafio:
        return await _procesar_respuesta_desafio(usuario, texto)

    # ─── Comando /admin ───────────────────────────────────────────────────────
    if es_comando_admin(texto):
        return procesar_comando_admin(texto, usuario)["resultado"]

    # ─── Análisis en paralelo (con fallbacks individuales) ────────────────────
    contexto = f"Rol: {usuario.get('rol_nombre', '?')}, Nombre: {usuario.get('nombre', '')}"

    resultado_bio, resultado_manip, resultado_estafa, score_hist = await asyncio.gather(
        _bio(usuario_id, texto),
        _manip(texto),
        _estafa(texto, contexto),
        asyncio.to_thread(_historial_score_sync, usuario_id),
    )

    # ─── Enriquecer biometría con perfil cacheado ─────────────────────────────
    score_bio_enriquecido = _enriquecer_bio_con_perfil(
        usuario_id, resultado_bio["score_riesgo"], texto
    )

    # ─── Score central unificado (score_engine) ───────────────────────────────
    hora_actual     = datetime.now().hour
    perfil_cacheado = get_perfil_con_fallback(usuario_id)
    franja_habitual = perfil_cacheado.get("franja_dominante") if perfil_cacheado else None

    score_result: ResultadoScore = calcular_score(
        usuario_id         = usuario_id,
        rol_nivel          = usuario.get("rol_nivel", 1),
        texto              = texto,
        score_biometria    = score_bio_enriquecido,
        score_manipulacion = resultado_manip["score_riesgo"],
        score_estafa       = resultado_estafa["score_final"],
        score_historial    = score_hist,
        tipo_estafa        = resultado_estafa.get("tipo_estafa", "ninguno"),
        categorias         = resultado_estafa.get("categorias", []),
        señales            = resultado_estafa.get("señales", []),
        hora_actual        = hora_actual,
        franja_habitual    = franja_habitual,
        usuario_bloqueado  = bool(usuario.get("bloqueado", 0)),
    )

    logger.debug(f"[GUARDIAN] {reporte_score(score_result)}")

    # ─── Evaluación del firewall ──────────────────────────────────────────────
    decision_fw = evaluar_firewall(
        usuario            = usuario,
        score_biometria    = score_result.biometria,
        score_manipulacion = score_result.manipulacion,
        texto_original     = texto,
        score_estafa       = score_result.estafa,
        score_result       = score_result,     # Pasar el objeto completo
    )

    # ─── Log si hay riesgo relevante ──────────────────────────────────────────
    if score_result.total >= 3.5:
        registrar_log_seguridad(
            usuario_id,
            evento       = f"ANALISIS_{decision_fw['accion'].upper()}",
            score_riesgo = score_result.total,
            detalle      = score_result.detalle,
            accion_tomada= decision_fw["accion"],
        )

    # ─── Acciones del firewall ────────────────────────────────────────────────
    if decision_fw["accion"] == AccionFirewall.BLOQUEAR:
        return decision_fw["mensaje_respuesta"]

    if decision_fw["accion"] == AccionFirewall.DESAFIO_2FA:
        pregunta = decision_fw.get("pregunta_desafio")
        if pregunta:
            _sesiones_desafio[usuario_id] = {"pregunta": pregunta, "intentos": 0}
        return decision_fw["mensaje_respuesta"]

    # ─── Aprendizaje incremental ──────────────────────────────────────────────
    _tick_aprendizaje(usuario_id)

    # ─── Respuesta de IA ──────────────────────────────────────────────────────
    alerta_estafa = resultado_estafa.get("mensaje_alerta", "")

    respuesta = generar_respuesta(
        usuario        = usuario,
        mensaje_usuario= texto,
        score_riesgo   = score_result.total,
        tipo_contenido = "texto",
        datos_extra    = {
            "score_riesgo":     score_result.total,
            "nivel_riesgo":     score_result.nivel_riesgo,
            "categorias_manip": resultado_manip["categorias"],
            "tipo_estafa":      resultado_estafa.get("tipo_estafa", "ninguno"),
        },
    )

    if alerta_estafa and resultado_estafa["es_estafa"]:
        return f"{alerta_estafa}\n\n---\n{respuesta}"
    return respuesta


async def _procesar_respuesta_desafio(usuario: Dict[str, Any], texto: str) -> str:
    usuario_id = usuario["id"]
    sesion   = _sesiones_desafio.pop(usuario_id, {})
    pregunta = sesion.get("pregunta")
    if not pregunta:
        return "Continúa con tu mensaje."
    resultado = procesar_resultado_desafio(usuario, pregunta, texto)
    return resultado["mensaje"]


def _historial_score_sync(usuario_id: int) -> float:
    """Versión síncrona para asyncio.to_thread."""
    try:
        from db import obtener_logs_recientes
        from config import UMBRAL_ALERTA
        logs = obtener_logs_recientes(usuario_id, 20)
        e = sum(1 for l in logs if l.get("score_riesgo", 0) >= UMBRAL_ALERTA)
        b = sum(1 for l in logs if "BLOQUEO" in l.get("evento", "") or "FALLIDO" in l.get("evento", ""))
        return round(min(e * 0.5 + b * 2.0, 10.0), 2)
    except Exception:
        return 0.0


# ==============================================================================
# Procesadores de imagen y voz (con fallbacks completos)
# ==============================================================================

async def _procesar_imagen(usuario: Dict, img: bytes, mime: str) -> str:
    try:
        from vision_engine import analizar_imagen, generar_alerta_imagen
        r = await analizar_imagen(img, mime)
        alerta = generar_alerta_imagen(r)
        if r["es_phishing"]:
            registrar_log_seguridad(usuario["id"], "PHISHING_VISUAL_DETECTADO",
                                    r["score_riesgo"], r["descripcion"], "alerta_enviada")
            return alerta
        respuesta = generar_respuesta(usuario=usuario,
                                      mensaje_usuario="[Imagen enviada]",
                                      score_riesgo=r["score_riesgo"],
                                      tipo_contenido="imagen",
                                      datos_extra={"analisis_phishing": r["descripcion"]})
        return f"{alerta}\n\n{respuesta}" if alerta else respuesta
    except Exception as e:
        logger.error(f"[GUARDIAN] Visión error user={usuario['id']}: {e}")
        return generar_respuesta(usuario=usuario, mensaje_usuario="[Imagen]", score_riesgo=0.0)


async def _procesar_voz(usuario: Dict, audio: bytes) -> str:
    try:
        from voice_engine import procesar_mensaje_voz
        r = await procesar_mensaje_voz(audio, usuario["id"])
        if not r["procesado"]:
            return "No pude procesar el audio. ¿Puedes escribirme?"
        transcripcion = r["transcripcion"]
        r_bio = await _bio(usuario["id"], transcripcion)
        decision = evaluar_firewall(usuario, r_bio["score_riesgo"],
                                    r["score_manipulacion"], transcripcion)
        if decision["accion"] == AccionFirewall.BLOQUEAR:
            return decision["mensaje_respuesta"]
        if decision["accion"] == AccionFirewall.DESAFIO_2FA:
            pregunta = decision.get("pregunta_desafio")
            if pregunta:
                _sesiones_desafio[usuario["id"]] = {"pregunta": pregunta, "intentos": 0}
            return decision["mensaje_respuesta"]
        return generar_respuesta(usuario=usuario, mensaje_usuario=transcripcion,
                                 score_riesgo=decision["score_compuesto"],
                                 tipo_contenido="voz",
                                 datos_extra={"transcripcion": transcripcion})
    except Exception as e:
        logger.error(f"[GUARDIAN] Voz error user={usuario['id']}: {e}")
        return "Tuve un problema con el audio. ¿Puedes escribirme?"


# ==============================================================================
# Punto de entrada principal
# ==============================================================================

async def procesar_mensaje(
    telefono:          str,
    tipo:              str,
    contenido_texto:   Optional[str],
    contenido_binario: Optional[bytes] = None,
    mime_type:         Optional[str]   = None,
    nombre_remitente:  str             = "Desconocido",
) -> str:
    """
    Punto de entrada con protección anti-spam como primera capa,
    antes de cualquier análisis costoso.
    """
    # ─── Obtener / crear usuario ──────────────────────────────────────────────
    try:
        usuario = obtener_usuario(telefono)
        if not usuario:
            crear_usuario_desconocido(telefono, nombre_remitente)
            usuario = obtener_usuario(telefono)
        if not usuario or not usuario.get("activo"):
            return ""
        actualizar_ultimo_contacto(usuario["id"])
    except Exception as e:
        logger.exception(f"[GUARDIAN] Error cargando usuario {telefono}: {e}")
        return "Hubo un problema. Intenta en un momento."

    usuario_id = usuario["id"]
    logger.info(f"[GUARDIAN] [{telefono}] ({usuario.get('rol_nombre','?')}) tipo={tipo}")

    # ─── Protección anti-spam (primera capa, O(1), sin DB) ───────────────────
    texto_para_spam = contenido_texto or f"[{tipo}]"
    resultado_spam  = evaluar_spam(usuario_id, texto_para_spam)

    if resultado_spam.debe_bloquear:
        logger.warning(
            f"[GUARDIAN] 🚫 SPAM user={usuario_id} | "
            f"motivo={resultado_spam.motivo} | "
            f"score={resultado_spam.score_spam}"
        )
        registrar_log_seguridad(
            usuario_id,
            evento       = "SPAM_BLOQUEADO",
            score_riesgo = resultado_spam.score_spam,
            detalle      = resultado_spam.motivo,
            accion_tomada= "spam_temporal",
        )
        return resultado_spam.sugerencia_msg

    # ─── Enrutar según tipo de contenido ──────────────────────────────────────
    try:
        if tipo == "texto" and contenido_texto:
            return await _procesar_texto(usuario, contenido_texto)

        elif tipo == "imagen" and contenido_binario and VISION_ENABLED:
            return await _procesar_imagen(usuario, contenido_binario, mime_type or "image/jpeg")

        elif tipo == "voz" and contenido_binario and VOICE_ENABLED:
            return await _procesar_voz(usuario, contenido_binario)

        else:
            return generar_respuesta(
                usuario        = usuario,
                mensaje_usuario= contenido_texto or f"[{tipo}]",
                score_riesgo   = 0.0,
            )

    except Exception as e:
        logger.exception(f"[GUARDIAN] Error crítico procesando mensaje: {e}")
        try:
            registrar_log_seguridad(usuario_id, "ERROR_SISTEMA", 0.0, str(e)[:500], "error")
        except Exception:
            pass
        return "Tuve un problema procesando tu mensaje. Intenta nuevamente en un momento."
