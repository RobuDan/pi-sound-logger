#!/bin/bash
# Run explicitly on the Raspberry Pi. Does not start a shutdown countdown.
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ ${EUID} -ne 0 ]]; then
    echo "Run: sudo bash install.sh" >&2
    exit 1
fi
if [[ ! -e /dev/i2c-1 ]]; then
    echo "Enable I2C in raspi-config and reboot first; /dev/i2c-1 is missing." >&2
    exit 1
fi

apt-get update
apt-get install -y python3-smbus2 i2c-tools

# Replace the previously discussed units; leave the old CSV untouched.
systemctl stop ups-logger.service 2>/dev/null || true
systemctl stop upsv6-config.service 2>/dev/null || true
if systemctl cat ups-config.service >/dev/null 2>&1; then
    systemctl disable --now ups-config.service
fi

# Do not raise hardware protection around an already depleted battery.
/usr/bin/python3 - <<'PY'
from smbus2 import SMBus
from ups_logger import Device, Settings

settings = Settings.load("upsv6.json")
with SMBus(settings.bus) as bus:
    sample = Device(bus, settings.address).read()
if (not sample["sample_valid"] or sample["input_mv"] < 4000
        or sample["battery_mv"] <= settings.software_shutdown_mv):
    raise SystemExit("Connect external power and charge above the software shutdown threshold before installation.")
print(f"Preflight: input={sample['input_mv']}mV battery={sample['battery_mv']}mV")
PY

install -d -m 0750 /var/log/upsv6
install -d -m 0755 /run/upsv6
install -m 0755 ups_logger.py /usr/local/sbin/ups_logger.py
if [[ -e /etc/upsv6.json ]]; then
    cp -p /etc/upsv6.json "/etc/upsv6.json.backup.$(date +%s)"
fi
install -m 0644 upsv6.json /etc/upsv6.json
install -m 0644 upsv6-config.service ups-logger.service /etc/systemd/system/

# The existing deployment uses TimeoutStopSec=10. Allow more cleanup time.
app_service="${APP_SERVICE:-pi-sound-logger.service}"
if [[ ! "$app_service" =~ ^[a-zA-Z0-9_.@-]+\.service$ ]]; then
    echo "APP_SERVICE must be a systemd service name." >&2
    exit 1
fi
if systemctl cat "$app_service" >/dev/null 2>&1; then
    install -d -m 0755 "/etc/systemd/system/${app_service}.d"
    cat >"/etc/systemd/system/${app_service}.d/upsv6-stop-timeout.conf" <<'UNIT'
[Service]
TimeoutStopSec=60
UNIT
    echo "Allowed 60 seconds for ${app_service} to stop."
else
    echo "No ${app_service} found; check your actual application's stop timeout."
fi

systemctl daemon-reload
systemctl enable upsv6-config.service ups-logger.service
if ! systemctl restart upsv6-config.service; then
    echo "Configuration attempt failed; waiting up to 35 seconds for the service's automatic retries."
fi
config_deadline=$((SECONDS + 35))
until systemctl is-active --quiet upsv6-config.service; do
    if (( SECONDS >= config_deadline )); then
        echo "UPS configuration did not succeed; monitoring was not started. Recent errors:" >&2
        journalctl -u upsv6-config.service -b -n 80 --no-pager -o cat >&2 || true
        exit 1
    fi
    sleep 1
done
systemctl start ups-logger.service
systemctl --no-pager --full status upsv6-config.service ups-logger.service
echo "Logs: /var/log/upsv6 ; configuration: /etc/upsv6.json"
