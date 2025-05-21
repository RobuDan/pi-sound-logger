import numpy as np

def calculate_laeq(sound_levels):
    """
    Calculate the equivalent continuous sound level (LAeq) from a list of sound levels.
    
    Parameters:
    sound_levels (list of float): Sound levels in decibels (dB).
    
    Returns:
    float: LAeq value in decibels (dB), rounded to two decimals. Returns None if list is empty.
    """
    sound_levels = np.array(sound_levels)
    T = len(sound_levels)

    if T > 0:
        laeq = 10 * np.log10(np.sum(10 ** (sound_levels / 10)) / T)
        return round(laeq, 2)
    else:
        return None
