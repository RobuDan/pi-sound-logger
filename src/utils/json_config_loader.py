import json 
import logging
import copy
import os

# Define supported parameter sets per weighting
A_WEIGHTED = {"LAeq", "LAF", "LAFmin", "LAFmax"}
C_WEIGHTED = {"LCeq", "LCF", "LCFmin", "LCFmax"}
Z_WEIGHTED = {"LZeq", "LZF", "LZFmin", "LZFmax"}
VALID_PARAMS = A_WEIGHTED | C_WEIGHTED | Z_WEIGHTED

class LoadConfiguration:

    def __init__(self):
        self.config = None

    def load_config(self, config_path):
        """
        Loads parameters.json and appends weighting to it.
        The original file on disk is not modified.
        Returns: (parameters_with_weighting, copy_of_original)
        """
        try:
            with open(config_path, 'r') as config_file:
                self.config = json.load(config_file)

            # There are created 2 variables. Agconfig and paramaters.
            # Agconfig is going to be passed to a class that computes calucations.
            agconfig = copy.deepcopy(self.config)
            parameters = self.append_weight_values(self.config)

            return parameters, agconfig

        except FileNotFoundError:
            logging.error(f"Configuration file {config_path} not found.")
        except json.JSONDecodeError:
            logging.error(f"Configuration file {config_path} contains invalid JSON.")
            return None, None

    def append_weight_values(self, config):
        """
        Adds the weighting ('A', 'C', or 'Z') to the parameter set.
        Raises ValueError if parameters are invalid or mixed.
        """
        config.setdefault("AcousticSequences", [])
        config.setdefault("SpectrumSequences", [])
        config.setdefault("AudioSequences", [])

        config["Weighting"] = self.extract_weighting(config["AcousticSequences"])
        return config

    def extract_weighting(self, acoustic_sequences):
        """
        Enforces single-weighting logic for the device.
        Raises ValueError if no valid parameters found or mixed classes are used.
        """
        a_params = A_WEIGHTED.intersection(acoustic_sequences)
        c_params = C_WEIGHTED.intersection(acoustic_sequences)
        z_params = Z_WEIGHTED.intersection(acoustic_sequences)

        total_classes = sum(bool(group) for group in [a_params, c_params, z_params])

        if total_classes == 0:
            raise ValueError(f"No valid weighting parameters found in: {acoustic_sequences}")

        if total_classes > 1:
            raise ValueError(f"Mixed weighting parameters not allowed: {acoustic_sequences}")

                # Log unsupported parameters
        unsupported = [p for p in acoustic_sequences if p not in VALID_PARAMS]
        if unsupported:
            logging.warning(f"Ignoring unsupported acoustic parameters: {unsupported}")

        if a_params:
            return "A"
        if c_params:
            return "C"
        if z_params:
            return "Z"
        

class WeatherConfiguration:
    """
    Handles reading and writing runtime weather-related configuration
    stored locally in config/weather.json.
    """

    VALID_POSITIONS = {"N", "S", "E", "W"}
    VALID_STATUSES = {"Active", "Inactive"}

    def __init__(self, path="config/weather.json"):
        self.path = path

    def _read(self):
        """
        Internal method to read JSON safely.
        Returns empty dict if file does not exist or is invalid.
        """
        if not os.path.exists(self.path):
            logging.warning(f"Weather config file not found: {self.path}")
            return {}

        try:
            with open(self.path, "r") as file:
                return json.load(file)
        except Exception as e:
            logging.error(f"Failed to read weather config: {e}")
            return {}

    def _write(self, data):
        """
        Internal method to write JSON safely.
        """
        try:
            with open(self.path, "w") as file:
                json.dump(data, file, indent=4)
        except Exception as e:
            logging.error(f"Failed to write weather config: {e}")

    def _validate_position(self, value):
        """
        Ensures value is either None or one of allowed directions.
        """
        if value is None:
            return None

        if isinstance(value, str):
            value = value.upper().strip()

            if value in self.VALID_POSITIONS:
                return value

        logging.warning(
            f"Ignoring invalid noise_source_position value: {value}"
        )
        return None
    
    def _validate_status(self, value):
        """
        Ensures status is one of the allowed weather states.
        """
        if isinstance(value, str):
            value = value.title().strip()

            if value in self.VALID_STATUSES:
                return value

        logging.warning(f"Ignoring invalid weather status value: {value}")
        return None
    
    def get_noise_source_position(self):
        """
        Returns the current noise source position.
        """
        data = self._read()
        return data.get("noise_source_position")

    def get_status(self):
        """
        Returns the current weather station status.
        Defaults to inactive if no status exists.
        """
        data = self._read()
        return data.get("status", "Inactive")

    def get_last_data_time(self):
        """
        Returns the last data time for the weather station.
        """
        data = self._read()
        return data.get("last_data_time")

    def get_rain_event_baseline(self):
        """
        Returns the last raw cumulative rain_event value read from the API.
        """
        data = self._read()
        value = data.get("rain_event_baseline")

        if value is None:
            return None

        try:
            return float(value)
        except (TypeError, ValueError):
            logging.warning(f"Ignoring invalid rain_event_baseline value: {value}")
            return None

    def get_rain_event_baseline_time(self):
        """
        Returns the timestamp associated with the stored rain_event baseline.
        """
        data = self._read()
        return data.get("rain_event_baseline_time")
    
    def update_noise_source_position(self, value):
        """
        Updates the noise source position in the JSON file.
        """
        validated_value = self._validate_position(value)

        data = self._read()

        # Avoid unnecessary writes
        if data.get("noise_source_position") == validated_value:
            return

        data["noise_source_position"] = validated_value

        self._write(data)

        logging.info(
            f"Updated weather config: noise_source_position={validated_value}"
        )

    def update_status(self, status, last_data_time=None):
        """
        Updates runtime weather station status.

        Args:
            status: Expected values are 'Active' or 'Inactive'.
            last_data_time: Optional timestamp string for the last fetch attempt.
        """
        validated_status = self._validate_status(status)

        if validated_status is None:
            return

        data = self._read()
        changed = False

        if data.get("status") != validated_status:
            data["status"] = validated_status
            changed = True

        if last_data_time is not None and data.get("last_data_time") != last_data_time:
            data["last_data_time"] = last_data_time

        if not changed:
            return

        self._write(data)

        logging.info(
            f"Updated weather config: status={validated_status}, "
            f"last_data_time={last_data_time}"
        )

    def update_rain_event_baseline(self, value, timestamp=None):
        """
        Stores the latest raw cumulative rain_event value used as the delta baseline.
        """
        try:
            baseline = float(value)
        except (TypeError, ValueError):
            logging.warning(f"Ignoring invalid rain_event baseline update: {value}")
            return

        data = self._read()

        data["rain_event_baseline"] = baseline
        if timestamp is not None:
            data["rain_event_baseline_time"] = timestamp

        self._write(data)

    def clear_rain_event_baseline(self, timestamp=None):
        """
        Clears the rain_event baseline after missing or invalid API rain data.
        """
        data = self._read()

        data["rain_event_baseline"] = None
        if timestamp is not None:
            data["rain_event_baseline_time"] = timestamp

        self._write(data)
