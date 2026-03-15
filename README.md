# 🛡️ Guardián Digital v2.0

> **Sistema de seguridad perimetral para WhatsApp con IA y biometría conductual.**  
> Protege tu identidad, entorno familiar y administración de servidor desde un único bot.

---

## ¿Qué es?

Guardián Digital es un bot de WhatsApp construido con Python y Google Gemini que actúa como un **SOC personal** (Security Operations Center). Cada mensaje que llega pasa por un sistema de análisis multicapa antes de recibir respuesta, detectando impostores, ingeniería social y estafas en tiempo real.

No es un chatbot común. Es un sistema de seguridad que además puede conversar.

---

## ¿Cómo funciona?

```
WhatsApp
   │
   ▼
Evolution API (Baileys)
   │
   ▼
spam_guard.py ──────────── Primera capa: rate limiting O(1), sin DB
   │
   ▼
┌──────────────────────────────────────────────┐
│  Análisis en paralelo (asyncio.gather)       │
│                                              │
│  biometria.py      ¿Escribe como el dueño?   │
│  manipulacion.py   ¿Ingeniería social?        │
│  detector_estafas  ¿Intento de estafa?        │
└──────────────────────────────────────────────┘
   │
   ▼
score_engine.py ─────────── Score unificado 4 dimensiones
   │
   ▼
firewall.py ─────────────── PERMITIR / ALERTA / DESAFÍO 2FA / BLOQUEAR
   │
   ▼
ia_engine.py ────────────── Respuesta con Google Gemini (tono por rol)
   │
   ▼
WhatsApp
```

---

## Score de Riesgo (0–10)

El corazón del sistema. Cada mensaje recibe un score calculado con 4 dimensiones:

| Dimensión | Peso | Descripción |
|---|---|---|
| Biometría conductual | 40% | ¿El estilo de escritura coincide con el perfil guardado? |
| Manipulación | 30% | Patrones de ingeniería social, urgencia, presión emocional |
| Detector de estafas | 20% | "Hola mamá cambié de número", CBU sospechosos, promesas de dinero |
| Improvisación/Contexto | 10% | Rol del usuario, horario inusual, historial de incidentes |

| Score | Acción |
|---|---|
| ≥ 8.0 | 🔴 BLOQUEAR — respuesta neutra, sin información |
| ≥ 5.5 | 🟠 DESAFÍO 2FA — pregunta de verificación personal |
| ≥ 3.5 | 🟡 ALERTA — responder con cautela, registrar en logs |
| < 3.5 | 🟢 PERMITIR — conversación normal |

---

## Sistema de Roles

Cada número de WhatsApp tiene un rol asignado. Gemini adapta su tono automáticamente:

| Rol | Nivel | Tono | Permisos |
|---|---|---|---|
| `super_admin` | 5 | Técnico y directo | Comandos `/admin` de servidor |
| `familia_directa` | 4 | Cálido y afectuoso | Conversación completa |
| `amigo` | 3 | Casual y relajado | Conversación completa |
| `ex_pareja` | 2 | Profesional y distante | Limitado |
| `desconocido` | 1 | Cordial pero cauteloso | Mínimo |

---

## Módulos del sistema

| Archivo | Función |
|---|---|
| `score_engine.py` | Motor de score central — única fuente de verdad |
| `cache_perfiles.py` | Caché de perfiles lingüísticos (memoria o Redis) |
| `spam_guard.py` | Rate limiting y protección anti-flood |
| `biometria.py` | Análisis de huella digital conductual |
| `manipulacion.py` | 40+ patrones de ingeniería social en ES/EN |
| `detector_estafas.py` | Detección de estafas con heurístico + Gemini |
| `firewall.py` | Motor de decisión y desafío 2FA |
| `ia_engine.py` | Integración con Google Gemini (google-genai SDK) |
| `memoria.py` | Historial conversacional con RAG opcional |
| `perfil_usuario.py` | Aprendizaje continuo del perfil lingüístico |
| `sysadmin_engine.py` | Comandos de administración del servidor VPS |
| `vision_engine.py` | Análisis de imágenes con Gemini Vision (opcional) |
| `voice_engine.py` | Transcripción de audios con Whisper (opcional) |
| `main_guardian.py` | Orquestador principal |
| `whatsapp_gateway.py` | API FastAPI + parser de Evolution API |

