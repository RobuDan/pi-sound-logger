#!/bin/bash
# Master orchestrator for Pi deployment

set -e

cd "$(dirname "$0")"

echo "[DEPLOY] ==== Pi Sound Logger Deployment Script ===="

# Check variables.env exists
if [ ! -f variables.env ]; then
    echo "[ERROR] variables.env not found! Please copy variables.env.example and fill in your details."
    exit 1
fi

# Source variables
source variables.env

echo "[DEPLOY] [1/6] Installing MariaDB and securing database..."
./mariadb_setup.sh

echo "[DEPLOY] [2/6] Setting up WiFi configuration..."
./wifi_setup.sh

echo "[DEPLOY] [3/6] Installing Apache, PHP, and phpMyAdmin..."
./phpmyadmin_setup.sh

echo "[DEPLOY] [4/6] Building Python 3.10.0, creating venv, and installing requirements..."
./venv_setup.sh

echo "[DEPLOY] [5/6] Creating and enabling app systemd service..."
./systemd_setup.sh

echo "[DEPLOY] [6/6] All steps complete! Pi Sound Logger should now be running on reboot or after network comes up."

echo "[DEPLOY] You can check your app's status with:"
echo "  sudo systemctl status ${SERVICE_NAME}.service"
echo "And access phpMyAdmin at:"
echo "  http://$(hostname -I | awk '{print $1}')/phpmyadmin"
