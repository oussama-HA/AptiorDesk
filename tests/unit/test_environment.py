"""Environment detection, guarded installs, and model downloads.

Nothing here touches the real network or runs a real pip.
"""

import json

import httpx
import pytest
import respx

from aptiordesk.core import environment as env
from aptiordesk.features.interviews.voice import transcriber


class TestDetection:
    def test_python_version_reported(self):
        assert env.python_version_ok() is True
        assert env.python_version_text().count(".") == 2

    def test_module_availability(self):
        assert env.module_available("json")
        assert not env.module_available("definitely_not_a_real_module_xyz")

    def test_feature_status_lists_missing_modules(self, monkeypatch):
        monkeypatch.setattr(env, "module_available", lambda name: name != "faster_whisper")
        ready, missing = env.feature_status("voice")
        assert not ready
        assert missing == ["faster_whisper"]

        monkeypatch.setattr(env, "module_available", lambda name: True)
        ready, missing = env.feature_status("voice")
        assert ready and missing == []

    def test_unknown_feature_is_ready_by_definition(self):
        ready, missing = env.feature_status("teleportation")
        assert ready and missing == []


class TestInstallGuard:
    def test_only_allow_listed_features_install(self):
        """The package list must never come from outside this module."""
        with pytest.raises(env.InstallRefused):
            env.install_feature("requests")
        with pytest.raises(env.InstallRefused):
            env.install_feature("voice; rm -rf /")

    def test_allow_list_is_explicit(self):
        assert set(env.ALLOWED_PACKAGES) == {"voice"}
        for packages in env.ALLOWED_PACKAGES.values():
            for spec in packages:
                assert not any(c in spec for c in ";&|$`\n")

    def test_install_runs_pip_without_a_shell(self, monkeypatch):
        captured = {}

        class FakeProcess:
            stdout = iter(["Collecting sounddevice\n", "Successfully installed\n"])

            def wait(self):
                return 0

        def fake_popen(command, **kwargs):
            captured["command"] = command
            captured["shell"] = kwargs.get("shell", False)
            return FakeProcess()

        monkeypatch.setattr(env.subprocess, "Popen", fake_popen)
        lines: list[str] = []
        ok, message = env.install_feature("voice", on_output=lines.append)

        assert ok
        assert "Restart AptiorDesk" in message
        assert captured["shell"] is False
        assert captured["command"][1:4] == ["-m", "pip", "install"]
        assert "sounddevice>=0.5" in captured["command"]
        assert any("Collecting" in line for line in lines)

    def test_install_failure_tells_the_user_what_to_run(self, monkeypatch):
        class FakeProcess:
            stdout = iter(["ERROR: no network\n"])

            def wait(self):
                return 1

        monkeypatch.setattr(env.subprocess, "Popen", lambda *a, **k: FakeProcess())
        ok, message = env.install_feature("voice")
        assert not ok
        assert "pip install sounddevice" in message

    def test_missing_pip_is_reported_not_raised(self, monkeypatch):
        def boom(*args, **kwargs):
            raise OSError("pip not found")

        monkeypatch.setattr(env.subprocess, "Popen", boom)
        ok, message = env.install_feature("voice")
        assert not ok
        assert "Could not start pip" in message


class TestOllamaProbe:
    @respx.mock
    def test_running_with_models(self, monkeypatch):
        monkeypatch.setattr(env, "ollama_binary_present", lambda: True)
        respx.get("http://localhost:11434/api/version").respond(json={"version": "0.5.1"})
        respx.get("http://localhost:11434/api/tags").respond(
            json={"models": [{"name": "gemma3:4b"}, {"name": "llama3.2:3b"}]}
        )
        status = env.probe_ollama()
        assert status.running
        assert status.version == "0.5.1"
        assert status.models == ["gemma3:4b", "llama3.2:3b"]
        assert not status.needs_install
        assert not status.needs_model

    @respx.mock
    def test_running_without_models(self, monkeypatch):
        monkeypatch.setattr(env, "ollama_binary_present", lambda: True)
        respx.get("http://localhost:11434/api/version").respond(json={"version": "0.5"})
        respx.get("http://localhost:11434/api/tags").respond(json={"models": []})
        status = env.probe_ollama()
        assert status.needs_model

    @respx.mock
    def test_not_running_never_raises(self, monkeypatch):
        monkeypatch.setattr(env, "ollama_binary_present", lambda: False)
        respx.get("http://localhost:11434/api/version").mock(
            side_effect=httpx.ConnectError("refused")
        )
        status = env.probe_ollama()
        assert not status.running
        assert status.needs_install
        assert status.error


