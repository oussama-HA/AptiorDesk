from aptiordesk.database.models.profile import ProfileItem
from aptiordesk.database.models.provider import CLIAdapterKind, ProviderConfig, ProviderKind
from aptiordesk.database.repositories.profile_repo import ProfileRepository
from aptiordesk.database.repositories.provider_repo import ProviderRepository
from aptiordesk.database.repositories.settings_repo import SettingsRepository


class TestSettingsRepository:
    def test_get_missing_returns_default(self, conn):
        repo = SettingsRepository(conn)
        assert repo.get("nope", 42) == 42

    def test_set_get_roundtrip_json(self, conn):
        repo = SettingsRepository(conn)
        repo.set("theme", {"dark": True, "accent": "#2f6fed"})
        assert repo.get("theme") == {"dark": True, "accent": "#2f6fed"}

    def test_overwrite(self, conn):
        repo = SettingsRepository(conn)
        repo.set("k", 1)
        repo.set("k", 2)
        assert repo.get("k") == 2


class TestProfileRepository:
    def test_get_default_creates_singleton(self, conn):
        repo = ProfileRepository(conn)
        first = repo.get_default()
        second = repo.get_default()
        assert first.id == second.id

    def test_save_roundtrip(self, conn):
        repo = ProfileRepository(conn)
        profile = repo.get_default()
        profile.display_name = "Ada Lovelace"
        profile.contact.email = "ada@example.com"
        profile.preferences.target_titles = ["Engineer"]
        profile.work_auth.needs_sponsorship = True
        repo.save(profile)

        reloaded = repo.get_default()
        assert reloaded.display_name == "Ada Lovelace"
        assert reloaded.contact.email == "ada@example.com"
        assert reloaded.preferences.target_titles == ["Engineer"]
        assert reloaded.work_auth.needs_sponsorship is True

    def test_item_crud(self, conn):
        repo = ProfileRepository(conn)
        profile = repo.get_default()
        item = repo.add_item(
            ProfileItem(
                profile_id=profile.id,
                kind="experience",
                data={"title": "Engineer", "organization": "Acme", "highlights": ["Shipped X"]},
            )
        )
        assert item.id is not None

        items = repo.list_items(profile.id, "experience")
        assert len(items) == 1
        parsed = items[0].parsed()
        assert parsed.title == "Engineer"
        assert parsed.highlights == ["Shipped X"]

        items[0].data["title"] = "Senior Engineer"
        repo.update_item(items[0])
        assert repo.list_items(profile.id, "experience")[0].data["title"] == "Senior Engineer"

        repo.delete_item(items[0].id)
        assert repo.list_items(profile.id, "experience") == []

    def test_item_data_validated_on_write(self, conn):
        import pytest
        from pydantic import ValidationError

        repo = ProfileRepository(conn)
        profile = repo.get_default()
        with pytest.raises(ValidationError):
            repo.add_item(
                ProfileItem(
                    profile_id=profile.id,
                    kind="experience",
                    data={"highlights": "not-a-list"},
                )
            )


class TestProviderRepository:
    def _make(self, name="p", kind=ProviderKind.OLLAMA) -> ProviderConfig:
        return ProviderConfig(name=name, kind=kind, model="gemma3")

    def test_create_and_get(self, conn):
        repo = ProviderRepository(conn)
        created = repo.create(self._make())
        fetched = repo.get(created.id)
        assert fetched.name == "p"
        assert fetched.kind == ProviderKind.OLLAMA

    def test_only_one_active(self, conn):
        repo = ProviderRepository(conn)
        a = repo.create(self._make("a"))
        b = repo.create(self._make("b", ProviderKind.OPENAI_COMPAT))
        repo.set_active(a.id)
        repo.set_active(b.id)
        actives = [c for c in repo.list() if c.is_active]
        assert len(actives) == 1
        assert actives[0].id == b.id
        assert repo.get_active().id == b.id

    def test_delete(self, conn):
        repo = ProviderRepository(conn)
        created = repo.create(self._make())
        repo.delete(created.id)
        assert repo.get(created.id) is None
        assert repo.list() == []

    def test_effective_base_url_default(self):
        config = ProviderConfig(kind=ProviderKind.ANTHROPIC)
        assert config.effective_base_url() == "https://api.anthropic.com"
        config = ProviderConfig(kind=ProviderKind.OLLAMA, base_url="http://localhost:11434/")
        assert config.effective_base_url() == "http://localhost:11434"
        assert config.is_local

    def test_device_cli_fields_roundtrip(self, conn):
        repo = ProviderRepository(conn)
        created = repo.create(
            ProviderConfig(
                name="My Claude CLI",
                kind=ProviderKind.CLI,
                model="sonnet",
                cli_adapter=CLIAdapterKind.CLAUDE,
                cli_executable="C:/Tools/claude.exe",
            )
        )
        fetched = repo.get(created.id)
        assert fetched.kind == ProviderKind.CLI
        assert fetched.cli_adapter == CLIAdapterKind.CLAUDE
        assert fetched.cli_executable == "C:/Tools/claude.exe"
