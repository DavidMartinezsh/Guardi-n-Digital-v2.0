# ==============================================================================
# GUARDIÁN DIGITAL v4.0 - main_guardian.py
# Orquestador principal — integra v2.0 (seguridad) + v4.0 (cerebro familiar)
#
# FLUJO COMPLETO:
#   WhatsApp → spam_guard → [bio + manip + estafa] → score_engine → firewall
#   → [emotion + decision + memory + family + diary + twin] → ia_engine → respuesta
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
from spam_guard      import evaluar_spam

# ── Módulos v4.0 (con fallback si no están disponibles) ──────────────────────
try:
    from emotion_engine    import analizar_emocion, ResultadoEmocion
    EMOTION_ENABLED = True
except ImportError:
    EMOTION_ENABLED = False

try:
    from decision_engine   import analizar_situacion, ResultadoDecision
    DECISION_ENABLED = True
except ImportError:
    DECISION_ENABLED = False

try:
    from memory_engine     import extraer_hechos_automatico, actualizar_contexto_sesion
    MEMORY_ENABLED = True
except ImportError:
    MEMORY_ENABLED = False

try:
    from family_engine     import actualizar_estado_emocional, registrar_conversacion
    FAMILY_ENABLED = True
except ImportError:
    FAMILY_ENABLED = False

try:
    from diary_engine      import registrar_momento
    DIARY_ENABLED = True
except ImportError:
    DIARY_ENABLED = False

try:
    from twin_engine       import construir_prompt_gemelo
    TWIN_ENABLED = True
except ImportError:
    TWIN_ENABLED = False

try:
    from legacy_mode       import esta_activo, generar_respuesta_legado, es_comando_legado, procesar_comando_legado
    LEGACY_ENABLED = True
except ImportError:
    LEGACY_ENABLED = False

try:
    from doc_engine        import procesar_documento, formatear_respuesta_documento
    DOC_ENABLED = True
except ImportError:
    DOC_ENABLED = False

logger = logging.getLogger(__name__)

# ==============================================================================
# Constantes
# ==============================================================================

_ACTUALIZAR_PERFIL_CADA = 10
_contadores: Dict[int, int] = {}
_sesiones_desafio: Dict[int, Dict] = {}


# ==============================================================================
# Análisis de seguridad (v2.0) — con fallbacks individuales
# ==============================================================================

async def _bio(usuario_id: int, texto: str) -> Dict[str, Any]:
    try:
        return await asyncio.to_thread(analizar_biometria, usuario_id, texto)
    except Exception as e:
        logger.error(f"[GUARDIAN] Biometría error user={usuario_id}: {e}")
        return {"score_riesgo": 0.0, "alerta": False, "tiene_historial": False}


async def _manip(texto: str) -> Dict[str, Any]:
    try:
        return await asyncio.to_thread(analizar_manipulacion, texto)
    except Exception as e:
        logger.error(f"[GUARDIAN] Manipulación error: {e}")
        return {"score_riesgo": 0.0, "categorias": [], "es_peligroso": False}


async def _estafa(texto: str, contexto: str) -> Dict[str, Any]:
    try:
        from detector_estafas import analizar_mensaje_completo
        return await analizar_mensaje_completo(texto, contexto)
    except Exception as e:
        logger.error(f"[GUARDIAN] Estafas error: {e}")
        return {"score_final": 0.0, "es_estafa": False, "tipo_estafa": "ninguno",
                "categorias": [], "nivel_alerta": "ninguno", "mensaje_alerta": ""}


def _historial_score_sync(usuario_id: int) -> float:
    try:
        from db import obtener_logs_recientes
        from config import UMBRAL_ALERTA
        logs     = obtener_logs_recientes(usuario_id, 20)
        eventos  = sum(1 for l in logs if l.get("score_riesgo", 0) >= UMBRAL_ALERTA)
        bloqueos = sum(1 for l in logs if "BLOQUEO" in l.get("evento", "") or "FALLIDO" in l.get("evento", ""))
        return round(min(eventos * 0.5 + bloqueos * 2.0, 10.0), 2)
    except Exception:
        return 0.0


def _enriquecer_bio_con_perfil(usuario_id: int, score_bio_base: float, texto: str) -> float:
    try:
        perfil = get_perfil_con_fallback(usuario_id)
        if not perfil:
            return score_bio_base
        from perfil_usuario import comparar_con_perfil
        comp = comparar_con_perfil(texto, perfil)
        desv = comp.get("score_desviacion", 0.0)
        if desv > 5.0:
            incremento = min((desv - 5.0) * 0.4, 2.5)
            return round(min(score_bio_base + incremento, 10.0), 2)
    except Exception:
        pass
    return score_bio_base


