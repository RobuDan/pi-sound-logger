# UPS Gen 6 logging and coordinated shutdown

This is a standalone Raspberry Pi OS service. It uses the system Python and
`python3-smbus2`; it does not depend on the sound logger's virtual environment.
The current Windows workspace cannot validate actual UPS power switching.

The existing simple CSV logger and boot configuration do **not** implement
graceful low-battery shutdown. This replacement does. Linux/systemd must still
successfully finish stopping the application, databases, and filesystems before
the physical UPS countdown expires. A successful poweroff request is not proof
that every service finished cleanly.

## Initial test configuration

| Setting | Value | Purpose |
| --- | ---: | --- |
| `protection_mv` | 7400 | Native hardware emergency fallback |
| `software_shutdown_mv` | 7600 | Normal software shutdown trigger |
| `restart_mv` | 8000 | Battery reserve before automatic startup |
| `low_battery_hold_seconds` | 15 | Continuous valid low readings required |
| `cutoff_delay_seconds` | 120 | Physical power cutoff, counted from arming |
| `pre_poweroff_log_seconds` | 5 | Short observation window after arming, before requesting Linux shutdown |

The manufacturer's register table lists **7400 mV for both protection and
restart**. Only the 7400 mV fallback here is that default. The 7600/8000 values
are deliberately separated test settings, not manufacturer recommendations or
a guarantee of successful recovery. The manufacturer's sample monitor uses
7400 mV for Linux shutdown; using that simultaneously as the hardware cutoff
does not leave an earlier software trigger.

