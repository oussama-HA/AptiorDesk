"""Resume file to populated profile, over a real HTTP server.

Everything here is real except the model itself: a real PDF on disk, a real
socket, Ollama's real wire protocol, a real SQLite database with real
migrations. The provider adapter, JSON mode, section routing, token budgets,
grounding, persistence, and the re-import path are all exercised together.

Unit tests use ``ScriptedProvider`` and cannot catch a mistake in the HTTP
layer between the service and the model. This can.
"""

from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from aptiordesk.ai.registry import get_active_provider
from aptiordesk.database.db import connect, migrate
from aptiordesk.database.models.provider import ProviderConfig, ProviderKind
from aptiordesk.database.repositories.profile_repo import ProfileRepository
from aptiordesk.database.repositories.provider_repo import ProviderRepository
from aptiordesk.features.profile.import_service import ProfileImporter
from aptiordesk.features.resumes.service import ResumeService
from tests.helpers import make_minimal_pdf

RESUME_LINES = [
    "Ada Lovelace",
    "Senior Data Engineer",
    "ada@example.com | +44 20 7946 0958 | London, UK",
    "linkedin.com/in/adalovelace",
    "",
    "SUMMARY",
    "Data engineer with eight years building analytical pipelines.",
    "",
    "EXPERIENCE",
    "Principal Engineer, Analytical Engines Ltd, London",
    "March 2021 - Present",
    "- Rebuilt the ingest pipeline, cutting latency from 40 minutes to 6.",
    "- Led a team of five engineers.",
    "Data Engineer, Analytical Engines Ltd, London",
    "January 2018 - February 2021",
    "- Designed the differencing warehouse schema.",
    "",
    "EDUCATION",
    "MSc Mathematics, University of London, 2017",
    "",
    "SKILLS",
    "Python, SQL, Spark, Airflow",
    "",
    "LANGUAGES",
    "English (native), Arabic (fluent)",
]

# The third role is invented, so the grounding check has a real fabrication to
# catch rather than a synthetic one.
ANSWERS = {
    "contact": {
        "full_name": "Ada Lovelace",
        "professional_title": "Senior Data Engineer",
        "email": "ada@example.com",
        "phone": "+44 20 7946 0958",
        "location": "London, UK",
        "linkedin_url": "linkedin.com/in/adalovelace",
        "github_url": "",
        "portfolio_url": "",
        "summary": "Data engineer with eight years building analytical pipelines.",
    },
    "work experience": {
        # Deliberately use common provider aliases here.  This exercises the
        # real HTTP -> extraction-contract -> canonical-domain mapping instead
        # of only proving that a perfectly obedient fake model works.
        "workHistory": [
            {
                "jobTitle": "Principal Engineer",
                "companyName": "Analytical Engines Ltd",
                "workLocation": "London",
                "startDate": "2021-03",
                "endDate": "Present",
                "roleDescription": "",
                "achievements": [
                    "Rebuilt the ingest pipeline, cutting latency from 40 minutes to 6.",
                    "Led a team of five engineers.",
                ],
            },
            {
                "position": "Data Engineer",
                "employer": "Analytical Engines Ltd",
                "location": "London",
                "from": "2018-01",
                "to": "2021-02",
                "description": "",
                "bullets": ["Designed the differencing warehouse schema."],
            },
            {
                "role": "Chief Architect",
                "company": "Cyberdyne Systems",
                "location": "",
                "dates": "2015-01 - 2017-12",
                "description": "",
                "accomplishments": ["Increased revenue by 340%."],
            },
        ]
    },
    "education": {
        "education": [
            {
                "institution": "University of London",
                "degree": "MSc",
                "field_of_study": "Mathematics",
                "start_date": "",
                "end_date": "2017",
                "details": "",
            }
        ]
    },
    "skills": {
        "skills": [
            {"name": n, "level": "", "category": ""} for n in ["Python", "SQL", "Spark", "Airflow"]
        ],
        "certifications": [],
        "languages": [
            {"name": "English", "proficiency": "native"},
            {"name": "Arabic", "proficiency": "fluent"},
        ],
    },
    "projects": {"projects": [], "awards": [], "publications": [], "volunteer": []},
}


class _Recorder:
    def __init__(self):
        self.calls = 0
        self.budgets: list[int | None] = []
        self.json_mode_requested: list[bool] = []
        self.fenced: list[bool] = []


