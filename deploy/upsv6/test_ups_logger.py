"""Hardware-free checks. No test can access I2C or power off this machine."""
import csv
from contextlib import redirect_stdout
from dataclasses import replace
import io
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

import ups_logger as ups


def registers(battery=8100, current=-600, temperature=30, sr1=0x89, cr1=0x08,
              countdown=0, output=5250):
    raw = bytearray(54)
    raw[0:2] = bytes([0xA6, 1])
    struct.pack_into("<III", raw, 2, 1, 2, 3)
    for offset, value in ((14, output), (16, 80), (18, battery), (20, 3300),
                          (22, 850), (24, 10), (33, 7400), (35, countdown), (37, 8000), (51, 300)):
        struct.pack_into("<H", raw, offset, value)
    struct.pack_into("<h", raw, 26, current)
    struct.pack_into("<b", raw, 28, temperature)
    raw[29], raw[31] = cr1, sr1
    struct.pack_into("<Q", raw, 43, 100_000_000)
    return raw


class FakeBus:
    def __init__(self, raw=None):
        self.raw = registers() if raw is None else raw
        self.writes = []
        self.ignore_register = None
        self.fail_after_countdown_write = False

    def read_i2c_block_data(self, address, register, length):
        return list(self.raw[register:register + length])

    def read_byte_data(self, address, register):
        return self.raw[register]

    def write_byte_data(self, address, register, value):
        self.writes.append((register, value))
        self.raw[register] = value

    def read_word_data(self, address, register):
        return struct.unpack_from("<H", self.raw, register)[0]

    def write_word_data(self, address, register, value):
        self.writes.append((register, value))
        if register != self.ignore_register:
            struct.pack_into("<H", self.raw, register, value)
        if register == 0x23 and self.fail_after_countdown_write:
            raise OSError("lost acknowledgement after accepted write")


class MemoryJournal:
    def __init__(self):
        self.events = []

    def write(self, event, sample=None, note="", **metadata):
        self.events.append(dict(event=event, sample=sample, note=note, **metadata))


