#!/usr/bin/env python3
"""UPS Gen 6 telemetry, explicit configuration, and coordinated shutdown.

Register source: https://wiki.52pi.com/index.php?title=EP-0245
Only configure and the live shutdown path write UPS registers. A dry-run
monitor never writes registers or requests Linux poweroff.
"""

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import struct
import subprocess
import time
import uuid


@dataclass(frozen=True)
class Settings:
    bus: int = 1
    address: int = 0x17
    protection_mv: int = 7400
    software_shutdown_mv: int = 7600
    restart_mv: int = 8000
    low_battery_hold_seconds: float = 15
    poll_seconds: float = 1
    log_seconds: float = 10
    fast_log_below_mv: int = 7800
    cutoff_delay_seconds: int = 120
    pre_poweroff_log_seconds: float = 5
    fsync_seconds: float = 10
    max_log_bytes: int = 10 * 1024 * 1024
    max_log_files: int = 20
    log_dir: str = "/var/log/upsv6"
    lock_file: str = "/run/upsv6/i2c.lock"
    shutdown_state_file: str = "/run/upsv6/shutdown.json"

    def validate(self):
        for name in ("bus", "address", "protection_mv", "software_shutdown_mv", "restart_mv",
                     "cutoff_delay_seconds", "fast_log_below_mv", "max_log_bytes", "max_log_files"):
            if type(getattr(self, name)) is not int:
                raise ValueError(f"{name} must be an integer")
        if not (4500 <= self.protection_mv < self.software_shutdown_mv
                < self.restart_mv <= 8400):
            raise ValueError("Require 4500 <= protection < software shutdown < restart <= 8400 mV")
        if not (30 <= self.cutoff_delay_seconds <= 600):
            raise ValueError("cutoff_delay_seconds must be 30..600")
        if not (0 <= self.pre_poweroff_log_seconds < self.cutoff_delay_seconds - 10):
            raise ValueError("Observation must leave at least 10 seconds for Linux shutdown")
        if not (0 < self.poll_seconds <= 5 and self.log_seconds >= self.poll_seconds):
            raise ValueError("Require 0 < poll_seconds <= 5 and log_seconds >= poll_seconds")
        if self.low_battery_hold_seconds < 2 * self.poll_seconds:
            raise ValueError("Low-battery confirmation must span at least three samples")
        if self.fsync_seconds <= 0 or self.max_log_bytes < 256 or self.max_log_files < 3:
            raise ValueError("Invalid log durability/rotation settings")
        if not (0 <= self.bus and 0x03 <= self.address <= 0x77):
            raise ValueError("Invalid I2C bus/address")
        return self

    @classmethod
    def load(cls, path):
        return cls(**json.loads(Path(path).read_text(encoding="utf-8"))).validate()


def boot_id():
    return Path("/proc/sys/kernel/random/boot_id").read_text().strip()


def uptime_seconds():
    return float(Path("/proc/uptime").read_text().split()[0])