def _tick_aprendizaje(usuario_id: int) -> None:
    _contadores[usuario_id] = _contadores.get(usuario_id, 0) + 1
    if _contadores[usuario_id] >= _ACTUALIZAR_PERFIL_CADA:
        _contadores[usuario_id] = 0
        asyncio.get_event_loop().run_in_executor(
            None, actualizar_y_cachear_perfil, usuario_id
        )


# ==============================================================================
# Análisis v4.0 — emoción, decisión, memoria (con fallbacks)
# ==============================================================================

def _analizar_emocion_seguro(texto: str):
    if not EMOTION_ENABLED:
        return None
    try:
        return analizar_emocion(texto)
    except Exception as e:
        logger.debug(f"[GUARDIAN] emotion_engine error: {e}")
        return None


def _analizar_decision_segura(texto: str, rol: str):
    if not DECISION_ENABLED:
        return None
    try:
        return analizar_situacion(texto, rol)
    except Exception as e:
        logger.debug(f"[GUARDIAN] decision_engine error: {e}")
        return None


def _extraer_memoria_seguro(usuario_id: int, texto: str) -> None:
    if not MEMORY_ENABLED:
        return
    try:
        hechos = extraer_hechos_automatico(usuario_id, texto)
        if hechos:
            logger.debug(f"[GUARDIAN] Memoria: {len(hechos)} hechos extraídos")
    except Exception as e:
        logger.debug(f"[GUARDIAN] memory_engine error: {e}")


def _construir_prompt_gemelo_seguro(
    usuario: Dict,
    resultado_emocion=None,
    resultado_decision=None,
) -> Optional[str]:
    if not TWIN_ENABLED:
        return None
    try:
        return construir_prompt_gemelo(
            usuario=usuario,
            resultado_emocion=resultado_emocion,
            resultado_decision=resultado_decision,
        )
    except Exception as e:
        logger.debug(f"[GUARDIAN] twin_engine error: {e}")
        return None


def _registrar_en_diario(usuario: Dict, texto: str, estado_emocional: str = "neutro") -> None:
    if not DIARY_ENABLED:
        return
    try:
        registrar_momento(
            telefono=usuario.get("telefono", ""),
            nombre=usuario.get("nombre", "?"),
            contenido=texto[:200],
            tipo="conversacion",
            estado_emocional=estado_emocional,
        )
    except Exception as e:
        logger.debug(f"[GUARDIAN] diary_engine error: {e}")


def _actualizar_contexto_familiar(usuario: Dict, texto: str, estado_emocional: str) -> None:
    telefono = usuario.get("telefono", "")
    if not telefono:
        return
    if FAMILY_ENABLED:
        try:
            actualizar_estado_emocional(telefono, estado_emocional)
            registrar_conversacion(telefono, texto[:200])
        except Exception:
            pass
    if MEMORY_ENABLED:
        try:
            actualizar_contexto_sesion(
                usuario_id=usuario["id"],
                tema="",
                estado_emocional=estado_emocional,
                resumen=texto[:200],
            )
        except Exception:
            pass


# ==============================================================================
# Procesador de texto — núcleo del sistema
# ==============================================================================

