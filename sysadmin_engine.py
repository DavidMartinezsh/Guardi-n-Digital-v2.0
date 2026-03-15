# ==============================================================================
# GUARDIÁN DIGITAL v2.0 - sysadmin_engine.py
# Motor de administración remota del servidor VPS. Solo para super_admin.
# ==============================================================================

import subprocess
import shlex
import logging
import re
from typing import Dict, Any, Optional, Tuple

from config import ADMIN_PREFIX, ADMIN_COMANDOS_PERMITIDOS

logger = logging.getLogger(__name__)

# Timeout máximo para comandos de sistema (segundos)
CMD_TIMEOUT = 15

# ==============================================================================
# Mapa de comandos seguros (alias → comando real en shell)
# ==============================================================================

COMANDOS_SEGUROS: Dict[str, str] = {
    "status":          "systemctl status nginx php8.2-fpm mysql --no-pager",
    "restart_nginx":   "systemctl restart nginx && echo 'Nginx reiniciado ✅'",
    "restart_php":     "systemctl restart php8.2-fpm && echo 'PHP-FPM reiniciado ✅'",
    "restart_mysql":   "systemctl restart mysql && echo 'MySQL reiniciado ✅'",
    "uptime":          "uptime -p && echo '' && w",
    "logs_nginx":      "tail -n 30 /var/log/nginx/error.log",
    "logs_php":        "tail -n 30 /var/log/php8.2-fpm.log",
    "logs_guardian":   "tail -n 50 /var/log/guardian_digital.log",
    "disk":            "df -h --output=source,size,used,avail,pcent | head -10",
    "ram":             "free -h && echo '' && vmstat -s | head -5",
    "cpu":             "top -bn1 | head -20",
    "block_user":      None,   # Manejado por lógica especial
    "unblock_user":    None,   # Manejado por lógica especial
}


# ==============================================================================
# Parser de comandos
# ==============================================================================

def es_comando_admin(texto: str) -> bool:
    """Verifica si el texto es un comando de administración."""
    return texto.strip().startswith(ADMIN_PREFIX)


