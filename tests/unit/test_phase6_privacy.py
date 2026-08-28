"""Backup, restore, deletion, and privacy guarantees."""

import json
import zipfile

import pytest

from aptiordesk.core.errors import DataError
from aptiordesk.database.models.cover_letter import CoverLetterInputs
from aptiordesk.database.models.profile import ProfileItem
from aptiordesk.database.models.provider import ProviderConfig, ProviderKind
from aptiordesk.database.models.resume import ResumeContent
from aptiordesk.database.repositories.profile_repo import ProfileRepository
from aptiordesk.database.repositories.provider_repo import ProviderRepository
from aptiordesk.database.repositories.resume_repo import ResumeRepository
from aptiordesk.features.cover_letters.service import CoverLetterService
from aptiordesk.features.jobs.service import JobService
from aptiordesk.features.privacy import service as export_service
from aptiordesk.features.resumes.service import ResumeService

JD = (
    "Senior Data Engineer at Initech. Requirements: Python, Airflow, and cloud "
    "warehouses. You will own the pipelines end to end. Remote within the US."
)


@pytest.fixture
def populated(conn):
    """A database with data across most tables."""
    profile_repo = ProfileRepository(conn)
    profile = profile_repo.get_default()
    profile.display_name = "Jane Roe"
    profile.contact.email = "jane@example.com"
    profile_repo.save(profile)
    profile_repo.add_item(
        ProfileItem(
            profile_id=profile.id,
            kind="experience",
            data={"title": "Data Engineer", "organization": "ACME"},
        )
    )
    content = ResumeContent.model_validate({"full_name": "Jane Roe", "summary": "Data engineer."})
    _, version = ResumeService(conn).create_manual("Base", content)
    job = JobService(conn).create_job(JD)
    letter = CoverLetterService(conn).create(job, version, CoverLetterInputs())
    CoverLetterService(conn)._repo.add_version(letter.id, "Dear team, ...")
    ProviderRepository(conn).create(
        ProviderConfig(name="Local Ollama", kind=ProviderKind.OLLAMA, model="gemma3")
    )
    return conn


