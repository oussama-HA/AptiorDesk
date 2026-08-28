"""Local speech-to-text with faster-whisper.

Audio never leaves the machine. Release builds include the recommended model
as a verified application asset. Source builds may still prepare a model in
the AptiorDesk data directory for development.

faster-whisper is an optional dependency: if it is not installed, voice
practice is disabled and typed answers still work.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path

from aptiordesk.core import paths
from aptiordesk.core.errors import AptiorDeskError

log = logging.getLogger(__name__)

MODEL_SIZES: dict[str, str] = {
    "tiny": "Fastest, least accurate (~75 MB). Fine for a quick pace check.",
    "base": "Fast, modest accuracy (~145 MB).",
    "small": "Recommended balance of speed and accuracy (~460 MB).",
    "medium": "More accurate, noticeably slower on CPU (~1.5 GB).",
}
DEFAULT_MODEL = "small"


@dataclass(frozen=True)
class ModelDownloadProgress:
    """Real progress for the individual model file currently downloading."""

    status: str
    completed: int = 0
    total: int = 0


class TranscriptionUnavailable(AptiorDeskError):
    """faster-whisper is not installed or the model could not be loaded."""


def faster_whisper_available() -> bool:
    """Cheap readiness check that does not import the heavy runtime on the UI thread."""
    return find_spec("faster_whisper") is not None


def model_is_downloaded(size: str = DEFAULT_MODEL) -> bool:
    """Return true only for a complete local snapshot, not a partial cache folder."""
    return model_path(size) is not None


def bundled_model_is_available(size: str = DEFAULT_MODEL) -> bool:
    """Validate the installer-owned model without reading or migrating user data."""
    return any(
        _complete_model_directory(candidate) for candidate in _bundled_model_candidates(size)
    )


def model_path(size: str = DEFAULT_MODEL) -> Path | None:
    """Locate a complete faster-whisper model without performing network access."""
    root = paths.models_dir()
    direct = root / "faster-whisper" / size
    candidates = [*_bundled_model_candidates(size), direct]
    snapshots = root / f"models--Systran--faster-whisper-{size}" / "snapshots"
    try:
        if snapshots.is_dir():
            candidates.extend(
                sorted(
                    (path for path in snapshots.iterdir() if path.is_dir()),
                    key=lambda path: path.stat().st_mtime,
                    reverse=True,
                )
            )
    except OSError as exc:
        # Older downloads used Hugging Face's linked cache layout. Windows can
        # reject those links as untrusted mount points (WinError 448). Ignore
        # that cache and let setup create the normal local directory below.
        log.warning("Ignoring inaccessible speech-model cache: %s", exc)
    for candidate in candidates:
        if _complete_model_directory(candidate):
            return candidate
    return None


def _bundled_model_candidates(size: str) -> list[Path]:
    """Return install-time model locations without assuming a machine path."""
    candidates: list[Path] = []
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        candidates.append(Path(frozen_root) / "models" / "faster-whisper" / size)
    executable_root = Path(sys.executable).resolve().parent
    candidates.append(executable_root / "models" / "faster-whisper" / size)
    output: list[Path] = []
    for candidate in candidates:
        if candidate not in output:
            output.append(candidate)
    return output


def _complete_model_directory(candidate: Path) -> bool:
    try:
        required = (
            candidate / "config.json",
            candidate / "model.bin",
            candidate / "tokenizer.json",
        )
        vocabulary = tuple(candidate.glob("vocabulary.*"))
        return bool(
            all(path.is_file() and path.stat().st_size > 0 for path in required)
            and vocabulary
            and all(path.is_file() and path.stat().st_size > 0 for path in vocabulary)
        )
    except OSError as exc:
        log.warning("Ignoring inaccessible speech-model directory %s: %s", candidate, exc)
        return False


def prepare_model(
    size: str = DEFAULT_MODEL,
    report: Callable[[object], None] | None = None,
) -> str:
    """Explicitly download if needed and warm the model before recording begins."""
    notify = report or (lambda _message: None)
    if size not in MODEL_SIZES:
        raise ValueError(f"Unknown model size: {size}")
    if not faster_whisper_available():
        raise TranscriptionUnavailable(
            "Voice input needs the optional 'faster-whisper' package. Install the "
            "AptiorDesk voice components, then try again."
        )
    location = model_path(size)
    if location is None:
        if getattr(sys, "frozen", False):
            raise TranscriptionUnavailable(
                "The bundled local speech model is missing or incomplete. Repair "
                "AptiorDesk with the installer; the packaged application does not "
                "modify its embedded runtime or download required model files."
            )
        notify(f"Downloading the {size} local speech model")
        destination = paths.models_dir() / "faster-whisper" / size
        destination.mkdir(parents=True, exist_ok=True)
        try:
            _download_model_files(size, destination, notify)
        except Exception as exc:
            raise TranscriptionUnavailable(
                "The local speech model could not be downloaded. Check your "
                "connection and available disk space, then retry.",
                detail=str(exc),
            ) from exc
        location = model_path(size)
        if location is None:
            raise TranscriptionUnavailable(
                "The speech-model download finished without a complete model. "
                "Retry setup to repair the interrupted download."
            )
    notify("Loading the local speech model with a responsive CPU limit")
    LocalTranscriber(size=size).load()
    return f"Microphone transcription is ready with the {size} model."


def _download_model_files(
    size: str,
    destination: Path,
    report: Callable[[object], None],
) -> None:
    """Download ordinary files and forward Hugging Face's real byte counters."""
    from huggingface_hub import snapshot_download
    from tqdm.auto import tqdm

    class ReportingTqdm(tqdm):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._report()

        def update(self, n=1):
            refreshed = super().update(n)
            self._report()
            return refreshed

        def close(self):
            self._report()
            return super().close()

        def _report(self) -> None:
            label = str(self.desc or "speech model file").strip()
            report(
                ModelDownloadProgress(
                    status=f"Downloading {label}",
                    completed=int(self.n or 0),
                    total=int(self.total or 0),
                )
            )

    snapshot_download(
        repo_id=f"Systran/faster-whisper-{size}",
        local_dir=str(destination),
        allow_patterns=[
            "config.json",
            "preprocessor_config.json",
            "model.bin",
            "tokenizer.json",
            "vocabulary.*",
        ],
        tqdm_class=ReportingTqdm,
    )