---

## Stack tecnológico

- **Python 3.12** + FastAPI + Uvicorn
- **Google Gemini** (google-genai SDK) — modelo `gemini-1.5-flash`
- **MySQL / MariaDB** — almacenamiento principal
- **Evolution API** (Baileys) — gateway de WhatsApp
- **Nginx** — proxy inverso con SSL
- **Systemd** — proceso 24/7 con reinicio automático
- **Redis** (opcional) — caché de perfiles lingüísticos
- **ChromaDB** (opcional) — memoria RAG vectorial
- **Whisper** (opcional) — transcripción de notas de voz
- **Tesseract + Gemini Vision** (opcional) — detección de phishing visual

---

## Comandos /admin (solo super_admin)

Enviados como mensajes de WhatsApp desde el número administrador:

```
/admin status             → Estado de Nginx, PHP y MySQL
/admin uptime             → Tiempo activo del servidor
/admin disk               → Uso del disco
/admin ram                → Uso de memoria RAM
/admin cpu                → Uso de CPU
/admin restart_nginx      → Reiniciar Nginx
/admin restart_mysql      → Reiniciar MariaDB
/admin logs_nginx         → Últimas líneas del log de Nginx
/admin logs_guardian      → Logs del bot en tiempo real
/admin block_user <nro>   → Bloquear número
/admin unblock_user <nro> → Desbloquear número
```

---

## Instalación rápida

```bash
# 1. Clonar y preparar entorno
git clone https://github.com/tu_usuario/guardian-digital.git
cd guardian-digital
python3.12 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 2. Configurar credenciales
cp .env.example .env
nano .env

# 3. Crear base de datos
mysql -u root -p < database.sql

# 4. Instalar como servicio
cp guardian_bot.service /etc/systemd/system/
systemctl enable guardian_bot
systemctl start guardian_bot

# 5. Verificar
curl http://127.0.0.1:8000/bot-webhook/health
```

Ver la guía completa de despliegue en `GuardianDigital_v2_DeployGuide.docx`.

---

## Requisitos mínimos

- VPS con Ubuntu 22.04+
- Python 3.12+
- MySQL 8.0 / MariaDB 10.6+
- Nginx con SSL (Certbot)
- API Key de Google Gemini (gratuita en aistudio.google.com)
- Evolution API con WhatsApp vinculado

---

## Variables de entorno principales

```env
DB_HOST=localhost
DB_USER=guardian_user
DB_PASSWORD=tu_password
DB_NAME=guardian_bot

GEMINI_API_KEY=AIza...

EVOLUTION_API_URL=http://localhost:8080
EVOLUTION_API_KEY=tu_key
EVOLUTION_INSTANCE=guardian_instance

# Pesos del score (deben sumar 1.0)
SCORE_PESO_BIOMETRIA=0.40
SCORE_PESO_MANIPULACION=0.30
SCORE_PESO_ESTAFA=0.20
SCORE_PESO_IMPROVISACION=0.10

# Módulos opcionales
VISION_ENABLED=false
VOICE_ENABLED=false
RAG_ENABLED=false
```

---

## Arquitectura de seguridad

```
Mensaje entrante
       │
       ▼
[1] spam_guard ──── ¿Flood? ¿30 msgs/min? → Bloqueo temporal 5 min
       │
       ▼
[2] biometría ────── ¿Escribe diferente al perfil guardado? → +score
       │
       ▼
[3] manipulación ─── ¿Urgencia / presión / amenaza? → +score
       │
       ▼
[4] estafas ─────── ¿"Soy tu hijo, cambié de número"? → +score
       │
       ▼
[5] score_engine ─── Suma ponderada → 0 a 10
       │
       ├─ ≥8.0 → BLOQUEAR
       ├─ ≥5.5 → DESAFÍO: "¿Cuál es el nombre de nuestra mascota?"
       ├─ ≥3.5 → ALERTA: responder con cautela
       └─ <3.5 → PERMITIR: conversación normal con Gemini
```

---

## Licencia

Proyecto personal. Uso libre para fines educativos y personales.

---

*Desarrollado para proteger a las personas reales detrás de los teléfonos.*