"""Service-level tests for resumes, jobs, and tailoring — AI fully scripted."""

import json

import pytest

from aptiordesk.database.models.job import JobAnalysis
from aptiordesk.database.models.resume import ResumeContent
from aptiordesk.database.repositories.job_repo import JobRepository
from aptiordesk.database.repositories.resume_repo import ResumeRepository
from aptiordesk.features.jobs.service import JobService
from aptiordesk.features.resumes.service import ResumeService
from aptiordesk.features.tailoring.service import TailoringService
from tests.helpers import ScriptedProvider, SectionedProvider

BASE_CONTENT = ResumeContent.model_validate(
    {
        "full_name": "John Doe",
        "email": "john@example.com",
        "summary": "Data engineer with 6 years of experience.",
        "experiences": [
            {
                "title": "Data Engineer",
                "organization": "Acme",
                "start_date": "2019-01",
                "highlights": [
                    "Built ETL pipelines in Python processing 2 TB daily",
                    "Maintained Airflow DAGs",
                ],
            }
        ],
        "skills": [{"name": "Python"}, {"name": "SQL"}],
    }
)

JD_TEXT = (
    "Senior Data Engineer at Initech. Requirements: 5+ years Python, Airflow, "
    "cloud data warehouses. You will design pipelines and mentor juniors. "
    "Salary $150k-$180k. Remote in the US."
)


@pytest.fixture
def base_version(conn):
    service = ResumeService(conn)
    _, version = service.create_manual("Base resume", BASE_CONTENT)
    return version


class TestResumeService:
    def test_manual_create_produces_version_1(self, conn):
        service = ResumeService(conn)
        resume, version = service.create_manual("My resume", BASE_CONTENT)
        assert version.version_no == 1
        assert ResumeRepository(conn).latest_version(resume.id).content.full_name == "John Doe"

    def test_extract_structure_uses_ai_and_fences_input(self, conn, tmp_path):
        """Extraction now runs section by section over a read document; see
        tests/unit/test_extraction.py for the per-section behaviour."""
        path = tmp_path / "resume.txt"
        path.write_text(
            "John Doe\njohn@example.com\n\nEXPERIENCE\nData Engineer at Initech\n"
            "- Built pipelines that processed a lot of data every single day.\n",
            encoding="utf-8",
        )
        service = ResumeService(conn)
        document = service.read_document(path)
        provider = SectionedProvider(
            {
                "contact": '{"full_name": "John Doe", "email": "john@example.com"}',
                "experience": '{"experiences": [{"title": "Data Engineer", '
                '"organization": "Initech"}]}',
                "education": '{"education": []}',
                "skills": '{"skills": [], "certifications": [], "languages": []}',
                "extras": '{"projects": [], "awards": [], "publications": [], "volunteer": []}',
            }
        )

        content, report = service.extract_structure(provider, document)

        assert content.full_name == "John Doe"
        assert content.experiences[0].organization == "Initech"
        assert all("<<<BEGIN RESUME>>>" in p for p in provider.prompts)
        assert all(section.ok for section in report.sections)

    def test_edit_creates_new_version_never_overwrites(self, conn, base_version):
        service = ResumeService(conn)
        modified = BASE_CONTENT.model_copy(deep=True)
        modified.summary = "Changed summary"
        new_version = service.save_edited(base_version, modified)
        assert new_version.version_no == 2
        assert new_version.created_from_version_id == base_version.id
        # base version unchanged
        repo = ResumeRepository(conn)
        assert repo.get_version(base_version.id).content.summary.startswith("Data engineer")

    def test_restore_creates_new_version(self, conn, base_version):
        service = ResumeService(conn)
        modified = BASE_CONTENT.model_copy(deep=True)
        modified.summary = "v2"
        service.save_edited(base_version, modified)
        restored = service.restore(base_version)
        assert restored.version_no == 3
        assert restored.content.summary == BASE_CONTENT.summary
        assert "Restored from v1" in restored.label

    def test_delete_one_version_keeps_resume_and_rejects_last_version(self, conn, base_version):
        service = ResumeService(conn)
        edited_content = BASE_CONTENT.model_copy(deep=True)
        edited_content.summary = "A removable edit"
        edited = service.save_edited(base_version, edited_content)

        service.delete_version(edited)

        repo = ResumeRepository(conn)
        assert repo.get_version(edited.id) is None
        assert repo.get_version(base_version.id) is not None
        with pytest.raises(ValueError, match="at least one version"):
            service.delete_version(base_version)


