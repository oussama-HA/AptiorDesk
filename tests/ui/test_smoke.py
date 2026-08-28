"""UI smoke tests (offscreen). Verifies the shell builds, pages exist, and
core interactions round-trip through the database."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton

from aptiordesk.database import db


@pytest.fixture
def memconn():
    connection = db.connect(":memory:")
    db.migrate(connection)
    yield connection
    connection.close()


NAV_LABELS = [
    "Home",
    "Profile",
    "Resumes",
    "Jobs",
    "Tailoring",
    "Cover Letters",
    "Interview",
    "Settings",
    "Privacy & Data",
]


def test_main_window_builds_with_all_pages(qtbot, memconn):
    from aptiordesk.app.main_window import MainWindow

    window = MainWindow(memconn)
    qtbot.addWidget(window)
    assert window.nav.count() == window.stack.count() == len(NAV_LABELS)
    labels = [window.nav.item(i).text() for i in range(window.nav.count())]
    assert labels == NAV_LABELS
    visible_copy = " ".join(label.text() for label in window.findChildren(QLabel))
    assert "LOCAL" not in visible_copy
    assert "Oussama Hamida" in visible_copy
    assert "Glidd.io" in visible_copy


def test_nav_switches_stack(qtbot, memconn):
    from aptiordesk.app.main_window import MainWindow

    window = MainWindow(memconn)
    qtbot.addWidget(window)
    for row in range(window.nav.count()):
        window.nav.setCurrentRow(row)
        assert window.stack.currentIndex() == row
        assert window.nav.item(row).text() in window.workspace_context.text()


def test_dashboard_recommends_the_first_missing_product_foundation(qtbot, memconn):
    from aptiordesk.features.dashboard.page import DashboardPage

    page = DashboardPage(memconn)
    qtbot.addWidget(page)

    assert page._next_destination == "Profile"
    assert "profile" in page.next_title.text().lower()


def test_profile_page_saves_fields(qtbot, memconn):
    from aptiordesk.database.repositories.profile_repo import ProfileRepository
    from aptiordesk.features.profile.page import ProfilePage

    page = ProfilePage(memconn)
    qtbot.addWidget(page)
    page.display_name.setText("Test User")
    page.email.setText("test@example.com")
    page.target_titles.setText("Engineer, Analyst")
    page.save()

    profile = ProfileRepository(memconn).get_default()
    assert profile.display_name == "Test User"
    assert profile.contact.email == "test@example.com"
    assert profile.preferences.target_titles == ["Engineer", "Analyst"]


def test_settings_page_lists_providers(qtbot, memconn):
    from aptiordesk.database.models.provider import ProviderConfig, ProviderKind
    from aptiordesk.database.repositories.provider_repo import ProviderRepository
    from aptiordesk.features.settings.page import SettingsPage

    repo = ProviderRepository(memconn)
    repo.create(ProviderConfig(name="Local Ollama", kind=ProviderKind.OLLAMA, model="gemma3"))

    page = SettingsPage(memconn)
    qtbot.addWidget(page)
    assert page.provider_list.count() == 1
    assert "Local Ollama" in page.provider_list.item(0).text()
    assert page.tabs.tabText(1) == "Interview voice"
    assert page.tabs.tabText(2) == "Browser extension"


def test_settings_provider_workspace_exposes_quick_and_advanced_actions(qtbot, memconn):
    from PySide6.QtWidgets import QPushButton

    from aptiordesk.database.models.provider import ProviderConfig, ProviderKind
    from aptiordesk.database.repositories.provider_repo import ProviderRepository
    from aptiordesk.features.settings.page import SettingsPage

    repo = ProviderRepository(memconn)
    provider = repo.create(
        ProviderConfig(
            name="Local workspace",
            kind=ProviderKind.OLLAMA,
            model="gemma3",
        )
    )
    assert provider.id is not None
    repo.set_active(provider.id)

    page = SettingsPage(memconn)
    qtbot.addWidget(page)
    buttons = {button.text() for button in page.findChildren(QPushButton)}
    assert {"Add Ollama", "Connect CLI", "Connect API"} <= buttons
    assert {
        "Test connection",
        "Refresh models",
        "Advanced settings",
        "Use model",
    } <= buttons
    assert page.detail_heading.text() == "Local workspace"
    assert page.detail_status.text() == "Active provider"
    assert not page.activate_button.isEnabled()
    assert page.provider_scroll.widgetResizable()
    assert page.provider_workspace.minimumHeight() >= 500
    assert page.provider_list.minimumHeight() >= 330

    page.quick_model_combo.setCurrentText("qwen3:8b")
    page.save_model_button.click()
    assert repo.get(provider.id).model == "qwen3:8b"
    assert page.quick_status.text() == "Model preference saved."


def test_provider_dialog_supports_device_cli(qtbot, monkeypatch):
    from PySide6.QtWidgets import QTabWidget

    from aptiordesk.database.models.provider import CLIAdapterKind, ProviderKind
    from aptiordesk.features.settings.page import ProviderDialog

    monkeypatch.setattr(
        "aptiordesk.features.settings.page.detect_cli_executable",
        lambda adapter: (
            "C:/Tools/claude.exe" if adapter == CLIAdapterKind.CLAUDE else "C:/Tools/codex.exe"
        ),
    )
    dialog = ProviderDialog(config=None)
    qtbot.addWidget(dialog)
    dialog.kind_combo.setCurrentIndex(dialog.kind_combo.findData(ProviderKind.CLI))
    dialog.cli_adapter_combo.setCurrentIndex(
        dialog.cli_adapter_combo.findData(CLIAdapterKind.CLAUDE)
    )

    config = dialog.result_config()
    assert config.kind == ProviderKind.CLI
    assert config.cli_adapter == CLIAdapterKind.CLAUDE
    assert config.cli_executable == "C:/Tools/claude.exe"
    assert dialog.cli_executable_row.isVisibleTo(dialog)
    assert not dialog.api_key_edit.isVisibleTo(dialog)
    editor_tabs = dialog.findChildren(QTabWidget)
    assert any(
        [tabs.tabText(index) for index in range(tabs.count())] == ["Connection", "Advanced"]
        for tabs in editor_tabs
    )


def test_jobs_page_is_extension_only(qtbot, memconn):
    from PySide6.QtWidgets import QPushButton

    from aptiordesk.features.jobs.page import JobsPage

    page = JobsPage(memconn)
    qtbot.addWidget(page)

    buttons = [button.text() for button in page.findChildren(QPushButton)]
    assert not hasattr(page, "search_tab")
    assert "Add job…" not in buttons
    assert "Delete" in buttons


def test_extension_settings_have_no_manual_pairing_key(qtbot, memconn):
    from PySide6.QtWidgets import QLabel, QPushButton

    from aptiordesk.features.jobs.browser_extension_panel import BrowserExtensionPanel

    panel = BrowserExtensionPanel(memconn)
    qtbot.addWidget(panel)

    text = " ".join(label.text() for label in panel.findChildren(QLabel))
    assert "pairs automatically" in text
    assert "separately distributed proprietary product" in text
    assert "copy pairing key" not in text.lower()
    buttons = {button.text() for button in panel.findChildren(QPushButton)}
    assert "Open Chrome Web Store" in buttons
    assert "Open extension folder" not in buttons


def test_resumes_page_lists_versions_and_previews(qtbot, memconn):
    from aptiordesk.database.models.resume import ResumeContent
    from aptiordesk.features.resumes.page import ResumesPage
    from aptiordesk.features.resumes.service import ResumeService

    content = ResumeContent.model_validate(
        {"full_name": "Jane Roe", "summary": "Engineer.", "skills": [{"name": "Python"}]}
    )
    service = ResumeService(memconn)
    _, version = service.create_manual("My resume", content)
    service.save_edited(version, content, label="Second")

    page = ResumesPage(memconn)
    qtbot.addWidget(page)
    assert page.resume_list.count() == 1
    page.resume_list.setCurrentRow(0)
    assert page.version_list.count() == 2
    # newest first, and the preview renders markdown of the selected version
    assert page.version_list.item(0).text().startswith("v2")
    assert "Jane Roe" in page.preview.toPlainText()


def test_resume_page_downloads_selected_version_as_pdf_and_docx(
    qtbot, memconn, monkeypatch, tmp_path
):
    from pathlib import Path

    from aptiordesk.database.models.resume import ResumeContent
    from aptiordesk.features.resumes.page import ResumesPage
    from aptiordesk.features.resumes.service import ResumeService

    ResumeService(memconn).create_manual(
        "Jane: Product Resume",
        ResumeContent(
            full_name="Jane Roe",
            professional_title="Product Designer",
            summary="Designs accessible products.",
        ),
    )
    page = ResumesPage(memconn)
    qtbot.addWidget(page)
    page.resume_list.setCurrentRow(0)
    calls = []

    def choose_path(parent, title, default_name, file_filter):
        extension = ".pdf" if "PDF" in file_filter else ".docx"
        return str(tmp_path / f"download{extension}"), file_filter

    def fake_export(markdown, path, fmt):
        calls.append((markdown, Path(path), fmt))
        return Path(path)

    monkeypatch.setattr("aptiordesk.features.resumes.page.QFileDialog.getSaveFileName", choose_path)
    monkeypatch.setattr("aptiordesk.features.resumes.page.export_document", fake_export)

    page._export_version("pdf")
    page._export_version("docx")

    assert [call[2] for call in calls] == ["pdf", "docx"]
    assert calls[0][1].suffix == ".pdf"
    assert calls[1][1].suffix == ".docx"
    assert "Product Designer" in calls[0][0]
    assert page.download_pdf_button.isEnabled()
    assert page.download_docx_button.isEnabled()


def test_jobs_page_shows_job_and_analysis(qtbot, memconn):
    from aptiordesk.database.models.job import JobAnalysis
    from aptiordesk.database.repositories.job_repo import JobRepository
    from aptiordesk.features.jobs.page import JobsPage
    from aptiordesk.features.jobs.service import JobService

    job = JobService(memconn).create_job(
        "Senior Data Engineer at Initech. Requirements: Python, Airflow, "
        "cloud warehouses. Remote in the US."
    )
    JobRepository(memconn).add_analysis(
        JobAnalysis(
            job_id=job.id,
            kind="extraction",
            result={"title": "Senior Data Engineer", "technical_skills": ["Python"]},
        )
    )

    page = JobsPage(memconn)
    qtbot.addWidget(page)
    assert page.job_list.count() == 1
    page.job_list.setCurrentRow(0)
    assert "Senior Data Engineer" in page.extraction_view.toPlainText()
    assert "Initech" in page.jd_view.toPlainText()


def test_jobs_list_rows_do_not_clip_and_selection_survives_reload(qtbot, memconn):
    from aptiordesk.database.repositories.job_repo import JobRepository
    from aptiordesk.features.jobs.page import JobsPage
    from aptiordesk.features.jobs.service import JobService

    repo = JobRepository(memconn)
    for index, title in enumerate(
        (
            "Digital Content Designer",
            "Social Producer and Content Specialist",
            "Video Creative Lead for Global Social Media Campaigns",
        )
    ):
        job = JobService(memconn).create_job(
            f"{title} at Company {index}. This is a sufficiently detailed job "
            "description with responsibilities and qualification requirements."
        )
        job.title = title
        job.company = f"Company {index}"
        repo.update(job)

    page = JobsPage(memconn)
    page.resize(1200, 720)
    qtbot.addWidget(page)
    page.show()
    qtbot.waitExposed(page)
    page.job_list.setCurrentRow(2)
    selected_id = page._current_job().id

    assert all(page.job_list.item(i).sizeHint().height() >= 82 for i in range(3))
    page.reload()
    assert page._current_job().id == selected_id
    assert page.job_title_label.text() != "Choose a captured job"


def test_selected_job_highlight_and_widget_share_the_same_vertical_geometry(qtbot, memconn):
    from aptiordesk.features.jobs.page import JobsPage
    from aptiordesk.features.jobs.service import JobService

    JobService(memconn).create_job(
        "Senior product designer at Northstar. Responsibilities include leading "
        "accessible design systems and partnering with engineering. Requirements "
        "include five years of product design experience and strong communication."
    )
    page = JobsPage(memconn)
    qtbot.addWidget(page)
    page.resize(1100, 720)
    page.show()
    page.job_list.setCurrentRow(0)
    qtbot.waitUntil(lambda: page.job_list.itemWidget(page.job_list.item(0)) is not None)

    item = page.job_list.item(0)
    row = page.job_list.itemWidget(item)
    highlight = page.job_list.visualItemRect(item)
    row_rect = row.geometry()
    assert abs(highlight.top() - row_rect.top()) <= 1
    assert abs(highlight.bottom() - row_rect.bottom()) <= 1
    assert highlight.height() == item.sizeHint().height()


def test_all_live_comboboxes_use_the_shared_dropdown(qtbot, memconn):
    from PySide6.QtWidgets import QComboBox

    from aptiordesk.app.main_window import MainWindow
    from aptiordesk.ui.components.dropdown import Dropdown

    window = MainWindow(memconn)
    qtbot.addWidget(window)
    combos = window.findChildren(QComboBox)
    assert combos
    assert all(isinstance(combo, Dropdown) for combo in combos)


def test_sidebar_provider_status_updates_immediately_from_settings(qtbot, memconn):
    from aptiordesk.app.main_window import MainWindow
    from aptiordesk.database.models.provider import ProviderConfig, ProviderKind
    from aptiordesk.database.repositories.provider_repo import ProviderRepository

    repo = ProviderRepository(memconn)
    first = repo.create(
        ProviderConfig(name="Local Gemma", kind=ProviderKind.OLLAMA, model="gemma3")
    )
    second = repo.create(
        ProviderConfig(name="Claude Team", kind=ProviderKind.ANTHROPIC, model="sonnet")
    )
    repo.set_active(first.id)
    window = MainWindow(memconn)
    qtbot.addWidget(window)
    assert "Local Gemma" in window.provider_status.text()

    window.settings_page.provider_list.setCurrentRow(1)
    window.settings_page._activate_selected()

    assert repo.get_active().id == second.id
    assert "Claude Team" in window.provider_status.text()
    assert "sends data out" in window.provider_status.text()


def test_jobs_page_fit_worker_persists_on_ui_thread(qtbot, memconn, monkeypatch):
    """Regression for persisting QThread AI output through a UI-owned SQLite connection."""
    import json

    from aptiordesk.database.models.resume import ResumeContent
    from aptiordesk.database.repositories.job_repo import JobRepository
    from aptiordesk.features.jobs.page import JobsPage
    from aptiordesk.features.jobs.service import JobService
    from aptiordesk.features.resumes.service import ResumeService
    from tests.helpers import ScriptedProvider

    ResumeService(memconn).create_manual(
        "Primary resume",
        ResumeContent.model_validate(
            {
                "summary": "Data engineer who builds Python data platforms.",
                "skills": [{"name": "Python"}],
            }
        ),
    )
    job = JobService(memconn).create_job(
        "Senior Data Engineer at Initech. Build production data pipelines in "
        "Python, operate cloud warehouses, and partner with analytics teams."
    )
    provider = ScriptedProvider(
        [
            json.dumps(
                {
                    "strong_matches": [
                        {
                            "requirement": "Python",
                            "candidate_evidence": "Builds Python data platforms.",
                        }
                    ],
                    "summary": "Strong technical overlap.",
                    "methodology": "Compared the posting with resume evidence.",
                }
            )
        ]
    )

    page = JobsPage(memconn)
    qtbot.addWidget(page)
    page.job_list.setCurrentRow(0)
    monkeypatch.setattr(page, "_provider_or_warn", lambda: provider)

    page._run_fit()

    qtbot.waitUntil(lambda: page.status.text() == "Fit analysis complete.", timeout=5_000)
    qtbot.waitUntil(lambda: page._analysis_worker is None, timeout=5_000)
    stored = JobRepository(memconn).latest_analysis(job.id, "fit")
    assert stored is not None
    assert stored.result["summary"] == "Strong technical overlap."


def test_cover_letter_worker_persists_on_ui_thread(qtbot, memconn, monkeypatch):
    """Regression: AI drafting may run in QThread; SQLite versioning may not."""
    import json

    from aptiordesk.database.models.cover_letter import CoverLetterInputs
    from aptiordesk.database.models.resume import ResumeContent
    from aptiordesk.features.cover_letters import page as cover_letter_page
    from aptiordesk.features.cover_letters.service import CoverLetterService
    from aptiordesk.features.jobs.service import JobService
    from aptiordesk.features.resumes.service import ResumeService
    from tests.helpers import ScriptedProvider

    _, resume_version = ResumeService(memconn).create_manual(
        "Primary resume",
        ResumeContent.model_validate(
            {
                "summary": "Product designer focused on accessible workflows.",
                "experiences": [
                    {
                        "title": "Product Designer",
                        "organization": "Northstar",
                        "highlights": ["Redesigned a complex publishing workflow"],
                    }
                ],
            }
        ),
    )
    job = JobService(memconn).create_job(
        "Product Designer at Initech. Lead accessible workflow design, partner "
        "with engineering, and improve a complex content publishing platform."
    )
    inputs = CoverLetterInputs(tone="warm", length="short")
    service = CoverLetterService(memconn)
    letter = service.create(job, resume_version, inputs)
    provider = ScriptedProvider(
        [
            json.dumps(
                {
                    "body_markdown": "Dear Hiring Team,\n\nI design accessible workflows.",
                    "selected_experiences": ["Publishing workflow redesign"],
                    "selection_rationale": "Directly supports the role.",
                    "claims_needing_confirmation": [],
                }
            )
        ]
    )
    monkeypatch.setattr(cover_letter_page, "get_active_provider", lambda _conn: provider)

    page = cover_letter_page.CoverLettersPage(memconn)
    qtbot.addWidget(page)
    page._generate(letter, job, resume_version, inputs)

    qtbot.waitUntil(lambda: page.status.text().startswith("Draft ready"), timeout=5_000)
    qtbot.waitUntil(lambda: page._generation_worker is None, timeout=5_000)
    stored = service.list_versions(letter)
    assert len(stored) == 1
    assert "accessible workflows" in stored[0].content_md


def test_tailoring_page_renders_cards_and_gates_apply(qtbot, memconn):
    import json

    from aptiordesk.database.models.resume import ResumeContent
    from aptiordesk.features.jobs.service import JobService
    from aptiordesk.features.resumes.service import ResumeService
    from aptiordesk.features.tailoring.page import TailoringPage
    from aptiordesk.features.tailoring.service import TailoringService
    from tests.helpers import ScriptedProvider

    content = ResumeContent.model_validate({"summary": "Data engineer."})
    _, version = ResumeService(memconn).create_manual("R", content)
    job = JobService(memconn).create_job(
        "Data Engineer role requiring Python and pipeline design experience. "
        "Remote within the US. You will build and own ETL workflows."
    )
    service = TailoringService(memconn)
    session = service.create_session(job, version, "ats")
    service.generate_suggestions(
        ScriptedProvider(
            [
                json.dumps(
                    {
                        "suggestions": [
                            {
                                "target_path": "/summary",
                                "original_text": "Data engineer.",
                                "suggested_text": "Data engineer focused on pipeline design.",
                                "rationale": "Mirrors posting.",
                                "jd_evidence": "pipeline design",
                                "profile_evidence": "Data engineer.",
                            }
                        ]
                    }
                )
            ]
        ),
        session,
        job,
    )

    page = TailoringPage(memconn)
    qtbot.addWidget(page)
    page.load_session(session.id)
    assert len(page._cards) == 1
    assert not page.apply_button.isEnabled()  # nothing accepted yet

    card = page._cards[0]
    card.accepted.emit(card.suggestion)
    assert page.apply_button.isEnabled()

    tailored = service.apply(session, job)
    page.reload(tailored.id)
    assert page.history_list.count() == 1
    assert page.view_resume_button.isEnabled()
    requested: list[tuple[int, int]] = []
    page.view_resume_requested.connect(
        lambda resume_id, version_id: requested.append((resume_id, version_id))
    )
    page.view_resume_button.click()
    assert requested == [(tailored.resume_id, tailored.id)]


def test_tailoring_page_persists_generated_result_on_ui_thread(qtbot, memconn):
    import json
    from concurrent.futures import ThreadPoolExecutor

    from aptiordesk.database.models.resume import ResumeContent
    from aptiordesk.features.jobs.service import JobService
    from aptiordesk.features.resumes.service import ResumeService
    from aptiordesk.features.tailoring import page as tailoring_page
    from aptiordesk.features.tailoring.service import TailoringService
    from tests.helpers import ScriptedProvider

    _, version = ResumeService(memconn).create_manual(
        "Primary resume",
        ResumeContent.model_validate({"summary": "Data engineer."}),
    )
    job = JobService(memconn).create_job(
        "Data Engineer at Northstar. Build reliable Python data pipelines, "
        "maintain production workflows, and partner with analytics teams."
    )
    service = TailoringService(memconn)
    session = service.create_session(job, version, "ats")
    provider = ScriptedProvider(
        [
            json.dumps(
                {
                    "suggestions": [
                        {
                            "target_path": "/summary",
                            "original_text": "Data engineer.",
                            "suggested_text": "Data engineer focused on reliable pipelines.",
                            "rationale": "Aligns with the posting.",
                            "jd_evidence": "reliable Python data pipelines",
                            "profile_evidence": "Data engineer.",
                        }
                    ]
                }
            )
        ]
    )
    page = tailoring_page.TailoringPage(memconn)
    qtbot.addWidget(page)
    page.load_session(session.id)

    with ThreadPoolExecutor(max_workers=1) as pool:
        generated = pool.submit(
            service.generate_suggestions_for_version,
            provider,
            session,
            job,
            version,
        ).result()
    page._on_generated(generated)

    assert len(page._cards) == 1
    assert page._cards[0].suggestion.suggested_text.endswith("reliable pipelines.")
    assert TailoringService(memconn).list_suggestions(session.id)


def test_interview_prepare_uses_aligned_sectioned_form(qtbot, memconn):
    from PySide6.QtWidgets import QApplication

    from aptiordesk.features.interviews.page import InterviewPage
    from aptiordesk.ui.components.forms import SectionCard
    from aptiordesk.ui.theme import apply_theme

    app = QApplication.instance()
    previous_stylesheet = app.styleSheet()
    apply_theme("dark", app)
    page = InterviewPage(memconn)
    qtbot.addWidget(page)
    page.resize(1200, 850)
    page.show()
    qtbot.wait(1)

    setup = page.setup_tab
    assert len(setup.findChildren(SectionCard)) == 1
    assert setup.job_combo.accessibleName() == "Target job"
    assert setup.persona_combo.accessibleName() == "Interviewer style"
    assert setup.difficulty_combo.currentData() == "mixed"
    assert abs(setup.job_combo.width() - setup.resume_combo.width()) <= 1
    content = setup.scroll.widget()
    first_row = {
        control.mapTo(content, control.rect().topLeft()).y()
        for control in (setup.job_combo, setup.resume_combo, setup.stage_combo)
    }
    second_row = {
        control.mapTo(content, control.rect().topLeft()).y()
        for control in (
            setup.persona_combo,
            setup.count_spin,
            setup.difficulty_combo,
        )
    }
    assert len(first_row) == len(second_row) == 1
    assert max(first_row) < min(second_row)
    assert setup.config_card.height() >= setup.config_card.minimumSizeHint().height()
    assert all(button.text() != "Generate questions" for button in setup.findChildren(QPushButton))
    app.setStyleSheet(previous_stylesheet)


def test_interview_prepare_scrolls_instead_of_crushing_controls(qtbot, memconn):
    from PySide6.QtWidgets import QApplication

    from aptiordesk.features.interviews.page import InterviewPage
    from aptiordesk.ui.theme import apply_theme

    app = QApplication.instance()
    previous_stylesheet = app.styleSheet()
    apply_theme("dark", app)
    page = InterviewPage(memconn)
    qtbot.addWidget(page)
    page.resize(1200, 700)
    page.show()
    qtbot.wait(1)

    setup = page.setup_tab
    content = setup.scroll.widget()
    first_row_bottom = max(
        control.mapTo(content, control.rect().bottomLeft()).y()
        for control in (setup.job_combo, setup.resume_combo, setup.stage_combo)
    )
    second_row_top = min(
        control.mapTo(content, control.rect().topLeft()).y()
        for control in (
            setup.persona_combo,
            setup.count_spin,
            setup.difficulty_combo,
        )
    )
    assert first_row_bottom < second_row_top
    # With the obsolete preview panel removed, the complete form should fit
    # this height without either clipping fields or forcing a scrollbar.
    assert setup.config_card.height() <= setup.scroll.viewport().height()
    app.setStyleSheet(previous_stylesheet)


def test_interview_page_runs_a_question(qtbot, memconn):
    import json

    from aptiordesk.features.interviews.page import InterviewPage
    from aptiordesk.features.interviews.service import InterviewService
    from aptiordesk.features.jobs.service import JobService
    from tests.helpers import ScriptedProvider

    job = JobService(memconn).create_job(
        "Data Engineer at Initech. Requirements: Python, Airflow, and pipeline "
        "ownership. Remote within the US. You will mentor junior engineers."
    )
    service = InterviewService(memconn)
    session = service.start_session(job, None, persona="coaching", stage="behavioral")
    service.generate_questions(
        ScriptedProvider(
            [
                json.dumps(
                    {
                        "questions": [
                            {
                                "text": "Tell me about a pipeline you owned.",
                                "category": "behavioral",
                                "difficulty": "medium",
                                "key_points": ["Scope", "Outcome"],
                            },
                            {"text": "How do you debug a flaky DAG?", "category": "technical"},
                        ]
                    }
                )
            ]
        ),
        job,
        None,
        stage="behavioral",
        session=session,
    )

    page = InterviewPage(memconn)
    qtbot.addWidget(page)
    page._on_session_started(session.id)

    mock = page.mock_tab
    assert page.tabs.currentWidget() is mock
    assert len(mock._queue) == 2
    assert mock.question_progress.text() == "Welcome"
    assert mock._welcome_timer.interval() == 1_000
    # Environment preparation is asynchronous; exercise the room countdown
    # directly instead of assuming the avatar/voice workers have completed.
    mock._begin_welcome()
    assert mock.countdown_label.text() == "3"
    assert not mock.countdown_overlay.isHidden()
    assert mock.room_view.graphicsEffect() is None
    assert mock.room_view.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert not mock.answer_edit.isEnabled()
    assert not mock.record_button.isEnabled()
    mock._complete_welcome()
    assert mock.countdown_overlay.isHidden()
    assert mock.room_view.graphicsEffect() is None
    assert not mock.room_view.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert "pipeline you owned" in mock.question_label.text()
    # Reports and coaching content do not exist inside the live room.
    assert not hasattr(mock, "feedback_view")
    assert not hasattr(mock, "feedback_panel")
    mock.answer_edit.setPlainText("I owned the pipeline and improved reliability.")
    mock._submit()
    qtbot.waitUntil(lambda: "flaky DAG" in mock.question_label.text())
    assert "flaky DAG" in mock.question_label.text()


def test_interview_room_is_fully_staged_before_it_becomes_visible(qtbot, memconn, monkeypatch):
    import json

    from aptiordesk.features.interviews.page import InterviewPage
    from aptiordesk.features.interviews.service import InterviewService
    from tests.helpers import ScriptedProvider

    service = InterviewService(memconn)
    session = service.start_session(
        None,
        None,
        persona="friendly_recruiter",
        stage="behavioral",
    )
    service.generate_questions(
        ScriptedProvider(
            [
                json.dumps(
                    {
                        "questions": [
                            {
                                "text": "Tell me about a difficult project.",
                                "category": "behavioral",
                            }
                        ]
                    }
                )
            ]
        ),
        None,
        None,
        stage="behavioral",
        session=session,
    )
    page = InterviewPage(memconn)
    qtbot.addWidget(page)
    page.resize(1400, 900)
    page._on_session_started(session.id)
    mock = page.mock_tab
    monkeypatch.setattr(mock.camera_tile, "start", lambda: None)
    monkeypatch.setattr(mock, "_prime_microphone", lambda: None)
    mock._welcome_started = False
    mock._welcome_active = True
    mock.view_stack.setCurrentWidget(mock.loading_view)

    room_frames = []

    def capture_visible_frame(_index):
        if mock.view_stack.currentWidget() is mock.room_container:
            room_frames.append(
                (
                    not mock.countdown_overlay.isHidden(),
                    mock.room_view.graphicsEffect(),
                )
            )

    mock.view_stack.currentChanged.connect(capture_visible_frame)
    mock._show_room()

    assert room_frames == [
        (True, None),
    ]


def test_interview_report_generation_is_single_flight_and_exits_cleanly(
    qtbot, memconn, monkeypatch
):
    import json

    from aptiordesk.database.models.interview import InterviewQuestion
    from aptiordesk.database.repositories.interview_repo import InterviewRepository
    from aptiordesk.features.interviews import page as interview_page
    from aptiordesk.features.interviews.service import InterviewService
    from tests.helpers import ScriptedProvider

    service = InterviewService(memconn)
    session = service.start_session(
        None,
        None,
        persona="friendly_recruiter",
        stage="behavioral",
    )
    question = InterviewRepository(memconn).add_question(
        InterviewQuestion(
            session_id=session.id,
            text="Tell me about a project you owned.",
            category="behavioral",
            stage="behavioral",
        )
    )
    service.record_answer(
        question,
        "I owned the launch and improved completion rates.",
        session=session,
    )
    provider = ScriptedProvider(
        [
            json.dumps(
                {
                    "overall_summary": "You showed clear ownership and need stronger metrics.",
                    "strongest_answers": ["Project ownership was direct and relevant."],
                    "weakest_answers": ["The outcome was not quantified."],
                    "recurring_patterns": ["Answers clearly separate personal contribution."],
                    "priorities": ["Add one verified outcome to each example."],
                }
            )
        ]
    )
    monkeypatch.setattr(
        interview_page,
        "get_active_provider",
        lambda _conn: provider,
    )
    page = interview_page.InterviewPage(memconn)
    qtbot.addWidget(page)
    page._on_session_started(session.id)
    mock = page.mock_tab

    class _Signal:
        def __init__(self):
            self.callbacks = []

        def connect(self, callback):
            self.callbacks.append(callback)

        def emit(self, value=None):
            for callback in self.callbacks:
                if value is None:
                    callback()
                else:
                    callback(value)

    class DeferredWorker:
        def __init__(self, fn, parent=None):
            self.fn = fn
            self.result = _Signal()
            self.error = _Signal()
            self.finished = _Signal()
            self.progress = _Signal()

        def show_progress(self, _title, _detail):
            return self

        def start(self):
            pass

        def complete(self):
            try:
                self.result.emit(self.fn())
            except Exception as exc:
                self.error.emit(exc)
            self.finished.emit()

    monkeypatch.setattr(interview_page, "Worker", DeferredWorker)
    monkeypatch.setattr(mock, "_choose_report_destination", lambda: True)
    spoken = []
    monkeypatch.setattr(
        mock._speech,
        "speak",
        lambda text, _settings: spoken.append(text),
    )

    mock._finish()
    first_worker = mock._report_worker
    assert first_worker is not None
    assert not mock.end_button.isEnabled()
    assert mock.end_button.text().startswith("Generating")

    mock._finish()
    assert mock._report_worker is first_worker
    assert spoken and spoken[-1].startswith("Thank you")
    assert "report is being generated" in spoken[-1]

    first_worker.complete()
    assert mock._report_ready
    assert mock._report_dialog_pending
    assert page.tabs.currentWidget() is mock
    mock._speech_finished()
    qtbot.waitUntil(lambda: page.tabs.currentWidget() is page.library_tab)
    assert mock._report_worker is None
    assert page.tabs.isTabEnabled(page._library_tab_index)
    assert "Session report" in page.library_tab.answer_list.item(0).text()
    assert "clear ownership" in page.library_tab.detail.toPlainText()
    assert page.tabs.currentWidget() is page.library_tab
    assert not page.tabs.isTabEnabled(page._mock_tab_index)
    assert not hasattr(mock, "feedback_view")


def test_interview_long_question_and_camera_cards_do_not_collide(qtbot, memconn):
    from aptiordesk.database.models.interview import InterviewQuestion
    from aptiordesk.database.repositories.interview_repo import InterviewRepository
    from aptiordesk.features.interviews.page import InterviewPage
    from aptiordesk.features.interviews.service import InterviewService

    service = InterviewService(memconn)
    session = service.start_session(
        None,
        None,
        persona="friendly_recruiter",
        stage="technical",
    )
    question = (
        "We require proficiency across Premiere Pro, After Effects, Photoshop, "
        "Illustrator, and Figma. Which discipline is your most underdeveloped "
        "relative to this role, and how would you rapidly close that gap?"
    )
    InterviewRepository(memconn).add_question(
        InterviewQuestion(
            session_id=session.id,
            text=question,
            category="technical",
            stage="technical",
            sort_order=0,
        )
    )
    page = InterviewPage(memconn)
    qtbot.addWidget(page)
    page.resize(1600, 900)
    assert not page.tabs.isTabEnabled(page._mock_tab_index)
    assert not page.tabs.isTabEnabled(page._library_tab_index)
    page.set_library_available(True)
    assert page.tabs.isTabEnabled(page._library_tab_index)
    page.set_library_available(False)
    page._on_session_started(session.id)

    mock = page.mock_tab
    mock._complete_welcome()
    mock._apply_room_layout(1600)
    mock.question_panel.layout().activate()
    mock.question_label._fit_text()
    assert page.tabs.isTabEnabled(page._mock_tab_index)
    assert page.tabs.currentWidget() is mock
    assert mock.question_label.text() == question
    assert mock.room_splitter.orientation() == Qt.Orientation.Horizontal
    assert mock.room_splitter.widget(0) is mock.video_splitter
    assert mock.room_splitter.widget(1) is mock.context_splitter
    assert mock.video_splitter.orientation() == Qt.Orientation.Vertical
    assert mock.video_splitter.indexOf(mock.avatar_stage) >= 0
    assert mock.video_splitter.indexOf(mock.camera_tile) >= 0
    assert mock.context_splitter.indexOf(mock.question_panel) >= 0
    assert mock.context_splitter.indexOf(mock.transcript_panel) >= 0
    assert mock.video_splitter.sizes() == mock.context_splitter.sizes()
    assert mock.room_scroll.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert mock.question_label.font().pointSizeF() >= 10.5

    mock._apply_room_layout(700)
    assert mock.room_splitter.orientation() == Qt.Orientation.Vertical
    assert mock.room_splitter.widget(0) is mock.context_splitter
    assert mock.video_splitter.orientation() == Qt.Orientation.Vertical
    assert mock.context_splitter.orientation() == Qt.Orientation.Vertical
    mock._avatar.shutdown()
    page.close()


def test_interview_offers_kokoro_repair_when_voice_initialization_fails(qtbot, memconn):
    from aptiordesk.features.interviews.page import InterviewPage

    page = InterviewPage(memconn)
    qtbot.addWidget(page)
    mock = page.mock_tab

    mock._voice_prepare_failed(RuntimeError("Kokoro runtime missing"))

    assert not mock.loading_install_button.isHidden()
    assert mock.loading_install_button.text() == "Repair Kokoro"
    assert "no fallback voice was used" in mock.loading_error.text()


def test_microphone_recording_only_shows_recording_state(qtbot, memconn):
    from aptiordesk.features.interviews.page import InterviewPage

    page = InterviewPage(memconn)
    qtbot.addWidget(page)
    mock = page.mock_tab

    class ActiveRecorder:
        is_recording = True
        elapsed_s = 0.0

    mock._recording_started(ActiveRecorder())

    assert mock._transcriber.device == "cpu"
    assert "recording" in mock.transcript_status.text().lower()
    assert "after Stop" in mock.transcript_status.text()
    assert not hasattr(mock, "_live_transcript_tick")
    assert not hasattr(mock, "_live_transcription_worker")

    mock._tick.stop()
    mock._recorder = None
    mock._avatar.shutdown()
    page.close()


def test_interview_library_lists_saved_answers(qtbot, memconn):
    import json

    from aptiordesk.features.interviews.page import InterviewPage
    from aptiordesk.features.interviews.service import InterviewService
    from tests.helpers import ScriptedProvider

    service = InterviewService(memconn)
    session = service.start_session(None, None, persona="executive", stage="behavioral")
    questions = service.generate_questions(
        ScriptedProvider(
            [
                json.dumps(
                    {
                        "questions": [
                            {
                                "text": "Describe a hard trade-off you made.",
                                "category": "behavioral",
                            }
                        ]
                    }
                )
            ]
        ),
        None,
        None,
        stage="behavioral",
        session=session,
    )
    answer = service.record_answer(questions[0], "I chose reliability over speed.", session=session)
    service.save_to_library(answer)

    page = InterviewPage(memconn)
    qtbot.addWidget(page)
    page.library_tab.reload()
    assert page.library_tab.answer_list.count() == 1
    assert "hard trade-off" in page.library_tab.answer_list.item(0).text()
    assert "reliability over speed" in page.library_tab.detail.toPlainText()


def test_worker_progress_dialog_is_prominent_and_closes_when_done(qtbot):
    from PySide6.QtWidgets import QWidget

    from aptiordesk.ui.workers import Worker

    parent = QWidget()
    qtbot.addWidget(parent)
    parent.show()
    worker = Worker(lambda: "done", parent=parent)
    worker.show_progress("Analyzing application", "Comparing the job and resume evidence.")
    dialog = worker._progress_dialog
    assert dialog is not None
    assert dialog.isVisible()
    assert dialog.title_label.text() == "Analyzing application"
    assert "job and resume" in dialog.detail_label.text()
    assert dialog.progress.minimum() == 0
    assert dialog.progress.maximum() == 0

    with qtbot.waitSignal(worker.finished, timeout=3000):
        worker.start()
    qtbot.waitUntil(lambda: not dialog.isVisible(), timeout=2000)


def test_task_progress_uses_real_totals_and_labels_unknown_work(qtbot):
    from PySide6.QtWidgets import QWidget

    from aptiordesk.core.environment import PullProgress
    from aptiordesk.ui.components.task_progress import TaskProgressDialog

    parent = QWidget()
    qtbot.addWidget(parent)
    dialog = TaskProgressDialog("Downloading", "Starting", parent)
    qtbot.addWidget(dialog)

    dialog.report(PullProgress("pulling model", completed=25, total=100))
    assert dialog.progress.maximum() == 100
    assert dialog.progress.value() == 25
    assert dialog.progress.format() == "25%"
    assert "of" in dialog.detail_label.text()

    dialog.report("Loading model into memory")
    assert dialog.progress.minimum() == 0
    assert dialog.progress.maximum() == 0
    assert dialog.progress.format() == "Indeterminate"


def test_main_window_uses_packaged_brand_icon(qtbot, memconn):
    from PySide6.QtWidgets import QLabel

    from aptiordesk.app.main_window import MainWindow
    from aptiordesk.ui.theme.brand import application_icon_path

    window = MainWindow(memconn)
    qtbot.addWidget(window)
    assert application_icon_path().exists()
    assert not window.windowIcon().isNull()
    mark = window.findChild(QLabel, "brandMark")
    assert mark is not None
    assert mark.pixmap() is not None
    assert not mark.pixmap().isNull()


def test_main_window_has_no_light_theme_control(qtbot, memconn):
    from PySide6.QtWidgets import QPushButton

    from aptiordesk.app.main_window import MainWindow

    window = MainWindow(memconn)
    qtbot.addWidget(window)
    assert window.findChild(QPushButton, "themeToggle") is None
