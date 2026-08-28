"""Neural speech synthesis backends that return local playable artifacts."""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
import wave
from dataclasses import dataclass
from functools import lru_cache
from importlib.util import find_spec
from pathlib import Path

import httpx

from aptiordesk.core import paths
from aptiordesk.features.interviews.voice.settings import (
    KOKORO_VOICES,
    VoiceProvider,
    VoiceSettings,
)

log = logging.getLogger(__name__)
_KOKORO_SYNTHESIS_LOCK = threading.Lock()


class SpeechSynthesisError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class MouthCue:
    time_ms: int
    viseme: str | None
    weight: float


@dataclass(frozen=True, slots=True)
class SpeechArtifact:
    path: Path
    provider_label: str
    mouth_cues: tuple[MouthCue, ...] = ()


def synthesize(
    text: str, settings: VoiceSettings, *, elevenlabs_api_key: str | None = None
) -> SpeechArtifact:
    text = _prepare_interview_text(text)
    if settings.provider == VoiceProvider.KOKORO:
        return _synthesize_kokoro(text, settings)
    if settings.provider == VoiceProvider.ELEVENLABS:
        return _synthesize_elevenlabs(text, settings, elevenlabs_api_key)
    raise SpeechSynthesisError("System speech is played directly and is not synthesized here.")


def kokoro_available() -> bool:
    # Availability checks run while the Settings page is being built. Avoid
    # importing ONNX Runtime and NumPy on the UI thread merely to paint a label.
    return find_spec("kokoro_onnx") is not None and kokoro_files() is not None


def prepare_voice(settings: VoiceSettings, *, elevenlabs_api_key: str | None = None) -> str:
    """Load and validate the selected high-quality provider before a session.

    This is intentionally separate from ``synthesize`` so the interview room
    can remain behind its initialization screen until voice readiness is known.
    """
    if settings.provider == VoiceProvider.KOKORO:
        if settings.voice not in KOKORO_VOICES:
            raise SpeechSynthesisError(
                f"The selected Kokoro voice {settings.voice!r} is not bundled."
            )
        files = kokoro_files()
        if files is None:
            raise SpeechSynthesisError(
                "Kokoro voice files are missing. Repair or reinstall AptiorDesk, "
                "then retry voice initialization."
            )
        try:
            import kokoro_onnx  # noqa: F401

            model_path, voices_path = files
            _kokoro_engine(str(model_path), str(voices_path))
        except Exception as exc:
            raise SpeechSynthesisError(
                "Kokoro could not be initialized. Repair the bundled neural voice "
                "runtime, then retry."
            ) from exc
        return "Kokoro neural voice"
    if settings.provider == VoiceProvider.ELEVENLABS:
        if not elevenlabs_api_key:
            raise SpeechSynthesisError("ElevenLabs is selected, but no API key is stored.")
        if not settings.voice.strip():
            raise SpeechSynthesisError("Choose an ElevenLabs voice before continuing.")
        return "ElevenLabs neural voice"
    raise SpeechSynthesisError(
        "The legacy system voice is not supported for mock interviews. "
        "Choose Kokoro or another supported neural voice."
    )


