from __future__ import annotations

import json

from aptiordesk.core import system_health
from aptiordesk.core.system_health import (
    ComponentCheck,
    ComponentState,
    HealthContext,
    SystemHealthReport,
)
from aptiordesk.features.interviews.voice.installer import KokoroRuntimeStatus


def test_core_runtime_check_accepts_pyinstaller_embedded_modules(monkeypatch, tmp_path):
    executable = tmp_path / "AptiorDesk.exe"
    executable.write_bytes(b"launcher")
    bundle_root = tmp_path / "_internal"
    bundle_root.mkdir()
    monkeypatch.setattr(system_health.sys, "executable", str(executable))
    monkeypatch.setattr(system_health.sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        system_health.sys,
        "_MEIPASS",
        str(bundle_root),
        raising=False,
    )
    monkeypatch.setattr(
        system_health,
        "__file__",
        str(tmp_path / "embedded" / "system_health.py"),
    )

    assert system_health.core_runtime_ready()


def test_core_runtime_check_rejects_missing_pyinstaller_bundle(monkeypatch, tmp_path):
    executable = tmp_path / "AptiorDesk.exe"
    executable.write_bytes(b"launcher")
    monkeypatch.setattr(system_health.sys, "executable", str(executable))
    monkeypatch.setattr(system_health.sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        system_health.sys,
        "_MEIPASS",
        str(tmp_path / "missing"),
        raising=False,
    )

    assert not system_health.core_runtime_ready()


def test_report_separates_required_and_feature_specific_components():
    report = SystemHealthReport(
        "now",
        (
            ComponentCheck(
                "core",
                "Core",
                ComponentState.READY,
                "Ready",
                required=True,
            ),
            ComponentCheck(
                "voice",
                "Voice",
                ComponentState.NOT_CONFIGURED,
                "Optional setup",
                feature="Interviews",
            ),
        ),
    )

    assert report.critical_ready
    assert report.components[0].required
    assert not report.components[1].required
    assert "core:Ready" in report.changed_signature


def test_inspection_marks_kokoro_repair_and_missing_ai_as_feature_specific(monkeypatch, tmp_path):
    monkeypatch.setattr(system_health.paths, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(
        system_health,
        "inspect_kokoro_runtime",
        lambda **_kwargs: KokoroRuntimeStatus(
            False,
            "Native runtime missing.",
            missing_modules=("espeakng_loader",),
        ),
    )
    monkeypatch.setattr(
        system_health.environment,
        "probe_ollama",
        lambda *args, **kwargs: system_health.environment.OllamaStatus(),
    )
    monkeypatch.setattr(
        system_health.recorder,
        "sounddevice_available",
        lambda: False,
    )
    monkeypatch.setattr(system_health.transcriber, "faster_whisper_available", lambda: False)
    monkeypatch.setattr(
        system_health.httpx, "get", lambda *args, **kwargs: (_ for _ in ()).throw(OSError())
    )
    monkeypatch.setattr(system_health, "_port_available", lambda *_args: True)

    report = system_health.inspect_system(HealthContext(None), full=False)
    by_id = {component.id: component for component in report.components}

    assert report.critical_ready
    assert by_id["kokoro"].state == ComponentState.REPAIR_AVAILABLE
    assert by_id["kokoro"].action == "repair_kokoro"
    assert by_id["ai_provider"].state == ComponentState.NOT_CONFIGURED
    assert by_id["ai_provider"].action == "configure_ai"


def test_exported_diagnostics_excludes_secrets_and_user_content(tmp_path):
    report = SystemHealthReport(
        "now",
        (
            ComponentCheck(
                "ai_provider",
                "AI provider",
                ComponentState.READY,
                "Provider connected.",
            ),
        ),
    )
    destination = tmp_path / "diagnostics.json"

    system_health.write_diagnostics(report, destination)

    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert payload["critical_ready"] is True
    serialized = destination.read_text(encoding="utf-8").casefold()
    assert "api_key" not in serialized
    assert "resume" not in serialized
    assert "answer" not in serialized
