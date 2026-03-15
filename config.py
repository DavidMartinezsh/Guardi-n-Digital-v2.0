# ==============================================================================
# GUARDIÁN DIGITAL v2.0 - config.py
# Centraliza todas las credenciales, parámetros y constantes del sistema.
# ==============================================================================

import os
from dotenv import load_dotenv

load_dotenv()

# --- Servidor & Identidad ---
VPS_IP = "161.97.129.40"
WEBHOOK_URL = "https://fusionshaiya.com/bot-webhook/webhook"
BOT_PORT = 8000

# --- Base de Datos MySQL ---
DB_CONFIG = {
    "host":     os.getenv("DB_HOST", "localhost"),
    "port":     int(os.getenv("DB_PORT", 3306)),
    "user":     os.getenv("DB_USER", "guardian_user"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME", "guardian_bot"),
    "charset":  "utf8mb4",
    "autocommit": True,
}

# --- Google Gemini ---
GEMINI_API_KEY   = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL     = "gemini-1.5-flash"
GEMINI_MAX_TOKENS = 1024
GEMINI_TEMP      = 0.7

# --- Evolution API (WhatsApp Gateway) ---
EVOLUTION_API_URL     = os.getenv("EVOLUTION_API_URL", "http://localhost:8080")
EVOLUTION_API_KEY     = os.getenv("EVOLUTION_API_KEY", "")
EVOLUTION_INSTANCE    = os.getenv("EVOLUTION_INSTANCE", "guardian_instance")

# --- Umbrales del Firewall ---
UMBRAL_BLOQUEO  = 8.0   # Score ≥ este valor  → bloquear conversación
UMBRAL_DESAFIO  = 5.5   # Score ≥ este valor  → lanzar desafío 2FA
UMBRAL_ALERTA   = 3.5   # Score ≥ este valor  → registrar en LogsSeguridad

# --- Biometría Conductual ---
BIOMETRIA_VENTANA_MENSAJES = 30   # Últimos N mensajes para calcular el perfil
BIOMETRIA_UMBRAL_SIMILITUD = 0.45 # Similitud mínima para considerar "es el mismo usuario"
BIOMETRIA_PESO_EMOJI       = 0.25
BIOMETRIA_PESO_LONGITUD    = 0.35
BIOMETRIA_PESO_ESTILO      = 0.40

# --- Memoria Conversacional ---
MEMORIA_VENTANA_CORTO = 5    # Mensajes recientes para contexto inmediato
MEMORIA_VENTANA_LARGO = 50   # Mensajes para perfil biométrico histórico

# --- RAG (Vector Store) ---
RAG_ENABLED           = os.getenv("RAG_ENABLED", "false").lower() == "true"
RAG_COLLECTION_NAME   = "guardian_memory"
RAG_EMBED_MODEL       = "models/embedding-001"   # Google Embedding
RAG_TOP_K             = 5
CHROMA_PERSIST_DIR    = os.getenv("CHROMA_PERSIST_DIR", "/var/guardian/chroma_db")

# --- Vision (Análisis de Imágenes) ---
VISION_ENABLED        = os.getenv("VISION_ENABLED", "false").lower() == "true"
VISION_MAX_FILE_MB    = 10
VISION_PHISHING_KEYWORDS = [
    "verifica tu cuenta", "clic aquí", "acceso suspendido",
    "ingresa tu contraseña", "premio", "ganaste", "urgente",
    "verify your account", "click here", "suspended",
]

# --- Procesamiento de Voz ---
VOICE_ENABLED         = os.getenv("VOICE_ENABLED", "false").lower() == "true"
WHISPER_MODEL         = os.getenv("WHISPER_MODEL", "base")  # tiny/base/small/medium
VOICE_TEMP_DIR        = "/tmp/guardian_audio"

# --- Roles del Sistema ---
ROLES = {
    "super_admin":    {"nivel": 5, "alias": "Administrador"},
    "familia_directa":{"nivel": 4, "alias": "Familia"},
    "amigo":          {"nivel": 3, "alias": "Amigo/a"},
    "ex_pareja":      {"nivel": 2, "alias": "Conocido/a"},
    "desconocido":    {"nivel": 1, "alias": "Desconocido"},
}

# --- Comandos Administrativos ---
ADMIN_PREFIX = "/admin"
ADMIN_COMANDOS_PERMITIDOS = [
    "status", "restart_nginx", "restart_php", "restart_mysql",
    "uptime", "logs_nginx", "logs_php", "logs_guardian",
    "disk", "ram", "cpu", "block_user", "unblock_user",
]

# --- Caché de Perfiles ---
REDIS_ENABLED          = os.getenv("REDIS_ENABLED", "false").lower() == "true"
REDIS_URL              = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CACHE_TTL_SEGUNDOS     = int(os.getenv("CACHE_TTL_SEGUNDOS", 3600))   # 1 hora

# --- Protección Anti-Spam ---
SPAM_VENTANA_SEGUNDOS     = int(os.getenv("SPAM_VENTANA_SEGUNDOS",    60))
SPAM_MAX_MENSAJES         = int(os.getenv("SPAM_MAX_MENSAJES",         30))
SPAM_MAX_IDENTICOS        = int(os.getenv("SPAM_MAX_IDENTICOS",         5))
SPAM_INTERVALO_MIN_MS     = int(os.getenv("SPAM_INTERVALO_MIN_MS",    300))
SPAM_BLOQUEO_TEMPORAL_SEG = int(os.getenv("SPAM_BLOQUEO_TEMPORAL_SEG", 300))

# --- Score Central ---
# Pesos para score_engine.py (deben sumar 1.0)
SCORE_PESO_BIOMETRIA     = float(os.getenv("SCORE_PESO_BIOMETRIA",    0.40))
SCORE_PESO_MANIPULACION  = float(os.getenv("SCORE_PESO_MANIPULACION", 0.30))
SCORE_PESO_ESTAFA        = float(os.getenv("SCORE_PESO_ESTAFA",       0.20))
SCORE_PESO_IMPROVISACION = float(os.getenv("SCORE_PESO_IMPROVISACION",0.10))

# --- Logging ---
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE  = os.getenv("LOG_FILE", "/var/log/guardian_digital.log")

# ==============================================================================
# GUARDIÁN DIGITAL v4.0 — Configuración adicional
# ==============================================================================

# --- Archivos de personalidad ---
PERSONALITY_FILE     = os.getenv("PERSONALITY_FILE",     "/home/guardian_bot/personality.yaml")
VALUES_FILE          = os.getenv("VALUES_FILE",          "/home/guardian_bot/values.json")

# --- Directorios de datos familiares ---
FAMILY_PROFILES_DIR  = os.getenv("FAMILY_PROFILES_DIR",  "/var/guardian/family")
DIARY_DIR            = os.getenv("DIARY_DIR",            "/var/guardian/diary")
STORY_DIR            = os.getenv("STORY_DIR",            "/var/guardian/story")
LEGACY_FILE          = os.getenv("LEGACY_FILE",          "/var/guardian/legacy_config.json")

# --- Módulos v4.0 (todos opcionales, activar gradualmente) ---
EMOTION_ENABLED      = os.getenv("EMOTION_ENABLED",  "true").lower()  == "true"
DECISION_ENABLED     = os.getenv("DECISION_ENABLED", "true").lower()  == "true"
MEMORY_ENABLED       = os.getenv("MEMORY_ENABLED",   "true").lower()  == "true"
FAMILY_ENABLED       = os.getenv("FAMILY_ENABLED",   "true").lower()  == "true"
DIARY_ENABLED        = os.getenv("DIARY_ENABLED",    "true").lower()  == "true"
TWIN_ENABLED         = os.getenv("TWIN_ENABLED",     "true").lower()  == "true"
LEGACY_ENABLED       = os.getenv("LEGACY_ENABLED",   "false").lower() == "true"
DOC_ENABLED          = os.getenv("DOC_ENABLED",      "false").lower() == "true"
