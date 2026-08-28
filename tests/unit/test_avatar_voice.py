"""Avatar-state coordination and interviewer voice settings."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QObject

from aptiordesk.features.interviews import page as interview_page_module
from aptiordesk.features.interviews.avatar.assets import (
    DEFAULT_AVATAR_ID,
    _repair_conditioned_component,
    avatar_catalog,
    bundled_avatar_runtime_status,
    get_avatar,
    prepare_avatar,
)
from aptiordesk.features.interviews.avatar.controller import AvatarController, AvatarState
from aptiordesk.features.interviews.avatar.picker import AvatarPickerDialog
from aptiordesk.features.interviews.avatar.stage import AvatarStage
from aptiordesk.features.interviews.camera import CandidateCameraTile
from aptiordesk.features.interviews.voice import installer as installer_module
from aptiordesk.features.interviews.voice import playback as playback_module
from aptiordesk.features.interviews.voice import synthesis as synthesis_module
from aptiordesk.features.interviews.voice.playback import SpeechPlayer
from aptiordesk.features.interviews.voice.settings import (
    VoiceProvider,
    VoiceSettings,
    VoiceSettingsRepository,
)


class _PredictableRandom:
    def random(self):
        return 0.0

    def triangular(self, low, high, mode):
        return mode

    def uniform(self, low, high):
        return (low + high) / 2

    def randint(self, low, high):
        return low


def test_voice_settings_round_trip_and_clamp(conn):
    repository = VoiceSettingsRepository(conn)
    repository.save(
        VoiceSettings(
            provider=VoiceProvider.KOKORO,
            voice="af_heart",
            speed=0.94,
            reduced_motion=True,
        )
    )
    loaded = repository.load()
    assert loaded.provider == VoiceProvider.KOKORO
    assert loaded.voice == "af_heart"
    assert loaded.speed == 0.94
    assert loaded.reduced_motion is True

    clamped = VoiceSettings.from_dict(
        {"provider": "unknown", "speed": 9, "pitch": -9, "expressiveness": 3}
    )
    assert clamped.provider == VoiceProvider.KOKORO
    assert clamped.speed == 1.25
    assert clamped.pitch == -0.5
    assert clamped.expressiveness == 1.0


def test_legacy_system_voice_is_migrated_to_kokoro_without_fallback(conn):
    from aptiordesk.database.repositories.settings_repo import SettingsRepository
    from aptiordesk.features.interviews.voice.settings import SETTINGS_KEY

    SettingsRepository(conn).set(
        SETTINGS_KEY,
        {
            "provider": "system",
            "voice": "Microsoft Zira",
            "allow_fallback": True,
        },
    )

    loaded = VoiceSettingsRepository(conn).load()

    assert loaded.provider == VoiceProvider.KOKORO
    assert loaded.voice == "af_heart"
    assert loaded.allow_fallback is False
    stored = SettingsRepository(conn).get(SETTINGS_KEY, {})
    assert stored["provider"] == "kokoro"
    assert stored["allow_fallback"] is False


def test_speech_player_rejects_legacy_system_voice(qtbot):
    player = SpeechPlayer()
    player._settings = VoiceSettings(provider=VoiceProvider.SYSTEM)
    player._request_serial = 7

    with qtbot.waitSignal(player.failed, timeout=1000) as signal:
        player._begin(7)

    assert "legacy system voice is disabled" in signal.args[0]


def test_kokoro_repair_restores_assets_without_invoking_pip(monkeypatch, tmp_path):
    import hashlib

    progress = []
    source = tmp_path / "bundled"
    destination = tmp_path / "user-models"
    source.mkdir()
    payloads = {
        "model.onnx": b"model",
        "voices.bin": b"voices",
    }
    for name, payload in payloads.items():
        (source / name).write_bytes(payload)
    monkeypatch.setattr(
        installer_module,
        "KOKORO_ASSET_HASHES",
        {name: hashlib.sha256(payload).hexdigest() for name, payload in payloads.items()},
    )
    monkeypatch.setattr(installer_module, "bundled_kokoro_dir", lambda: source)
    monkeypatch.setattr(installer_module.paths, "models_dir", lambda: destination)
    statuses = iter(
        [
            installer_module.KokoroRuntimeStatus(True, "runtime ready"),
            installer_module.KokoroRuntimeStatus(
                True,
                "verified",
                assets_dir=destination / "kokoro",
                assets_valid=True,
                initialized=True,
            ),
        ]
    )
    monkeypatch.setattr(
        installer_module.importlib,
        "invalidate_caches",
        lambda: None,
    )
    monkeypatch.setattr(
        installer_module,
        "inspect_kokoro_runtime",
        lambda **_kwargs: next(statuses),
    )

    result = installer_module.repair_kokoro_runtime(progress.append)

    assert result == "Kokoro voice assets were restored and verified."
    assert (destination / "kokoro" / "model.onnx").read_bytes() == b"model"
    assert (destination / "kokoro" / "voices.bin").read_bytes() == b"voices"
    assert not hasattr(installer_module, "subprocess")
    assert progress[-1] == "Initializing the repaired neural voice"


def test_kokoro_repair_requires_installer_for_missing_native_runtime(monkeypatch):
    monkeypatch.setattr(
        installer_module,
        "inspect_kokoro_runtime",
        lambda **_kwargs: installer_module.KokoroRuntimeStatus(
            False,
            "The packaged neural-voice runtime is incomplete: espeakng_loader. "
            "Rerun the AptiorDesk installer.",
            missing_modules=("espeakng_loader",),
        ),
    )
    try:
        installer_module.repair_kokoro_runtime()
    except installer_module.KokoroInstallError as exc:
        assert "Rerun the AptiorDesk installer" in str(exc)
    else:
        raise AssertionError("Expected native-runtime repair to require the installer")


def test_avatar_nods_only_while_listening(qtbot):
    controller = AvatarController(rng=_PredictableRandom())
    controller.set_state(AvatarState.SPEAKING)
    assert not controller.request_nod(elapsed_ms=12_000)
    controller.set_state(AvatarState.LISTENING)
    with qtbot.waitSignal(controller.nod_started, timeout=1000):
        assert controller.request_nod(elapsed_ms=12_000)
    controller.set_reduced_motion(True)
    assert not controller.request_nod(elapsed_ms=30_000)
    controller.shutdown()


def test_camera_start_timeout_releases_device_and_recovers_ui(qtbot):
    tile = CandidateCameraTile()
    qtbot.addWidget(tile)
    tile._starting = True

    with qtbot.waitSignal(tile.state_changed, timeout=1000) as signal:
        tile._start_timed_out()

    assert signal.args == ["timeout"]
    assert not tile.camera_busy
    assert tile.state_title.text() == "Camera start timed out"


def test_avatar_has_restrained_motion_while_speaking():
    controller = AvatarController(rng=_PredictableRandom())
    controller.set_state(AvatarState.SPEAKING)

    controller._idle_motion()

    assert controller._head_animation is not None
    controller.shutdown()


def test_blink_schedule_has_a_safe_minimum():
    controller = AvatarController(rng=_PredictableRandom())
    delays = {controller._next_blink_delay_ms() for _ in range(5)}
    assert min(delays) >= 2_800
    controller.shutdown()


def test_avatar_conditioning_disables_tracks_and_repairs_eye_shells(tmp_path):
    component = tmp_path / "Avatar.qml"
    component.write_text(
        """
        Timeline {
            id: facial_timeline
            objectName: "faceit_bake_test_action"
            enabled: true
            animations: TimelineAnimation {
                running: true
                loops: Animation.Infinite
            }
        }
        Timeline {
            id: authored_idle_timeline
            objectName: "AptiorDesk_Idle_Pose"
            property real framesPerSecond: 1000
            startFrame: 0
            endFrame: 17
            currentFrame: 0
            enabled: true
            animations: TimelineAnimation {
                duration: 17
                from: 0
                to: 17
                running: true
                loops: Animation.Infinite
            }
        }
        PrincipledMaterial {
            objectName: "Std_Eye_Occlusion_R"
            baseColor: "#ff000000"
        }
        PrincipledMaterial {
            objectName: "Std_Eye_Occlusion_L"
            baseColor: "#ff000000"
        }
        """,
        encoding="utf-8",
    )
    _repair_conditioned_component(component)
    repaired = component.read_text(encoding="utf-8")
    assert repaired.count("enabled: false") == 1
    assert repaired.count("enabled: true") == 1
    assert repaired.count("running: false") == 2
    assert "currentFrame: endFrame" in repaired
    assert repaired.count('baseColor: "#00000000"') == 2


def test_avatar_catalog_contains_only_bundled_assets():
    avatars = avatar_catalog()

    assert avatars
    assert DEFAULT_AVATAR_ID == avatars[0].id
    assert len({avatar.id for avatar in avatars}) == len(avatars)
    assert all(avatar.source_path.is_file() for avatar in avatars)
    assert all(avatar.thumbnail_path.is_file() for avatar in avatars)
    assert get_avatar(DEFAULT_AVATAR_ID) is avatars[0]


def test_prepare_avatar_copies_preconditioned_release_assets_without_subprocess(
    tmp_path, monkeypatch
):
    from aptiordesk.features.interviews.avatar import assets as assets_module

    library = tmp_path / "library"
    conditioned = library / "ari-conditioned"
    (conditioned / "maps").mkdir(parents=True)
    (conditioned / "meshes").mkdir()
    (conditioned / "Ari.qml").write_text("import QtQuick3D\nNode {}", encoding="utf-8")
    (conditioned / "maps" / "skin.png").write_bytes(b"texture")
    (conditioned / "meshes" / "body.mesh").write_bytes(b"mesh")
    cache = tmp_path / "models"

    monkeypatch.setattr(assets_module, "_library_dir", lambda: library)
    monkeypatch.setattr(assets_module.paths, "models_dir", lambda: cache)
    monkeypatch.setattr(
        assets_module.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("release assets must not invoke pyside6-balsam")
        ),
    )

    component = prepare_avatar(DEFAULT_AVATAR_ID)

    assert component.is_file()
    assert component.read_text(encoding="utf-8") == "import QtQuick3D\nNode {}"
    assert (component.parent / "maps" / "skin.png").read_bytes() == b"texture"
    assert (component.parent / "meshes" / "body.mesh").read_bytes() == b"mesh"


def test_avatar_runtime_status_requires_preconditioned_release_assets(tmp_path, monkeypatch):
    from aptiordesk.features.interviews.avatar import assets as assets_module

    monkeypatch.setattr(assets_module, "_library_dir", lambda: tmp_path)

    ready, detail = bundled_avatar_runtime_status()

    assert not ready
    assert "conditioned interviewer assets" in detail


def test_avatar_picker_lists_only_the_curated_catalog(qtbot):
    dialog = AvatarPickerDialog(DEFAULT_AVATAR_ID)
    qtbot.addWidget(dialog)

    assert dialog.list.count() == len(avatar_catalog())
    assert dialog.selected_avatar_id == DEFAULT_AVATAR_ID
    assert dialog.windowTitle() == "Choose your interviewer"


def test_kokoro_discovery_does_not_depend_on_working_directory(tmp_path, monkeypatch):
    project = tmp_path / "project"
    module_file = (
        project / "src" / "aptiordesk" / "features" / "interviews" / "voice" / "synthesis.py"
    )
    module_file.parent.mkdir(parents=True)
    model_dir = project / "models" / "kokoro"
    model_dir.mkdir(parents=True)
    model = model_dir / "kokoro-v1.0.int8.onnx"
    voices = model_dir / "voices-v1.0.bin"
    model.write_bytes(b"model")
    voices.write_bytes(b"voices")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    monkeypatch.setattr(synthesis_module, "__file__", str(module_file))
    monkeypatch.setattr(
        synthesis_module.paths,
        "models_dir",
        lambda: tmp_path / "empty-app-models",
    )
    monkeypatch.chdir(elsewhere)

    assert synthesis_module._kokoro_files() == (model, voices)


def test_avatar_selects_one_blink_and_mouth_control_family(qtbot):
    controller = AvatarController(rng=_PredictableRandom())
    stage = AvatarStage(controller)
    qtbot.addWidget(stage)
    controls = {}
    for name in (
        "eyeBlinkLeft",
        "eyeBlinkRight",
        "Eye_Blink_L",
        "Eye_Blink_R",
        "jawOpen",
        "A25_Jaw_Open",
        "mouthClose",
        "mouthPressLeft",
        "mouthPressRight",
        "mouthRollLower",
        "mouthPucker",
        "V_Open",
    ):
        target = QObject()
        target.setProperty("weight", 0.0)
        controls[name] = [target]
    stage._controls = controls
    stage._select_control_families()

    stage.set_blink(0.8)
    assert controls["eyeBlinkLeft"][0].property("weight") == 0.8
    assert controls["eyeBlinkRight"][0].property("weight") == 0.8
    assert controls["Eye_Blink_L"][0].property("weight") == 0.0
    assert controls["Eye_Blink_R"][0].property("weight") == 0.0

    stage.set_viseme("open", 0.6)
    for _ in range(20):
        stage._animate_mouth()
    assert abs(controls["jawOpen"][0].property("weight") - 0.372) < 0.005
    assert controls["A25_Jaw_Open"][0].property("weight") == 0.0
    assert controls["V_Open"][0].property("weight") == 0.0

    stage.set_viseme("tight", 0.8)
    for _ in range(20):
        stage._animate_mouth()
    # ARKit mouthClose is a jaw-open corrective, not a neutral consonant pose.
    assert controls["mouthClose"][0].property("weight") == 0.0
    assert 0.0 < controls["mouthPressLeft"][0].property("weight") <= 0.11
    assert 0.0 < controls["mouthPressRight"][0].property("weight") <= 0.11
    assert controls["jawOpen"][0].property("weight") < 0.005
    controller.shutdown()


def test_kokoro_mouth_cues_follow_audio_energy_and_phonemes():
    sample_rate = 24_000
    silence = np.zeros(sample_rate // 10, dtype=np.float32)
    voiced = np.full(sample_rate // 5, 0.2, dtype=np.float32)
    samples = np.concatenate((silence, voiced, silence))

    cues = synthesis_module._build_mouth_cues(samples, sample_rate, "pɑːd")

    assert cues
    assert cues[0].viseme is None
    assert any(cue.viseme in {"explosive", "open", "tight"} for cue in cues)
    assert cues[-1].viseme is None
    assert all(0.0 <= cue.weight <= 0.72 for cue in cues)


def test_kokoro_mouth_cues_do_not_advance_phonemes_during_pauses():
    sample_rate = 24_000
    voiced = np.full(sample_rate // 5, 0.2, dtype=np.float32)
    pause = np.zeros(sample_rate // 2, dtype=np.float32)
    samples = np.concatenate((voiced, pause, voiced))

    cues = synthesis_module._build_mouth_cues(samples, sample_rate, "pai")

    def cue_at(time_ms):
        return max(
            (cue for cue in cues if cue.time_ms <= time_ms),
            key=lambda cue: cue.time_ms,
        )

    assert cue_at(300).viseme is None
    assert cue_at(740).viseme == "wide"
    assert cues[-1].viseme is None


def test_speech_cue_clock_compensates_for_renderer_interpolation():
    cue_times = (0, 100, 200, 300)

    assert (
        playback_module._cue_index_for_position(
            cue_times,
            60,
            400,
        )
        == 1
    )
    assert (
        playback_module._cue_index_for_position(
            cue_times,
            380,
            400,
        )
        == 3
    )
    assert playback_module.MOUTH_UPDATE_INTERVAL_MS <= 20


def test_speech_preload_is_reused_without_a_second_synthesis(tmp_path, monkeypatch):
    artifact = synthesis_module.SpeechArtifact(
        tmp_path / "question.wav",
        "Kokoro neural voice",
    )
    player = SpeechPlayer()
    settings = VoiceSettings()
    text = "Tell me about your experience."
    key = playback_module._speech_cache_key(text, settings)
    player._preload_ready((key, text, artifact))
    monkeypatch.setattr(
        playback_module,
        "synthesize",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("cached speech must not be synthesized again")
        ),
    )

    played = []
    monkeypatch.setattr(player, "_play_artifact", played.append)
    player._text = text
    player._settings = settings
    player._request_serial = 4
    player._begin(4)

    assert played[0][1] is artifact


def test_current_question_text_resizes_without_losing_content(qtbot):
    label = interview_page_module._ResponsiveQuestionLabel()
    qtbot.addWidget(label)
    label.resize(340, 130)
    question = (
        "Describe a complex project where priorities changed unexpectedly, "
        "how you aligned the team, and what measurable result you delivered."
    )

    label.setText(question)
    label._fit_text()

    assert label.text() == question
    assert 10.5 <= label.font().pointSizeF() <= 15.0
    assert label.wordWrap()
