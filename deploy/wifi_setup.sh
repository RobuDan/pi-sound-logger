#!/bin/bash
# WiFi setup: Writes wpa_supplicant.conf using values from variables.env
set -e

cd "$(dirname "$0")"

# Load WiFi settings from variables.env, or prompt for them
if [ -f variables.env ]; then
    source variables.env
fi

WIFI_SSID="${WIFI_SSID:-HUAWEI-B311-EC9F}"
WIFI_PASS="${WIFI_PASS:-Unu23456}"
WIFI_COUNTRY="${WIFI_COUNTRY:-RO}"

WPA_CONF="/etc/wpa_supplicant/wpa_supplicant.conf"

echo "[INFO] Backing up old $WPA_CONF as $WPA_CONF.bak_$(date +%Y%m%d_%H%M%S)"
sudo cp "$WPA_CONF" "$WPA_CONF.bak_$(date +%Y%m%d_%H%M%S)" 2>/dev/null || true

echo "[INFO] Writing new $WPA_CONF"

sudo tee "$WPA_CONF" > /dev/null <<EOF
ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
update_config=1
country=$WIFI_COUNTRY

network={
    ssid="$WIFI_SSID"
    psk="$WIFI_PASS"
    scan_ssid=1
    key_mgmt=WPA-PSK
    priority=1
    id_str="main_wifi"
    ap_scan=1
    retry=forever
}
EOF

echo "[INFO] Enabling wpa_supplicant.service"
sudo systemctl enable wpa_supplicant.service

echo "[INFO] Restarting networking to apply WiFi changes"
sudo systemctl restart dhcpcd.service || echo "[WARN] dhcpcd.service not found, may not be needed on all Pi images"
sudo systemctl restart wpa_supplicant.service

echo "[SUCCESS] WiFi config applied. The Pi should auto-connect to $WIFI_SSID on reboot or network restart."
echo "If you are on a headless setup, disconnect and reconnect power if not automatically on WiFi after ~30 seconds."