class UpsTests(unittest.TestCase):
    def setUp(self):
        temp_parent = Path(__file__).resolve().parent
        self.temp = tempfile.TemporaryDirectory(prefix=".upsv6-test-", dir=temp_parent)
        # Verify the recursive cleanup target stays within this workspace.
        self.assertTrue(Path(self.temp.name).resolve().is_relative_to(temp_parent.resolve()))
        self.addCleanup(self.temp.cleanup)
        output = redirect_stdout(io.StringIO())
        output.__enter__()
        self.addCleanup(output.__exit__, None, None, None)
        self.settings = replace(ups.Settings(), log_dir=self.temp.name,
                                shutdown_state_file=str(Path(self.temp.name) / "shutdown.json"))
        self.bus = FakeBus()
        self.device = ups.Device(self.bus, 0x17)
        self.journal = MemoryJournal()
        self.poweroff = Mock()

    def shutdown(self, dry_run=False):
        return ups.Shutdown(self.settings, self.device, self.journal, "test-boot", dry_run, self.poweroff)

    def test_decode_signed_values_full_map_and_fault_flag(self):
        sample = ups.decode_registers(registers(current=-780, temperature=-5))
        self.assertEqual(sample["battery_ma"], -780)
        self.assertEqual(sample["temperature_c"], -5)
        self.assertEqual(sample["ups_runtime_ms"], 100_000_000)
        self.assertEqual(sample["charge_detect_interval_s"], 300)
        self.assertEqual(sample["battery_failure"], 1)
        self.assertEqual(sample["sample_valid"], 1)
        self.assertEqual(sample["battery_direction"], "discharging")

    def test_register_echo_retained_but_excluded_from_decisions(self):
        sample = ups.decode_registers(registers(battery=422, output=422))
        self.assertEqual(sample["sample_valid"], 0)
        self.assertEqual(sample["battery_mv"], 422)
        self.assertEqual(len(sample["raw_registers_hex"]), 108)
        self.assertIn("header_echo", sample["validation_errors"])

    def test_configure_preserves_other_cr1_bits_and_never_arms_countdown(self):
        ups.configure_and_record(self.settings, self.device, self.journal)
        self.assertEqual(self.bus.raw[29], 0x09)
        self.assertEqual(self.journal.events[0]["sample"]["cr1"], 0x08)
        self.assertEqual(self.journal.events[-1]["sample"]["cr1"], 0x09)
        self.assertFalse(any(reg == 0x23 for reg, value in self.bus.writes))

    def test_invalid_configuration_sample_causes_no_writes(self):
        self.bus.raw[0] = 0
        with self.assertRaises(RuntimeError):
            ups.configure_and_record(self.settings, self.device, self.journal)
        self.assertEqual(self.bus.writes, [])

    def test_configure_fails_on_incorrect_readback(self):
        self.bus.ignore_register = 0x25
        with self.assertRaises(RuntimeError):
            self.device.configure(replace(self.settings, restart_mv=8100))

    def test_short_i2c_frame_is_not_zero_padded(self):
        self.bus.raw = self.bus.raw[:40]
        with self.assertRaises(ValueError):
            self.device.read()

    def test_rejects_equal_or_reversed_thresholds(self):
        for kwargs in ({"software_shutdown_mv": 7400}, {"restart_mv": 7500},
                       {"restart_mv": 8500}, {"protection_mv": 7400.5}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                replace(self.settings, **kwargs).validate()

    def test_rejects_observation_consuming_linux_grace_period(self):
        with self.assertRaises(ValueError):
            replace(self.settings, cutoff_delay_seconds=30, pre_poweroff_log_seconds=25).validate()

    def test_low_battery_requires_continuous_valid_samples(self):
        gate = ups.LowBatteryGate(self.settings)
        low = ups.decode_registers(registers(battery=7550))
        for now in range(15):
            self.assertFalse(gate.observe(low, now))
        self.assertTrue(gate.observe(low, 15))
        self.assertFalse(gate.observe(ups.decode_registers(registers()), 16))
        self.assertEqual(gate.duration(16), 0)

    def test_invalid_sample_and_read_gap_reset_confirmation(self):
        gate = ups.LowBatteryGate(self.settings)
        low = ups.decode_registers(registers(battery=7550))
        gate.observe(low, 0)
        gate.observe(ups.decode_registers(registers(battery=422)), 1)
        self.assertFalse(gate.observe(low, 2))
        self.assertEqual(gate.since, 2)
        self.assertFalse(gate.observe(low, 30))
        self.assertEqual(gate.since, 30)

    def test_dry_run_never_writes_or_powers_off(self):
        controller = self.shutdown(dry_run=True)
        controller.begin(self.device.read(), "sustained_low_battery", 0)
        controller.tick(200, immediate=True)
        self.assertEqual(self.bus.writes, [])
        self.poweroff.assert_not_called()
        self.assertFalse(Path(self.settings.shutdown_state_file).exists())
        self.assertEqual(self.journal.events[0]["event"], "would_shutdown")

    def test_shutdown_arms_once_and_observes_before_poweroff(self):
        controller = self.shutdown()
        controller.begin(self.device.read(), "sustained_low_battery", 10)
        marker = json.loads(Path(self.settings.shutdown_state_file).read_text())
        self.assertEqual(marker["boot_id"], "test-boot")
        controller.tick(14)
        self.poweroff.assert_not_called()
        controller.tick(15)
        controller.begin(self.device.read(), "duplicate_trigger", 20)
        controller.tick(200)
        self.poweroff.assert_called_once()
        self.assertEqual([v for r, v in self.bus.writes if r == 0x23], [120])

    def test_accepted_write_with_lost_ack_still_shuts_linux_down_without_rearming(self):
        self.bus.fail_after_countdown_write = True
        controller = self.shutdown()
        controller.begin(self.device.read(), "sustained_low_battery", 10)
        self.assertEqual(controller.state, "cutoff_uncertain")
        controller.tick(10)
        controller.begin(self.device.read(), "again", 20)
        self.poweroff.assert_called_once()
        self.assertEqual([v for r, v in self.bus.writes if r == 0x23], [120])

    def test_cannot_enable_auto_start_does_not_arm_new_countdown(self):
        self.device.enable_auto_start = Mock(side_effect=OSError("bus unavailable"))
        controller = self.shutdown()
        controller.begin(self.device.read(), "sustained_low_battery", 0)
        controller.tick(200)
        self.assertFalse(controller.armed)
        self.assertEqual(self.bus.writes, [])
        self.poweroff.assert_not_called()

    def test_existing_timer_not_extended_even_if_auto_start_write_fails(self):
        struct.pack_into("<H", self.bus.raw, 0x23, 8)
        self.device.enable_auto_start = Mock(side_effect=OSError("bus unavailable"))
        controller = self.shutdown()
        controller.begin(self.device.read(), "existing_countdown", 0)
        controller.tick(0)
        self.assertTrue(controller.armed)
        self.poweroff.assert_called_once()
        self.assertFalse(any(reg == 0x23 for reg, value in self.bus.writes))

    def test_poweroff_failure_retries_linux_command_without_rearming_ups(self):
        self.poweroff.side_effect = [subprocess.CalledProcessError(1, "systemctl"), None]
        controller = self.shutdown()
        controller.begin(self.device.read(), "sustained_low_battery", 0)
        controller.tick(5)
        self.assertEqual(controller.state, "poweroff_failed")
        controller.tick(9)
        self.assertEqual(self.poweroff.call_count, 1)
        controller.tick(10)
        self.assertTrue(controller.requested)
        self.assertEqual(self.poweroff.call_count, 2)
        self.assertEqual([v for r, v in self.bus.writes if r == 0x23], [120])

    def test_same_boot_restart_does_not_extend_countdown(self):
        ups.save_marker(self.settings.shutdown_state_file, "test-boot", "prior attempt")
        controller = self.shutdown()
        controller.resume()
        controller.tick(0)
        self.poweroff.assert_called_once()
        self.assertEqual(self.bus.writes, [])

    def test_broken_log_disk_does_not_block_committed_poweroff(self):
        controller = self.shutdown()
        controller.begin(self.device.read(), "sustained_low_battery", 0)
        self.journal.write = Mock(side_effect=OSError("disk full"))
        controller.tick(5)
        self.poweroff.assert_called_once()
        self.assertTrue(controller.requested)

    def test_marker_from_previous_boot_does_not_trigger_poweroff(self):
        ups.save_marker(self.settings.shutdown_state_file, "previous-boot", "prior attempt")
        controller = self.shutdown()
        controller.resume()
        controller.tick(200)
        self.poweroff.assert_not_called()

    def test_malformed_marker_does_not_risk_rearming_a_running_timer(self):
        Path(self.settings.shutdown_state_file).write_text("{")
        controller = self.shutdown()
        controller.resume()
        controller.tick(0)
        self.poweroff.assert_called_once()
        self.assertEqual(self.bus.writes, [])

    @patch.object(ups, "uptime_seconds", return_value=123.5)
    def test_csv_files_have_separate_sessions_and_durable_raw_events(self, uptime):
        paths = []
        for _ in range(2):
            journal = ups.CsvJournal(self.settings, "test-boot", "monitor")
            journal.write("invalid_sample", ups.decode_registers(registers(battery=422)), force=True)
            journal.close()
            paths.append(journal.path)
        self.assertNotEqual(paths[0], paths[1])
        with paths[0].open(newline="") as file:
            row = next(csv.DictReader(file))
        self.assertEqual(row["sample_valid"], "0")
        self.assertEqual(row["battery_mv"], "422")
        self.assertEqual(row["linux_uptime_s"], "123.5")
        self.assertTrue(row["timestamp_utc"].endswith("+00:00"))
        self.assertEqual(len(row["raw_registers_hex"]), 108)

    @patch.object(ups, "uptime_seconds", return_value=123.5)
    def test_log_rotation_is_bounded(self, uptime):
        settings = replace(self.settings, max_log_bytes=256, max_log_files=3)
        journal = ups.CsvJournal(settings, "test-boot", "monitor")
        for _ in range(6):
            journal.write("sample", self.device.read())
        journal.close()
        self.assertEqual(len(list(Path(settings.log_dir).glob("upsv6-*.csv"))), 3)

    def test_dry_run_monitor_integration_with_live_policy_and_fault_flag(self):
        settings = replace(self.settings, low_battery_hold_seconds=2)
        stop = [False]
        clock = [0.0]
        reads = [0]
        self.bus.raw = registers(battery=7500)
        original_read = self.device.read

        def read():
            reads[0] += 1
            if reads[0] >= 5:
                stop[0] = True
            return original_read()

        self.device.read = read
        with patch.object(ups.time, "monotonic", side_effect=lambda: clock[0]), \
             patch.object(ups.time, "sleep", side_effect=lambda seconds: clock.__setitem__(0, clock[0] + seconds)):
            ups.monitor(settings, self.device, self.journal, "test-boot", stop, True)
        self.assertIn("would_shutdown", [e["event"] for e in self.journal.events])
        self.assertEqual(self.bus.writes, [])

    def test_live_monitor_integration_queues_poweroff_once_after_observation(self):
        settings = replace(self.settings, low_battery_hold_seconds=2, pre_poweroff_log_seconds=2)
        stop, clock, reads = [False], [0.0], [0]
        self.bus.raw = registers(battery=7500)
        original_read = self.device.read

        def read():
            reads[0] += 1
            if reads[0] >= 8:
                stop[0] = True
            return original_read()

        self.device.read = read
        with patch.object(ups.time, "monotonic", side_effect=lambda: clock[0]), \
             patch.object(ups.time, "sleep", side_effect=lambda seconds: clock.__setitem__(0, clock[0] + seconds)), \
             patch.object(ups, "linux_poweroff", self.poweroff):
            ups.monitor(settings, self.device, self.journal, "test-boot", stop, False)
        self.poweroff.assert_called_once()
        self.assertEqual([v for r, v in self.bus.writes if r == 0x23], [120])
        events = [e["event"] for e in self.journal.events]
        self.assertLess(events.index("cutoff_armed"), events.index("linux_poweroff_request"))
        self.assertIn("monitor_stopping", events)

    def test_threshold_mismatch_monitor_logs_without_writing_or_poweroff(self):
        settings = replace(self.settings, low_battery_hold_seconds=2)
        stop, clock, reads = [False], [0.0], [0]
        self.bus.raw = registers(battery=7500)
        struct.pack_into("<H", self.bus.raw, 0x25, 6500)
        original_read = self.device.read

        def read():
            reads[0] += 1
            if reads[0] >= 5:
                stop[0] = True
            return original_read()

        self.device.read = read
        with patch.object(ups.time, "monotonic", side_effect=lambda: clock[0]), \
             patch.object(ups.time, "sleep", side_effect=lambda seconds: clock.__setitem__(0, clock[0] + seconds)), \
             patch.object(ups, "linux_poweroff", self.poweroff):
            ups.monitor(settings, self.device, self.journal, "test-boot", stop, False)
        self.assertTrue(any("threshold_config_mismatch" in e["event"] for e in self.journal.events))
        self.assertEqual(self.bus.writes, [])
        self.poweroff.assert_not_called()


if __name__ == "__main__":
    unittest.main()