class TestModelPull:
    @respx.mock
    def test_streams_progress(self):
        lines = [
            json.dumps({"status": "pulling manifest"}),
            json.dumps({"status": "downloading", "completed": 500, "total": 1000}),
            json.dumps({"status": "success", "completed": 1000, "total": 1000}),
        ]
        respx.post("http://localhost:11434/api/pull").mock(
            return_value=httpx.Response(200, text="\n".join(lines))
        )
        updates = list(env.pull_ollama_model("gemma3:4b"))
        assert [u.status for u in updates] == [
            "pulling manifest",
            "downloading",
            "success",
        ]
        assert updates[1].percent == 50
        assert updates[2].percent == 100

    @respx.mock
    def test_error_payload_raises(self):
        respx.post("http://localhost:11434/api/pull").mock(
            return_value=httpx.Response(200, text=json.dumps({"error": "model 'nope' not found"}))
        )
        with pytest.raises(RuntimeError, match="not found"):
            list(env.pull_ollama_model("nope"))

    @respx.mock
    def test_http_error_raises_readable_message(self):
        respx.post("http://localhost:11434/api/pull").mock(
            return_value=httpx.Response(404, text="not found")
        )
        with pytest.raises(RuntimeError, match="refused the download"):
            list(env.pull_ollama_model("gemma3:4b"))

    def test_model_name_is_validated(self):
        for bad in ("", "a b", 'x"y', "a\nb"):
            with pytest.raises(ValueError):
                list(env.pull_ollama_model(bad))

    @respx.mock
    def test_malformed_lines_are_skipped(self):
        respx.post("http://localhost:11434/api/pull").mock(
            return_value=httpx.Response(200, text="not json\n" + json.dumps({"status": "success"}))
        )
        updates = list(env.pull_ollama_model("gemma3:4b"))
        assert [u.status for u in updates] == ["success"]

    def test_percent_without_total_is_zero(self):
        assert env.PullProgress(status="x", completed=5, total=0).percent == 0


class TestSpeechModelSetup:
    def test_presence_uses_complete_model_validation(self, monkeypatch):
        monkeypatch.setattr(transcriber, "model_is_downloaded", lambda size: size == "small")

        assert env.whisper_model_present("small")
        assert not env.whisper_model_present("base")

    def test_download_uses_explicit_prepare_flow(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            transcriber,
            "prepare_model",
            lambda size, report=None: calls.append((size, report)) or "Speech model is ready.",
        )

        assert env.download_whisper_model("small") == "Speech model is ready."
        assert calls == [("small", None)]


class TestReport:
    def test_inspect_environment_summarises(self, monkeypatch):
        monkeypatch.setattr(env, "probe_ollama", lambda *a, **k: env.OllamaStatus(running=True))
        monkeypatch.setattr(env, "whisper_model_present", lambda *a, **k: False)
        report = env.inspect_environment()
        assert report.python_ok
        assert report.ollama.running
        assert report.blocking_problems() == []

    def test_old_python_is_a_blocking_problem(self, monkeypatch):
        monkeypatch.setattr(env, "probe_ollama", lambda *a, **k: env.OllamaStatus())
        monkeypatch.setattr(env, "python_version_ok", lambda: False)
        monkeypatch.setattr(env, "whisper_model_present", lambda *a, **k: False)
        report = env.inspect_environment()
        assert any("Python" in problem for problem in report.blocking_problems())

    def test_recommended_models_are_ordered_and_described(self):
        assert len(env.RECOMMENDED_MODELS) >= 3
        for suggestion in env.RECOMMENDED_MODELS:
            assert suggestion.name and suggestion.size and suggestion.note