def decode_registers(raw):
    """Decode the packed 0x00..0x35 map; retain the original bytes."""
    if len(raw) != 54:
        raise ValueError(f"Expected 54 register bytes, got {len(raw)}")
    u16 = lambda offset: struct.unpack_from("<H", raw, offset)[0]
    cr1, sr1 = raw[0x1D], raw[0x1F]
    values = {
        "who_am_i": raw[0], "firmware_raw": raw[1],
        "device_uid": "-".join(f"{v:08X}" for v in struct.unpack_from("<III", raw, 2)),
        "output_mv": u16(0x0E), "input_mv": u16(0x10),
        "battery_mv": u16(0x12), "mcu_mv": u16(0x14),
        "output_ma": u16(0x16), "input_ma": u16(0x18),
        "battery_ma": struct.unpack_from("<h", raw, 0x1A)[0],
        "temperature_c": struct.unpack_from("<b", raw, 0x1C)[0],
        "cr1": cr1, "cr2": raw[0x1E], "sr1": sr1, "sr2": raw[0x20],
        "auto_start": cr1 & 1, "output_enabled": sr1 & 1,
        "fast_charge_flag": (sr1 >> 1) & 1,
        "charge_bit_raw": (sr1 >> 2) & 1,
        "input_low": (sr1 >> 3) & 1, "output_low": (sr1 >> 4) & 1,
        "battery_low": (sr1 >> 5) & 1, "adc_mismatch": (sr1 >> 6) & 1,
        "battery_failure": (sr1 >> 7) & 1,
        "protection_mv": u16(0x21), "shutdown_countdown_s": u16(0x23),
        "restart_mv": u16(0x25), "python_output_bytes": u16(0x27),
        "ota_request": u16(0x29),
        "ups_runtime_ms": struct.unpack_from("<Q", raw, 0x2B)[0],
        "charge_detect_interval_s": u16(0x33), "led_ctl": raw[0x35],
        "raw_registers_hex": raw.hex(),
    }
    # Preserve bit 2 without trusting the contradictory charge labels in the
    # manufacturer's Python demo. Signed battery current is logged separately.
    ma = values["battery_ma"]
    values["battery_direction"] = "charging" if ma > 20 else "discharging" if ma < -20 else "idle"
    values["input_present_estimate"] = int(values["input_mv"] >= 1000)
    for prefix in ("input", "output", "battery"):
        values[f"{prefix}_power_w"] = round(values[f"{prefix}_mv"] * values[f"{prefix}_ma"] / 1e6, 4)
    problems = []
    if values["who_am_i"] != 0xA6:
        problems.append("wrong_device_id")
    for name, lower, upper in (("battery_mv", 4000, 9000), ("mcu_mv", 2000, 4000),
                               ("output_mv", 0, 6000), ("input_mv", 0, 22000)):
        if not lower <= values[name] <= upper:
            problems.append(f"implausible_{name}")
    # 0x01A6 = 422: observed register-header echo, not a valid running 5V rail.
    if values["output_mv"] == 0x01A6:
        problems.append("output_register_header_echo")
    # Captured failures return registers 0x00..0x15 for the requested second
    # block at 0x20. Compare the stable identity/UID bytes, not live voltages.
    if raw[0] == 0xA6 and raw[0x20:0x2E] == raw[:0x0E]:
        problems.append("second_block_register_header_echo")
    for name in ("protection_mv", "restart_mv"):
        if not 4000 <= values[name] <= 9000:
            problems.append(f"implausible_{name}")
    values["sample_valid"] = int(not problems)
    values["validation_errors"] = "|".join(problems)
    return values


class Device:
    def __init__(self, bus, address):
        self.bus, self.address = bus, address

    def read(self):
        started = time.monotonic()
        first = bytes(self.bus.read_i2c_block_data(self.address, 0, 32))
        second = bytes(self.bus.read_i2c_block_data(self.address, 32, 22))
        if len(first) != 32 or len(second) != 22:
            raise ValueError("Short I2C block read")
        result = decode_registers(first + second)
        result["read_duration_ms"] = round((time.monotonic() - started) * 1000, 3)
        result["sample_monotonic_s"] = round(time.monotonic(), 6)
        return result

    def verify_readback(self, register, expected, read, mask=None, report=None):
        """Retry reads only: a delayed/stale reply must not repeat a write."""
        last = "no reply"
        for attempt in range(1, 6):
            try:
                observed = read(self.address, register)
                last = f"{observed} (0x{observed:04X})"
                if (observed if mask is None else observed & mask) == expected:
                    return
            except OSError as exc:
                last = f"{type(exc).__name__}: {exc}"
            note = (f"Register 0x{register:02X}: expected {expected}"
                    f"{'' if mask is None else f' with mask 0x{mask:02X}'}, "
                    f"observed {last}; read {attempt}/5")
            print(note, flush=True)
            if report is not None:
                report(note)
            if attempt < 5:
                time.sleep(0.1)
        raise RuntimeError(f"Readback failed at 0x{register:02X}: expected {expected}, observed {last} after 5 reads")

    def enable_auto_start(self, report=None):
        current = self.bus.read_byte_data(self.address, 0x1D)
        self.bus.write_byte_data(self.address, 0x1D, current | 1)
        self.verify_readback(0x1D, 1, self.bus.read_byte_data, mask=1, report=report)

    def configure(self, settings, report=None):
        for register, target in ((0x21, settings.protection_mv), (0x25, settings.restart_mv)):
            self.bus.write_word_data(self.address, register, target)
            self.verify_readback(register, target, self.bus.read_word_data, report=report)
        self.enable_auto_start(report=report)

    def arm_cutoff(self, seconds):
        # Exactly one write attempt: a failed acknowledgement can still mean
        # the MCU accepted it. Never extend/re-arm an uncertain countdown.
        self.bus.write_word_data(self.address, 0x23, seconds)
        observed = self.bus.read_word_data(self.address, 0x23)
        if not max(1, seconds - 5) <= observed <= seconds:
            raise RuntimeError(f"Countdown readback uncertain: {observed}")

    def read_countdown(self):
        """Independent word read to confirm a timer seen in a block sample."""
        return self.bus.read_word_data(self.address, 0x23)


