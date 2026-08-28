"""First-run setup wizard behaviour."""

import pytest
from PySide6.QtWidgets import QLabel

from aptiordesk.app import onboarding as onboarding_module
from aptiordesk.app.onboarding import (
    OnboardingWizard,
    mark_onboarded,
    needs_onboarding,
)
from aptiordesk.core import environment as env
from aptiordesk.core.system_health import (
    ComponentCheck,
    ComponentState,
    SystemHealthReport,
)
from aptiordesk.database import db
from aptiordesk.database.models.provider import (
    DEFAULT_BASE_URLS,
    ProviderConfig,
    ProviderKind,
)
from aptiordesk.database.repositories.profile_repo import ProfileRepository
from aptiordesk.database.repositories.provider_repo import ProviderRepository
from aptiordesk.features.interviews.voice.installer import KokoroRuntimeStatus


@pytest.fixture
def memconn():
    connection = db.connect(":memory:")
    db.migrate(connection)
    yield connection
    connection.close()


@pytest.fixture
def offline(monkeypatch):
    """No probing the real machine during tests."""
    monkeypatch.setattr(env, "probe_ollama", lambda *a, **k: env.OllamaStatus())
    monkeypatch.setattr(env, "whisper_model_present", lambda *a, **k: False)
    monkeypatch.setattr(env, "feature_status", lambda feature: (False, ["sounddevice"]))
    monkeypatch.setattr(
        onboarding_module,
        "inspect_system",
        lambda *_args, **_kwargs: SystemHealthReport(
            "now",
            (
                ComponentCheck(
                    "core",
                    "AptiorDesk core",
                    ComponentState.READY,
                    "Ready",
                    required=True,
                ),
            ),
        ),
    )
    monkeypatch.setattr(
        onboarding_module,
        "inspect_kokoro_runtime",
        lambda: KokoroRuntimeStatus(False, "Kokoro needs repair."),
    )


class TestFirstRunFlag:
    def test_first_run_is_detected_then_cleared(self, memconn):
        assert needs_onboarding(memconn)
        mark_onboarded(memconn)
        assert not needs_onboarding(memconn)


