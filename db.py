# ==============================================================================
# GUARDIÁN DIGITAL v2.0 - db.py
# Gestión centralizada de conexiones MySQL y consultas de negocio.
# ==============================================================================

import logging
import pymysql
import pymysql.cursors
from contextlib import contextmanager
from typing import Optional, Dict, Any, List

from config import DB_CONFIG

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pool / Conexión
# ---------------------------------------------------------------------------

@contextmanager
def get_connection():
    """Context manager que entrega una conexión MySQL y la cierra al salir."""
    conn = None
    try:
        conn = pymysql.connect(
            **DB_CONFIG,
            cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=10,
        )
        yield conn
    except pymysql.MySQLError as e:
        logger.error(f"[DB] Error de conexión: {e}")
        raise
    finally:
        if conn:
            conn.close()


# ---------------------------------------------------------------------------
# Usuarios
# ---------------------------------------------------------------------------

def obtener_usuario(telefono: str) -> Optional[Dict[str, Any]]:
    """Retorna el registro completo del usuario o None si no existe."""
    sql = """
        SELECT u.*, r.nombre AS rol_nombre, r.nivel AS rol_nivel
        FROM Usuarios u
        JOIN Roles r ON u.rol_id = r.id
        WHERE u.telefono = %s
        LIMIT 1
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (telefono,))
            return cur.fetchone()


def crear_usuario_desconocido(telefono: str, nombre: str = "Desconocido") -> int:
    """Inserta un usuario con rol 'desconocido' y retorna su ID."""
    sql_rol = "SELECT id FROM Roles WHERE nombre = 'desconocido' LIMIT 1"
    sql_ins = """
        INSERT INTO Usuarios (telefono, nombre, rol_id, activo, fecha_registro)
        VALUES (%s, %s, %s, 1, NOW())
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql_rol)
            rol = cur.fetchone()
            rol_id = rol["id"] if rol else 1
            cur.execute(sql_ins, (telefono, nombre, rol_id))
            conn.commit()
            return conn.lastrowid


def actualizar_ultimo_contacto(usuario_id: int) -> None:
    sql = "UPDATE Usuarios SET ultimo_contacto = NOW() WHERE id = %s"
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (usuario_id,))
            conn.commit()


def bloquear_usuario(usuario_id: int, motivo: str = "") -> None:
    sql = "UPDATE Usuarios SET bloqueado = 1, motivo_bloqueo = %s WHERE id = %s"
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (motivo, usuario_id))
            conn.commit()


def desbloquear_usuario(usuario_id: int) -> None:
    sql = "UPDATE Usuarios SET bloqueado = 0, motivo_bloqueo = NULL WHERE id = %s"
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (usuario_id,))
            conn.commit()


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------

def obtener_rol_por_nombre(nombre: str) -> Optional[Dict[str, Any]]:
    sql = "SELECT * FROM Roles WHERE nombre = %s LIMIT 1"
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (nombre,))
            return cur.fetchone()


def obtener_todos_roles() -> List[Dict[str, Any]]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM Roles ORDER BY nivel DESC")
            return cur.fetchall()


# ---------------------------------------------------------------------------
# Logs de Seguridad
# ---------------------------------------------------------------------------

def registrar_log_seguridad(
    usuario_id: int,
    evento: str,
    score_riesgo: float,
    detalle: str = "",
    accion_tomada: str = "",
) -> None:
    sql = """
        INSERT INTO LogsSeguridad
            (usuario_id, evento, score_riesgo, detalle, accion_tomada, fecha)
        VALUES (%s, %s, %s, %s, %s, NOW())
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (usuario_id, evento, score_riesgo, detalle, accion_tomada))
            conn.commit()


def obtener_logs_recientes(usuario_id: int, limite: int = 20) -> List[Dict[str, Any]]:
    sql = """
        SELECT * FROM LogsSeguridad
        WHERE usuario_id = %s
        ORDER BY fecha DESC
        LIMIT %s
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (usuario_id, limite))
            return cur.fetchall()


# ---------------------------------------------------------------------------
# Verificación Familiar (Desafío 2FA)
# ---------------------------------------------------------------------------