class TestJobService:
    def test_too_short_jd_rejected(self, conn):
        with pytest.raises(ValueError, match="too short"):
            JobService(conn).create_job("tiny")

    def test_analyze_stores_analysis_and_fills_headline(self, conn):
        service = JobService(conn)
        job = service.create_job(JD_TEXT, url="https://example.com/job")
        extraction_json = json.dumps(
            {
                "title": "Senior Data Engineer",
                "company": "Initech",
                "technical_skills": ["Python", "Airflow"],
                "keywords": ["ETL", "Python"],
                "salary_info": "$150k-$180k",
            }
        )
        provider = ScriptedProvider([extraction_json])
        extraction = service.analyze(provider, job)
        assert extraction.company == "Initech"
        assert job.title == "Senior Data Engineer"
        stored = service._repo.latest_analysis(job.id, "extraction")
        assert stored.prompt_id == "job_extraction"
        assert stored.result["technical_skills"] == ["Python", "Airflow"]
        assert "<<<BEGIN JOB DESCRIPTION>>>" in provider.prompts[0]

    def test_fit_analysis_grounded_and_stored(self, conn, base_version):
        service = JobService(conn)
        job = service.create_job(JD_TEXT)
        fit_json = json.dumps(
            {
                "strong_matches": [
                    {
                        "requirement": "Python",
                        "candidate_evidence": "Built ETL pipelines in Python",
                    }
                ],
                "missing_qualifications": [{"requirement": "Mentoring juniors"}],
                "summary": "Good technical overlap.",
                "methodology": "Text comparison of resume and posting.",
            }
        )
        provider = ScriptedProvider([fit_json])
        fit = service.fit_analysis(provider, job, base_version)
        assert fit.strong_matches[0].candidate_evidence.startswith("Built ETL")
        stored = service._repo.latest_analysis(job.id, "fit")
        assert stored.resume_version_id == base_version.id
        # both fenced blocks present in the prompt
        assert "<<<BEGIN JOB DESCRIPTION>>>" in provider.prompts[0]
        assert "<<<BEGIN RESUME>>>" in provider.prompts[0]

    def test_fit_generation_can_run_in_worker_then_persist_on_owner_thread(
        self, conn, base_version
    ):
        """Regression for SQLite connections being reused by the QThread worker."""
        from concurrent.futures import ThreadPoolExecutor

        service = JobService(conn)
        job = service.create_job(JD_TEXT)
        provider = ScriptedProvider(
            [
                json.dumps(
                    {
                        "strong_matches": [
                            {
                                "requirement": "Python",
                                "candidate_evidence": "Built ETL pipelines in Python",
                            }
                        ],
                        "summary": "Good overlap.",
                        "methodology": "Grounded comparison.",
                    }
                )
            ]
        )

        with ThreadPoolExecutor(max_workers=1) as pool:
            generated = pool.submit(
                service.generate_fit_analysis, provider, job, base_version
            ).result()

        # This call is deliberately back on the connection-owner thread.
        fit = service.persist_generated_analysis(generated)

        assert fit.summary == "Good overlap."
        stored = service._repo.latest_analysis(job.id, "fit")
        assert stored is not None
        assert stored.result["summary"] == "Good overlap."

    def test_job_extraction_generation_can_run_in_worker_then_persist_on_owner_thread(self, conn):
        from concurrent.futures import ThreadPoolExecutor

        service = JobService(conn)
        job = service.create_job(JD_TEXT)
        provider = ScriptedProvider(
            [json.dumps({"title": "Senior Data Engineer", "company": "Initech"})]
        )

        with ThreadPoolExecutor(max_workers=1) as pool:
            generated = pool.submit(service.generate_analysis, provider, job).result()
        service.persist_generated_analysis(generated)

        reloaded = service._repo.get(job.id)
        assert reloaded.title == "Senior Data Engineer"
        assert reloaded.company == "Initech"