SAMPLE_FIELDS = list(decode_registers(bytes(54))) + ["read_duration_ms", "sample_monotonic_s"]
META_FIELDS = ["schema_version", "timestamp_utc", "boot_id", "session_id", "sequence",
               "monotonic_s", "linux_uptime_s", "event", "mode", "shutdown_state",
               "low_duration_s", "i2c_error_count", "software_shutdown_mv",
               "low_battery_hold_seconds", "cutoff_delay_seconds", "pre_poweroff_log_seconds", "note"]


class CsvJournal:
    """New files per process/boot, bounded rotation, durable event records."""
    def __init__(self, settings, boot, mode):
        self.settings, self.boot, self.mode = settings, boot, mode
        self.session = uuid.uuid4().hex
        self.sequence = self.part = 0
        self.last_sync = time.monotonic()
        self.file = None
        Path(settings.log_dir).mkdir(parents=True, exist_ok=True)
        self._open()

    def _open(self):
        self.part += 1
        self.path = Path(self.settings.log_dir) / f"upsv6-{self.boot}-{self.session}-{self.part:03d}.csv"
        self.file = self.path.open("x", newline="", encoding="utf-8")
        self.writer = csv.DictWriter(self.file, fieldnames=META_FIELDS + SAMPLE_FIELDS)
        self.writer.writeheader()
        self.sync()
        owned = sorted(Path(self.settings.log_dir).glob("upsv6-*.csv"), key=lambda p: p.stat().st_mtime)
        for old in [p for p in owned if p != self.path][:(max(0, len(owned) - self.settings.max_log_files))]:
            old.unlink()
        print(f"CSV: {self.path}", flush=True)

    def sync(self):
        self.file.flush()
        os.fsync(self.file.fileno())
        self.last_sync = time.monotonic()

    def write(self, event, sample=None, note="", state="monitoring", low_seconds=0,
              error_count=0, force=False):
        if self.file.tell() >= self.settings.max_log_bytes:
            self.close()
            self._open()
        self.sequence += 1
        now = time.monotonic()
        row = dict.fromkeys(META_FIELDS + SAMPLE_FIELDS, "")
        row.update(sample or {})
        row.update(schema_version=1, timestamp_utc=datetime.now(timezone.utc).isoformat(),
                   boot_id=self.boot, session_id=self.session, sequence=self.sequence,
                   monotonic_s=round(now, 6), linux_uptime_s=uptime_seconds(),
                   event=event, mode=self.mode, shutdown_state=state,
                   low_duration_s=round(low_seconds, 3), i2c_error_count=error_count,
                   software_shutdown_mv=self.settings.software_shutdown_mv,
                   low_battery_hold_seconds=self.settings.low_battery_hold_seconds,
                   cutoff_delay_seconds=self.settings.cutoff_delay_seconds,
                   pre_poweroff_log_seconds=self.settings.pre_poweroff_log_seconds, note=note)
        self.writer.writerow(row)
        self.file.flush()
        if force or now - self.last_sync >= self.settings.fsync_seconds:
            self.sync()
        reading = "" if sample is None else (
            f" BAT={sample['battery_mv']} IN={sample['input_mv']} OUT={sample['output_mv']}"
            f" CR1=0x{sample['cr1']:02X} SR1=0x{sample['sr1']:02X}"
            f" countdown={sample['shutdown_countdown_s']} valid={sample['sample_valid']}"
        )
        print(f"{row['timestamp_utc']} {event}{reading} {note}", flush=True)

    def close(self):
        if self.file is not None and not self.file.closed:
            self.sync()
            self.file.close()