def obtener_preguntas_desafio(usuario_id: int) -> List[Dict[str, Any]]:
    """Retorna las preguntas de verificación familiar del usuario."""
    sql = """
        SELECT * FROM VerificacionFamiliar
        WHERE usuario_id = %s AND activa = 1
        ORDER BY RAND()
        LIMIT 3
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (usuario_id,))
            return cur.fetchall()


def registrar_intento_desafio(
    usuario_id: int, pregunta_id: int, respuesta_dada: str, correcto: bool
) -> None:
    sql = """
        INSERT INTO IntentosDesafio
            (usuario_id, pregunta_id, respuesta_dada, correcto, fecha)
        VALUES (%s, %s, %s, %s, NOW())
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (usuario_id, pregunta_id, respuesta_dada, int(correcto)))
            conn.commit()


# ---------------------------------------------------------------------------
# Inicialización de Tablas (DDL)
# ---------------------------------------------------------------------------

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS Roles (
    id      INT AUTO_INCREMENT PRIMARY KEY,
    nombre  VARCHAR(50) UNIQUE NOT NULL,
    nivel   TINYINT NOT NULL DEFAULT 1,
    descripcion TEXT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT IGNORE INTO Roles (nombre, nivel, descripcion) VALUES
    ('super_admin',    5, 'Acceso total incluye comandos de servidor'),
    ('familia_directa',4, 'Familia cercana con tono cálido'),
    ('amigo',          3, 'Amigos de confianza'),
    ('ex_pareja',      2, 'Tono profesional y distante'),
    ('desconocido',    1, 'Usuario nuevo sin perfil');

CREATE TABLE IF NOT EXISTS Usuarios (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    telefono         VARCHAR(20) UNIQUE NOT NULL,
    nombre           VARCHAR(100),
    rol_id           INT NOT NULL DEFAULT 1,
    activo           TINYINT NOT NULL DEFAULT 1,
    bloqueado        TINYINT NOT NULL DEFAULT 0,
    motivo_bloqueo   TEXT,
    fecha_registro   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ultimo_contacto  DATETIME,
    FOREIGN KEY (rol_id) REFERENCES Roles(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS MemoriaConversacion (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    usuario_id  INT NOT NULL,
    rol         ENUM('user','assistant') NOT NULL,
    contenido   TEXT NOT NULL,
    fecha       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (usuario_id) REFERENCES Usuarios(id),
    INDEX idx_usuario_fecha (usuario_id, fecha)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS LogsSeguridad (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    usuario_id    INT NOT NULL,
    evento        VARCHAR(100) NOT NULL,
    score_riesgo  FLOAT NOT NULL DEFAULT 0,
    detalle       TEXT,
    accion_tomada VARCHAR(100),
    fecha         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (usuario_id) REFERENCES Usuarios(id),
    INDEX idx_usuario_fecha (usuario_id, fecha)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS VerificacionFamiliar (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    usuario_id  INT NOT NULL,
    pregunta    TEXT NOT NULL,
    respuesta   VARCHAR(255) NOT NULL,
    activa      TINYINT NOT NULL DEFAULT 1,
    FOREIGN KEY (usuario_id) REFERENCES Usuarios(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS IntentosDesafio (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    usuario_id   INT NOT NULL,
    pregunta_id  INT NOT NULL,
    respuesta_dada VARCHAR(255),
    correcto     TINYINT NOT NULL DEFAULT 0,
    fecha        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (usuario_id) REFERENCES Usuarios(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS CategoriasTemas (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    nombre      VARCHAR(100) UNIQUE NOT NULL,
    descripcion TEXT,
    activa      TINYINT NOT NULL DEFAULT 1
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS PerfilLinguistico (
    usuario_id   INT PRIMARY KEY,
    estadisticas JSON NOT NULL,
    actualizado  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (usuario_id) REFERENCES Usuarios(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


def inicializar_schema() -> None:
    """Crea todas las tablas si no existen. Ejecutar una sola vez al arrancar."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            for statement in SCHEMA_SQL.strip().split(";"):
                stmt = statement.strip()
                if stmt:
                    try:
                        cur.execute(stmt)
                    except pymysql.MySQLError as e:
                        logger.warning(f"[DB] Schema: {e}")
            conn.commit()
    logger.info("[DB] Schema v2.0 verificado/creado correctamente.")

    # v4.0: inicializar tablas de memoria de largo plazo
    try:
        from memory_engine import inicializar_memoria
        inicializar_memoria()
        logger.info("[DB] Schema v4.0 (memoria) verificado/creado correctamente.")
    except Exception as e:
        logger.warning(f"[DB] Schema v4.0 no disponible: {e}")


if __name__ == "__main__":
    logging.basicConfig(level="INFO")
    inicializar_schema()
    print("✅ Base de datos inicializada.")
