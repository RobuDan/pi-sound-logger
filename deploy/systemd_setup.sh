#!/bin/bash
# Creates and enables a systemd service for your Python app
set -e

cd "$(dirname "$0")"
if [ -f variables.env ]; then
    source variables.env
fi

# Defaults
SERVICE_NAME="${SERVICE_NAME:-pi-sound-logger}"
SERVICE_DESC="${SERVICE_DESC:-Pi Sound Logger Service}"
SERVICE_USER="${SERVICE_USER:-pi}"
PROJECT_ROOT="${PROJECT_ROOT:-/home/pi/pi-sound-logger}"
PYTHON_BIN="${PYTHON_BIN:-$PROJECT_ROOT/.venv/bin/python}"
APP_ENTRY="${APP_ENTRY:-src/main.py}"

SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

echo "[INFO] Creating systemd service at $SERVICE_FILE ..."

sudo tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=$SERVICE_DESC
After=network.target

[Service]
User=$SERVICE_USER
WorkingDirectory=$PROJECT_ROOT
ExecStartPre=/bin/sleep 12
ExecStartPre=/usr/bin/udevadm settle
ExecStart=$PYTHON_BIN $PROJECT_ROOT/$APP_ENTRY
Restart=always
KillSignal=SIGTERM
TimeoutStopSec=10

[Install]
WantedBy=multi-user.target
EOF

echo "[INFO] Reloading systemd, enabling, and starting service..."

sudo systemctl daemon-reload
sudo systemctl enable "${SERVICE_NAME}.service"
sudo systemctl restart "${SERVICE_NAME}.service"

echo "[SUCCESS] Service '${SERVICE_NAME}' is now enabled and running."
sudo systemctl status "${SERVICE_NAME}.service" --no-pager
