"""Persisted, provider-neutral interviewer voice preferences."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum

from aptiordesk.database.repositories.settings_repo import SettingsRepository

SETTINGS_KEY = "interview.voice.v1"
ELEVENLABS_SECRET = "interview-tts-elevenlabs"


class VoiceProvider(StrEnum):
    KOKORO = "kokoro"
    ELEVENLABS = "elevenlabs"
    SYSTEM = "system"


KOKORO_VOICES = {
    "af_heart": "Heart — warm feminine, American",
    "af_bella": "Bella — clear feminine, American",
    "af_nicole": "Nicole — calm feminine, American",
    "af_sarah": "Sarah — professional feminine, American",
    "bf_emma": "Emma — warm feminine, British",
    "bf_isabella": "Isabella — clear feminine, British",
}


@dataclass(slots=True)
class VoiceSettings:
    provider: VoiceProvider = VoiceProvider.KOKORO
    voice: str = "af_heart"
    accent: str = "en-us"
    speed: float = 0.96
    pitch: float = 0.0
    expressiveness: float = 0.32
    allow_fallback: bool = False
    reduced_motion: bool = False

    @classmethod
    def from_dict(cls, value: object) -> VoiceSettings:
        if not isinstance(value, dict):
            return cls()
        try:
            provider = VoiceProvider(value.get("provider", VoiceProvider.KOKORO))
        except ValueError:
            provider = VoiceProvider.KOKORO
        # The legacy operating-system voice is deliberately not an interview
        # provider anymore. Existing preferences are migrated to Kokoro rather
        # than silently retaining the low-quality fallback.
        if provider == VoiceProvider.SYSTEM:
            provider = VoiceProvider.KOKORO
        voice = str(value.get("voice") or "af_heart")
        if provider == VoiceProvider.KOKORO and voice not in KOKORO_VOICES:
            voice = "af_heart"
        return cls(
            provider=provider,
            voice=voice,
            accent=str(value.get("accent") or "en-us"),
            speed=max(0.75, min(1.25, float(value.get("speed", 0.96)))),
            pitch=max(-0.5, min(0.5, float(value.get("pitch", 0.0)))),
            expressiveness=max(0.0, min(1.0, float(value.get("expressiveness", 0.32)))),
            allow_fallback=False,
            reduced_motion=bool(value.get("reduced_motion", False)),
        )

    def to_dict(self) -> dict:
        result = asdict(self)
        result["provider"] = self.provider.value
        return result


class VoiceSettingsRepository:
    def __init__(self, conn):
        self._settings = SettingsRepository(conn)

    def load(self) -> VoiceSettings:
        stored = self._settings.get(SETTINGS_KEY, {})
        settings = VoiceSettings.from_dict(stored)
        # Persist the canonical value so browser-style refreshes, new sessions,
        # and upgraded installations all converge on the same safe default.
        if stored != settings.to_dict():
            self.save(settings)
        return settings

    def save(self, settings: VoiceSettings) -> None:
        settings.allow_fallback = False
        if settings.provider == VoiceProvider.SYSTEM:
            settings.provider = VoiceProvider.KOKORO
            settings.voice = "af_heart"
        self._settings.set(SETTINGS_KEY, settings.to_dict())
