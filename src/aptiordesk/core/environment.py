"""Environment detection and first-run setup.

Everything here touches the network or the local Python environment, so the
rules are strict:

- Nothing runs without the user asking for it. There is no "check for
  updates on launch", no silent download, no background install.
- Package installation is limited to a fixed allow-list. A package name
  never comes from user input, a config file, or a model response.
- AptiorDesk does not download or execute system installers. For software
  that needs one (Ollama), it reports status and shows the official link.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

import httpx

log = logging.getLogger(__name__)

MIN_PYTHON = (3, 11)
OLLAMA_URL = "https://ollama.com/download"
DEFAULT_OLLAMA_BASE = "http://localhost:11434"

# The ONLY packages AptiorDesk will ever install. Anything not listed here is
# refused, so a compromised config or model output cannot reach pip.
ALLOWED_PACKAGES: dict[str, tuple[str, ...]] = {
    "voice": ("sounddevice>=0.5", "faster-whisper>=1.1"),
}

# Modules whose importability tells us a feature is ready.
FEATURE_MODULES: dict[str, tuple[str, ...]] = {
    "voice": ("sounddevice", "faster_whisper"),
}


@dataclass
class ModelSuggestion:
    name: str
    size: str
    note: str


# Ordered smallest-first so a modest machine can pick the top entry.
RECOMMENDED_MODELS: list[ModelSuggestion] = [
    ModelSuggestion("llama3.2:3b", "~2 GB", "Fastest. Fine for drafts on any laptop."),
    ModelSuggestion("gemma3:4b", "~3.3 GB", "Good balance of speed and quality."),
    ModelSuggestion("qwen2.5:7b", "~4.7 GB", "Stronger reasoning; needs ~8 GB RAM."),
    ModelSuggestion("gemma3:12b", "~8 GB", "Best output here; needs ~16 GB RAM."),
]


# --------------------------------------------------------------------- python


def python_version_ok() -> bool:
    return sys.version_info[:2] >= MIN_PYTHON


def python_version_text() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"


def in_virtualenv() -> bool:
    return sys.prefix != getattr(sys, "base_prefix", sys.prefix)


# ------------------------------------------------------------------- packages


def module_available(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def feature_status(feature: str) -> tuple[bool, list[str]]:
    """(ready, missing module names) for a feature in FEATURE_MODULES."""
    modules = FEATURE_MODULES.get(feature, ())
    missing = [m for m in modules if not module_available(m)]
    return (not missing, missing)


class InstallRefused(RuntimeError):
    """A package outside the allow-list was requested."""


def install_feature(
    feature: str, on_output: Callable[[str], None] | None = None
) -> tuple[bool, str]:
    """Install a feature's packages with pip, in a subprocess.

    Returns (succeeded, final message). Output is streamed to `on_output` so
    the UI can show real progress rather than an indeterminate spinner.
    """
    packages = ALLOWED_PACKAGES.get(feature)
    if not packages:
        raise InstallRefused(
            f"'{feature}' is not an installable AptiorDesk feature. "
            "AptiorDesk only installs packages from its own fixed list."
        )
    if getattr(sys, "frozen", False):
        return False, (
            "Packaged AptiorDesk cannot modify its embedded Python runtime. "
            "Rerun the AptiorDesk installer to repair application components."
        )

    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--progress-bar",
        "off",
        *packages,
    ]
    log.info("Installing %s: %s", feature, " ".join(packages))
    if on_output:
        on_output("$ " + " ".join(command[1:]) + "\n")

    try:
        process = subprocess.Popen(  # noqa: S603 — fixed argv, no shell
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
    except OSError as exc:
        return False, f"Could not start pip: {exc}"

    assert process.stdout is not None
    for line in process.stdout:
        if on_output:
            on_output(line)
    code = process.wait()

    if code != 0:
        return False, (
            "Installation failed. You can install it yourself with:\n\n"
            f"    pip install {' '.join(packages)}"
        )
    return True, "Installed. Restart AptiorDesk to start using it."


# --------------------------------------------------------------------- ollama


@dataclass
class OllamaStatus:
    running: bool = False
    version: str = ""
    models: list[str] = field(default_factory=list)
    installed: bool = False  # binary present on PATH
    error: str = ""

    @property
    def needs_install(self) -> bool:
        return not self.running and not self.installed

    @property
    def needs_model(self) -> bool:
        return self.running and not self.models


def ollama_binary_present() -> bool:
    return shutil.which("ollama") is not None


def probe_ollama(base_url: str = DEFAULT_OLLAMA_BASE, timeout: float = 2.0) -> OllamaStatus:
    """Ask a local Ollama whether it is up, and what it has. Never raises."""
    status = OllamaStatus(installed=ollama_binary_present())
    base = base_url.rstrip("/")
    try:
        with httpx.Client(timeout=timeout) as client:
            version = client.get(f"{base}/api/version")
            if version.is_success:
                status.running = True
                status.version = version.json().get("version", "")
            tags = client.get(f"{base}/api/tags")
            if tags.is_success:
                status.models = [m["name"] for m in tags.json().get("models", [])]
    except httpx.HTTPError as exc:
        status.error = str(exc)
    return status


@dataclass
class PullProgress:
    status: str = ""
    completed: int = 0
    total: int = 0

    @property
    def percent(self) -> int:
        if self.total <= 0:
            return 0
        return min(100, int(self.completed / self.total * 100))


def pull_ollama_model(
    model: str,
    base_url: str = DEFAULT_OLLAMA_BASE,
    *,
    timeout: float = 3600.0,
) -> Iterator[PullProgress]:
    """Stream an `ollama pull`, yielding progress. The caller decides when to
    stop iterating, which cancels the download."""
    if not model or any(c in model for c in " \t\n\"'\\"):
        raise ValueError(f"Invalid model name: {model!r}")
    base = base_url.rstrip("/")
    with httpx.Client(timeout=httpx.Timeout(timeout, connect=10)) as client:
        with client.stream(
            "POST", f"{base}/api/pull", json={"model": model, "stream": True}
        ) as response:
            if not response.is_success:
                response.read()
                raise RuntimeError(
                    f"Ollama refused the download (HTTP {response.status_code}). "
                    "Check that the model name is correct."
                )
            for line in response.iter_lines():
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if payload.get("error"):
                    raise RuntimeError(str(payload["error"]))
                yield PullProgress(
                    status=payload.get("status", ""),
                    completed=int(payload.get("completed", 0) or 0),
                    total=int(payload.get("total", 0) or 0),
                )


# ---------------------------------------------------------------- speech model


def whisper_model_present(size: str = "small") -> bool:
    from aptiordesk.features.interviews.voice.transcriber import model_is_downloaded

    return model_is_downloaded(size)


def download_whisper_model(
    size: str = "small",
    report=None,
) -> str:
    """Explicitly download and warm the local speech model.

    Hugging Face reports real byte totals for each downloaded model file.
    Model initialization remains explicitly indeterminate because the native
    runtime does not expose measurable loading progress.
    """
    from aptiordesk.features.interviews.voice.transcriber import prepare_model

    return prepare_model(size, report)


# -------------------------------------------------------------------- summary


@dataclass
class EnvironmentReport:
    python_ok: bool
    python_version: str
    virtualenv: bool
    voice_ready: bool
    voice_missing: list[str]
    whisper_model: bool
    ollama: OllamaStatus

    def blocking_problems(self) -> list[str]:
        """Things that stop AptiorDesk working at all (as opposed to optional
        features being unavailable)."""
        problems = []
        if not self.python_ok:
            problems.append(
                f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ is required; "
                f"this is {self.python_version}."
            )
        return problems


def inspect_environment(base_url: str = DEFAULT_OLLAMA_BASE) -> EnvironmentReport:
    ready, missing = feature_status("voice")
    return EnvironmentReport(
        python_ok=python_version_ok(),
        python_version=python_version_text(),
        virtualenv=in_virtualenv(),
        voice_ready=ready,
        voice_missing=missing,
        whisper_model=whisper_model_present(),
        ollama=probe_ollama(base_url),
    )