class LocalTranscriber:
    """Wraps faster-whisper with one serialized, process-wide model."""

    _model = None
    _model_key: tuple[str, str] | None = None
    _model_lock = threading.RLock()

    def __init__(self, size: str = DEFAULT_MODEL, device: str = "cpu"):
        if size not in MODEL_SIZES:
            raise ValueError(f"Unknown model size: {size}")
        self.size = size
        self.device = device

    # -- model ---------------------------------------------------------------

    def load(self):
        """Load a prepared local model. This method never downloads implicitly."""
        with LocalTranscriber._model_lock:
            key = (self.size, self.device)
            if LocalTranscriber._model is not None and LocalTranscriber._model_key == key:
                return LocalTranscriber._model
            if not faster_whisper_available():
                raise TranscriptionUnavailable(
                    "The local speech-to-text component is unavailable in this "
                    "installation. Open Settings → System setup to run diagnostics "
                    "or repair AptiorDesk. You can keep practicing with typed "
                    "answers in the meantime."
                )
            location = model_path(self.size)
            if location is None:
                raise TranscriptionUnavailable(
                    "The local speech model is not prepared. Use Set up microphone "
                    "before recording an answer."
                )
            from faster_whisper import WhisperModel

            device, compute_type = _pick_device(self.device)
            log.info("Loading whisper '%s' on %s (%s)", self.size, device, compute_type)
            try:
                model = WhisperModel(
                    str(location),
                    device=device,
                    compute_type=compute_type,
                    cpu_threads=_cpu_thread_limit(),
                    num_workers=1,
                )
            except Exception as exc:
                raise TranscriptionUnavailable(
                    "Could not load the speech model. If this was the first run, the "
                    "download may have been interrupted — check your connection and "
                    "try again.",
                    detail=str(exc),
                ) from exc
            LocalTranscriber._model = model
            LocalTranscriber._model_key = key
            return model

    # -- transcription -------------------------------------------------------

    def transcribe(self, wav_path: str | Path, language: str | None = None) -> str:
        # CTranslate2's model object is shared. Serializing inference prevents
        # a live/final pair (or two interview windows) from entering the native
        # runtime concurrently and terminating the desktop process.
        with LocalTranscriber._model_lock:
            try:
                return self._run(self.load(), wav_path, language)
            except Exception as exc:
                # Explicit GPU users still get one CPU retry for recoverable
                # runtime errors. The desktop default never enters CUDA.
                if self.device != "cpu" and _is_gpu_library_error(exc):
                    log.warning("GPU inference failed (%s) — retrying on CPU", exc)
                    self.device = "cpu"
                    LocalTranscriber._model = None
                    LocalTranscriber._model_key = None
                    try:
                        return self._run(self.load(), wav_path, language)
                    except Exception as cpu_exc:
                        raise _transcription_error(cpu_exc) from cpu_exc
                raise _transcription_error(exc) from exc

    def _run(self, model, wav_path: str | Path, language: str | None) -> str:
        segments, _info = model.transcribe(
            str(wav_path),
            language=language,
            vad_filter=True,
            beam_size=1,
            condition_on_previous_text=False,
        )
        return " ".join(segment.text.strip() for segment in segments).strip()