def parsear_comando(texto: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Extrae el comando y argumento de un mensaje.
    Ejemplo: '/admin restart_nginx' → ('restart_nginx', None)
             '/admin block_user 5491123456789' → ('block_user', '5491123456789')
    Retorna: (comando, argumento) o (None, None) si no es válido.
    """
    texto = texto.strip()
    if not texto.startswith(ADMIN_PREFIX):
        return None, None

    partes = texto[len(ADMIN_PREFIX):].strip().split(maxsplit=1)
    if not partes:
        return None, None

    comando = partes[0].lower()
    argumento = partes[1].strip() if len(partes) > 1 else None

    if comando not in ADMIN_COMANDOS_PERMITIDOS:
        return None, None

    return comando, argumento


# ==============================================================================
# Ejecutor de comandos
# ==============================================================================

def _ejecutar_shell(cmd: str) -> Tuple[str, int]:
    """
    Ejecuta un comando en shell de forma segura.
    Retorna (salida, código_de_retorno).
    """
    try:
        resultado = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=CMD_TIMEOUT,
            user="guardian",   # Ejecutar como usuario sin privilegios
        )
        salida = resultado.stdout + resultado.stderr
        return salida.strip()[:3000], resultado.returncode  # Limitar salida
    except subprocess.TimeoutExpired:
        return "⏱️ Comando expiró (timeout).", 124
    except Exception as e:
        logger.error(f"[SYSADMIN] Error ejecutando '{cmd}': {e}")
        return f"❌ Error interno: {str(e)}", 1


def _sanitizar_argumento(arg: str) -> Optional[str]:
    """
    Sanitiza un argumento para evitar inyección de comandos.
    Solo permite números de teléfono (para block/unblock).
    """
    if not arg:
        return None
    # Solo dígitos y + (para números de teléfono)
    limpio = re.sub(r"[^\d+]", "", arg)
    return limpio if limpio else None


# ==============================================================================
# Procesador principal de comandos admin
# ==============================================================================

def procesar_comando_admin(
    texto: str,
    usuario: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Procesa un comando /admin si el usuario tiene rol super_admin.

    Retorna:
        {
            "ejecutado":   bool,
            "comando":     str,
            "argumento":   str | None,
            "resultado":   str,
            "codigo":      int,
            "autorizado":  bool,
        }
    """
    # Verificar autorización
    if usuario.get("rol_nombre") != "super_admin":
        logger.warning(
            f"[SYSADMIN] Intento no autorizado de user={usuario.get('id')}"
        )
        return {
            "ejecutado": False,
            "comando": "desconocido",
            "argumento": None,
            "resultado": "⛔ No tienes permisos para ejecutar comandos de administración.",
            "codigo": 403,
            "autorizado": False,
        }

    # Parsear comando
    comando, argumento = parsear_comando(texto)
    if not comando:
        lista_cmds = "\n".join(f"  • /admin {c}" for c in ADMIN_COMANDOS_PERMITIDOS)
        return {
            "ejecutado": False,
            "comando": "desconocido",
            "argumento": None,
            "resultado": f"❓ Comando no reconocido.\n\nComandos disponibles:\n{lista_cmds}",
            "codigo": 404,
            "autorizado": True,
        }

    logger.info(
        f"[SYSADMIN] Ejecutando '{comando}' arg='{argumento}' "
        f"por user={usuario.get('id')}"
    )

    # ─── Comandos con lógica especial ─────────────────────────────────────────
    if comando in ("block_user", "unblock_user"):
        return _procesar_block_unblock(comando, argumento, usuario)

    # ─── Comandos de shell ────────────────────────────────────────────────────
    cmd_shell = COMANDOS_SEGUROS.get(comando)
    if not cmd_shell:
        return {
            "ejecutado": False,
            "comando": comando,
            "argumento": None,
            "resultado": f"⚠️ Comando '{comando}' no tiene implementación shell.",
            "codigo": 501,
            "autorizado": True,
        }

    salida, codigo = _ejecutar_shell(cmd_shell)
    exito = codigo == 0

    emoji = "✅" if exito else "❌"
    resultado_formateado = f"{emoji} `{comando}`\n\n```\n{salida}\n```"

    return {
        "ejecutado": True,
        "comando": comando,
        "argumento": None,
        "resultado": resultado_formateado,
        "codigo": codigo,
        "autorizado": True,
    }


def _procesar_block_unblock(
    comando: str,
    argumento: Optional[str],
    usuario_admin: Dict[str, Any],
) -> Dict[str, Any]:
    """Maneja los comandos block_user y unblock_user."""
    from db import obtener_usuario, bloquear_usuario, desbloquear_usuario

    telefono = _sanitizar_argumento(argumento or "")
    if not telefono:
        return {
            "ejecutado": False,
            "comando": comando,
            "argumento": argumento,
            "resultado": (
                f"❓ Uso: `/admin {comando} <número_de_teléfono>`\n"
                "Ejemplo: `/admin block_user 5491123456789`"
            ),
            "codigo": 400,
            "autorizado": True,
        }

    objetivo = obtener_usuario(telefono)
    if not objetivo:
        return {
            "ejecutado": False,
            "comando": comando,
            "argumento": telefono,
            "resultado": f"❓ No encontré usuario con teléfono `{telefono}`.",
            "codigo": 404,
            "autorizado": True,
        }

    if comando == "block_user":
        bloquear_usuario(
            objetivo["id"],
            f"Bloqueado manualmente por admin id={usuario_admin['id']}",
        )
        return {
            "ejecutado": True,
            "comando": comando,
            "argumento": telefono,
            "resultado": f"🔒 Usuario `{objetivo['nombre']}` ({telefono}) bloqueado.",
            "codigo": 0,
            "autorizado": True,
        }
    else:
        desbloquear_usuario(objetivo["id"])
        return {
            "ejecutado": True,
            "comando": comando,
            "argumento": telefono,
            "resultado": f"🔓 Usuario `{objetivo['nombre']}` ({telefono}) desbloqueado.",
            "codigo": 0,
            "autorizado": True,
        }


# ==============================================================================
# Ayuda
# ==============================================================================

def obtener_ayuda_admin() -> str:
    lineas = ["*🛡️ Guardián Digital — Comandos de Administración*\n"]
    descripciones = {
        "status":        "Estado de Nginx, PHP y MySQL",
        "restart_nginx": "Reiniciar servidor web Nginx",
        "restart_php":   "Reiniciar PHP-FPM",
        "restart_mysql": "Reiniciar base de datos MySQL",
        "uptime":        "Tiempo activo del servidor",
        "logs_nginx":    "Últimas 30 líneas del log de Nginx",
        "logs_php":      "Últimas 30 líneas del log de PHP",
        "logs_guardian": "Últimas 50 líneas del log de Guardián",
        "disk":          "Uso del disco",
        "ram":           "Uso de memoria RAM",
        "cpu":           "Uso de CPU (top)",
        "block_user":    "Bloquear usuario por teléfono",
        "unblock_user":  "Desbloquear usuario por teléfono",
    }
    for cmd, desc in descripciones.items():
        lineas.append(f"• `/admin {cmd}` — {desc}")
    return "\n".join(lineas)
