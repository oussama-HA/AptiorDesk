"""Opt-in import from the legacy whisper_interview_mvp ``config.json``.

The legacy file contained a free-text bio, Ollama model choice, and
personal interview notes. Nothing is imported automatically — the user picks
the file explicitly, and we report exactly what was brought in.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from aptiordesk.database.models.provider import ProviderConfig, ProviderKind
from aptiordesk.database.repositories.profile_repo import ProfileRepository
from aptiordesk.database.repositories.provider_repo import ProviderRepository
from aptiordesk.database.repositories.settings_repo import SettingsRepository

LEGACY_ANSWERS_KEY = "legacy_interview_notes"  # surfaced again in Phase 4 (answer library)


@dataclass
class ImportReport:
    imported: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = []
        if self.imported:
            lines.append("Imported:")
            lines.extend(f"  • {item}" for item in self.imported)
        if self.skipped:
            lines.append("Skipped (already present or empty):")
            lines.extend(f"  • {item}" for item in self.skipped)
        return "\n".join(lines) or "Nothing to import."


def import_legacy_config(conn: sqlite3.Connection, config_path: str | Path) -> ImportReport:
    report = ImportReport()
    data = json.loads(Path(config_path).read_text(encoding="utf-8"))
    settings = data.get("settings", {})

    profile_repo = ProfileRepository(conn)
    profile = profile_repo.get_default()

    bio = (settings.get("user_bio") or "").strip()
    if bio and not profile.summary:
        profile.summary = bio
        profile_repo.save(profile)
        report.imported.append("Professional bio → profile summary")
    elif bio:
        report.skipped.append("Bio (profile summary already filled)")

    model = (data.get("ollama_model") or "").strip()
    provider_repo = ProviderRepository(conn)
    if model and not provider_repo.list():
        created = provider_repo.create(
            ProviderConfig(name="Local Ollama (imported)", kind=ProviderKind.OLLAMA, model=model)
        )
        provider_repo.set_active(created.id)
        report.imported.append(f"Ollama provider with model '{model}'")
    elif model:
        report.skipped.append("Ollama model (a provider is already configured)")

    notes = (settings.get("custom_instructions") or "").strip()
    settings_repo = SettingsRepository(conn)
    if notes and settings_repo.get(LEGACY_ANSWERS_KEY) is None:
        settings_repo.set(LEGACY_ANSWERS_KEY, notes)
        report.imported.append(
            "Interview notes (saved; they will surface in the Phase 4 answer library)"
        )
    elif notes:
        report.skipped.append("Interview notes (already imported)")

    return report
