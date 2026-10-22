"""Shared streaming audio converter between telephony and provider formats.

All voice providers use PCM16 at various sample rates (16kHz, 24kHz) while
the simulation framework uses telephony format (8kHz mu-law). This module
provides a single converter that handles both directions with streaming
resample state to avoid artifacts at chunk boundaries.

Usage:
    converter = StreamingTelephonyConverter(
        input_sample_rate=16000,   # provider expects 16kHz PCM16 input
        output_sample_rate=24000,  # provider produces 24kHz PCM16 output
    )

    # In each tick:
    provider_audio = converter.convert_input(telephony_audio)
    telephony_audio = converter.convert_output(provider_audio)

    # On interruption or new session:
    converter.reset()
"""

import audioop
from typing import Optional, Tuple

from tau2.config import DEFAULT_TELEPHONY_RATE

TELEPHONY_SAMPLE_RATE = DEFAULT_TELEPHONY_RATE


def telephony_to_pcm16(
    audio_bytes: bytes,
    target_sample_rate: int,
    resample_state: Optional[Tuple] = None,
) -> Tuple[bytes, Optional[Tuple]]:
    """Convert telephony audio (8kHz mu-law) to PCM16 at target rate.

    Returns:
        Tuple of (converted audio bytes, new resample state for streaming).
    """
    if len(audio_bytes) == 0:
        return b"", resample_state

    pcm16_8khz = audioop.ulaw2lin(audio_bytes, 2)

    pcm16_resampled, new_state = audioop.ratecv(
        pcm16_8khz,
        2,  # sample width (16-bit)
        1,  # channels (mono)
        TELEPHONY_SAMPLE_RATE,
        target_sample_rate,
        resample_state,
    )

    return pcm16_resampled, new_state


def pcm16_to_telephony(
    audio_bytes: bytes,
    source_sample_rate: int,
    resample_state: Optional[Tuple] = None,
) -> Tuple[bytes, Optional[Tuple]]:
    """Convert PCM16 at source rate to telephony audio (8kHz mu-law).

    Returns:
        Tuple of (converted audio bytes, new resample state for streaming).
    """
    if len(audio_bytes) == 0:
        return b"", resample_state

    pcm16_8khz, new_state = audioop.ratecv(
        audio_bytes,
        2,  # sample width (16-bit)
        1,  # channels (mono)
        source_sample_rate,
        TELEPHONY_SAMPLE_RATE,
        resample_state,
    )

    ulaw_8khz = audioop.lin2ulaw(pcm16_8khz, 2)

    return ulaw_8khz, new_state


class StreamingTelephonyConverter:
    """Streaming audio converter between telephony (8kHz mu-law) and PCM16.

    Maintains resample state across calls to avoid audio artifacts at chunk
    boundaries. Used by all provider adapters that need format conversion
    (everything except xAI which uses native mu-law).

    Args:
        input_sample_rate: Provider's expected input rate (e.g., 16000).
        output_sample_rate: Provider's output rate (e.g., 24000).
    """

    def __init__(
        self,
        input_sample_rate: int = 16000,
        output_sample_rate: int = 24000,
    ):
        self.input_sample_rate = input_sample_rate
        self.output_sample_rate = output_sample_rate
        self._input_resample_state: Optional[Tuple] = None
        self._output_resample_state: Optional[Tuple] = None

    def convert_input(self, telephony_audio: bytes) -> bytes:
        """Convert telephony (8kHz mu-law) to provider input (PCM16)."""
        result, self._input_resample_state = telephony_to_pcm16(
            telephony_audio, self.input_sample_rate, self._input_resample_state
        )
        return result

    def convert_output(self, provider_audio: bytes) -> bytes:
        """Convert provider output (PCM16) to telephony (8kHz mu-law)."""
        result, self._output_resample_state = pcm16_to_telephony(
            provider_audio, self.output_sample_rate, self._output_resample_state
        )
        return result

    def reset(self) -> None:
        """Reset resample state. Call on interruption or new session."""
        self._input_resample_state = None
        self._output_resample_state = None
