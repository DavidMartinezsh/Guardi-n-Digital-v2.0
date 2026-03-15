#!/bin/bash
# ==============================================================================
# GUARDIÁN DIGITAL v2.0 - deploy.sh
# Script de instalación y despliegue en VPS Ubuntu.
# Uso: sudo bash deploy.sh
# ==============================================================================

set -e

APP_DIR="/opt/guardian_digital"
APP_USER="guardian"
SERVICE_FILE="/etc/systemd/system/guardian-digital.service"
NGINX_CONF="/etc/nginx/sites-available/guardian"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

info()    { echo -e "${GREEN}[INFO]${NC} $1"; }
warning() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error()   { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# ─── Verificar root ───────────────────────────────────────────────────────────
[[ "$EUID" -ne 0 ]] && error "Ejecutar como root: sudo bash deploy.sh"

info "🛡️  Iniciando despliegue de Guardián Digital v2.0..."

# ─── Dependencias del sistema ─────────────────────────────────────────────────
info "Actualizando sistema e instalando dependencias..."
apt-get update -qq
apt-get install -y -qq \
    python3.12 python3.12-venv python3-pip \
    mysql-client libmysqlclient-dev \
    nginx certbot python3-certbot-nginx \
    ffmpeg tesseract-ocr tesseract-ocr-spa \
    git curl

# ─── Crear usuario del sistema ────────────────────────────────────────────────
if ! id "$APP_USER" &>/dev/null; then
    info "Creando usuario del sistema '$APP_USER'..."
    useradd --system --shell /bin/bash --home "$APP_DIR" --create-home "$APP_USER"
fi

# ─── Copiar archivos de la aplicación ────────────────────────────────────────
info "Copiando archivos a $APP_DIR..."
mkdir -p "$APP_DIR"
cp -r ./* "$APP_DIR/"
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

# ─── Entorno virtual Python ───────────────────────────────────────────────────
info "Creando entorno virtual Python..."
sudo -u "$APP_USER" python3.12 -m venv "$APP_DIR/venv"
sudo -u "$APP_USER" "$APP_DIR/venv/bin/pip" install --upgrade pip -q
sudo -u "$APP_USER" "$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt" -q

# ─── Directorios de datos ─────────────────────────────────────────────────────
info "Creando directorios de datos..."
mkdir -p /var/guardian/chroma_db /tmp/guardian_audio
touch /var/log/guardian_digital.log
chown -R "$APP_USER:$APP_USER" /var/guardian /tmp/guardian_audio /var/log/guardian_digital.log

# ─── Verificar .env ───────────────────────────────────────────────────────────
if [ ! -f "$APP_DIR/.env" ]; then
    warning ".env no encontrado. Copiando plantilla..."
    cp "$APP_DIR/.env.example" "$APP_DIR/.env"
    warning "⚠️  IMPORTANTE: Edita $APP_DIR/.env con tus credenciales reales."
    warning "    Luego ejecuta: systemctl start guardian-digital"
fi

# ─── Inicializar base de datos ────────────────────────────────────────────────
info "Inicializando schema de base de datos..."
cd "$APP_DIR"
sudo -u "$APP_USER" "$APP_DIR/venv/bin/python" db.py || warning "Schema ya inicializado o error de conexión."

# ─── Servicio systemd ─────────────────────────────────────────────────────────
info "Creando servicio systemd..."
cat > "$SERVICE_FILE" << EOF
[Unit]
Description=Guardián Digital v2.0 - WhatsApp Security Bot
After=network.target mysql.service

[Service]
Type=exec
User=$APP_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
ExecStart=$APP_DIR/venv/bin/python whatsapp_gateway.py
Restart=always
RestartSec=5
StandardOutput=append:/var/log/guardian_digital.log
StandardError=append:/var/log/guardian_digital.log

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable guardian-digital
info "Servicio 'guardian-digital' habilitado."

# ─── Configuración Nginx ──────────────────────────────────────────────────────
info "Configurando Nginx como proxy inverso..."
cat > "$NGINX_CONF" << 'EOF'
server {
    listen 80;
    server_name fusionshaiya.com www.fusionshaiya.com;

    location /bot-webhook/ {
        proxy_pass         http://127.0.0.1:8000/bot-webhook/;
        proxy_http_version 1.1;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_read_timeout 30s;
        client_max_body_size 15M;
    }
}
EOF

ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/guardian
nginx -t && systemctl reload nginx

# ─── SSL con Certbot ──────────────────────────────────────────────────────────
info "Solicitando certificado SSL..."
certbot --nginx -d fusionshaiya.com --non-interactive --agree-tos \
    -m admin@fusionshaiya.com || warning "Certbot falló. Verifica el dominio."

# ─── Sudoers para comandos del sistema ────────────────────────────────────────
info "Configurando sudoers para comandos de sistema..."
SUDOERS_FILE="/etc/sudoers.d/guardian"
cat > "$SUDOERS_FILE" << EOF
# Guardián Digital - Comandos permitidos sin contraseña
$APP_USER ALL=(ALL) NOPASSWD: /bin/systemctl restart nginx
$APP_USER ALL=(ALL) NOPASSWD: /bin/systemctl restart php8.2-fpm
$APP_USER ALL=(ALL) NOPASSWD: /bin/systemctl restart mysql
$APP_USER ALL=(ALL) NOPASSWD: /bin/systemctl status nginx php8.2-fpm mysql
EOF
chmod 440 "$SUDOERS_FILE"

# ─── Resumen ──────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   ✅  Guardián Digital v2.0 instalado             ║${NC}"
echo -e "${GREEN}╠══════════════════════════════════════════════════╣${NC}"
echo -e "${GREEN}║  1. Edita:   $APP_DIR/.env            ║${NC}"
echo -e "${GREEN}║  2. Inicia:  systemctl start guardian-digital     ║${NC}"
echo -e "${GREEN}║  3. Estado:  systemctl status guardian-digital    ║${NC}"
echo -e "${GREEN}║  4. Logs:    tail -f /var/log/guardian_digital.log║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════╝${NC}"
