"""Interview service and voice tests. No audio hardware, no real models."""

import json
import sqlite3
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from aptiordesk.database.models.interview import InterviewQuestion, InterviewSession
from aptiordesk.database.models.resume import ResumeContent
from aptiordesk.database.repositories.interview_repo import InterviewRepository
from aptiordesk.features.interviews.service import (
    MAX_FOLLOWUPS_PER_QUESTION,
    GeneratedQuestions,
    InterviewService,
)
from aptiordesk.features.interviews.voice.analysis import (
    analyze_delivery,
    count_fillers,
    count_words,
)
from aptiordesk.features.jobs.service import JobService
from aptiordesk.features.resumes.service import ResumeService
from tests.helpers import ScriptedProvider

JD = (
    "Senior Data Engineer at Initech. Requirements: 5+ years Python, Airflow, "
    "cloud data warehouses. You will design pipelines and mentor juniors. Remote."
)

QUESTIONS_JSON = json.dumps(
    {
        "questions": [
            {
                "text": "Tell me about a pipeline you owned end to end.",
                "category": "behavioral",
                "difficulty": "medium",
                "key_points": ["Scope", "Personal contribution", "Outcome"],
                "why_asked": "Tests real ownership rather than team association.",
            },
            {
                "text": "How do you handle a DAG that fails intermittently?",
                "category": "technical",
                "difficulty": "hard",
                "key_points": ["Diagnosis", "Idempotency"],
            },
            {"text": "", "category": "behavioral"},  # blank must be skipped
        ],
    }
)

FEEDBACK_JSON = json.dumps(
    {
        "scores": {"relevance": 4, "clarity": 3, "structure": 2, "specificity": 2},
        "strengths": ["Named the specific technology and your role."],
        "improvements": ["Give the outcome, not just the activity."],
        "star_assessment": "Situation and Action present; Result missing.",
        "missing_specifics": ["What was the pipeline's throughput before and after?"],
        "red_flags": [],
        "stronger_version": "I owned the ingestion pipeline at ACME... [add the actual number]",
        "summary": "Solid grounding, but quantify the result.",
    }
)


@pytest.fixture
def setup(conn):
    content = ResumeContent.model_validate(
        {
            "full_name": "Jane Roe",
            "summary": "Data engineer with 6 years of experience.",
            "experiences": [
                {
                    "title": "Data Engineer",
                    "organization": "ACME",
                    "highlights": ["Built ETL pipelines in Python"],
                }
            ],
        }
    )
    _, version = ResumeService(conn).create_manual("Base", content)
    job = JobService(conn).create_job(JD)
    return job, version