async def _procesar_texto(usuario: Dict[str, Any], texto: str) -> str:
    usuario_id = usuario["id"]
    telefono   = usuario.get("telefono", "")
    rol        = usuario.get("rol_nombre", "desconocido")

    # ─── Modo legado ──────────────────────────────────────────────────────────
    if LEGACY_ENABLED:
        if es_comando_legado(texto):
            return procesar_comando_legado(texto, telefono)
        if esta_activo():
            return generar_respuesta_legado(texto, usuario)

    # ─── Desafío 2FA pendiente ────────────────────────────────────────────────
    if usuario_id in _sesiones_desafio:
        return await _procesar_respuesta_desafio(usuario, texto)

    # ─── Comando /admin ───────────────────────────────────────────────────────
    if es_comando_admin(texto):
        return procesar_comando_admin(texto, usuario)["resultado"]

    # ─── Análisis de seguridad en paralelo (v2.0) ─────────────────────────────
    contexto = f"Rol: {rol}, Nombre: {usuario.get('nombre', '')}"

    resultado_bio, resultado_manip, resultado_estafa, score_hist = await asyncio.gather(
        _bio(usuario_id, texto),
        _manip(texto),
        _estafa(texto, contexto),
        asyncio.to_thread(_historial_score_sync, usuario_id),
    )

    score_bio_enriquecido = _enriquecer_bio_con_perfil(
        usuario_id, resultado_bio["score_riesgo"], texto
    )

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

    # ─── Firewall ─────────────────────────────────────────────────────────────
    decision_fw = evaluar_firewall(
        usuario            = usuario,
        score_biometria    = score_result.biometria,
        score_manipulacion = score_result.manipulacion,
        texto_original     = texto,
        score_estafa       = score_result.estafa,
        score_result       = score_result,
    )

    if score_result.total >= 3.5:
        registrar_log_seguridad(
            usuario_id,
            evento        = f"ANALISIS_{decision_fw['accion'].upper()}",
            score_riesgo  = score_result.total,
            detalle       = score_result.detalle,
            accion_tomada = decision_fw["accion"],
        )

    if decision_fw["accion"] == AccionFirewall.BLOQUEAR:
        return decision_fw["mensaje_respuesta"]

    if decision_fw["accion"] == AccionFirewall.DESAFIO_2FA:
        pregunta = decision_fw.get("pregunta_desafio")
        if pregunta:
            _sesiones_desafio[usuario_id] = {"pregunta": pregunta, "intentos": 0}
        return decision_fw["mensaje_respuesta"]

    # ─── Análisis v4.0 (emoción + decisión + memoria) ────────────────────────
    resultado_emocion  = _analizar_emocion_seguro(texto)
    resultado_decision = _analizar_decision_segura(texto, rol)
    estado_emocional   = resultado_emocion.estado_primario if resultado_emocion else "neutro"

    # Extraer hechos de memoria en background
    _extraer_memoria_seguro(usuario_id, texto)

    # Registrar en diario familiar
    _registrar_en_diario(usuario, texto, estado_emocional)

    # Actualizar contexto familiar y sesión
    _actualizar_contexto_familiar(usuario, texto, estado_emocional)

    # ─── Construir prompt del gemelo digital ──────────────────────────────────
    system_prompt_gemelo = _construir_prompt_gemelo_seguro(
        usuario,
        resultado_emocion=resultado_emocion,
        resultado_decision=resultado_decision,
    )

    # ─── Aprendizaje incremental ──────────────────────────────────────────────
    _tick_aprendizaje(usuario_id)

    # ─── Respuesta de IA ──────────────────────────────────────────────────────
    alerta_estafa = resultado_estafa.get("mensaje_alerta", "")

    respuesta = generar_respuesta(
        usuario               = usuario,
        mensaje_usuario       = texto,
        score_riesgo          = score_result.total,
        tipo_contenido        = "texto",
        system_prompt_override = system_prompt_gemelo,   # ← v4.0
        datos_extra           = {
            "score_riesgo":     score_result.total,
            "nivel_riesgo":     score_result.nivel_riesgo,
            "categorias_manip": resultado_manip["categorias"],
            "tipo_estafa":      resultado_estafa.get("tipo_estafa", "ninguno"),
            "estado_emocional": estado_emocional,
        },
    )

    if alerta_estafa and resultado_estafa["es_estafa"]:
        return f"{alerta_estafa}\n\n---\n{respuesta}"
    return respuesta


async def _procesar_respuesta_desafio(usuario: Dict[str, Any], texto: str) -> str:
    usuario_id = usuario["id"]
    sesion     = _sesiones_desafio.pop(usuario_id, {})
    pregunta   = sesion.get("pregunta")
    if not pregunta:
        return "Continúa con tu mensaje."
    return procesar_resultado_desafio(usuario, pregunta, texto)["mensaje"]


# ==============================================================================
# Procesadores de imagen, voz y documento
# ==============================================================================

async def _procesar_imagen(usuario: Dict, img: bytes, mime: str) -> str:
    try:
        from vision_engine import analizar_imagen, generar_alerta_imagen
        r      = await analizar_imagen(img, mime)
        alerta = generar_alerta_imagen(r)
        if r["es_phishing"]:
            registrar_log_seguridad(usuario["id"], "PHISHING_VISUAL_DETECTADO",
                                    r["score_riesgo"], r["descripcion"], "alerta_enviada")
            return alerta
        prompt = _construir_prompt_gemelo_seguro(usuario)
        respuesta = generar_respuesta(
            usuario=usuario, mensaje_usuario="[Imagen enviada]",
            score_riesgo=r["score_riesgo"], tipo_contenido="imagen",
            system_prompt_override=prompt,
            datos_extra={"analisis_phishing": r["descripcion"]},
        )
        return f"{alerta}\n\n{respuesta}" if alerta else respuesta
    except Exception as e:
        logger.error(f"[GUARDIAN] Visión error: {e}")
        return generar_respuesta(usuario=usuario, mensaje_usuario="[Imagen]", score_riesgo=0.0)