Sources:
- [UPS features and registers](https://wiki.52pi.com/index.php?title=EP-0245)
- [Manufacturer's battery monitor](https://github.com/geeekpi/upsv6_pub/blob/main/script/tools/python_demo/battery_monitor.py)
- [C register definitions](https://github.com/geeekpi/upsv6_pub/blob/main/script/tools/read_device.c)

## Install on the Pi

1. Connect external power and charge above 7600 mV before installation. Keep
   I2C enabled (`raspi-config` -> Interface Options -> I2C). Stop any manually
   launched old UPS Python logger with Ctrl+C. The installer replaces the
   `ups-logger.service` and `upsv6-config.service` discussed in this chat and
   disables the alternative `ups-config.service` if installed. Do not run both
   old and new loggers, or another battery-monitor daemon, during the test.
2. Copy this entire folder to the Pi, for example as `~/upsv6`. If using the
   supplied ZIP, copy it to `~/upsv6-setup.zip`, then run:

   ```bash
   python3 -m zipfile -e ~/upsv6-setup.zip ~
   cd ~/upsv6
   sudo bash install.sh
   ```

   The installer **enables automatic low-battery shutdown**. It installs the
   script at `/usr/local/sbin/ups_logger.py`, configuration at
   `/etc/upsv6.json`, and logs at `/var/log/upsv6`. It preserves the old
   `~/ups_discharge.csv` and backs up any existing `/etc/upsv6.json`.

   When `pi-sound-logger.service` exists, it adds a systemd drop-in allowing
   that application 60 seconds to stop (the repository's existing deployment
   allows only 10). It does not restart the sound application during installation.
   For another application service name, use:

   ```bash
   sudo env APP_SERVICE=your-app.service bash install.sh
   ```

3. Check both services:

   ```bash
   sudo systemctl status upsv6-config.service ups-logger.service --no-pager
   sudo journalctl -u upsv6-config.service -u ups-logger.service -b --no-pager
   sudo systemctl show pi-sound-logger.service -p TimeoutStopUSec
   ```

   Configuration should be `active (exited)` and monitoring `active (running)`.
   Configuration records the initial registers **before** rewriting them.
   Check for 7400 protection / 8000 restart and `auto_start=1` in the CSV.
   The software trigger is in `/etc/upsv6.json`, not a UPS register.

4. Follow live events while external power is disconnected:

   ```bash
   sudo journalctl -u ups-logger.service -f
   ```

   Normal path:

   ```text
   battery <= 7600 mV for 15 seconds of continuous valid readings
     -> fsync shutdown-trigger evidence
     -> enable and verify auto-start
     -> arm the UPS's 120-second physical cutoff ONCE
     -> log for up to 5 seconds
     -> request systemctl --no-block poweroff
     -> logger records its last available sample when stopped by systemd
     -> Linux completes shutdown
     -> UPS reaches its cutoff and removes output power
   ```

   The 120 seconds includes the 5-second observation window; Linux does **not**
   keep running for 120 seconds. `pre_poweroff_log_seconds=0` requests Linux
   poweroff immediately after arming. Do not lengthen the observation window
   at the expense of the time needed for Linux to stop.

5. Leave external power absent after physical cutoff, then restore it and
   observe automatic startup without pressing the UPS button. If output cycles
   repeatedly on batteries, or the system remains off after charging, the
   recovery test has failed. A post-boot configuration read alone is not success.

6. After recovery inspect the previous boot journal if persistent journals are
   enabled, and collect all CSVs from both sides of the test:

   ```bash
   sudo journalctl --list-boots
   sudo journalctl -b -1 -u pi-sound-logger.service -u mariadb.service --no-pager
   sudo journalctl -b -1 -u ups-logger.service --no-pager
   sudo ls -lt /var/log/upsv6
   ```

   Missing previous-boot journals are not proof of a poweroff failure; Raspberry
   Pi OS may use volatile journals. Check for application cleanup, stop timeouts,
   or forced kills. Adjust the cutoff delay above the measured full shutdown
   duration, including other services. The installer cannot guarantee that
   60 seconds is sufficient for every application or that 120 is sufficient for
   all services on your machine.

## Logging and diagnostic limits

The monitor polls every second. It writes at least every 10 seconds normally,
every second below 7800 mV or during committed shutdown, and immediately on
control/configuration/status changes and read errors. Bit-2 charge status can
toggle frequently, so status changes may generate more rows than the normal
10-second interval even with external power present.

Every record includes:
- UTC event time, Linux boot ID, per-process session ID, record sequence,
  monotonic sample/event times, Linux uptime, and I2C read duration.
- Input/output/battery voltages and currents, MCU voltage, signed temperature,
  derived powers and signed-current charge direction.
- Raw CR1/CR2/SR1/SR2, auto-start/output flags, all documented SR1 fault bits,
  raw charge bit, firmware ID, device UID, and complete raw register bytes.
- Actual protection/restart settings, current UPS shutdown countdown, UPS MCU
  runtime, charger detection interval, LED register, and Python/OTA registers.
- Validation errors, low-battery confirmation duration, action state and events,
  I2C error count, and the relevant policy settings.

The 54-byte map is read in two I2C transactions (32 + 22); the two blocks are
**not an atomic snapshot**. Raw bytes and timing help identify inconsistent
reads. Anomalies such as 422 mV are logged, but invalid samples reset the
low-voltage confirmation and do not trigger shutdown. Threshold mismatch also
suspends ordinary automatic shutdown actions rather than silently rewriting
evidence. The emergency native cutoff remains active.

The manufacturer's Python demo reverses the fast-charge and charge labels
relative to its C definitions. This logger retains the raw charge bit and
uses signed battery current for its human-readable charge direction. The
policy does not depend on that disputed bit. The persistent `battery_failure`
flag is recorded, not silently cleared or treated as proof that cells are bad.

Each run creates a new CSV with its own header. Existing CSVs are never appended
with a different schema. Files rotate at approximately 10 MiB and the newest
20 are retained by filesystem modification time (clock changes can affect that
ordering). Copy important test files elsewhere before subsequent long tests.
Rows are flushed immediately; events and regular 10-second checkpoints are
fsynced. This reduces data loss but cannot guarantee SD-card persistence after
an uncontrolled power interruption.

Once Linux halts, its logger cannot observe the UPS. Button recovery can change
the state seen at startup. These logs can show changes **before Linux stops**,
not definitively establish what happened during the off interval. Definitive
off-state evidence needs an independent UPS-side observer or vendor support.

## Shutdown safeguards and limitations

- Sustained low voltage triggers even if the charger is connected: a present
  but weak input must not veto low-battery shutdown. Invalid samples/I2C gaps
  reset confirmation. At or below hardware protection, it skips the observation
  delay and attempts poweroff immediately; the UPS may cut first.
- Configuration never writes `shutdown_countdown`. That register starts a
  countdown immediately when written; it is not a saved grace-period preference.
- A manual `sudo poweroff` alone still does not arm a UPS timer. The new
  coordinated sequence runs when this monitor confirms sustained low battery.
- A live shutdown enables auto-start, then attempts exactly one countdown write.
  Once committed, input recovery does not cancel the power cycle.
- If countdown acknowledgement/readback fails, the timer may already be running.
  It logs uncertainty and requests Linux poweroff without extending the timer.
  If the write actually failed, Linux could halt with UPS output still on;
  recovery is not guaranteed. Hardware cannot be made transactional by Python.
- A same-boot marker under `/run/upsv6` prevents a monitor process restart from
  re-arming an uncertain countdown. It is cleared by a Linux reboot. Do not
  remove it to cancel a committed shutdown. Malformed state is treated as a
  possibly armed timer and requests Linux poweroff without another timer write.
- After the timer might be armed, log-disk errors cannot block the poweroff
  request. Linux command failures are recorded/retried without re-arming the UPS.
- Native protection at 7400 mV remains the emergency fallback. That path still
  has the unresolved recovery behavior seen in earlier tests.
- The manufacturer documents abandoning repeated low-voltage starts. Neither
  this program nor boot configuration can promise unlimited retries or wake a
  Pi whose UPS output remains off. Continue investigating the fault flag.

## Read-only testing and changes

Only this program's instances share its Linux I2C lock. Stop other manual/vendor
readers yourself. For read-only observation:

```bash
sudo systemctl stop ups-logger.service
sudo /usr/bin/python3 /usr/local/sbin/ups_logger.py monitor --dry-run
```

Ctrl+C stops observation without UPS register writes or Linux poweroff. An
already active UPS timer remains independent of this read-only process.
The enabled live service will return on reboot; use `disable --now` if you need
it disabled across boots. To resume after an ordinary dry run:

```bash
sudo systemctl start ups-logger.service
```

For a one-off full JSON status, stop the logger then run:

```bash
sudo /usr/bin/python3 /usr/local/sbin/ups_logger.py status
```

To change settings, with external power connected and the battery charged:

```bash
sudo systemctl stop ups-logger.service
sudo nano /etc/upsv6.json
sudo systemctl restart upsv6-config.service
sudo systemctl start ups-logger.service
```

Validation requires `protection_mv < software_shutdown_mv < restart_mv`.
Changing only a Python constant in the old `upsv6-config.py` no longer affects
this installation; `/etc/upsv6.json` is the shared source of settings.

Run hardware-free checks from the source folder:

```bash
python3 -m unittest discover -s . -p test_ups_logger.py -v
```

Tests use fake I2C and a fake poweroff callback. They do not validate physical
switching, your cells, the actual shutdown time, or vendor restart firmware.
