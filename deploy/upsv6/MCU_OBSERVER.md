# Observe the UPS while Linux is off

This is an explicit diagnostic tool, separate from the normal installation.
It uploads `mcu_observer.py` to the UPS PikaPython interpreter using the audited
manufacturer uploader. It replaces any existing user PikaPython application.
It does not flash firmware or change power thresholds. The observer itself
only calls telemetry getters and `Device.sleep`; it cannot turn the output on,
reset auto-start lockout, or request shutdown.

The manufacturer states that uploaded Python continues after the Pi and UPS
output shut down, until the controller loses all power:
https://github.com/geeekpi/upsv6_pub/blob/main/script/pikaPython_examples/TFT_Module/README.md

The host uploader and output-reader use the manufacturer's upload/FIFO registers:
https://github.com/geeekpi/upsv6_pub/blob/3df938a02730f67bce4391d4f746c473b168a409/script/pikaPython_examples/rpi.py

The program is below the uploader's 4096-byte limit. CPython simulation tests
verify its event policy, not PikaPython compatibility or hardware behavior.
The setup checks actual interpreter feedback before declaring startup verified.

## First check: external power stays connected

Keep the input connected and battery above 8000 mV. Stop any manually launched
vendor reader. From the existing project clone:

```bash
cd ~/pi-sound-logger-ups
git switch codex/ups-v6-logging-graceful-shutdown
git pull --ff-only origin codex/ups-v6-logging-graceful-shutdown
python3 -m unittest discover -s deploy/upsv6 -p 'test_*.py' -v
cd deploy/upsv6
sudo bash setup_mcu_observer.sh
sudo systemctl status ups-logger.service --no-pager
```

The setup downloads a fixed, checksum-verified manufacturer tool, pauses the
Pi logger, checks safe initial conditions without writing power registers,
saves previous MCU output, uploads the observer, waits eight seconds and saves
the startup feedback. It restores a previously running logger even on failure.
The uploader may take several minutes. Do not interrupt its upload or remove
external power. No Linux reboot is needed for this observer upload.

Proceed only if feedback contains all three:

```text
UPS_OBSERVER_V1
OBS,...
OBS_LIVE
```

The `Device.getInfo()` result is included to help identify the firmware build.
If startup is not verified, share the feedback before a discharge test. The
vendor uploader can exit zero even after printing an error, so its completion
message alone is not sufficient. An interpreter exception is not success.

## One recovery test after successful observer startup

Keep the existing 7400/7600/8000 mV configuration. Do not manually halt Linux or
write the countdown. Follow the normal Pi monitor while unplugging external
input:

```bash
sudo journalctl -u ups-logger.service -f
```

Let the existing monitor detect sustained low battery and request shutdown.
Record whether the UPS output really switches off after its timer. Restore
external input after the intended cutoff. Record whether the Pi returns by
itself, any repeated output/start attempts, and whether either button was used.
Once recovered, retrieve MCU feedback before another upload or total UPS reset.
If manual recovery is necessary, it may generate another output transition;
note that the last transition followed your button press.

## Retrieve evidence after recovery

Keep external power connected. This uses the manufacturer output reader, which
clears the MCU output buffer after reading. `tee` saves its printed result.
Read once and retain the file. Do not run the observer upload again beforehand.

```bash
sudo bash -s <<'SH'
set -euo pipefail
prior_state=$(systemctl show ups-logger.service -p ActiveState --value)
restore_monitor() {
    if [[ "$prior_state" == active || "$prior_state" == activating || "$prior_state" == reloading ]]; then
        systemctl start ups-logger.service
    fi
}
trap restore_monitor EXIT
systemctl stop ups-logger.service
stamp=$(date -u +%Y%m%dT%H%M%SZ)-$$
python3 /var/lib/upsv6-observer/rpi.py -r \
    | tee "/var/log/upsv6/mcu-observer-recovery-${stamp}.txt"
SH

sudo tar -C /var/log -czf - upsv6 > ~/upsv6-logs.tar.gz
```

Transfer the archive as before. It now includes both Pi CSVs and MCU `.txt`
feedback. The startup output was cleared and saved before the test; it remains
in a separate startup file. Use both files together for the event baseline.

## Interpret the records

Each transition line has this order:

```text
OBS,runtime_ms,input_mv,battery_mv,output_mv,input_state,output_state,battery_zone
```

- `runtime_ms`: UPS MCU runtime; unaffected by Pi wall-clock/NTP jumps. It is
  useful for ordering, not an independently calibrated physical timer.
- `input_state`: 1 above 4000 mV, 0 below 1000 mV, previous state between them.
  This is an observer estimate, not the native firmware's input-valid flag.
- `output_state`: 0 below 1000 mV, 1 for an intermediate rail, 2 at/above 4500 mV.
- `battery_zone`: 0 at/below 7600 mV, 2 above 8000 mV, otherwise 1, with 50 mV
  hysteresis to suppress repeated messages around thresholds. These markers
  are estimates and do not change the native protection or restart settings.

An output transition to zero after Linux stops would support actual output
cutoff. A later record with high input, battery above 8000 mV, and output still
zero supports a failure to restore output. Output returning then collapsing
would support failed start attempts. Identify manual button events separately.

## Limits

Only state changes are printed, with a cap of 24 records and a single
`OBS_LIVE` startup marker. `OBS_LIMIT` means later transitions were not printed;
do not interpret missing later transitions as stable output in that case.
There is no steady heartbeat during hours of unchanged state. Event output is
kept small, but actual firmware buffer capacity and retention are not established.

These are the MCU firmware's reported readings. They do not independently prove
the physical rail voltage, CR1, or a firmware lockout reason. A meter is still
the independent reference if reported output is stale or inconsistent.
The MCU APIs do not expose CR1 or retry control. Losing all controller power,
replacing/restarting its application, or firmware buffer behavior can lose
evidence. Empty output alone is not proof the UPS failed to cut or restart.
The running script may not survive total controller power loss; do not claim
this is persistent storage or an autonomous recovery fix.

The observer keeps running after feedback is retrieved. There is no documented
standalone stop command for a running PikaPython application, nor a guarantee
that its uploaded application is reloaded after a total controller reset.
Do not flash firmware merely to stop it, and do not assume stopping the Pi
logger stops the UPS-side observer.
