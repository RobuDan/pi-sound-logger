import time
import logging
import sounddevice as sd

keywords = ["NSRT", "mk3"]

def get_device_index(retries=10, delay=1):
    """
    Find the index of a USB audio input device based on predefined identifying keywords.

    This function scans all available input audio devices and returns the index of the
    first one whose name contains any of the specified keywords. The keyword list is 
    defined at module level.

    Returns:
        int: Index of the matched input device.

    Raises:
        ValueError: If no matching device is found.
    """
    for attempt in range(retries):
            devices = sd.query_devices()
            for i, dev in enumerate(devices):
                if dev['max_input_channels'] > 0:
                    name_lower = dev['name'].lower()
                    if all(kw.lower() in name_lower for kw in keywords):
                        logging.info(f"Matched audio device: [{i}] {dev['name']}")
                        return i

            logging.warning(f"[Audio detection] Attempt {attempt+1}/{retries}: No matching USB input device found with keywords: {keywords}")
            # Log all input devices for debugging
            for i, dev in enumerate(devices):
                if dev['max_input_channels'] > 0:
                    logging.info(f"Available input device: [{i}] {dev['name']}")
            time.sleep(delay)

    raise ValueError(f"No matching USB input device found with keywords: {keywords}")