class TestTailoringService:
    def _session(self, conn, base_version):
        job = JobService(conn).create_job(JD_TEXT)
        service = TailoringService(conn)
        session = service.create_session(job, base_version, "ats")
        return service, session, job

    def test_generate_validates_and_stores(self, conn, base_version):
        service, session, job = self._session(conn, base_version)
        suggestions_json = json.dumps(
            {
                "suggestions": [
                    {
                        "target_path": "/experiences/0/highlights/0",
                        "original_text": "Built ETL pipelines in Python processing 2 TB daily",
                        "suggested_text": "Designed and built Python ETL pipelines processing 2 TB daily",
                        "rationale": "Mirrors the posting's 'design pipelines' language.",
                        "jd_evidence": "You will design pipelines",
                        "profile_evidence": "Built ETL pipelines in Python",
                    },
                    {  # invalid path — must be dropped
                        "target_path": "/experiences/9/highlights/0",
                        "suggested_text": "Whatever",
                        "profile_evidence": "x",
                    },
                    {  # invented metric — must be flagged, not dropped
                        "target_path": "/summary",
                        "original_text": "Data engineer with 6 years of experience.",
                        "suggested_text": "Data engineer with 6 years of experience improving throughput by 45%.",
                        "rationale": "Adds impact.",
                        "jd_evidence": "Senior Data Engineer",
                        "profile_evidence": "6 years of experience",
                    },
                ]
            }
        )
        provider = ScriptedProvider([suggestions_json])
        stored = service.generate_suggestions(provider, session, job)
        assert len(stored) == 2
        assert stored[0].warnings == ""
        assert "45%" in stored[1].warnings

    def test_tailoring_uses_long_request_timeout_without_shortening_user_value(
        self, conn, base_version
    ):
        from aptiordesk.features.tailoring.service import TAILORING_REQUEST_TIMEOUT_S

        service, session, job = self._session(conn, base_version)
        response = json.dumps({"suggestions": []})
        provider = ScriptedProvider([response])
        provider.config.timeout_s = 60
        service.generate_suggestions_for_version(provider, session, job, base_version)
        assert provider.overrides[0]["request_timeout_s"] == TAILORING_REQUEST_TIMEOUT_S

        provider = ScriptedProvider([response])
        provider.config.timeout_s = 420
        service.generate_suggestions_for_version(provider, session, job, base_version)
        assert provider.overrides[0]["request_timeout_s"] == 420

    def test_generation_can_run_in_worker_then_persist_on_owner_thread(self, conn, base_version):
        """Regression for the TailoringPage QThread reusing its UI connection."""
        from concurrent.futures import ThreadPoolExecutor

        service, session, job = self._session(conn, base_version)
        provider = ScriptedProvider(
            [
                json.dumps(
                    {
                        "suggestions": [
                            {
                                "target_path": "/summary",
                                "original_text": "Data engineer with 6 years of experience.",
                                "suggested_text": "Data engineer focused on reliable pipelines.",
                                "rationale": "Aligns the summary with the role.",
                                "jd_evidence": "design reliable pipelines",
                                "profile_evidence": "Data engineer",
                            }
                        ]
                    }
                )
            ]
        )

        with ThreadPoolExecutor(max_workers=1) as pool:
            generated = pool.submit(
                service.generate_suggestions_for_version,
                provider,
                session,
                job,
                base_version,
            ).result()

        stored = service.persist_generated_suggestions(generated)

        assert len(stored) == 1
        assert service.list_suggestions(session.id)[0].suggested_text.endswith(
            "reliable pipelines."
        )

    def test_apply_accepted_creates_tailored_version(self, conn, base_version):
        service, session, job = self._session(conn, base_version)
        suggestions_json = json.dumps(
            {
                "suggestions": [
                    {
                        "target_path": "/summary",
                        "original_text": "Data engineer with 6 years of experience.",
                        "suggested_text": "Senior-track data engineer with 6 years of experience.",
                        "rationale": "r",
                        "jd_evidence": "j",
                        "profile_evidence": "p",
                    },
                    {
                        "target_path": "/experiences/0/highlights/1",
                        "original_text": "Maintained Airflow DAGs",
                        "suggested_text": "Maintained and optimized Airflow DAGs",
                        "rationale": "r",
                        "jd_evidence": "Airflow",
                        "profile_evidence": "Maintained Airflow DAGs",
                    },
                ]
            }
        )
        service.generate_suggestions(ScriptedProvider([suggestions_json]), session, job)
        first, second = service.list_suggestions(session.id)
        service.accept(first)
        service.edit(second, "Maintained, optimized, and documented Airflow DAGs")

        new_version = service.apply(session, job)
        assert new_version is not None
        assert new_version.version_no == 2
        assert new_version.tailoring_session_id == session.id
        assert new_version.content.summary.startswith("Senior-track")
        assert new_version.content.experiences[0].highlights[1] == (
            "Maintained, optimized, and documented Airflow DAGs"
        )
        # base untouched
        base = ResumeRepository(conn).get_version(base_version.id)
        assert base.content.summary == "Data engineer with 6 years of experience."
        assert service._repo.get_session(session.id).status == "applied"

        # A source version cannot disappear while its tailored result depends
        # on it. Removing the tailored output then cleans up its session.
        with pytest.raises(ValueError, match="source of one or more tailored"):
            ResumeService(conn).delete_version(base_version)
        ResumeService(conn).delete_version(new_version)
        assert service._repo.get_session(session.id) is None

    def test_analysis_keywords_feed_prompt_and_supported_skill_can_be_added(
        self, conn, base_version
    ):
        service, session, job = self._session(conn, base_version)
        JobRepository(conn).add_analysis(
            JobAnalysis(
                job_id=job.id,
                kind="extraction",
                result={
                    "keywords": ["pipeline orchestration"],
                    "tools_and_platforms": ["Airflow"],
                },
            )
        )
        JobRepository(conn).add_analysis(
            JobAnalysis(
                job_id=job.id,
                kind="fit",
                resume_version_id=base_version.id,
                result={
                    "keywords_to_include": ["pipeline orchestration", "Airflow"],
                    "strong_matches": [
                        {
                            "requirement": "Airflow orchestration",
                            "candidate_evidence": "Maintained Airflow DAGs",
                        }
                    ],
                },
            )
        )
        response = json.dumps(
            {
                "suggestions": [
                    {
                        "operation": "replace",
                        "target_path": "/experiences/0/highlights/1",
                        "original_text": "Maintained Airflow DAGs",
                        "suggested_text": "Maintained Airflow DAGs for pipeline orchestration",
                        "rationale": "Uses a supported analysis keyword naturally.",
                        "jd_evidence": "design pipelines",
                        "profile_evidence": "Maintained Airflow DAGs",
                    },
                    {
                        "operation": "add_skill",
                        "target_path": "/skills/-",
                        "original_text": "",
                        "suggested_text": "Airflow",
                        "skill_category": "Data orchestration",
                        "rationale": "Makes an evidenced tool discoverable.",
                        "jd_evidence": "Airflow",
                        "profile_evidence": "Maintained Airflow DAGs",
                    },
                ]
            }
        )
        provider = ScriptedProvider([response])

        suggestions = service.generate_suggestions(provider, session, job)

        assert "truthfully_supported_keywords" in provider.prompts[0]
        assert "pipeline orchestration" in provider.prompts[0]
        assert [s.operation for s in suggestions] == ["replace", "add_skill"]
        added = suggestions[1]
        assert added.skill_category == "Data orchestration"
        service.accept(added)
        tailored = service.apply(session, job)
        assert tailored is not None
        assert any(
            skill.name == "Airflow" and skill.category == "Data orchestration"
            for skill in tailored.content.skills
        )

    def test_unsupported_or_duplicate_skill_additions_are_dropped(self, conn, base_version):
        service, session, job = self._session(conn, base_version)
        response = json.dumps(
            {
                "suggestions": [
                    {
                        "operation": "add_skill",
                        "target_path": "/skills/-",
                        "suggested_text": "Kubernetes",
                        "profile_evidence": "Managed Kubernetes clusters",
                    },
                    {
                        "operation": "add_skill",
                        "target_path": "/skills/-",
                        "suggested_text": "Python",
                        "profile_evidence": "Built ETL pipelines in Python",
                    },
                    {
                        "operation": "add_skill",
                        "target_path": "/skills/-",
                        "suggested_text": "Airflow",
                        "profile_evidence": "Built ETL pipelines in Python",
                    },
                ]
            }
        )
        assert service.generate_suggestions(ScriptedProvider([response]), session, job) == []

    def test_supported_analysis_keyword_omission_triggers_repair(self, conn, base_version):
        service, session, job = self._session(conn, base_version)
        JobRepository(conn).add_analysis(
            JobAnalysis(
                job_id=job.id,
                kind="fit",
                resume_version_id=base_version.id,
                result={"keywords_to_include": ["Airflow"]},
            )
        )
        without_keyword = json.dumps(
            {
                "suggestions": [
                    {
                        "target_path": "/summary",
                        "suggested_text": "Data engineer focused on reliable systems.",
                        "profile_evidence": "Data engineer",
                    }
                ]
            }
        )
        with_keyword = json.dumps(
            {
                "suggestions": [
                    {
                        "target_path": "/experiences/0/highlights/1",
                        "suggested_text": "Maintained production Airflow DAGs",
                        "profile_evidence": "Maintained Airflow DAGs",
                    }
                ]
            }
        )
        provider = ScriptedProvider([without_keyword, with_keyword])

        suggestions = service.generate_suggestions(provider, session, job)

        assert provider.calls == 2
        assert suggestions[0].suggested_text == "Maintained production Airflow DAGs"

    def test_apply_with_nothing_accepted_returns_none(self, conn, base_version):
        service, session, job = self._session(conn, base_version)
        suggestions_json = json.dumps(
            {
                "suggestions": [
                    {
                        "target_path": "/summary",
                        "suggested_text": "X",
                        "profile_evidence": "p",
                    }
                ]
            }
        )
        service.generate_suggestions(ScriptedProvider([suggestions_json]), session, job)
        (only,) = service.list_suggestions(session.id)
        service.reject(only)
        assert service.apply(session, job) is None
