"""Internal PCM input-level helpers."""

import numpy as np


def pcm16_rms_level(data: bytes) -> float:
    """Return normalized RMS level for signed little-endian PCM16 audio."""

    samples = np.frombuffer(data, dtype="<i2")
    if samples.size == 0:
        return 0.0
    rms = np.sqrt(np.mean(np.square(samples, dtype=np.float64)))
    return min(float(rms / 32_768), 1.0)
