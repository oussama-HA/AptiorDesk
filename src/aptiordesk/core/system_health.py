"""Safe, secret-free component diagnostics for setup and support."""

from __future__ import annotations

import json
import os
import socket
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

import httpx

from aptiordesk.ai.registry import build_provider
from aptiordesk.core import environment, paths
from aptiordesk.database.models.provider import ProviderConfig, ProviderKind
from aptiordesk.database.repositories.provider_repo import ProviderRepository
from aptiordesk.features.interviews.voice import recorder, transcriber
from aptiordesk.features.interviews.voice.installer import inspect_kokoro_runtime
from aptiordesk.integrations.browser_extension.bridge import DEFAULT_HOST, DEFAULT_PORT
from aptiordesk.integrations.browser_extension.config import EXTENSION_ID

HEALTH_SNAPSHOT_KEY = "system.health.snapshot.v1"
EXTENSION_PAIRED_MARKER = "browser-extension-paired.json"


class ComponentState(StrEnum):
    READY = "Ready"
    NOT_CONFIGURED = "Not configured"
    NOT_INSTALLED = "Not installed"
    CONNECTION_FAILED = "Connection failed"
    OPTIONAL = "Optional"
    REPAIR_AVAILABLE = "Repair available"


@dataclass(frozen=True, slots=True)
class ComponentCheck:
    id: str
    name: str
    state: ComponentState
    detail: str
    required: bool = False
    feature: str = ""
    action: str = ""

    @property
    def ready(self) -> bool:
        return self.state == ComponentState.READY


@dataclass(frozen=True, slots=True)
class HealthContext:
    provider: ProviderConfig | None
    database_path: str = ""


@dataclass(frozen=True, slots=True)
class SystemHealthReport:
    checked_at: str
    components: tuple[ComponentCheck, ...]

    @property
    def critical_ready(self) -> bool:
        return all(item.ready for item in self.components if item.required)

    @property
    def changed_signature(self) -> str:
        return "|".join(f"{item.id}:{item.state.value}" for item in self.components)

    def as_public_dict(self) -> dict:
        return {
            "checked_at": self.checked_at,
            "critical_ready": self.critical_ready,
            "components": [
                {
                    **asdict(item),
                    "state": item.state.value,
                }
                for item in self.components
            ],
        }


def build_health_context(conn) -> HealthContext:
    """Capture SQLite-owned state before diagnostics move to a worker thread."""
    provider = ProviderRepository(conn).get_active()
    database_path = ""
    try:
        rows = conn.execute("PRAGMA database_list").fetchall()
        database_path = str(rows[0][2] or "") if rows else ""
    except Exception:
        pass
    return HealthContext(provider=provider, database_path=database_path)


def inspect_system(context: HealthContext, *, full: bool = True) -> SystemHealthReport:
    checks: list[ComponentCheck] = []
    checks.extend(_core_checks(context))
    checks.append(_kokoro_check(full))
    checks.append(_ai_check(context.provider, full))
    checks.append(_ollama_check(context.provider))
    checks.extend(_capture_checks())
    checks.extend(_browser_checks())
    return SystemHealthReport(
        checked_at=datetime.now(UTC).isoformat(),
        components=tuple(checks),
    )


