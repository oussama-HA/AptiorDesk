from aptiordesk.ai.prompts.guards import find_unverified_numbers
from aptiordesk.database.models.resume import ResumeContent
from aptiordesk.documents.render import resume_to_markdown


class TestRender:
    def test_full_resume_renders_sections(self):
        content = ResumeContent.model_validate(
            {
                "full_name": "Jane Roe",
                "professional_title": "Senior Engineer",
                "email": "jane@example.com",
                "summary": "Builder of things.",
                "experiences": [
                    {
                        "title": "Engineer",
                        "organization": "Acme",
                        "start_date": "2020-01",
                        "end_date": "",
                        "highlights": ["Did A", "Did B"],
                    }
                ],
                "education": [{"institution": "MIT", "degree": "BSc", "field_of_study": "CS"}],
                "skills": [
                    {"name": "Python", "category": "Languages"},
                    {"name": "SQL", "category": "Languages"},
                ],
            }
        )
        markdown = resume_to_markdown(content)
        assert "# Jane Roe" in markdown
        assert "**Senior Engineer**" in markdown
        assert "## Experience" in markdown
        assert "Engineer — Acme (2020-01 – present)" in markdown
        assert "- Did A" in markdown
        assert "**Languages**: Python, SQL" in markdown
        assert "MIT" in markdown

    def test_empty_content_renders_without_error(self):
        assert resume_to_markdown(ResumeContent()).strip() == ""


class TestNumberGuard:
    SOURCES = ["Built pipelines processing 2 TB daily for 1,200 users over 6 years"]

    def test_numbers_present_in_source_pass(self):
        assert find_unverified_numbers("Handled 2 TB across 6 years", self.SOURCES) == []

    def test_separator_variants_match(self):
        assert find_unverified_numbers("Served 1200 users", self.SOURCES) == []

    def test_invented_numbers_flagged(self):
        flagged = find_unverified_numbers(
            "Improved throughput by 45% for 300 clients", self.SOURCES
        )
        assert "45%" in flagged
        assert "300" in flagged

    def test_no_numbers_no_flags(self):
        assert find_unverified_numbers("Improved throughput significantly", self.SOURCES) == []