class TestQuestionGeneration:
    def test_generates_and_persists_skipping_blanks(self, conn, setup):
        job, version = setup
        service = InterviewService(conn)
        provider = ScriptedProvider([QUESTIONS_JSON])
        questions = service.generate_questions(provider, job, version, stage="behavioral", count=3)
        assert len(questions) == 2  # blank dropped
        assert questions[0].job_id == job.id
        assert questions[0].stage == "behavioral"
        assert questions[0].key_points == ["Scope", "Personal contribution", "Outcome"]
        assert "<<<BEGIN JOB DESCRIPTION>>>" in provider.prompts[0]
        assert "<<<BEGIN RESUME>>>" in provider.prompts[0]

    def test_unknown_stage_rejected(self, conn, setup):
        job, version = setup
        with pytest.raises(ValueError, match="stage"):
            InterviewService(conn).generate_questions(
                ScriptedProvider([QUESTIONS_JSON]), job, version, stage="nonsense"
            )

    def test_works_without_job_or_resume(self, conn):
        service = InterviewService(conn)
        questions = service.generate_questions(
            ScriptedProvider([QUESTIONS_JSON]), None, None, stage="behavioral"
        )
        assert len(questions) == 2
        assert questions[0].job_id is None

    def test_ai_generation_runs_off_thread_and_persists_on_owner_thread(self, conn, setup):
        """Starting a mock interview must never carry SQLite into its QThread."""
        job, version = setup
        service = InterviewService(conn)
        session = service.start_session(job, version, persona="executive", stage="behavioral")
        with ThreadPoolExecutor(max_workers=1) as pool:
            generated = pool.submit(
                lambda: service.generate_questions_ai(
                    ScriptedProvider([QUESTIONS_JSON]),
                    job,
                    version,
                    stage="behavioral",
                    session=session,
                )
            ).result()

        questions = service.persist_questions(generated)
        assert len(questions) == 2
        assert InterviewRepository(conn).list_questions(session.id)[0].id == questions[0].id

    def test_database_ids_returned_by_ai_are_ignored(self, conn, setup):
        """AI output must never control question foreign keys."""
        job, version = setup
        service = InterviewService(conn)
        session = service.start_session(
            job, version, persona="friendly_recruiter", stage="recruiter_screen"
        )
        poisoned = json.dumps(
            {
                "questions": [
                    {
                        "id": 999,
                        "session_id": 999,
                        "job_id": 999,
                        "text": "Walk me through your recent work.",
                        "category": "behavioral",
                        "is_followup": True,
                        "parent_question_id": 999,
                    }
                ]
            }
        )
        provider = ScriptedProvider([poisoned])
        questions = service.generate_questions(
            provider, job, version, stage="recruiter_screen", session=session
        )

        question = questions[0]
        assert question.id != 999
        assert question.session_id == session.id
        assert question.job_id == job.id
        assert question.parent_question_id is None
        assert not question.is_followup
        assert "parent_question_id" not in provider.prompts[0]

    def test_generated_question_batch_rolls_back_atomically(self, conn, setup):
        job, version = setup
        service = InterviewService(conn)
        session = service.start_session(job, version, persona="executive", stage="behavioral")
        generated = GeneratedQuestions(
            questions=[
                InterviewQuestion(session_id=session.id, job_id=job.id, text="Valid question"),
                InterviewQuestion(
                    session_id=session.id,
                    job_id=job.id,
                    text="Invalid follow-up",
                    is_followup=True,
                    parent_question_id=999,
                ),
            ],
        )
        with pytest.raises(sqlite3.IntegrityError):
            service.persist_questions(generated)
        assert InterviewRepository(conn).list_questions(session.id) == []

    def test_failed_setup_session_can_be_discarded(self, conn, setup):
        job, version = setup
        service = InterviewService(conn)
        session = service.start_session(job, version, persona="coaching", stage="behavioral")
        service.discard_session(session.id)
        assert InterviewRepository(conn).get_session(session.id) is None


