# Copyright (c) 2024-2026, Daily
# SPDX-License-Identifier: BSD-2-Clause

"""NumPy-only Whisper log-mel features, adapted from Pipecat Smart Turn."""

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

_N_FFT = 400
_HOP_LENGTH = 160
_N_MELS = 80
_SAMPLING_RATE = 16_000
_MEL_FLOOR = 1e-10
_NORM_VARIANCE_EPS = 1e-7


def _hertz_to_mel_slaney(freq: np.ndarray) -> np.ndarray:
    min_log_hertz = 1_000.0
    min_log_mel = 15.0
    logstep = 27.0 / np.log(6.4)
    freq = np.atleast_1d(np.asarray(freq, dtype=np.float64))
    mels = 3.0 * freq / 200.0
    log_region = freq >= min_log_hertz
    mels[log_region] = min_log_mel + np.log(
        freq[log_region] / min_log_hertz
    ) * logstep
    return mels


def _mel_to_hertz_slaney(mels: np.ndarray) -> np.ndarray:
    min_log_hertz = 1_000.0
    min_log_mel = 15.0
    logstep = np.log(6.4) / 27.0
    mels = np.atleast_1d(np.asarray(mels, dtype=np.float64))
    freq = 200.0 * mels / 3.0
    log_region = mels >= min_log_mel
    freq[log_region] = min_log_hertz * np.exp(
        logstep * (mels[log_region] - min_log_mel)
    )
    return freq


def _build_mel_filterbank(
    num_frequency_bins: int,
    num_mel_filters: int,
    min_frequency: float,
    max_frequency: float,
    sampling_rate: int,
) -> np.ndarray:
    mel_min = float(
        _hertz_to_mel_slaney(np.array([min_frequency], dtype=np.float64))[0]
    )
    mel_max = float(
        _hertz_to_mel_slaney(np.array([max_frequency], dtype=np.float64))[0]
    )
    mel_freqs = np.linspace(mel_min, mel_max, num_mel_filters + 2)
    filter_freqs = _mel_to_hertz_slaney(mel_freqs)
    fft_freqs = np.linspace(0, sampling_rate // 2, num_frequency_bins)
    filter_diff = np.diff(filter_freqs)
    slopes = np.expand_dims(filter_freqs, 0) - np.expand_dims(fft_freqs, 1)
    down_slopes = -slopes[:, :-2] / filter_diff[:-1]
    up_slopes = slopes[:, 2:] / filter_diff[1:]
    filters = np.maximum(np.zeros(1), np.minimum(down_slopes, up_slopes))
    filters *= np.expand_dims(
        2.0
        / (
            filter_freqs[2 : num_mel_filters + 2]
            - filter_freqs[:num_mel_filters]
        ),
        0,
    )
    return filters


_HANN_WINDOW = np.hanning(_N_FFT + 1)[:-1]
_MEL_FILTERS = _build_mel_filterbank(
    num_frequency_bins=_N_FFT // 2 + 1,
    num_mel_filters=_N_MELS,
    min_frequency=0.0,
    max_frequency=_SAMPLING_RATE / 2.0,
    sampling_rate=_SAMPLING_RATE,
)


def _power_spectrogram(waveform: np.ndarray) -> np.ndarray:
    pad = _N_FFT // 2
    padded = np.pad(waveform.astype(np.float64), (pad, pad), mode="reflect")
    windows = sliding_window_view(padded, _N_FFT)[::_HOP_LENGTH]
    spectrum = np.fft.rfft(windows * _HANN_WINDOW.astype(np.float64), axis=-1)
    return (np.abs(spectrum) ** 2).T


def compute_whisper_log_mel_features(audio: np.ndarray) -> np.ndarray:
    """Return normalized Whisper features with shape ``(80, 800)``."""

    if audio.ndim != 1:
        raise ValueError(f"Expected 1-D audio, got shape {audio.shape}")

    samples = np.asarray(audio, dtype=np.float32)
    expected_samples = _SAMPLING_RATE * 8
    if samples.size < expected_samples:
        samples = np.pad(samples, (0, expected_samples - samples.size))
    elif samples.size > expected_samples:
        samples = samples[:expected_samples]

    samples = (samples - samples.mean()) / np.sqrt(
        samples.var() + _NORM_VARIANCE_EPS
    )
    magnitudes = _power_spectrogram(samples)
    mel_spectrum = np.maximum(_MEL_FLOOR, _MEL_FILTERS.T @ magnitudes)
    log_spectrum = np.log10(mel_spectrum)[:, :-1]
    log_spectrum = np.maximum(log_spectrum, log_spectrum.max() - 8.0)
    return ((log_spectrum + 4.0) / 4.0).astype(np.float32)
