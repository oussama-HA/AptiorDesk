"""Main-thread neural speech playback with no silent provider fallback."""

from __future__ import annotations

import logging
from bisect import bisect_right
from collections import OrderedDict

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

from aptiordesk.ai import keystore
from aptiordesk.features.interviews.voice.settings import (
    ELEVENLABS_SECRET,
    VoiceProvider,
    VoiceSettings,
)
from aptiordesk.features.interviews.voice.synthesis import SpeechArtifact, synthesize
from aptiordesk.ui.workers import Worker

log = logging.getLogger(__name__)

MOUTH_UPDATE_INTERVAL_MS = 20
MOUTH_VISUAL_LEAD_MS = 45
SPEECH_CACHE_LIMIT = 4


class SpeechPlayer(QObject):
    started = Signal(str)
    finished = Signal()
    failed = Signal(str)
    position_changed = Signal(int, int)
    frame_changed = Signal(int, int, object, float, bool)
    preloaded = Signal(str)
    preload_failed = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._audio_output: QAudioOutput | None = None
        self._media: QMediaPlayer | None = None
        self._position_timer = QTimer(self)
        self._position_timer.setInterval(MOUTH_UPDATE_INTERVAL_MS)
        self._position_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._position_timer.timeout.connect(self._report_position)
        self._active = False
        self._text = ""
        self._settings = VoiceSettings()
        self._worker: Worker | None = None
        self._request_serial = 0
        self._pending_provider_label = ""
        self._started_emitted = False
        self._mouth_cues = ()
        self._mouth_cue_times: tuple[int, ...] = ()
        self._artifact_cache: OrderedDict[tuple, SpeechArtifact] = OrderedDict()
        self._preload_workers: dict[tuple, Worker] = {}
        self._waiting_preload: tuple[tuple, int] | None = None

    def speak(self, text: str, settings: VoiceSettings) -> None:
        self.stop()
        self._request_serial += 1
        request_serial = self._request_serial
        self._text = text
        self._settings = settings
        log.info(
            "Preparing interview speech with provider=%s voice=%s",
            settings.provider.value,
            settings.voice,
        )
        # Let the status/transition frame paint, then start immediately. The
        # former 180 ms delay added latency without improving reliability.
        QTimer.singleShot(0, lambda: self._begin(request_serial))

    def preload(self, text: str, settings: VoiceSettings) -> None:
        """Generate a future question while the candidate is answering."""
        if settings.provider == VoiceProvider.SYSTEM:
            return
        key = _speech_cache_key(text, settings)
        if key in self._artifact_cache or key in self._preload_workers:
            return
        api_key = self._api_key(settings)
        worker = Worker(
            lambda: (
                key,
                text,
                synthesize(text, settings, elevenlabs_api_key=api_key),
            ),
            self,
        )
        worker.result.connect(self._preload_ready)
        worker.error.connect(
            lambda exc, item_key=key, item_text=text: self._preload_error(item_key, item_text, exc)
        )
        worker.finished.connect(
            lambda item_key=key, item_worker=worker: (
                self._preload_workers.pop(item_key, None)
                if self._preload_workers.get(item_key) is item_worker
                else None
            )
        )
        self._preload_workers[key] = worker
        worker.start()

    def is_preloaded(self, text: str, settings: VoiceSettings) -> bool:
        return _speech_cache_key(text, settings) in self._artifact_cache

    def prepare_output(self) -> None:
        """Initialize the native audio output before the first question."""
        self._ensure_media()

    def clear_cache(self) -> None:
        self._artifact_cache.clear()
        self._waiting_preload = None

    def stop(self) -> None:
        self._request_serial += 1
        was_active = self._active
        self._active = False
        self._started_emitted = False
        self._mouth_cues = ()
        self._mouth_cue_times = ()
        self._waiting_preload = None
        self._position_timer.stop()
        if self._media is not None:
            self._media.stop()
        if was_active:
            self.finished.emit()

    def pause(self) -> None:
        if self._media is not None:
            self._media.pause()

    def resume(self) -> None:
        if self._media is not None:
            self._media.play()

    def _begin(self, request_serial: int) -> None:
        if request_serial != self._request_serial:
            return
        if self._settings.provider == VoiceProvider.SYSTEM:
            self._fail(
                "The legacy system voice is disabled for mock interviews. "
                "Choose Kokoro or ElevenLabs in Interview voice settings."
            )
            return
        settings = self._settings
        text = self._text
        key = _speech_cache_key(text, settings)
        cached = self._artifact_cache.get(key)
        if cached is not None:
            self._artifact_cache.move_to_end(key)
            self._play_artifact((request_serial, cached))
            return
        if key in self._preload_workers:
            self._waiting_preload = (key, request_serial)
            return
        api_key = self._api_key(settings)
        worker = Worker(
            lambda: (
                request_serial,
                key,
                synthesize(text, settings, elevenlabs_api_key=api_key),
            ),
            self,
        )
        worker.result.connect(self._synthesis_ready)
        worker.error.connect(
            lambda exc: (
                self._synthesis_failed(exc) if request_serial == self._request_serial else None
            )
        )
        worker.finished.connect(
            lambda: setattr(self, "_worker", None) if self._worker is worker else None
        )
        self._worker = worker
        worker.start()

    def _synthesis_ready(self, result) -> None:
        request_serial, key, artifact = result
        self._remember(key, artifact)
        self._play_artifact((request_serial, artifact))

    def _preload_ready(self, result) -> None:
        key, text, artifact = result
        self._remember(key, artifact)
        self.preloaded.emit(text)
        if self._waiting_preload == (key, self._request_serial):
            request_serial = self._request_serial
            self._waiting_preload = None
            self._play_artifact((request_serial, artifact))

    def _preload_error(self, key: tuple, text: str, exc: Exception) -> None:
        log.warning("Could not preload interviewer speech: %s", exc)
        self.preload_failed.emit(text, str(exc))
        if self._waiting_preload == (key, self._request_serial):
            self._waiting_preload = None
            self._synthesis_failed(exc)

    def _remember(self, key: tuple, artifact: SpeechArtifact) -> None:
        self._artifact_cache[key] = artifact
        self._artifact_cache.move_to_end(key)
        while len(self._artifact_cache) > SPEECH_CACHE_LIMIT:
            self._artifact_cache.popitem(last=False)

    @staticmethod
    def _api_key(settings: VoiceSettings) -> str | None:
        return (
            keystore.get_secret(ELEVENLABS_SECRET)
            if settings.provider == VoiceProvider.ELEVENLABS
            else None
        )

    def _play_artifact(self, result) -> None:
        request_serial, artifact = result
        if request_serial != self._request_serial:
            return
        self._ensure_media()
        self._active = True
        self._started_emitted = False
        self._pending_provider_label = artifact.provider_label
        self._mouth_cues = artifact.mouth_cues
        self._mouth_cue_times = tuple(cue.time_ms for cue in artifact.mouth_cues)
        assert self._media is not None
        self._media.setSource(QUrl.fromLocalFile(str(artifact.path)))
        self._media.play()
        self._position_timer.start()
        log.info("Playing interview speech with %s", artifact.provider_label)

    def _synthesis_failed(self, exc: Exception) -> None:
        log.warning(
            "Preferred interview speech provider %s failed: %s",
            self._settings.provider.value,
            exc,
        )
        self._fail(str(exc))

    def _media_status_changed(self, status) -> None:
        if status == QMediaPlayer.MediaStatus.EndOfMedia and self._active:
            self._complete()
        elif status == QMediaPlayer.MediaStatus.InvalidMedia and self._active:
            self._fail("The generated interviewer audio could not be played.")

    def _media_playback_state_changed(self, state) -> None:
        if (
            state == QMediaPlayer.PlaybackState.PlayingState
            and self._active
            and not self._started_emitted
        ):
            self._started_emitted = True
            self.started.emit(self._pending_provider_label)
            self._report_position()

    def _ensure_media(self) -> None:
        if self._media is not None:
            return
        self._audio_output = QAudioOutput(self)
        self._audio_output.setVolume(0.92)
        self._media = QMediaPlayer(self)
        self._media.setAudioOutput(self._audio_output)
        self._media.mediaStatusChanged.connect(self._media_status_changed)
        self._media.playbackStateChanged.connect(self._media_playback_state_changed)
        self._media.errorOccurred.connect(
            lambda _error, text: self._fail(text or "Audio playback failed.")
        )

    def _report_position(self) -> None:
        if self._media is not None:
            duration = self._media.duration()
            if duration <= 0:
                return
            position = self._media.position()
            self.position_changed.emit(position, duration)
            if self._mouth_cues:
                cue_index = _cue_index_for_position(
                    self._mouth_cue_times,
                    position,
                    duration,
                )
                cue = self._mouth_cues[cue_index]
                self.frame_changed.emit(position, duration, cue.viseme, cue.weight, True)
            else:
                self.frame_changed.emit(position, duration, None, 0.0, False)

    def _complete(self) -> None:
        self._active = False
        self._position_timer.stop()
        self.finished.emit()

    def _fail(self, message: str) -> None:
        self._active = False
        self._position_timer.stop()
        log.warning("Interview speech playback failed: %s", message)
        self.failed.emit(message)


def _cue_index_for_position(
    cue_times: tuple[int, ...],
    position_ms: int,
    duration_ms: int,
    *,
    visual_lead_ms: int = MOUTH_VISUAL_LEAD_MS,
) -> int:
    """Compensate for mouth interpolation while remaining on the audio clock."""
    aligned_position = min(
        max(0, duration_ms),
        max(0, position_ms + visual_lead_ms),
    )
    return max(
        0,
        min(
            len(cue_times) - 1,
            bisect_right(cue_times, aligned_position) - 1,
        ),
    )


def _speech_cache_key(text: str, settings: VoiceSettings) -> tuple:
    return (
        " ".join(text.split()),
        settings.provider.value,
        settings.voice,
        settings.accent,
        round(settings.speed, 3),
        round(settings.pitch, 3),
        round(settings.expressiveness, 3),
    )
