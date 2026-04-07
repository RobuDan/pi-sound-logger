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
    
    def get_noise_source_position(self):
        """
        Returns the current noise source position.
        """
        data = self._read()
        return data.get("noise_source_position")

    def update_noise_source_position(self, value):
        """
        Updates the noise source position in the JSON file.
        """
        validated_value = self._validate_position(value)

        data = self._read()

        # Avoid unnecessary writes
        if data.get("noise_source_position") == validated_value:
            return

        data["noise_source_position"] = value

        self._write(data)

        logging.info(
            f"Updated weather config: noise_source_position={value}"
        )