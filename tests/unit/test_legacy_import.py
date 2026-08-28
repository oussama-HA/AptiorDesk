import json

from aptiordesk.database.repositories.profile_repo import ProfileRepository
from aptiordesk.database.repositories.provider_repo import ProviderRepository
from aptiordesk.database.repositories.settings_repo import SettingsRepository
from aptiordesk.features.profile.legacy_import import LEGACY_ANSWERS_KEY, import_legacy_config

LEGACY = {
    "ai_provider": "ollama",
    "ollama_model": "gemma3n:e4b",
    "settings": {
        "user_bio": "Engineer with 8 years in data platforms.",
        "meeting_context": "irrelevant",
        "custom_instructions": "Q: Tell me about yourself. A: ...",
    },
}


def _write(tmp_path, payload):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_full_import(conn, tmp_path):
    report = import_legacy_config(conn, _write(tmp_path, LEGACY))
    assert len(report.imported) == 3

    profile = ProfileRepository(conn).get_default()
    assert "8 years" in profile.summary

    active = ProviderRepository(conn).get_active()
    assert active is not None
    assert active.model == "gemma3n:e4b"

    assert SettingsRepository(conn).get(LEGACY_ANSWERS_KEY).startswith("Q:")


def test_import_never_overwrites_existing_data(conn, tmp_path):
    repo = ProfileRepository(conn)
    profile = repo.get_default()
    profile.summary = "My own summary"
    repo.save(profile)

    report = import_legacy_config(conn, _write(tmp_path, LEGACY))
    assert repo.get_default().summary == "My own summary"
    assert any("already filled" in s for s in report.skipped)


def test_import_is_idempotent(conn, tmp_path):
    path = _write(tmp_path, LEGACY)
    import_legacy_config(conn, path)
    second = import_legacy_config(conn, path)
    assert second.imported == []
    assert len(ProviderRepository(conn).list()) == 1


def test_empty_config(conn, tmp_path):
    report = import_legacy_config(conn, _write(tmp_path, {}))
    assert report.imported == []
    assert "Nothing to import" in report.summary()