class TestMockSession:
    def _session(self, conn, setup):
        job, version = setup
        service = InterviewService(conn)
        session = service.start_session(
            job, version, persona="skeptical_hiring_manager", stage="behavioral"
        )
        questions = service.generate_questions(
            ScriptedProvider([QUESTIONS_JSON]),
            job,
            version,
            stage="behavioral",
            session=session,
        )
        return service, session, questions, version

    def test_persona_and_stage_validated(self, conn, setup):
        job, version = setup
        service = InterviewService(conn)
        with pytest.raises(ValueError, match="persona"):
            service.start_session(job, version, persona="clown", stage="behavioral")
        with pytest.raises(ValueError, match="stage"):
            service.start_session(job, version, persona="executive", stage="nope")

    def test_answers_are_versioned_by_attempt(self, conn, setup):
        service, session, questions, _ = self._session(conn, setup)
        first = service.record_answer(questions[0], "First attempt.", session=session)
        second = service.record_answer(questions[0], "Second attempt.", session=session)
        assert first.attempt_no == 1
        assert second.attempt_no == 2
        stored = InterviewRepository(conn).list_answers(questions[0].id)
        assert [a.text for a in stored] == ["First attempt.", "Second attempt."]

    def test_voice_answer_records_delivery_stats(self, conn, setup):
        service, session, questions, _ = self._session(conn, setup)
        text = "Um, so I basically, you know, built the thing " * 8
        answer = service.record_answer(
            questions[0], text, session=session, input_mode="voice", duration_s=60.0
        )
        assert answer.input_mode == "voice"
        assert answer.words_per_minute is not None
        assert answer.filler["filler_total"] > 0
        assert "pace_comment" in answer.filler

    def test_feedback_stored_with_provenance(self, conn, setup):
        service, session, questions, version = self._session(conn, setup)
        answer = service.record_answer(questions[0], "I built a pipeline.", session=session)
        feedback = service.feedback_for(
            ScriptedProvider([FEEDBACK_JSON]), questions[0], answer, version
        )
        assert feedback.scores.structure == 2
        assert feedback.star_assessment.startswith("Situation and Action")
        stored = InterviewRepository(conn).get_feedback(answer.id)
        assert stored.summary == feedback.summary

    def test_feedback_ai_runs_off_thread_and_persists_on_owner_thread(self, conn, setup):
        service, session, questions, version = self._session(conn, setup)
        answer = service.record_answer(questions[0], "I built a pipeline.", session=session)
        with ThreadPoolExecutor(max_workers=1) as pool:
            feedback = pool.submit(
                service.generate_feedback,
                ScriptedProvider([FEEDBACK_JSON]),
                questions[0],
                answer,
                version,
            ).result()

        service.persist_feedback(answer, feedback)
        assert InterviewRepository(conn).get_feedback(answer.id).summary == feedback.summary

    def test_followup_decision_and_insertion(self, conn, setup):
        service, session, questions, _ = self._session(conn, setup)
        answer = service.record_answer(questions[0], "We shipped it.", session=session)
        decision = service.decide_followup(
            ScriptedProvider(
                [
                    json.dumps(
                        {
                            "ask_followup": True,
                            "followup_question": "What did YOU do on that project?",
                            "reason": "Answer describes the team, not the candidate.",
                        }
                    )
                ]
            ),
            session,
            questions[0],
            answer,
            followup_count=0,
        )
        assert decision.ask_followup
        followup = service.add_followup(session, questions[0], decision.followup_question)
        assert followup.is_followup
        assert followup.parent_question_id == questions[0].id

    def test_followup_limit_short_circuits_without_calling_ai(self, conn, setup):
        service, session, questions, _ = self._session(conn, setup)
        answer = service.record_answer(questions[0], "Vague.", session=session)
        provider = ScriptedProvider([])  # would IndexError if called
        decision = service.decide_followup(
            provider,
            session,
            questions[0],
            answer,
            followup_count=MAX_FOLLOWUPS_PER_QUESTION,
        )
        assert not decision.ask_followup
        assert provider.calls == 0

    def test_followup_without_text_is_not_asked(self, conn, setup):
        service, session, questions, _ = self._session(conn, setup)
        answer = service.record_answer(questions[0], "Answer.", session=session)
        decision = service.decide_followup(
            ScriptedProvider([json.dumps({"ask_followup": True, "followup_question": "  "})]),
            session,
            questions[0],
            answer,
            followup_count=0,
        )
        assert not decision.ask_followup

    def test_report_completes_session(self, conn, setup):
        service, session, questions, _ = self._session(conn, setup)
        service.record_answer(questions[0], "I built the ingestion pipeline.", session=session)
        report = service.build_report(
            ScriptedProvider(
                [
                    json.dumps(
                        {
                            "overall_summary": "Reasonable grounding, thin on outcomes.",
                            "recurring_patterns": ["Outcomes rarely quantified"],
                            "priorities": ["Add one metric to each story"],
                        }
                    )
                ]
            ),
            session,
        )
        assert report.priorities == ["Add one metric to each story"]
        stored = InterviewRepository(conn).get_session(session.id)
        assert stored.status == "completed"
        assert stored.ended_at
        assert stored.report["overall_summary"] == report.overall_summary

    def test_report_ai_runs_off_thread_and_persists_on_owner_thread(self, conn, setup):
        service, session, questions, _ = self._session(conn, setup)
        service.record_answer(questions[0], "I owned the pipeline.", session=session)
        context = service.report_context(session)
        response = json.dumps(
            {
                "overall_summary": "Good ownership evidence.",
                "priorities": ["Quantify the result"],
            }
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            report = pool.submit(
                service.generate_report, ScriptedProvider([response]), context
            ).result()

        service.persist_report(context, report)
        stored = InterviewRepository(conn).get_session(session.id)
        assert stored.status == "completed"
        assert stored.report["overall_summary"] == "Good ownership evidence."

    def test_report_requires_answers(self, conn, setup):
        service, session, _questions, _ = self._session(conn, setup)
        with pytest.raises(ValueError, match="no answers"):
            service.build_report(ScriptedProvider([]), session)

    def test_answer_library_roundtrip(self, conn, setup):
        service, session, questions, _ = self._session(conn, setup)
        answer = service.record_answer(questions[0], "A good answer.", session=session)
        service.save_to_library(answer)
        library = service.library()
        assert len(library) == 1
        saved, question_text = library[0]
        assert saved.text == "A good answer."
        assert question_text == questions[0].text
        service.remove_from_library(answer)
        assert service.library() == []


class TestDeliveryAnalysis:
    def test_word_count(self):
        assert count_words("Hello there, I'm fine.") == 4

    def test_multiword_fillers_not_double_counted(self):
        counts = count_fillers("You know, I mean, it was like, you know, fine")
        assert counts["you know"] == 2
        assert counts.get("know") is None
        assert counts["i mean"] == 1

    def test_filler_word_boundaries(self):
        # "likely" must not count as "like"
        assert count_fillers("That is likely correct").get("like") is None
        assert count_fillers("It was like that")["like"] == 1

    def test_pace_classification(self):
        slow = analyze_delivery(" ".join(["word"] * 50), duration_s=60)
        assert "slower" in slow.pace_comment
        fast = analyze_delivery(" ".join(["word"] * 200), duration_s=60)
        assert "fast" in fast.pace_comment
        ok = analyze_delivery(" ".join(["word"] * 140), duration_s=60)
        assert "comfortable" in ok.pace_comment

    def test_short_and_long_answer_notes(self):
        short = analyze_delivery("Yes, definitely.", duration_s=8)
        assert any("short" in note for note in short.notes)
        long_answer = analyze_delivery(" ".join(["word"] * 400), duration_s=200)
        assert any("three minutes" in note for note in long_answer.notes)

    def test_no_duration_means_no_wpm(self):
        stats = analyze_delivery("Some text here")
        assert stats.words_per_minute is None
        assert stats.pace_comment == ""

    def test_empty_text_is_safe(self):
        stats = analyze_delivery("", duration_s=10)
        assert stats.word_count == 0
        assert stats.filler_total == 0
        assert stats.as_dict()["words_per_minute"] is None


class TestRecorder:
    def test_records_to_wav_via_injected_stream(self, tmp_path, monkeypatch):
        from aptiordesk.core import paths
        from aptiordesk.features.interviews.voice.recorder import SAMPLE_RATE, Recorder

        monkeypatch.setattr(paths, "scratch_dir", lambda: tmp_path)

        class FakeStream:
            def __init__(self, callback):
                self._callback = callback

            def start(self):
                # 0.5s of silence in int16 mono
                self._callback(b"\x00\x00" * (SAMPLE_RATE // 2))

            def stop(self):
                pass

            def close(self):
                pass

        recorder = Recorder(stream_factory=lambda cb: FakeStream(cb))
        recorder.start()
        assert recorder.is_recording
        path = recorder.stop()
        assert not recorder.is_recording
        assert path.exists()
        with wave.open(str(path), "rb") as handle:
            assert handle.getnchannels() == 1
            assert handle.getframerate() == SAMPLE_RATE
            assert handle.getnframes() == SAMPLE_RATE // 2

    def test_level_callback_receives_values(self, tmp_path, monkeypatch):
        from aptiordesk.core import paths
        from aptiordesk.features.interviews.voice.recorder import Recorder

        monkeypatch.setattr(paths, "scratch_dir", lambda: tmp_path)
        levels: list[float] = []

        class FakeStream:
            def __init__(self, callback):
                self._callback = callback

            def start(self):
                self._callback(b"\x00\x40" * 512)  # non-silent

            def stop(self):
                pass

            def close(self):
                pass

        recorder = Recorder(stream_factory=lambda cb: FakeStream(cb))
        recorder.level_callback = levels.append
        recorder.start()
        recorder.stop()
        assert levels and levels[0] > 0

    def test_level_callback_is_throttled_for_ui_stability(self, tmp_path, monkeypatch):
        from aptiordesk.core import paths
        from aptiordesk.features.interviews.voice.recorder import Recorder

        monkeypatch.setattr(paths, "scratch_dir", lambda: tmp_path)
        levels: list[float] = []

        class FakeStream:
            def __init__(self, callback):
                self._callback = callback

            def start(self):
                for _ in range(20):
                    self._callback(b"\x00\x40" * 512)

            def stop(self):
                pass

            def close(self):
                pass

        recorder = Recorder(stream_factory=lambda cb: FakeStream(cb))
        recorder.level_callback = levels.append
        recorder.start()
        recorder.stop()

        assert len(levels) == 1

    def test_cancel_discards_audio(self, tmp_path, monkeypatch):
        from aptiordesk.core import paths
        from aptiordesk.features.interviews.voice.recorder import Recorder

        monkeypatch.setattr(paths, "scratch_dir", lambda: tmp_path)

        class FakeStream:
            def __init__(self, callback):
                self._callback = callback

            def start(self):
                self._callback(b"\x00\x00" * 100)

            def stop(self):
                pass

            def close(self):
                pass

        recorder = Recorder(stream_factory=lambda cb: FakeStream(cb))
        recorder.start()
        recorder.cancel()
        assert not recorder.is_recording
        assert list(tmp_path.glob("*.wav")) == []


class TestTranscriber:
    def test_desktop_transcription_defaults_to_safe_cpu(self):
        from aptiordesk.features.interviews.voice.transcriber import LocalTranscriber

        assert LocalTranscriber().device == "cpu"

    def test_model_readiness_rejects_partial_downloads(self, tmp_path, monkeypatch):
        from aptiordesk.core import paths
        from aptiordesk.features.interviews.voice import transcriber as module

        monkeypatch.setattr(paths, "models_dir", lambda: tmp_path)
        model = tmp_path / "faster-whisper" / "small"
        model.mkdir(parents=True)
        (model / "config.json").write_text("{}", encoding="utf-8")

        assert module.model_path("small") is None
        assert not module.model_is_downloaded("small")

        (model / "model.bin").write_bytes(b"model")
        (model / "tokenizer.json").write_text("{}", encoding="utf-8")
        (model / "vocabulary.txt").write_text("words", encoding="utf-8")

        assert module.model_path("small") == model
        assert module.model_is_downloaded("small")

    def test_model_readiness_finds_packaged_model(self, tmp_path, monkeypatch):
        import sys

        from aptiordesk.core import paths
        from aptiordesk.features.interviews.voice import transcriber as module

        monkeypatch.setattr(paths, "models_dir", lambda: tmp_path / "user-models")
        monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
        model = tmp_path / "models" / "faster-whisper" / "small"
        model.mkdir(parents=True)
        (model / "config.json").write_text("{}", encoding="utf-8")
        (model / "model.bin").write_bytes(b"model")
        (model / "tokenizer.json").write_text("{}", encoding="utf-8")
        (model / "vocabulary.json").write_text("{}", encoding="utf-8")

        assert module.model_path("small") == model
        assert module.model_is_downloaded("small")

    def test_model_load_never_downloads_implicitly(self, monkeypatch):
        from aptiordesk.features.interviews.voice import transcriber as module

        monkeypatch.setattr(module, "faster_whisper_available", lambda: True)
        monkeypatch.setattr(module, "model_path", lambda size: None)
        monkeypatch.setattr(module.LocalTranscriber, "_model", None)
        monkeypatch.setattr(module.LocalTranscriber, "_model_key", None)

        with pytest.raises(module.TranscriptionUnavailable, match="not prepared"):
            module.LocalTranscriber().load()

    def test_packaged_app_never_downloads_a_missing_required_model(self, monkeypatch):
        import sys

        from aptiordesk.features.interviews.voice import transcriber as module

        monkeypatch.setattr(module, "faster_whisper_available", lambda: True)
        monkeypatch.setattr(module, "model_path", lambda size: None)
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        called = False

        def download(*_args, **_kwargs):
            nonlocal called
            called = True

        monkeypatch.setattr(module, "_download_model_files", download)
        with pytest.raises(module.TranscriptionUnavailable, match="Repair AptiorDesk"):
            module.prepare_model("small")
        assert not called

    def test_model_readiness_ignores_untrusted_legacy_cache(self, tmp_path, monkeypatch):
        from aptiordesk.core import paths
        from aptiordesk.features.interviews.voice import transcriber as module

        monkeypatch.setattr(paths, "models_dir", lambda: tmp_path)
        snapshot = tmp_path / "models--Systran--faster-whisper-small" / "snapshots" / "legacy"
        snapshot.mkdir(parents=True)
        original_is_file = Path.is_file

        def reject_legacy_link(path):
            if "models--Systran" in str(path) and path.name == "config.json":
                raise OSError(448, "untrusted mount point")
            return original_is_file(path)

        monkeypatch.setattr(Path, "is_file", reject_legacy_link)

        assert module.model_path("small") is None

    def test_model_download_uses_normal_physical_directory(self, tmp_path, monkeypatch):
        from aptiordesk.core import paths
        from aptiordesk.features.interviews.voice import transcriber as module

        monkeypatch.setattr(paths, "models_dir", lambda: tmp_path)
        monkeypatch.setattr(module, "faster_whisper_available", lambda: True)
        monkeypatch.setattr(module.LocalTranscriber, "load", lambda self: object())
        captured = {}

        def download(size, destination, report):
            captured.update(size=size, destination=destination, report=report)
            (destination / "config.json").write_text("{}", encoding="utf-8")
            (destination / "model.bin").write_bytes(b"model")
            (destination / "tokenizer.json").write_text("{}", encoding="utf-8")
            (destination / "vocabulary.txt").write_text("words", encoding="utf-8")

        monkeypatch.setattr(module, "_download_model_files", download)

        assert "ready" in module.prepare_model("small").lower()
        assert captured["size"] == "small"
        assert captured["destination"] == tmp_path / "faster-whisper" / "small"

    def test_transcription_leaves_cpu_capacity_for_the_ui(self):
        from aptiordesk.features.interviews.voice.transcriber import _cpu_thread_limit

        assert 1 <= _cpu_thread_limit() <= 2

    def test_device_selection_falls_back_to_cpu(self, monkeypatch):
        import sys
        import types

        from aptiordesk.features.interviews.voice import transcriber as module

        assert module._pick_device("cpu") == ("cpu", "int8")

        fake = types.ModuleType("ctranslate2")
        fake.get_cuda_device_count = lambda: 0
        monkeypatch.setitem(sys.modules, "ctranslate2", fake)
        monkeypatch.setattr(module, "_cuda_runtime_loadable", lambda: True)
        assert module._pick_device("auto") == ("cpu", "int8")  # no devices

        fake.get_cuda_device_count = lambda: 1
        assert module._pick_device("auto") == ("cuda", "float16")

    def test_cuda_error_falls_back_to_cpu(self, monkeypatch):
        import sys
        import types

        from aptiordesk.features.interviews.voice.transcriber import _pick_device

        fake = types.ModuleType("ctranslate2")

        def boom():
            raise RuntimeError("driver mismatch")

        fake.get_cuda_device_count = boom
        monkeypatch.setitem(sys.modules, "ctranslate2", fake)
        assert _pick_device("auto") == ("cpu", "int8")

    def test_cuda_rejected_when_runtime_libraries_missing(self, monkeypatch):
        """A machine can report CUDA devices while lacking cuBLAS — counting
        devices is not proof the GPU is usable."""
        import sys
        import types

        from aptiordesk.features.interviews.voice import transcriber as module

        fake = types.ModuleType("ctranslate2")
        fake.get_cuda_device_count = lambda: 1
        monkeypatch.setitem(sys.modules, "ctranslate2", fake)
        monkeypatch.setattr(module, "_cuda_runtime_loadable", lambda: False)
        assert module._pick_device("auto") == ("cpu", "int8")
        monkeypatch.setattr(module, "_cuda_runtime_loadable", lambda: True)
        assert module._pick_device("auto") == ("cuda", "float16")

    def test_gpu_failure_at_inference_falls_back_to_cpu(self, tmp_path, monkeypatch):
        """The cuBLAS failure only surfaces during inference; the recording
        must still be transcribed rather than lost."""
        from aptiordesk.features.interviews.voice import transcriber as module

        attempts: list[str] = []

        class FakeModel:
            def __init__(self, device):
                self.device = device

            def transcribe(self, path, **kwargs):
                attempts.append(self.device)
                if self.device == "cuda":
                    raise RuntimeError("Library cublas64_12.dll is not found")
                segment = type("S", (), {"text": " transcribed on cpu "})()
                return [segment], None

        transcriber = module.LocalTranscriber(size="tiny", device="cuda")
        monkeypatch.setattr(module.LocalTranscriber, "load", lambda self: FakeModel(self.device))
        result = transcriber.transcribe(tmp_path / "a.wav")
        assert result == "transcribed on cpu"
        assert attempts == ["cuda", "cpu"]
        assert transcriber.device == "cpu"

    def test_gpu_error_message_is_specific(self, tmp_path, monkeypatch):
        from aptiordesk.features.interviews.voice import transcriber as module

        class AlwaysFails:
            def transcribe(self, path, **kwargs):
                raise RuntimeError("cublas64_12.dll is not found")

        transcriber = module.LocalTranscriber(size="tiny", device="cuda")
        monkeypatch.setattr(module.LocalTranscriber, "load", lambda self: AlwaysFails())
        with pytest.raises(module.TranscriptionUnavailable) as excinfo:
            transcriber.transcribe(tmp_path / "a.wav")
        assert "GPU libraries" in excinfo.value.user_message

    def test_non_gpu_error_does_not_retry(self, tmp_path, monkeypatch):
        from aptiordesk.features.interviews.voice import transcriber as module

        calls = []

        class Broken:
            def transcribe(self, path, **kwargs):
                calls.append(1)
                raise RuntimeError("file is empty")

        transcriber = module.LocalTranscriber(size="tiny", device="cuda")
        monkeypatch.setattr(module.LocalTranscriber, "load", lambda self: Broken())
        with pytest.raises(module.TranscriptionUnavailable):
            transcriber.transcribe(tmp_path / "a.wav")
        assert len(calls) == 1  # no pointless CPU retry

    def test_shared_native_model_inference_is_serialized(self, tmp_path, monkeypatch):
        import threading
        import time
        from concurrent.futures import ThreadPoolExecutor

        from aptiordesk.features.interviews.voice import transcriber as module

        active = 0
        highest_active = 0
        state_lock = threading.Lock()

        class FakeModel:
            def transcribe(self, path, **kwargs):
                nonlocal active, highest_active
                with state_lock:
                    active += 1
                    highest_active = max(highest_active, active)
                time.sleep(0.03)
                with state_lock:
                    active -= 1
                segment = type("S", (), {"text": "safe"})()
                return [segment], None

        shared_model = FakeModel()
        monkeypatch.setattr(module.LocalTranscriber, "load", lambda self: shared_model)
        first = module.LocalTranscriber()
        second = module.LocalTranscriber()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(
                pool.map(
                    lambda item: item.transcribe(tmp_path / "answer.wav"),
                    (first, second),
                )
            )

        assert results == ["safe", "safe"]
        assert highest_active == 1

    def test_missing_package_gives_actionable_error(self, monkeypatch):
        from aptiordesk.core.errors import AptiorDeskError
        from aptiordesk.features.interviews.voice import transcriber as module

        monkeypatch.setattr(module, "faster_whisper_available", lambda: False)
        monkeypatch.setattr(module.LocalTranscriber, "_model", None)
        with pytest.raises(AptiorDeskError) as excinfo:
            module.LocalTranscriber().load()
        assert "Settings → System setup" in excinfo.value.user_message
        assert "pip install" not in excinfo.value.user_message

    def test_unknown_size_rejected(self):
        from aptiordesk.features.interviews.voice.transcriber import LocalTranscriber

        with pytest.raises(ValueError, match="Unknown model size"):
            LocalTranscriber(size="enormous")


class TestSessionPersistence:
    def test_session_roundtrip(self, conn):
        repo = InterviewRepository(conn)
        session = repo.create_session(InterviewSession(persona="executive", stage="final_panel"))
        loaded = repo.get_session(session.id)
        assert loaded.persona == "executive"
        assert loaded.status == "active"
        assert loaded.started_at
        assert repo.list_sessions()[0].id == session.id
