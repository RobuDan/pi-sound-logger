"""Exercise the observer's event policy in CPython with a fake UPS module.

These checks cannot validate syntax/API support or buffer capacity on PikaPython.
"""
from contextlib import redirect_stdout
import io
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).with_name("mcu_observer.py")


class EndSimulation(Exception):
    pass


class ObserverTests(unittest.TestCase):
    def run_observer(self, samples):
        index = [0]
        def sleep(ms):
            self.assertEqual(ms, 1000)
            index[0] += 1
            if index[0] == len(samples):
                raise EndSimulation()
        device = SimpleNamespace(
            getInfo=lambda: "fake UPS build",
            getRuntime=lambda: index[0] * 1000,
            getInputVoltage=lambda: samples[index[0]][0],
            getBatteryVoltage=lambda: samples[index[0]][1],
            getOutputVoltage=lambda: samples[index[0]][2],
            sleep=sleep,
        )
        output = io.StringIO()
        with patch.dict(sys.modules, {"UPS": SimpleNamespace(Device=device)}), redirect_stdout(output):
            with self.assertRaises(EndSimulation):
                exec(compile(SOURCE.read_text(), str(SOURCE), "exec"), {})
        return output.getvalue().splitlines()

    def test_source_fits_manufacturer_4096_byte_upload_limit(self):
        self.assertLessEqual(len(SOURCE.read_bytes()), 4096)
        SOURCE.read_bytes().decode("ascii")

    def test_records_cutoff_input_restore_and_output_return(self):
        lines = self.run_observer([
            (11900, 8200, 5280), (80, 7950, 5280),
            (80, 7560, 5280), (80, 7700, 0),
            (11900, 7900, 0), (11900, 8010, 0), (11900, 8005, 5250),
        ])
        events = [line.split(",") for line in lines if line.startswith("OBS,")]
        self.assertEqual(len(events), 7)
        self.assertEqual(events[3][1:], ["3000", "80", "7700", "0", "0", "0", "1"])
        self.assertEqual(events[5][-3:], ["1", "0", "2"])
        self.assertEqual(events[6][-3:], ["1", "2", "2"])
        self.assertIn("OBS_LIVE", lines)

    def test_charged_battery_with_output_still_off_is_observable(self):
        lines = self.run_observer([(80, 7550, 5250), (80, 7700, 0),
                                   (11900, 7900, 0), (11900, 8200, 0)] * 2)
        self.assertTrue(any(line.startswith("OBS,") and line.endswith(",1,0,2") for line in lines))

    def test_battery_threshold_hysteresis_suppresses_chatter(self):
        samples = [(11900, battery, 5250) for battery in
                   [8010, 8000, 7990, 7995, 7950, 7560, 7601, 7649, 7650]]
        events = [line for line in self.run_observer(samples) if line.startswith("OBS,")]
        self.assertEqual(len(events), 4)

    def test_invalid_voltage_is_not_reported_as_a_real_state_transition(self):
        lines = self.run_observer([(11900, 8200, 5250), (11900, 422, 422),
                                   (11900, 422, 422), (11900, 8200, 5250)] * 2)
        self.assertEqual(sum(line.startswith("OBS_INVALID,") for line in lines), 2)
        self.assertFalse(any(line.startswith("OBS,") and ",422," in line for line in lines))

    def test_output_is_bounded_when_states_keep_switching(self):
        lines = self.run_observer([(11900, 8200, 5250), (80, 7900, 0)] * 100)
        self.assertEqual(sum(line.startswith("OBS,") for line in lines), 24)
        self.assertEqual(sum(line.startswith("OBS_LIMIT") for line in lines), 1)
        self.assertLess(len("\n".join(lines)), 2048)


if __name__ == "__main__":
    unittest.main()