@pytest.fixture
def ai_server():
    """A real HTTP server speaking Ollama's /api/chat protocol."""
    recorder = _Recorder()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path == "/api/tags":
                self._json({"models": [{"name": "llama3.2:3b"}]})

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            recorder.calls += 1
            recorder.budgets.append(body.get("options", {}).get("num_predict"))
            recorder.json_mode_requested.append(body.get("format") == "json")
            # The template wraps lines, so the section label can be split.
            prompt = re.sub(r"\s+", " ", " ".join(m["content"] for m in body["messages"]).lower())
            recorder.fenced.append("<<<begin resume>>>" in prompt)
            for key, answer in ANSWERS.items():
                if f"extract only the {key}" in prompt:
                    return self._reply(json.dumps(answer))
            self._reply("{}")

        def _reply(self, content: str):
            self._json(
                {
                    "model": "llama3.2:3b",
                    "done": True,
                    "message": {"role": "assistant", "content": content},
                }
            )

        def _json(self, payload):
            data = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    # Threading matters now: extraction sends its section requests
    # concurrently, and a single-threaded server would quietly serialise them.
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", recorder
    server.shutdown()


@pytest.fixture
def app(tmp_path, ai_server):
    base_url, recorder = ai_server
    pdf = tmp_path / "ada_lovelace_cv.pdf"
    pdf.write_bytes(make_minimal_pdf(RESUME_LINES))

    conn = connect(tmp_path / "aptiordesk.db")
    migrate(conn)
    ProviderRepository(conn).create(
        ProviderConfig(
            kind=ProviderKind.OLLAMA,
            name="local",
            model="llama3.2:3b",
            base_url=base_url,
            is_active=True,
            max_tokens=2048,
        )
    )
    return conn, pdf, recorder


def test_resume_file_becomes_a_populated_profile(app):
    conn, pdf, recorder = app
    service = ResumeService(conn)

    document = service.read_document(pdf)
    assert document.ok
    assert "Analytical Engines" in document.text

    progress: list = []
    provider = get_active_provider(conn)
    content, report = service.extract_structure(
        provider,
        document,
        on_progress=progress.append,
    )

    # One HTTP round-trip per section, each in JSON mode, each fenced.
    assert recorder.calls == 5
    assert all(recorder.json_mode_requested)
    assert all(recorder.fenced)
    # A running and a completion event per section.
    assert len(progress) == 10
    assert {e.status for e in progress} == {"running", "done"}
    # The experience section's floor beats the configured 2048 cap.
    assert max(b for b in recorder.budgets if b) > 2048

    assert content.full_name == "Ada Lovelace"
    assert content.professional_title == "Senior Data Engineer"
    assert len(content.experiences) == 3
    assert len(content.skills) == 4
    assert len(content.languages) == 2

    # The invented role is flagged in full; the real ones are not.
    flagged = {n.path for n in report.inferred()}
    assert "experiences.2.organization" in flagged
    assert "experiences.2.highlights.0" in flagged
    assert "experiences.0.organization" not in flagged
    assert "experiences.0.start_date" not in flagged  # "March 2021" -> "2021-03"

    _, version = service.create_imported(
        "Ada CV",
        document.filename,
        content,
        document.text,
        report=report,
        diagnosis=str(document.diagnosis),
    )
    reloaded = service._repo.get_version(version.id)
    assert len(reloaded.content.experiences) == 3
    assert reloaded.extraction_report.sections  # provenance survives the round-trip

    importer = ProfileImporter(conn)
    importer.apply_plan(importer.build_plan(content, report, source_resume_version_id=version.id))

    repo = ProfileRepository(conn)
    profile = repo.get_default()
    assert profile.display_name == "Ada Lovelace"
    assert profile.contact.email == "ada@example.com"
    assert profile.contact.location == "London, UK"
    items = repo.list_items(profile.id)
    counts = {k: sum(1 for i in items if i.kind == k) for i in items for k in [i.kind]}
    assert counts == {"experience": 3, "education": 1, "skill": 4, "language": 2}
    # Only the fabricated entry arrives needing review.
    assert [i.data["organization"] for i in items if i.needs_review] == ["Cyberdyne Systems"]


def test_reimporting_preserves_hand_edits_and_adds_no_duplicates(app):
    conn, pdf, _ = app
    service = ResumeService(conn)
    document = service.read_document(pdf)
    content, report = service.extract_structure(get_active_provider(conn), document)
    importer = ProfileImporter(conn)
    importer.apply_plan(importer.build_plan(content, report))

    repo = ProfileRepository(conn)
    profile = repo.get_default()
    before = repo.list_items(profile.id)
    edited = next(i for i in before if i.data.get("title") == "Principal Engineer")
    edited.data["highlights"] = ["My own hand-written bullet."]
    repo.update_item(edited)
    repo.mark_user_edited(edited.id)

    plan = importer.build_plan(content, report)
    importer.apply_plan(plan)

    after = repo.list_items(profile.id)
    assert len(after) == len(before)  # nothing duplicated
    kept = next(i for i in after if i.data.get("title") == "Principal Engineer")
    assert kept.data["highlights"] == ["My own hand-written bullet."]
    assert plan.conflicts()  # and the user was told about it