class LowBatteryGate:
    def __init__(self, settings):
        self.settings = settings
        self.since = self.last = None

    def reset(self):
        self.since = self.last = None

    def observe(self, sample, now):
        if (not sample["sample_valid"]
                or sample["battery_mv"] > self.settings.software_shutdown_mv):
            self.reset()
            return False
        if self.last is None or now - self.last > self.settings.poll_seconds * 3:
            self.since = now
        self.last = now
        return self.duration(now) >= self.settings.low_battery_hold_seconds

    def duration(self, now):
        return 0 if self.since is None else max(0, now - self.since)


def save_marker(path, boot, reason):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as file:
        json.dump({"boot_id": boot, "reason": reason}, file)
        file.flush()
        os.fsync(file.fileno())
    os.replace(temporary, path)


def linux_poweroff():
    # Queue the shutdown; do not wait on this service's own termination.
    subprocess.run(["/usr/bin/systemctl", "--no-block", "poweroff"],
                   check=True, timeout=10, capture_output=True, text=True)


class Shutdown:
    def __init__(self, settings, device, journal, boot, dry_run=False, poweroff=None):
        self.settings, self.device, self.journal = settings, device, journal
        self.boot, self.dry_run = boot, dry_run
        self.poweroff = linux_poweroff if poweroff is None else poweroff
        self.armed = self.requested = self.would_shutdown = False
        self.deadline = self.retry_at = 0
        self.state = "monitoring"

    def committed_record(self, event, sample=None, note=""):
        # A full/broken log disk must not prevent Linux from stopping once
        # a hardware power cut may already be scheduled.
        try:
            self.journal.write(event, sample, note, state=self.state, force=True)
        except OSError as exc:
            try:
                print(f"{event}: log write failed after shutdown commitment: {exc}", flush=True)
            except OSError:
                pass

    def resume(self):
        path = Path(self.settings.shutdown_state_file)
        if self.dry_run or not path.exists():
            return
        try:
            marker = json.loads(path.read_text(encoding="utf-8"))
            marker_boot = marker["boot_id"]
        except (ValueError, KeyError, TypeError):
            # /run is cleared on boot; malformed state may be an interrupted
            # same-boot shutdown. Do not risk extending its timer.
            self.armed = True
            self.state = "cutoff_uncertain"
            self.committed_record("invalid_shutdown_marker", note="Possible armed timer; requesting Linux poweroff without re-arming")
            return
        if marker_boot == self.boot:
            self.armed = True
            self.state = "cutoff_uncertain"
            self.committed_record("shutdown_resumed", note="Same-boot shutdown marker; countdown will not be re-armed")

    def begin(self, sample, reason, now):
        if not sample["sample_valid"]:
            self.journal.write("shutdown_sample_rejected", sample,
                               sample["validation_errors"], force=True)
            return
        if self.armed or (now < self.retry_at and not sample["shutdown_countdown_s"]):
            return
        existing = sample["shutdown_countdown_s"]
        if existing:
            try:
                observed = self.device.read_countdown()
            except OSError as exc:
                self.journal.write("countdown_unconfirmed", sample, str(exc), force=True)
                return
            if not max(1, existing - 5) <= observed <= existing:
                self.journal.write("countdown_unconfirmed", sample,
                                   f"Block countdown={existing}s, independent word read={observed}s; no shutdown committed",
                                   force=True)
                return
            existing = observed
        if self.dry_run:
            if not self.would_shutdown:
                self.journal.write("would_shutdown", sample, reason, state="dry_run", force=True)
                self.would_shutdown = True
            return
        if existing:
            self.armed = True
            self.state = "existing_cutoff"
            self.committed_record("shutdown_trigger", sample, reason)
        else:
            self.journal.write("shutdown_trigger", sample, reason, state="preparing", force=True)
        try:
            self.device.enable_auto_start()
            # Persist BEFORE any countdown write, including an uncertain one.
            save_marker(self.settings.shutdown_state_file, self.boot, reason)
        except (OSError, RuntimeError) as exc:
            if not existing:
                self.journal.write("shutdown_prepare_failed", sample, str(exc), force=True)
                self.retry_at = now + 5
                return
            # An independently armed timer cannot be stopped by a failed
            # auto-start/marker operation. Still shut Linux down promptly.
            self.committed_record("existing_cutoff_prepare_uncertain", sample, str(exc))
        self.armed = True
        self.retry_at = 0
        try:
            if not existing:
                self.device.arm_cutoff(self.settings.cutoff_delay_seconds)
            self.state = "cutoff_armed"
            self.committed_record("cutoff_armed", self.device.read(), reason)
        except (OSError, RuntimeError, ValueError) as exc:
            # The timer may already be running. Shut down Linux even if its
            # readback failed, and never issue the countdown write again.
            self.state = "cutoff_uncertain"
            self.committed_record("cutoff_uncertain", sample, str(exc))
        observation = self.settings.pre_poweroff_log_seconds
        if existing:
            observation = min(observation, max(0, existing - 15))
        if reason == "emergency_battery_low" or self.state == "cutoff_uncertain":
            observation = 0
        # Include I2C and durable-log time in the grace budget.
        self.deadline = now + observation

    def tick(self, now, sample=None, immediate=False):
        if not self.armed or self.requested or (not immediate and now < max(self.deadline, self.retry_at)):
            return
        self.committed_record("linux_poweroff_request", sample)
        try:
            self.poweroff()
        except (OSError, subprocess.SubprocessError) as exc:
            self.state = "poweroff_failed"
            self.retry_at = now + 5
            self.committed_record("linux_poweroff_failed", sample, str(exc))
        else:
            self.requested = True
            self.state = "poweroff_requested"
            self.committed_record("linux_poweroff_queued", sample)


