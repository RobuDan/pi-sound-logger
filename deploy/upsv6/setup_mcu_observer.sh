#!/bin/bash
# Explicit diagnostic setup; does not flash firmware or change power thresholds.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ ${EUID} -ne 0 ]]; then
    echo "Run: sudo bash setup_mcu_observer.sh" >&2
    exit 1
fi

apt-get update
apt-get install -y python3-smbus python3-smbus2 curl
install -d -m 0755 /var/lib/upsv6-observer

# Use the audited manufacturer uploader, with a fixed revision and checksum.
vendor_sha=e6048387e673be7b46f7085fc79634825dcfb2bd078996f9da840873615e636f
curl --fail --location --connect-timeout 15 --max-time 90 \
    https://raw.githubusercontent.com/geeekpi/upsv6_pub/3df938a02730f67bce4391d4f746c473b168a409/script/pikaPython_examples/rpi.py \
    -o /var/lib/upsv6-observer/rpi.py
printf '%s  %s\n' "$vendor_sha" /var/lib/upsv6-observer/rpi.py | sha256sum --check --status
install -m 0644 mcu_observer.py /var/lib/upsv6-observer/mcu_observer.py

# Preserve the monitor's state even if upload or interpreter validation fails.
prior_state=$(systemctl show ups-logger.service -p ActiveState --value)
restore_monitor() {
    if [[ "$prior_state" == active || "$prior_state" == activating || "$prior_state" == reloading ]]; then
        systemctl start ups-logger.service || echo "ERROR: restart ups-logger.service manually." >&2
    fi
}
trap restore_monitor EXIT
systemctl stop ups-logger.service

/usr/bin/python3 - <<'PY'
from pathlib import Path
import time
from smbus2 import SMBus
from ups_logger import Device, Settings

settings = Settings.load("/etc/upsv6.json")
if settings.bus != 1 or settings.address != 0x17:
    raise SystemExit("The manufacturer uploader only supports bus 1, address 0x17.")
if settings.software_shutdown_mv != 7600 or settings.restart_mv != 8000:
    raise SystemExit("This observer's battery-zone markers expect the current 7600/8000 mV settings.")
if Path(settings.shutdown_state_file).exists():
    raise SystemExit("Shutdown already committed. Do not upload or remove the marker; finish that power cycle first.")
with SMBus(1) as bus:
    device = Device(bus, 0x17)
    for attempt in range(3):
        sample = device.read()
        if sample["sample_valid"]:
            break
        time.sleep(0.1)
if (not sample["sample_valid"] or sample["input_mv"] < 4000
        or sample["battery_mv"] <= settings.restart_mv
        or not sample["auto_start"] or sample["shutdown_countdown_s"]
        or sample["protection_mv"] != settings.protection_mv
        or sample["restart_mv"] != settings.restart_mv):
    raise SystemExit("Need external input, battery >8000 mV, matching thresholds, enabled auto-start, and no active countdown.")
print(f"Observer preflight: input={sample['input_mv']}mV battery={sample['battery_mv']}mV auto-start=ON")
PY

install -d -m 0750 /var/log/upsv6
stamp=$(date -u +%Y%m%dT%H%M%SZ)-$$
tool=/var/lib/upsv6-observer/rpi.py
# Preserve any earlier interpreter output before replacing its application.
/usr/bin/python3 "$tool" -r | tee "/var/log/upsv6/mcu-observer-prior-${stamp}.txt"
/usr/bin/python3 "$tool" -u /var/lib/upsv6-observer/mcu_observer.py \
    | tee "/var/log/upsv6/mcu-observer-upload-${stamp}.txt"
sleep 8
feedback="/var/log/upsv6/mcu-observer-startup-${stamp}.txt"
/usr/bin/python3 "$tool" -r | tee "$feedback"

# The vendor CLI may print an error and still exit zero: check actual feedback.
if ! grep -q '^UPS_OBSERVER_V1' "$feedback" \
        || ! grep -q '^OBS,' "$feedback" \
        || ! grep -q '^OBS_LIVE' "$feedback"; then
    echo "Observer startup NOT verified. Keep external power connected and share $feedback." >&2
    exit 1
fi
echo "Observer startup verified. The Pi monitor will now be restored."
echo "Startup evidence: $feedback"
echo "Read MCU_OBSERVER.md before the recovery test."