class TestWizard:
    def test_has_all_steps_and_starts_at_the_first(self, qtbot, memconn, offline):
        wizard = OnboardingWizard(memconn)
        qtbot.addWidget(wizard)
        assert wizard.stack.count() == 6
        assert wizard.stack.currentIndex() == 0
        assert "Step 1 of 6" in wizard.step_label.text()
        assert not wizard.back_button.isEnabled()

    def test_navigates_forward_and_back(self, qtbot, memconn, offline):
        wizard = OnboardingWizard(memconn)
        qtbot.addWidget(wizard)
        wizard._next()
        assert wizard.stack.currentIndex() == 1
        assert wizard.back_button.isEnabled()
        wizard._back()
        assert wizard.stack.currentIndex() == 0

    def test_skip_jumps_to_the_summary(self, qtbot, memconn, offline):
        wizard = OnboardingWizard(memconn)
        qtbot.addWidget(wizard)
        wizard._skip()
        assert wizard.stack.currentIndex() == 1
        qtbot.waitUntil(lambda: wizard.steps[1]._report is not None, timeout=2000)
        wizard._skip()
        assert wizard.stack.currentIndex() == wizard.stack.count() - 1
        assert wizard.next_button.text() == "Finish"
        assert not wizard.skip_button.isVisible()

    def test_finishing_marks_setup_complete(self, qtbot, memconn, offline):
        wizard = OnboardingWizard(memconn)
        qtbot.addWidget(wizard)
        with qtbot.waitSignal(wizard.finished_setup, timeout=1000):
            wizard._skip()
            qtbot.waitUntil(lambda: wizard.steps[1]._report is not None, timeout=2000)
            wizard._skip()
            wizard._next()
        assert not needs_onboarding(memconn)

    def test_closing_does_not_nag_on_next_launch(self, qtbot, memconn, offline):
        """Dismissing the wizard is a choice, not a deferral."""
        wizard = OnboardingWizard(memconn)
        qtbot.addWidget(wizard)
        wizard._required_checks_passed = True
        wizard.reject()
        assert not needs_onboarding(memconn)

    def test_profile_step_saves_what_was_typed(self, qtbot, memconn, offline):
        wizard = OnboardingWizard(memconn)
        qtbot.addWidget(wizard)
        profile_step = wizard.steps[4]
        profile_step.on_enter()
        profile_step.name_edit.setText("Jane Roe")
        profile_step.email_edit.setText("jane@example.com")
        profile_step.titles_edit.setText("Data Engineer, Analytics Engineer")
        assert profile_step.on_leave()

        profile = ProfileRepository(memconn).get_default()
        assert profile.display_name == "Jane Roe"
        assert profile.contact.email == "jane@example.com"
        assert profile.preferences.target_titles == [
            "Data Engineer",
            "Analytics Engineer",
        ]

    def test_ai_step_offers_install_when_ollama_is_absent(self, qtbot, memconn, monkeypatch):
        monkeypatch.setattr(env, "feature_status", lambda f: (False, ["sounddevice"]))
        monkeypatch.setattr(env, "whisper_model_present", lambda *a, **k: False)
        wizard = OnboardingWizard(memconn)
        qtbot.addWidget(wizard)
        ai_step = wizard.steps[2]
        ai_step._show_status(env.OllamaStatus(running=False, installed=False))
        assert ai_step.get_ollama_button.isVisible() or not ai_step.isVisible()
        assert "Install Ollama" in ai_step.status_label.text()

    def test_ai_step_shows_models_when_ollama_is_running(self, qtbot, memconn, monkeypatch):
        monkeypatch.setattr(env, "feature_status", lambda f: (True, []))
        monkeypatch.setattr(env, "whisper_model_present", lambda *a, **k: True)
        wizard = OnboardingWizard(memconn)
        qtbot.addWidget(wizard)
        ai_step = wizard.steps[2]
        ai_step._show_status(env.OllamaStatus(running=True, version="0.5.1", models=["gemma3:4b"]))
        assert "running" in ai_step.status_label.text()
        assert "gemma3:4b" in ai_step.status_label.text()
        assert ai_step.model_card.isHidden()

    def test_ai_step_only_offers_model_download_when_ollama_has_no_models(
        self, qtbot, memconn, offline
    ):
        wizard = OnboardingWizard(memconn)
        qtbot.addWidget(wizard)
        ai_step = wizard.steps[2]

        ai_step._show_status(env.OllamaStatus(running=True, models=[]))

        assert not ai_step.model_card.isHidden()
        assert ai_step.pull_button.isEnabled()

    def test_ai_step_labels_local_and_cloud_costs(self, qtbot, memconn, offline):
        wizard = OnboardingWizard(memconn)
        qtbot.addWidget(wizard)
        ai_step = wizard.steps[2]

        assert ai_step.ollama_cost_badge.text() == "FREE"
        assert ai_step.ollama_cost_badge.property("tone") == "success"
        assert ai_step.cloud_cost_badge.text() == "MAY COST MONEY"
        assert ai_step.cloud_cost_badge.property("tone") == "warning"

    def test_ai_step_offers_multiple_cloud_provider_types(self, qtbot, memconn, offline):
        wizard = OnboardingWizard(memconn)
        qtbot.addWidget(wizard)
        ai_step = wizard.steps[2]
        labels = {ai_step.cloud_kind.itemText(index) for index in range(ai_step.cloud_kind.count())}

        assert {
            "OpenAI",
            "Anthropic Claude",
            "Google Gemini",
            "Other OpenAI-compatible provider",
        } <= labels

    def test_ai_step_saves_the_selected_cloud_provider(self, qtbot, memconn, offline, monkeypatch):
        stored = {}
        monkeypatch.setattr(
            onboarding_module.keystore,
            "set_key",
            lambda provider_id, key: stored.update(provider_id=provider_id, key=key),
        )
        wizard = OnboardingWizard(memconn)
        qtbot.addWidget(wizard)
        ai_step = wizard.steps[2]
        ai_step.cloud_card.clicked.emit()
        ai_step.cloud_kind.setCurrentIndex(ai_step.cloud_kind.findData("anthropic"))
        ai_step.cloud_key.setText("secret")
        ai_step.cloud_model.setText("chosen-model")

        assert ai_step.on_leave()
        active = ProviderRepository(memconn).get_active()
        assert active is not None
        assert active.kind == ProviderKind.ANTHROPIC
        assert active.model == "chosen-model"
        assert active.base_url == DEFAULT_BASE_URLS[ProviderKind.ANTHROPIC]
        assert stored == {"provider_id": active.id, "key": "secret"}

    def test_clicking_ollama_card_selects_and_saves_detected_model(self, qtbot, memconn, offline):
        wizard = OnboardingWizard(memconn)
        qtbot.addWidget(wizard)
        ai_step = wizard.steps[2]
        ai_step._show_status(env.OllamaStatus(running=True, installed=True, models=["gemma3:4b"]))

        ai_step.status_card.clicked.emit()

        assert ai_step.status_card.property("selected")
        assert not ai_step.cloud_card.property("selected")
        assert ai_step.status_card.selection_indicator.isVisible() or not ai_step.isVisible()
        assert ai_step.cloud_card.selection_indicator.isHidden()
        assert ai_step.on_leave()
        active = ProviderRepository(memconn).get_active()
        assert active is not None
        assert active.kind == ProviderKind.OLLAMA
        assert active.model == "gemma3:4b"

    def test_clicking_cloud_card_requires_cloud_credentials(self, qtbot, memconn, offline):
        wizard = OnboardingWizard(memconn)
        qtbot.addWidget(wizard)
        ai_step = wizard.steps[2]

        ai_step.cloud_card.clicked.emit()

        assert ai_step.cloud_card.property("selected")
        assert not ai_step.status_card.property("selected")
        assert not ai_step.on_leave()
        assert "API key" in ai_step.cloud_status.text()

    def test_provider_choice_cards_are_compact_and_reveal_one_detail_panel(
        self, qtbot, memconn, offline
    ):
        wizard = OnboardingWizard(memconn)
        qtbot.addWidget(wizard)
        ai_step = wizard.steps[2]

        assert ai_step.status_card.minimumHeight() == ai_step.cloud_card.minimumHeight()
        assert ai_step.status_card.maximumHeight() == ai_step.cloud_card.maximumHeight()
        assert ai_step.status_card.cost_badge.parent() is ai_step.status_card
        assert ai_step.cloud_card.cost_badge.parent() is ai_step.cloud_card
        assert all(
            label.text() != "SELECTED"
            for label in ai_step.status_card.findChildren(QLabel)
            + ai_step.cloud_card.findChildren(QLabel)
        )
        assert ai_step.cloud_details_card.isHidden()

        ai_step.cloud_card.clicked.emit()
        assert not ai_step.cloud_details_card.isHidden()
        assert ai_step.model_card.isHidden()

        ai_step.status_card.clicked.emit()
        assert ai_step.cloud_details_card.isHidden()

    def test_pulled_model_becomes_the_active_provider(self, qtbot, memconn, offline):
        wizard = OnboardingWizard(memconn)
        qtbot.addWidget(wizard)
        ai_step = wizard.steps[2]
        ai_step._save_ollama_provider("gemma3:4b")

        active = ProviderRepository(memconn).get_active()
        assert active is not None
        assert active.kind == ProviderKind.OLLAMA
        assert active.model == "gemma3:4b"

    def test_pulling_again_updates_the_existing_provider(self, qtbot, memconn, offline):
        repo = ProviderRepository(memconn)
        repo.create(ProviderConfig(name="Local Ollama", kind=ProviderKind.OLLAMA, model="old"))
        wizard = OnboardingWizard(memconn)
        qtbot.addWidget(wizard)
        wizard.steps[2]._save_ollama_provider("gemma3:12b")

        providers = repo.list()
        assert len(providers) == 1  # updated, not duplicated
        assert providers[0].model == "gemma3:12b"
        assert providers[0].is_active

    def test_summary_reports_what_is_and_is_not_ready(self, qtbot, memconn, offline):
        wizard = OnboardingWizard(memconn)
        qtbot.addWidget(wizard)
        summary = wizard.steps[5]
        summary.on_enter()
        text = summary.summary_label.text()
        assert "No AI provider yet" in text
        assert "Voice practice not installed" in text

        ProviderRepository(memconn).set_active(
            ProviderRepository(memconn)
            .create(ProviderConfig(name="Local Ollama", kind=ProviderKind.OLLAMA, model="gemma3"))
            .id
        )
        summary.on_enter()
        assert "runs on this computer" in summary.summary_label.text()


class TestWorkerProgress:
    """The wizard reports download progress from a background thread; it must
    arrive on the UI thread via a signal, never by touching widgets directly."""

    def test_progress_callback_is_passed_and_emitted(self, qtbot):
        from aptiordesk.ui.workers import Worker

        received: list[object] = []

        def job(report):
            for value in (1, 2, 3):
                report(value)
            return "done"

        worker = Worker(job)
        worker.progress.connect(received.append)
        with qtbot.waitSignal(worker.result, timeout=2000) as blocker:
            worker.start()
        assert blocker.args == ["done"]
        assert received == [1, 2, 3]

    def test_zero_argument_functions_still_work(self, qtbot):
        from aptiordesk.ui.workers import Worker

        worker = Worker(lambda: "plain")
        with qtbot.waitSignal(worker.result, timeout=2000) as blocker:
            worker.start()
        assert blocker.args == ["plain"]

    def test_errors_arrive_as_a_signal(self, qtbot):
        from aptiordesk.ui.workers import Worker

        def boom():
            raise ValueError("nope")

        worker = Worker(boom)
        with qtbot.waitSignal(worker.error, timeout=2000) as blocker:
            worker.start()
        assert isinstance(blocker.args[0], ValueError)