async def _procesar_voz(usuario: Dict, audio: bytes) -> str:
    try:
        from voice_engine import procesar_mensaje_voz
        r = await procesar_mensaje_voz(audio, usuario["id"])
        if not r["procesado"]:
            return "No pude procesar el audio. ¿Puedes escribirme?"
        transcripcion = r["transcripcion"]
        r_bio   = await _bio(usuario["id"], transcripcion)
        decision = evaluar_firewall(usuario, r_bio["score_riesgo"],
                                    r["score_manipulacion"], transcripcion)
        if decision["accion"] == AccionFirewall.BLOQUEAR:
            return decision["mensaje_respuesta"]
        if decision["accion"] == AccionFirewall.DESAFIO_2FA:
            pregunta = decision.get("pregunta_desafio")
            if pregunta:
                _sesiones_desafio[usuario["id"]] = {"pregunta": pregunta, "intentos": 0}
            return decision["mensaje_respuesta"]
        prompt = _construir_prompt_gemelo_seguro(usuario)
        return generar_respuesta(
            usuario=usuario, mensaje_usuario=transcripcion,
            score_riesgo=decision["score_compuesto"],
            tipo_contenido="voz",
            system_prompt_override=prompt,
            datos_extra={"transcripcion": transcripcion},
        )
    except Exception as e:
        logger.error(f"[GUARDIAN] Voz error: {e}")
        return "Tuve un problema con el audio. ¿Puedes escribirme?"


async def _procesar_documento(usuario: Dict, doc: bytes, mime: str, nombre: str = "") -> str:
    if not DOC_ENABLED:
        return generar_respuesta(usuario=usuario, mensaje_usuario="[Documento recibido]",
                                 score_riesgo=0.0)
    try:
        resultado  = await procesar_documento(doc, mime, nombre)
        respuesta  = formatear_respuesta_documento(resultado)
        # Registrar en diario si hay algo importante
        if resultado.get("requiere_accion"):
            _registrar_en_diario(usuario, f"Documento: {resultado.get('resumen','')}", "neutro")
        return respuesta
    except Exception as e:
        logger.error(f"[GUARDIAN] doc_engine error: {e}")
        return "Recibí el documento pero no pude procesarlo. ¿Puedes describirme qué contiene?"


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
    nombre_archivo:    str             = "",
) -> str:
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

    # ─── Protección anti-spam (primera capa) ─────────────────────────────────
    texto_spam    = contenido_texto or f"[{tipo}]"
    resultado_spam = evaluar_spam(usuario_id, texto_spam)
    if resultado_spam.debe_bloquear:
        registrar_log_seguridad(usuario_id, "SPAM_BLOQUEADO",
                                resultado_spam.score_spam, resultado_spam.motivo, "spam_temporal")
        return resultado_spam.sugerencia_msg

    # ─── Enrutar por tipo ─────────────────────────────────────────────────────
    try:
        if tipo == "texto" and contenido_texto:
            return await _procesar_texto(usuario, contenido_texto)

        elif tipo == "imagen" and contenido_binario and VISION_ENABLED:
            return await _procesar_imagen(usuario, contenido_binario, mime_type or "image/jpeg")

        elif tipo == "voz" and contenido_binario and VOICE_ENABLED:
            return await _procesar_voz(usuario, contenido_binario)

        elif tipo == "documento" and contenido_binario:
            return await _procesar_documento(
                usuario, contenido_binario,
                mime_type or "application/pdf", nombre_archivo
            )

        else:
            prompt = _construir_prompt_gemelo_seguro(usuario)
            return generar_respuesta(
                usuario=usuario,
                mensaje_usuario=contenido_texto or f"[{tipo}]",
                score_riesgo=0.0,
                system_prompt_override=prompt,
            )

    except Exception as e:
        logger.exception(f"[GUARDIAN] Error crítico procesando mensaje: {e}")
        try:
            registrar_log_seguridad(usuario_id, "ERROR_SISTEMA", 0.0, str(e)[:500], "error")
        except Exception:
            pass
        return "Tuve un problema procesando tu mensaje. Intenta nuevamente en un momento."
