import logging
import sounddevice as sd

keywords = ["Convergence_Instruments", "NSRT", "mk4"]

def get_device_index():
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
    devices = sd.query_devices()
    for i, dev in enumerate(devices):
        if dev['max_input_channels'] > 0:
            name_lower = dev['name'].lower()
            if any(keyword.lower() in name_lower for keyword in keywords):
                logging.info(f"Matched audio device: [{i}] {dev['name']}")
                return i

    raise ValueError(f"No matching USB input device found with keywords: {keywords}")