def _synthesize_kokoro(text: str, settings: VoiceSettings) -> SpeechArtifact:
    files = kokoro_files()
    if files is None:
        raise SpeechSynthesisError(
            "The local neural voice is not installed. Install kokoro-onnx and place "
            "kokoro-v1.0.int8.onnx plus voices-v1.0.bin in AptiorDesk's models/kokoro "
            "folder."
        )
    try:
        import kokoro_onnx  # noqa: F401
        import numpy as np
    except Exception as exc:
        raise SpeechSynthesisError(
            "The bundled Kokoro speech runtime is unavailable. Repair or reinstall "
            "AptiorDesk to restore its standard voice components."
        ) from exc
    model_path, voices_path = files
    try:
        engine = _kokoro_engine(str(model_path), str(voices_path))
        # Kokoro's ONNX session is reused between questions. Serialize calls so
        # a preview and an interview cannot drive the same session at once.
        with _KOKORO_SYNTHESIS_LOCK:
            phonemes = engine.tokenizer.phonemize(text, settings.accent)
            samples, sample_rate = engine.create(
                phonemes,
                voice=settings.voice,
                speed=settings.speed,
                lang=settings.accent,
                is_phonemes=True,
            )
    except Exception as exc:
        raise SpeechSynthesisError(f"Kokoro could not synthesize this question: {exc}") from exc
    output = paths.scratch_dir() / f"interviewer-{time.time_ns()}.wav"
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(str(output), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(int(sample_rate))
        handle.writeframes(pcm.tobytes())
    cues = _build_mouth_cues(samples, int(sample_rate), phonemes)
    return SpeechArtifact(output, "Kokoro neural voice", cues)


@lru_cache(maxsize=2)
def _kokoro_engine(model_path: str, voices_path: str):
    import onnxruntime as ort
    from kokoro_onnx import Kokoro

    log.info("Loading Kokoro neural voice model from %s", model_path)
    providers = [os.environ.get("ONNX_PROVIDER", "CPUExecutionProvider")]
    options = ort.SessionOptions()
    if providers == ["CPUExecutionProvider"]:
        # Two inference threads benchmark substantially faster for short
        # interview questions without saturating the UI or audio threads.
        options.intra_op_num_threads = min(2, max(1, os.cpu_count() or 1))
        options.inter_op_num_threads = 1
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    session = ort.InferenceSession(
        model_path,
        sess_options=options,
        providers=providers,
    )
    return Kokoro.from_session(session, voices_path)


def _synthesize_elevenlabs(
    text: str, settings: VoiceSettings, api_key: str | None
) -> SpeechArtifact:
    if not api_key:
        raise SpeechSynthesisError(
            "ElevenLabs is selected, but no API key is stored in the secure keyring."
        )
    if not settings.voice.strip():
        raise SpeechSynthesisError("Choose or enter an ElevenLabs voice ID.")
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{settings.voice.strip()}"
    style = min(1.0, settings.expressiveness)
    payload = {
        "text": text,
        "model_id": "eleven_flash_v2_5",
        "voice_settings": {
            "stability": max(0.25, 0.72 - style * 0.32),
            "similarity_boost": 0.78,
            "style": min(0.45, style * 0.45),
            "use_speaker_boost": True,
            "speed": settings.speed,
        },
    }
    try:
        response = httpx.post(
            url,
            headers={"xi-api-key": api_key, "accept": "audio/mpeg"},
            json=payload,
            timeout=75,
        )
        response.raise_for_status()
    except Exception as exc:
        raise SpeechSynthesisError(f"ElevenLabs speech generation failed: {exc}") from exc
    output = paths.scratch_dir() / f"interviewer-{time.time_ns()}.mp3"
    output.write_bytes(response.content)
    return SpeechArtifact(output, "ElevenLabs neural voice")


KOKORO_ASSET_HASHES = {
    "kokoro-v1.0.int8.onnx": ("6e742170d309016e5891a994e1ce1559c702a2ccd0075e67ef7157974f6406cb"),
    "voices-v1.0.bin": ("bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d"),
}


def bundled_kokoro_dir() -> Path | None:
    """Return immutable Kokoro assets shipped with this build, if present."""
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        directory = Path(frozen_root) / "models" / "kokoro"
        if directory.is_dir():
            return directory
    source_directory = Path(__file__).resolve().parents[5] / "models" / "kokoro"
    return source_directory if source_directory.is_dir() else None


def kokoro_files() -> tuple[Path, Path] | None:
    """Locate complete Kokoro assets without writing to the application folder."""
    candidates: list[Path] = []
    configured = os.environ.get("APTIORDESK_KOKORO_DIR", "").strip()
    if configured:
        candidates.append(Path(configured).expanduser())
    # Repaired/downloaded assets live in user data and can be replaced without
    # mutating the signed/read-only application installation.
    candidates.append(paths.models_dir() / "kokoro")
    bundled = bundled_kokoro_dir()
    if bundled is not None:
        candidates.append(bundled)
    candidates.extend(
        [
            # Standard wheels install the bundled data files here.
            Path(sys.prefix) / "models" / "kokoro",
            # Editable/source installs must not depend on the process working
            # directory. Desktop launchers commonly start elsewhere.
            Path(__file__).resolve().parents[5] / "models" / "kokoro",
            Path(__file__).with_name("models") / "kokoro",
            Path.cwd() / "models" / "kokoro",
        ]
    )
    checked: set[Path] = set()
    for directory in candidates:
        directory = directory.resolve()
        if directory in checked:
            continue
        checked.add(directory)
        model = directory / "kokoro-v1.0.int8.onnx"
        voices = directory / "voices-v1.0.bin"
        if (
            model.is_file()
            and voices.is_file()
            and model.stat().st_size > 0
            and voices.stat().st_size > 0
        ):
            log.info("Using Kokoro voice assets from %s", directory)
            return model, voices
    return None


# Compatibility for existing tests and third-party integrations.
_kokoro_files = kokoro_files


def _build_mouth_cues(samples, sample_rate: int, phonemes: str) -> tuple[MouthCue, ...]:
    """Create a speech-clock cue track from Kokoro's waveform and phonemes.

    Kokoro does not currently expose word timestamps. Its generated waveform
    does expose real pauses and energy, though, so advance through phonemes
    only while the waveform is voiced. Pauses must not push the visible mouth
    several phonemes ahead of the audio.
    """
    import numpy as np

    if sample_rate <= 0 or len(samples) == 0:
        return ()
    frame_samples = max(1, int(sample_rate * 0.04))
    energies: list[float] = []
    for start in range(0, len(samples), frame_samples):
        frame = samples[start : start + frame_samples]
        energies.append(float(np.sqrt(np.mean(np.square(frame), dtype=np.float64))))
    if not energies:
        return ()
    reference = max(0.012, float(np.quantile(energies, 0.9)))
    silence_threshold = max(0.0045, reference * 0.11)
    voiced_mask = _bridge_short_silences(
        [energy >= silence_threshold for energy in energies],
        max_gap_frames=2,
    )
    symbols = [symbol for symbol in phonemes if symbol not in {"ˈ", "ˌ", "ː", "ˑ", "\u0361"}]
    if not symbols:
        return ()
    spoken_symbols = [
        (symbol, viseme) for symbol in symbols if (viseme := _ipa_viseme(symbol)) is not None
    ]
    if not spoken_symbols:
        return ()
    duration_weights = [
        _phoneme_duration_weight(symbol, viseme) for symbol, viseme in spoken_symbols
    ]
    cumulative_weights = np.cumsum(duration_weights)
    total_weight = float(cumulative_weights[-1])
    total_voiced_frames = max(1, sum(voiced_mask))
    voiced_frame_index = 0

    cues: list[MouthCue] = []
    for index, energy in enumerate(energies):
        time_ms = int(index * frame_samples / sample_rate * 1000)
        if not voiced_mask[index]:
            cue = MouthCue(time_ms, None, 0.0)
        else:
            voiced_progress = (voiced_frame_index + 0.5) / total_voiced_frames
            weighted_position = voiced_progress * total_weight
            symbol_index = int(np.searchsorted(cumulative_weights, weighted_position, side="right"))
            symbol_index = min(len(spoken_symbols) - 1, symbol_index)
            viseme = spoken_symbols[symbol_index][1]
            normalized = min(1.0, energy / reference)
            cue = MouthCue(time_ms, viseme, 0.24 + normalized * 0.48)
            voiced_frame_index += 1
        if not cues or (cue.viseme, round(cue.weight, 1)) != (
            cues[-1].viseme,
            round(cues[-1].weight, 1),
        ):
            cues.append(cue)
    duration_ms = int(len(samples) / sample_rate * 1000)
    if not cues or cues[-1].viseme is not None:
        cues.append(MouthCue(duration_ms, None, 0.0))
    return tuple(cues)


def _bridge_short_silences(mask: list[bool], *, max_gap_frames: int) -> list[bool]:
    """Keep tiny waveform dips from making the mouth chatter closed and open."""
    bridged = list(mask)
    index = 0
    while index < len(bridged):
        if bridged[index]:
            index += 1
            continue
        gap_start = index
        while index < len(bridged) and not bridged[index]:
            index += 1
        gap_length = index - gap_start
        has_voiced_before = gap_start > 0 and bridged[gap_start - 1]
        has_voiced_after = index < len(bridged) and bridged[index]
        if has_voiced_before and has_voiced_after and gap_length <= max_gap_frames:
            for gap_index in range(gap_start, index):
                bridged[gap_index] = True
    return bridged


def _phoneme_duration_weight(symbol: str, viseme: str) -> float:
    """Estimate relative phoneme length when the engine has no timestamps."""
    if viseme in {"open", "wide", "tight_o", "lip_open"}:
        return 1.65
    if symbol in {"m", "n", "ŋ", "l", "r", "ɹ", "w", "j"}:
        return 1.05
    if viseme in {"dental_lip", "affricate"}:
        return 0.9
    if viseme == "tight":
        return 0.75
    if viseme == "explosive":
        return 0.55
    return 1.0


def _nearby_spoken_symbol(symbols: list[str], index: int) -> str:
    if _ipa_viseme(symbols[index]) is not None:
        return symbols[index]
    for distance in (1, 2, 3):
        for candidate in (index + distance, index - distance):
            if 0 <= candidate < len(symbols) and _ipa_viseme(symbols[candidate]):
                return symbols[candidate]
    return ""


def _ipa_viseme(symbol: str) -> str | None:
    if symbol in "pbm":
        return "explosive"
    if symbol in "fv":
        return "dental_lip"
    if symbol in "oɔɒuʊw":
        return "tight_o"
    if symbol in "iɪyeɛ":
        return "wide"
    if symbol in "aɑæɐʌəɜɚɝɞ":
        return "open"
    if symbol in "ʃʒʧʤj":
        return "affricate"
    if symbol in "sztdnlɹrθðkgŋh":
        return "tight"
    return None


def _prepare_interview_text(text: str) -> str:
    text = " ".join(text.split())
    if not text:
        raise SpeechSynthesisError("There is no question text to speak.")
    # A short lead-in pause is added by the UI before playback. Keep punctuation
    # intact here so the neural model can produce its own sentence phrasing.
    return text