CHANGE_FIELDS = ("cr1", "cr2", "sr1", "sr2", "protection_mv", "restart_mv", "led_ctl",
                 "charge_detect_interval_s", "input_present_estimate", "sample_valid")


def configure_and_record(settings, device, journal):
    initial = device.read()
    journal.write("before_configuration", initial, force=True)
    if not initial["sample_valid"]:
        raise RuntimeError("Invalid initial sample; no registers were written")
    try:
        device.configure(settings, report=lambda note: journal.write("readback_retry", note=note, force=True))
    except (OSError, RuntimeError) as exc:
        journal.write("configuration_failed", note=str(exc), force=True)
        raise
    journal.write("after_configuration", device.read(), force=True)
    print(f"Protection={settings.protection_mv}mV Restart={settings.restart_mv}mV Auto-start=ON", flush=True)


def monitor(settings, device, journal, boot, stop, dry_run):
    gate = LowBatteryGate(settings)
    shutdown = Shutdown(settings, device, journal, boot, dry_run)
    shutdown.resume()
    previous = latest = None
    last_log = 0
    errors = 0
    dry_low_active = False
    last_clock = None
    try:
        journal.write("monitor_started", note="READ ONLY" if dry_run else "Automatic graceful shutdown ENABLED", force=True)
        while not stop[0]:
            started = time.monotonic()
            try:
                sample = device.read()
                latest = sample
                now = time.monotonic()
                ready = gate.observe(sample, now)
                events = []
                if previous is None:
                    events.append("initial_sample")
                else:
                    changed = [key for key in CHANGE_FIELDS if sample[key] != previous[key]]
                    if changed:
                        events.append("changed:" + ",".join(changed))
                    if (sample["sample_valid"] and previous["sample_valid"]
                            and sample["ups_runtime_ms"] < previous["ups_runtime_ms"]):
                        events.append("ups_runtime_decreased")
                clock = (time.time(), now)
                if last_clock and abs((clock[0] - last_clock[0]) - (now - last_clock[1])) > 2:
                    events.append("wall_clock_step")
                last_clock = clock
                if not sample["sample_valid"]:
                    events.append("invalid_sample")
                if gate.since is not None and not dry_low_active:
                    events.append("low_battery_pending")
                    dry_low_active = True
                if gate.since is None:
                    if dry_low_active:
                        events.append("low_battery_cleared")
                    dry_low_active = False
                    shutdown.would_shutdown = False
                matches = (sample["protection_mv"] == settings.protection_mv
                           and sample["restart_mv"] == settings.restart_mv)
                if not matches:
                    events.append("threshold_config_mismatch")
                interval = settings.poll_seconds if (
                    sample["battery_mv"] <= settings.fast_log_below_mv or shutdown.armed
                ) else settings.log_seconds
                if events or now - last_log >= interval:
                    journal.write("|".join(events) or "sample", sample,
                                  state=shutdown.state, low_seconds=gate.duration(now),
                                  error_count=errors, force=bool(events))
                    last_log = now
                if sample["sample_valid"]:
                    if sample["shutdown_countdown_s"] and not shutdown.armed:
                        shutdown.begin(sample, "existing_countdown", now)
                    elif matches and sample["battery_mv"] <= settings.protection_mv:
                        shutdown.begin(sample, "emergency_battery_low", now)
                    elif matches and ready:
                        shutdown.begin(sample, "sustained_low_battery", now)
                previous = sample
            except (OSError, ValueError) as exc:
                errors += 1
                gate.reset()
                journal.write("read_error", note=str(exc), state=shutdown.state,
                              error_count=errors, force=True)
            shutdown.tick(time.monotonic(), latest)
            # Short sleeps let SIGTERM close and fsync the CSV promptly.
            until = started + settings.poll_seconds
            while not stop[0] and time.monotonic() < until:
                time.sleep(min(0.1, max(0, until - time.monotonic())))
    finally:
        # Once committed, stopping this monitor must not leave Linux running
        # with an armed physical cutoff and no poweroff request.
        shutdown.tick(time.monotonic(), latest, immediate=True)
        try:
            latest = device.read()
        except (OSError, ValueError):
            latest = None
        journal.write("monitor_stopping", latest, state=shutdown.state, error_count=errors, force=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="/etc/upsv6.json")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("configure")
    commands.add_parser("status")
    watch = commands.add_parser("monitor")
    watch.add_argument("--dry-run", action="store_true", help="Read/log only; no UPS writes or poweroff")
    args = parser.parse_args()
    if args.command == "monitor" and not args.dry_run and os.geteuid() != 0:
        raise SystemExit("Live automatic shutdown requires root; run with sudo or use --dry-run.")
    settings = Settings.load(args.config)
    # Lazy imports permit hardware-free decoding/policy tests on other OSes.
    import fcntl
    from smbus2 import SMBus

    Path(settings.lock_file).parent.mkdir(parents=True, exist_ok=True)
    with Path(settings.lock_file).open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("UPS reader already running. Stop ups-logger.service before configure/status/manual monitoring.")
        with SMBus(settings.bus) as bus:
            device = Device(bus, settings.address)
            if args.command == "status":
                print(json.dumps(device.read(), indent=2))
                return
            boot = boot_id()
            journal = CsvJournal(settings, boot, args.command + ("_dry_run" if getattr(args, "dry_run", False) else ""))
            try:
                if args.command == "configure":
                    configure_and_record(settings, device, journal)
                else:
                    stop = [False]
                    def stop_requested(signum, frame):
                        stop[0] = True
                    signal.signal(signal.SIGTERM, stop_requested)
                    signal.signal(signal.SIGINT, stop_requested)
                    monitor(settings, device, journal, boot, stop, args.dry_run)
            finally:
                journal.close()


if __name__ == "__main__":
    main()