class TestBackup:
    def test_export_contains_all_populated_tables(self, populated, tmp_path):
        path = export_service.export_backup(populated, tmp_path / "b.zip")
        assert path.exists()
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            assert export_service.MANIFEST_NAME in names
            manifest = json.loads(archive.read(export_service.MANIFEST_NAME))
            assert manifest["format"] == export_service.BACKUP_FORMAT
            assert manifest["tables"]["profiles"] == 1
            assert manifest["tables"]["resumes"] == 1
            profiles = json.loads(archive.read("data/profiles.json"))
            assert profiles[0]["display_name"] == "Jane Roe"

    def test_backup_never_contains_api_keys(self, populated, tmp_path, monkeypatch):
        """Keys live in the keyring; a backup file must not carry them."""
        from aptiordesk.ai import keystore

        # Built at runtime so this synthetic value never appears as a
        # key-shaped literal in the source (it would trip secret scanners).
        secret = "sk-" + "T3stK3y" * 4
        stored: dict[int, str] = {}
        monkeypatch.setattr(keystore, "set_key", lambda pid, key: stored.update({pid: key}))
        provider = ProviderRepository(populated).list()[0]
        keystore.set_key(provider.id, secret)

        path = export_service.export_backup(populated, tmp_path / "b.zip")
        raw = path.read_bytes()
        assert secret.encode() not in raw
        with zipfile.ZipFile(path) as archive:
            providers = json.loads(archive.read("data/ai_providers.json"))
            assert "api_key" not in providers[0]
            assert secret not in json.dumps(providers)

    def test_backup_excludes_browser_extension_pairing_key(self, populated, tmp_path):
        from aptiordesk.database.repositories.settings_repo import SettingsRepository
        from aptiordesk.integrations.browser_extension.bridge import TOKEN_SETTING

        token = "browser-pairing-" + "private" * 4
        SettingsRepository(populated).set(TOKEN_SETTING, token)

        path = export_service.export_backup(populated, tmp_path / "b.zip")

        with zipfile.ZipFile(path) as archive:
            settings = json.loads(archive.read("data/settings.json"))
        assert token not in json.dumps(settings)
        assert all(row["key"] != TOKEN_SETTING for row in settings)

    def test_roundtrip_restores_data(self, populated, tmp_path):
        path = export_service.export_backup(populated, tmp_path / "b.zip")
        export_service.delete_all_data(populated)
        assert export_service.data_summary(populated) == {}

        restored = export_service.restore_backup(populated, path)
        assert restored["profiles"] == 1
        profile = ProfileRepository(populated).get_default()
        assert profile.display_name == "Jane Roe"
        assert profile.contact.email == "jane@example.com"
        items = ProfileRepository(populated).list_items(profile.id, "experience")
        assert items[0].data["organization"] == "ACME"
        assert len(ResumeRepository(populated).list()) == 1

    def test_restore_replaces_existing_data(self, populated, tmp_path):
        path = export_service.export_backup(populated, tmp_path / "b.zip")
        # add data that is NOT in the backup
        JobService(populated).create_job(JD + " A second, different posting here.")
        assert len(JobService(populated)._repo.list()) == 2

        export_service.restore_backup(populated, path)
        assert len(JobService(populated)._repo.list()) == 1

    def test_restore_rejects_non_backup(self, populated, tmp_path):
        bogus = tmp_path / "not-a-backup.zip"
        with zipfile.ZipFile(bogus, "w") as archive:
            archive.writestr("hello.txt", "hi")
        with pytest.raises(DataError, match="not an AptiorDesk backup"):
            export_service.restore_backup(populated, bogus)

    def test_legacy_manifest_is_still_readable(self, tmp_path):
        path = tmp_path / "legacy.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(
                export_service.LEGACY_MANIFEST_NAME,
                json.dumps({"format": 1, "schema_version": 8, "tables": {}}),
            )

        manifest = export_service.read_manifest(path)
        assert manifest["format"] == 1
        assert manifest["_manifest_name"] == export_service.LEGACY_MANIFEST_NAME

    def test_restore_rejects_newer_format(self, populated, tmp_path):
        path = tmp_path / "future.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(
                export_service.MANIFEST_NAME,
                json.dumps({"format": 99, "schema_version": 1, "tables": {}}),
            )
        with pytest.raises(DataError, match="cannot read"):
            export_service.restore_backup(populated, path)

    def test_restore_rejects_newer_schema(self, populated, tmp_path):
        path = tmp_path / "newer.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(
                export_service.MANIFEST_NAME,
                json.dumps(
                    {
                        "format": export_service.BACKUP_FORMAT,
                        "schema_version": 999,
                        "tables": {},
                    }
                ),
            )
        with pytest.raises(DataError, match="newer version"):
            export_service.restore_backup(populated, path)

    def test_failed_restore_leaves_data_intact(self, populated, tmp_path):
        """A corrupt payload must not destroy what the user already has."""
        path = tmp_path / "corrupt.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(
                export_service.MANIFEST_NAME,
                json.dumps(
                    {
                        "format": export_service.BACKUP_FORMAT,
                        "schema_version": 1,
                        "tables": {"profiles": 1},
                    }
                ),
            )
            archive.writestr("data/profiles.json", json.dumps([{"nonexistent_column": "boom"}]))
        before = export_service.data_summary(populated)
        with pytest.raises(DataError, match="left\n?\\s*unchanged|unchanged"):
            export_service.restore_backup(populated, path)
        assert export_service.data_summary(populated) == before


class TestDeletion:
    def test_delete_all_empties_every_table(self, populated):
        assert export_service.data_summary(populated)
        removed = export_service.delete_all_data(populated)
        assert export_service.data_summary(populated) == {}
        assert any("profile" in item for item in removed)

    def test_delete_all_removes_keyring_entries(self, populated, monkeypatch):
        from aptiordesk.ai import keystore

        deleted: list[int] = []
        monkeypatch.setattr(keystore, "delete_key", deleted.append)
        provider_ids = [p.id for p in ProviderRepository(populated).list()]
        export_service.delete_all_data(populated)
        assert deleted == provider_ids

    def test_delete_all_on_empty_database_is_safe(self, conn):
        removed = export_service.delete_all_data(conn)
        assert export_service.data_summary(conn) == {}
        assert removed  # still reports what it cleared

    def test_data_summary_counts_rows(self, populated):
        summary = export_service.data_summary(populated)
        assert summary["profiles"] == 1
        assert summary["profile_items"] == 1
        assert summary["jobs"] == 1
        assert "settings" not in summary  # empty tables omitted


class TestLogRedaction:
    def test_provider_errors_do_not_leak_keys(self, caplog):
        """Adapter errors include response bodies; the filter must scrub keys."""
        import logging

        from aptiordesk.core.logging import RedactionFilter

        logger = logging.getLogger("aptiordesk.test.redaction")
        logger.addFilter(RedactionFilter())
        secret = "sk-" + "abcd1234" * 3
        with caplog.at_level(logging.INFO):
            logger.info("Request failed with key %s", secret)
        assert secret not in caplog.text
        assert "[REDACTED]" in caplog.text