def write_diagnostics(report: SystemHealthReport, destination: Path) -> None:
    """Write only component state—never keys, resumes, prompts, or answers."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report.as_public_dict(), indent=2),
        encoding="utf-8",
    )


def mark_extension_paired() -> None:
    marker = paths.data_dir() / EXTENSION_PAIRED_MARKER
    marker.write_text(
        json.dumps({"paired_at": datetime.now(UTC).isoformat()}),
        encoding="utf-8",
    )


def _core_checks(context: HealthContext) -> list[ComponentCheck]:
    core_ready = core_runtime_ready()
    core = ComponentCheck(
        "core",
        "AptiorDesk core services",
        ComponentState.READY if core_ready else ComponentState.REPAIR_AVAILABLE,
        "Application runtime files are present."
        if core_ready
        else "Core application files are missing. Rerun the installer.",
        required=True,
        action="" if core_ready else "repair",
    )

    writable = False
    detail = ""
    probe = paths.data_dir() / ".write-check"
    try:
        probe.write_text("ok", encoding="utf-8")
        writable = probe.read_text(encoding="utf-8") == "ok"
        probe.unlink(missing_ok=True)
    except OSError as exc:
        detail = str(exc)
    data = ComponentCheck(
        "data",
        "Writable application data",
        ComponentState.READY if writable else ComponentState.CONNECTION_FAILED,
        f"User data is writable at {paths.data_dir()}."
        if writable
        else f"AptiorDesk cannot write its user-data directory: {detail}",
        required=True,
        action="" if writable else "repair",
    )

    database_ready = True
    database_detail = "The local database opened successfully."
    if context.database_path:
        db_file = Path(context.database_path)
        database_ready = db_file.is_file() and os.access(db_file, os.R_OK | os.W_OK)
        database_detail = (
            f"Local database is ready at {db_file}."
            if database_ready
            else "The local database is not readable and writable."
        )
    database = ComponentCheck(
        "database",
        "Local database",
        ComponentState.READY if database_ready else ComponentState.CONNECTION_FAILED,
        database_detail,
        required=True,
        action="" if database_ready else "repair",
    )
    return [core, data, database]


def core_runtime_ready() -> bool:
    """Validate the active runtime without assuming frozen modules are files.

    PyInstaller imports Python modules from its embedded archive. In a frozen
    build ``__file__`` therefore describes a logical source path that does not
    exist on disk. The executable and extraction/bundle directory are the
    physical runtime artifacts available to validate in that environment.
    """
    executable = Path(sys.executable)
    if not executable.is_file():
        return False
    if getattr(sys, "frozen", False):
        bundle_root = getattr(sys, "_MEIPASS", "")
        return bool(bundle_root) and Path(bundle_root).is_dir()
    return Path(__file__).is_file()


def _kokoro_check(full: bool) -> ComponentCheck:
    status = inspect_kokoro_runtime(initialize=full)
    return ComponentCheck(
        "kokoro",
        "Kokoro interviewer voice",
        ComponentState.READY if status.ready else ComponentState.REPAIR_AVAILABLE,
        status.detail,
        feature="Mock interview voice",
        action="" if status.ready else "repair_kokoro",
    )


def _ai_check(provider: ProviderConfig | None, full: bool) -> ComponentCheck:
    if provider is None:
        return ComponentCheck(
            "ai_provider",
            "AI provider",
            ComponentState.NOT_CONFIGURED,
            "Configure a device CLI, Ollama, or a cloud provider to use AI features.",
            feature="AI features",
            action="configure_ai",
        )
    if not full:
        return ComponentCheck(
            "ai_provider",
            "AI provider",
            ComponentState.READY,
            f"{provider.name or provider.kind.value} is selected; connection not retested.",
            feature="AI features",
            action="configure_ai",
        )
    limited = provider.model_copy(update={"timeout_s": min(8, provider.timeout_s)})
    status = build_provider(limited).health_check()
    return ComponentCheck(
        "ai_provider",
        "AI provider",
        ComponentState.READY if status.ok else ComponentState.CONNECTION_FAILED,
        (
            f"{provider.name or provider.kind.value} connected successfully."
            if status.ok
            else f"{provider.name or provider.kind.value}: {status.message}"
        ),
        feature="AI features",
        action="configure_ai",
    )


def _ollama_check(provider: ProviderConfig | None) -> ComponentCheck:
    base_url = (
        provider.effective_base_url()
        if provider is not None and provider.kind == ProviderKind.OLLAMA
        else environment.DEFAULT_OLLAMA_BASE
    )
    status = environment.probe_ollama(base_url, timeout=2.0)
    if status.running and status.models:
        state = ComponentState.READY
        detail = "Ollama is running with " + ", ".join(status.models[:4]) + "."
        action = ""
    elif status.running:
        state = ComponentState.NOT_CONFIGURED
        detail = "Ollama is running but has no downloaded models."
        action = "configure_ai"
    elif status.installed:
        state = ComponentState.CONNECTION_FAILED
        detail = "Ollama is installed but its local server is not running."
        action = "start_ollama"
    else:
        state = ComponentState.OPTIONAL
        detail = "Ollama is not installed. It is optional when another AI provider is used."
        action = "configure_ai"
    return ComponentCheck(
        "ollama",
        "Ollama local AI",
        state,
        detail,
        feature="Local AI",
        action=action,
    )


def _capture_checks() -> list[ComponentCheck]:
    microphone_runtime = recorder.sounddevice_available()
    devices = recorder.list_input_devices() if microphone_runtime else []
    microphone = ComponentCheck(
        "microphone",
        "Microphone",
        ComponentState.READY
        if devices
        else (
            ComponentState.NOT_CONFIGURED if microphone_runtime else ComponentState.NOT_INSTALLED
        ),
        (
            f"{len(devices)} microphone input device(s) available."
            if devices
            else (
                "Microphone runtime is bundled, but no input device is currently available."
                if microphone_runtime
                else "Microphone runtime is missing. Repair the AptiorDesk installation."
            )
        ),
        feature="Spoken interviews",
        action="test_microphone",
    )
    stt_runtime = transcriber.faster_whisper_available()
    stt_model = transcriber.model_is_downloaded()
    transcription = ComponentCheck(
        "speech_to_text",
        "Local speech-to-text",
        ComponentState.READY
        if stt_runtime and stt_model
        else (ComponentState.NOT_CONFIGURED if stt_runtime else ComponentState.NOT_INSTALLED),
        (
            "Local transcription runtime and model are ready."
            if stt_runtime and stt_model
            else (
                "The bundled speech model is missing. Repair the AptiorDesk installation."
                if stt_runtime
                else "Speech-to-text runtime is missing. Repair the installation."
            )
        ),
        feature="Recorded answers",
        action="configure_voice",
    )
    try:
        import PySide6.QtMultimedia  # noqa: F401

        camera_ready = True
    except Exception:
        camera_ready = False
    camera = ComponentCheck(
        "camera",
        "Camera",
        ComponentState.READY if camera_ready else ComponentState.NOT_INSTALLED,
        (
            "Camera runtime is bundled. Device permission is requested only when enabled."
            if camera_ready
            else "Camera runtime is missing. Repair the AptiorDesk installation."
        ),
        feature="Webcam preview",
        action="test_camera",
    )
    return [microphone, camera, transcription]


def _browser_checks() -> list[ComponentCheck]:
    bridge_ready = False
    try:
        response = httpx.get(
            f"http://{DEFAULT_HOST}:{DEFAULT_PORT}/v1/status",
            timeout=1.5,
        )
        bridge_ready = response.is_success and response.json().get("ok") is True
    except Exception:
        pass
    bridge = ComponentCheck(
        "browser_bridge",
        "Browser-extension connection",
        ComponentState.READY if bridge_ready else ComponentState.CONNECTION_FAILED,
        (
            f"Local import service is listening on {DEFAULT_HOST}:{DEFAULT_PORT}."
            if bridge_ready
            else f"Local import service is not reachable on {DEFAULT_HOST}:{DEFAULT_PORT}."
        ),
        feature="Job capture",
        action="configure_extension",
    )
    paired = (paths.data_dir() / EXTENSION_PAIRED_MARKER).is_file()
    extension = ComponentCheck(
        "browser_extension",
        "Browser extension",
        ComponentState.READY if paired else ComponentState.NOT_CONFIGURED,
        (
            "The browser extension has connected to AptiorDesk."
            if paired
            else (
                "Install the official extension "
                f"({EXTENSION_ID}) and open its side panel once to verify pairing."
            )
        ),
        feature="Job capture",
        action="configure_extension",
    )
    port_available = bridge_ready or _port_available(DEFAULT_HOST, DEFAULT_PORT)
    port = ComponentCheck(
        "local_port",
        "Required local port",
        ComponentState.READY if port_available else ComponentState.CONNECTION_FAILED,
        (
            f"Port {DEFAULT_PORT} is available to AptiorDesk."
            if port_available
            else f"Port {DEFAULT_PORT} is occupied by another application."
        ),
        feature="Browser extension",
        action="configure_extension",
    )
    return [bridge, extension, port]


def _port_available(host: str, port: int) -> bool:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.settimeout(0.5)
        probe.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        probe.close()


__all__ = [
    "ComponentCheck",
    "ComponentState",
    "EXTENSION_PAIRED_MARKER",
    "HealthContext",
    "SystemHealthReport",
    "build_health_context",
    "core_runtime_ready",
    "inspect_system",
    "mark_extension_paired",
    "write_diagnostics",
]
