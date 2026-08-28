"""Microphone capture for interview practice.

Derived from the legacy SystemAudioCapture, but pointed at the *microphone*
(the old app captured system loopback to hear the interviewer; here we
record the candidate). Audio is written to a WAV file in the scratch
directory and transcribed locally after the answer ends — nothing streams
anywhere.

`sounddevice` is imported lazily so the app runs (and tests pass) on
machines without PortAudio.
"""

from __future__ import annotations

import logging
import threading
import time
import wave
from collections.abc import Callable
from importlib.util import find_spec
from pathlib import Path

from aptiordesk.core import paths
from aptiordesk.core.errors import AptiorDeskError

log = logging.getLogger(__name__)

SAMPLE_RATE = 16_000
CHANNELS = 1
_BLOCK = 1024
_LEVEL_INTERVAL_S = 0.1


class AudioUnavailable(AptiorDeskError):
    """No microphone or no PortAudio backend."""


def sounddevice_available() -> bool:
    """Avoid importing PortAudio bindings on the UI thread just to paint state."""
    return find_spec("sounddevice") is not None


def list_input_devices() -> list[tuple[int, str]]:
    try:
        import sounddevice as sd

        return [
            (index, device["name"])
            for index, device in enumerate(sd.query_devices())
            if device.get("max_input_channels", 0) > 0
        ]
    except Exception as exc:
        log.warning("Could not enumerate audio devices: %s", exc)
        return []


class Recorder:
    """Records mono 16 kHz audio to a WAV file.

    `stream_factory` is injectable so tests can drive it without hardware.
    """

    def __init__(self, device: int | None = None, stream_factory: Callable | None = None):
        self.device = device
        self._stream_factory = stream_factory
        self._stream = None
        self._frames: list[bytes] = []
        self._frames_lock = threading.Lock()
        self._started_at: float | None = None
        self._elapsed: float = 0.0
        self._last_level_at = 0.0
        self.level_callback: Callable[[float], None] | None = None

    @property
    def is_recording(self) -> bool:
        return self._stream is not None

    @property
    def elapsed_s(self) -> float:
        if self._started_at is None:
            return self._elapsed
        return self._elapsed + (time.monotonic() - self._started_at)

    def start(self) -> None:
        if self._stream is not None:
            return
        with self._frames_lock:
            self._frames.clear()
        self._elapsed = 0.0
        self._last_level_at = 0.0
        self._stream = self._make_stream()
        self._stream.start()
        self._started_at = time.monotonic()

    def stop(self) -> Path:
        """Stop and write the WAV file. Returns its path."""
        if self._stream is None:
            raise AudioUnavailable("Recording is not running.")
        if self._started_at is not None:
            self._elapsed += time.monotonic() - self._started_at
            self._started_at = None
        self._stream.stop()
        self._stream.close()
        self._stream = None
        with self._frames_lock:
            frames = tuple(self._frames)
        return self._write_wav(frames)

    def cancel(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        with self._frames_lock:
            self._frames.clear()
        self._started_at = None
        self._elapsed = 0.0

    # -- internals -----------------------------------------------------------

    def _make_stream(self):
        if self._stream_factory is not None:
            return self._stream_factory(self._on_audio)
        try:
            import sounddevice as sd
        except Exception as exc:
            raise AudioUnavailable(
                "Audio recording is unavailable — the sounddevice/PortAudio backend "
                "could not be loaded. You can still type your answers.",
                detail=str(exc),
            ) from exc
        try:
            return sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype="int16",
                blocksize=_BLOCK,
                device=self.device,
                callback=lambda indata, frames, t, status: self._on_audio(bytes(indata)),
            )
        except Exception as exc:
            raise AudioUnavailable(
                "Could not open the microphone. Check that a recording device is "
                "connected and that AptiorDesk has permission to use it.",
                detail=str(exc),
            ) from exc

    def _on_audio(self, data: bytes) -> None:
        """Called from the audio thread — only appends and reports a level.
        Never touches Qt widgets."""
        with self._frames_lock:
            self._frames.append(data)
        now = time.monotonic()
        if self.level_callback is not None and now - self._last_level_at >= _LEVEL_INTERVAL_S:
            self._last_level_at = now
            self.level_callback(_rms_level(data))

    def _write_wav(
        self,
        frames: tuple[bytes, ...],
        *,
        name: str | None = None,
    ) -> Path:
        path = paths.scratch_dir() / (name or f"answer-{int(time.time())}.wav")
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(CHANNELS)
            handle.setsampwidth(2)  # int16
            handle.setframerate(SAMPLE_RATE)
            handle.writeframes(b"".join(frames))
        log.info("Recorded %.1fs to %s", self.elapsed_s, path.name)
        return path


def _rms_level(data: bytes) -> float:
    """Normalized 0..1 level from int16 PCM, without requiring numpy."""
    if not data:
        return 0.0
    import array

    samples = array.array("h")
    samples.frombytes(data[: len(data) - (len(data) % 2)])
    if not samples:
        return 0.0
    mean_square = sum(s * s for s in samples) / len(samples)
    return min(1.0, (mean_square**0.5) / 32768 * 4)