_GPU_ERROR_MARKERS = (
    "cublas",
    "cudnn",
    "cuda",
    "libcu",
    "no kernel image",
    "out of memory",
)


def _is_gpu_library_error(exc: Exception) -> bool:
    return any(marker in str(exc).lower() for marker in _GPU_ERROR_MARKERS)


def _transcription_error(exc: Exception) -> TranscriptionUnavailable:
    message = "Transcription failed. The recording may be empty or corrupted."
    if _is_gpu_library_error(exc):
        message = (
            "Transcription failed because the GPU libraries could not be loaded, "
            "and the CPU fallback also failed. Try selecting a smaller model."
        )
    return TranscriptionUnavailable(message, detail=str(exc))


def _cuda_runtime_loadable() -> bool:
    """A GPU can be present while the CUDA runtime libraries are missing.
    Counting devices is not proof; check that cuBLAS actually loads."""
    import ctypes.util
    import platform

    names = (
        ["cublas64_12.dll", "cublas64_11.dll"]
        if platform.system() == "Windows"
        else ["libcublas.so.12", "libcublas.so.11", "libcublas.so"]
    )
    for name in names:
        try:
            ctypes.CDLL(name)
            return True
        except OSError:
            continue
    return ctypes.util.find_library("cublas") is not None


def _pick_device(preference: str) -> tuple[str, str]:
    """CUDA only when genuinely usable, otherwise int8 on CPU. Never require a GPU."""
    if preference == "cpu":
        return "cpu", "int8"
    if preference in ("cuda", "auto"):
        try:
            import ctranslate2

            if ctranslate2.get_cuda_device_count() > 0 and _cuda_runtime_loadable():
                return "cuda", "float16"
            log.info("GPU present but CUDA runtime libraries not loadable — using CPU")
        except Exception as exc:  # missing lib, driver mismatch, etc.
            log.info("CUDA unavailable (%s) — using CPU", exc)
    return "cpu", "int8"


def _cpu_thread_limit() -> int:
    """Leave CPU capacity for Qt rendering, camera preview, and audio callbacks."""
    available = os.cpu_count() or 2
    return max(1, min(2, available - 1))
