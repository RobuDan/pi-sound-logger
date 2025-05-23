import numpy as np

def calculate_laeq(sound_levels):
    """
    Calculate the equivalent continuous sound level (LAeq) from a list of sound levels in dB.

    Parameters:
        sound_levels (list or array-like): Sequence of sound levels (floats).

    Returns:
        float: LAeq in dB (rounded to 2 decimals), or None if input is invalid or empty.
    """
    if not sound_levels:
        return None

    # Convert to numpy array and filter out NaN 
    levels = np.array(sound_levels, dtype=float)
    levels = levels[np.isfinite(levels)]  # removes NaN 

    T = len(levels)
    if T == 0:
        return None

    laeq = 10 * np.log10(np.sum(10 ** (levels / 10)) / T)
    return round(laeq, 2)

