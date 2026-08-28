"""Document extraction pipeline: format handling, diagnosis, normalisation.

Covers the failure modes that previously all collapsed into one generic
"no text could be extracted" message, plus the normalisation that PDF text
extraction makes necessary.
"""

from __future__ import annotations

import pytest

from aptiordesk.core.errors import DocumentError
from aptiordesk.documents.pipeline import (
    Diagnosis,
    detect_kind,
    load_document,
    normalise,
)
from tests.helpers import make_minimal_pdf

RESUME_LINES = [
    "Ada Lovelace",
    "Senior Data Engineer",
    "ada@example.com | +44 20 7946 0958 | London, UK",
    "linkedin.com/in/adalovelace  github.com/adal",
    "",
    "SUMMARY",
    "Data engineer with eight years building analytical pipelines.",
    "",
    "EXPERIENCE",
    "Principal Engineer, Analytical Engines Ltd, London 2021-03 - Present",
    "- Rebuilt the ingest pipeline, cutting latency from 40 minutes to 6.",
    "- Led a team of five engineers.",
    "Data Engineer, Babbage Systems, Cambridge 2018-01 - 2021-02",
    "- Designed the differencing warehouse schema.",
    "",
    "EDUCATION",
    "MSc Mathematics, University of London, 2017",
    "",
    "SKILLS",
    "Python, SQL, Spark, Airflow, dbt, AWS",
]


@pytest.fixture
def resume_pdf(tmp_path):
    path = tmp_path / "resume.pdf"
    path.write_bytes(make_minimal_pdf(RESUME_LINES))
    return path


# --- happy paths --------------------------------------------------------------


def test_text_pdf_extracts_and_reports_ok(resume_pdf):
    result = load_document(resume_pdf)

    assert result.ok
    assert result.diagnosis is Diagnosis.OK
    assert result.message() == ""
    assert result.page_count == 1
    assert result.pages_with_text == 1
    assert "Ada Lovelace" in result.text
    assert "Analytical Engines" in result.text
    assert "ada@example.com" in result.text


def test_docx_extracts_paragraphs_and_tables(tmp_path):
    docx = pytest.importorskip("docx")
    path = tmp_path / "resume.docx"
    document = docx.Document()
    for line in RESUME_LINES:
        document.add_paragraph(line)
    table = document.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "2021-2024"
    table.rows[0].cells[1].text = "Principal Engineer, Analytical Engines"
    document.save(path)

    result = load_document(path)

    assert result.ok
    assert result.diagnosis is Diagnosis.OK
    # Table cells must survive: many resumes put dates and roles in tables.
    assert "2021-2024" in result.text
    assert "Principal Engineer, Analytical Engines" in result.text


@pytest.mark.parametrize("suffix", [".txt", ".md", ".markdown"])
def test_plain_text_formats(tmp_path, suffix):
    path = tmp_path / f"resume{suffix}"
    path.write_text("\n".join(RESUME_LINES), encoding="utf-8")

    result = load_document(path)

    assert result.ok
    assert "Ada Lovelace" in result.text


def test_multilingual_text_survives_round_trip(tmp_path):
    """Arabic, accented Latin, and CJK must not be mangled or dropped."""
    body = (
        "\n".join(RESUME_LINES)
        + "\n\nLANGUAGES\n"
        + "Arabic (native) - مهندسة بيانات أولى\n"
        + "French - Ingenieur logiciel, Zurich\n"
        + "Japanese - データエンジニア\n"
    )
    path = tmp_path / "resume.txt"
    path.write_text(body, encoding="utf-8")

    result = load_document(path)

    assert result.ok
    assert "مهندسة بيانات أولى" in result.text
    assert "データエンジニア" in result.text


def test_utf16_and_cp1252_are_decoded(tmp_path):
    utf16 = tmp_path / "a.txt"
    utf16.write_bytes(("\n".join(RESUME_LINES)).encode("utf-16"))
    assert "Ada Lovelace" in load_document(utf16).text

    cp1252 = tmp_path / "b.txt"
    cp1252.write_bytes(("\n".join(RESUME_LINES) + "\nRésumé — naïve").encode("cp1252"))
    assert "Ada Lovelace" in load_document(cp1252).text


# --- failure modes, each with its own diagnosis -------------------------------


def test_image_only_pdf_is_named_as_such_not_reported_as_empty(tmp_path):
    """The case that previously produced a silent empty result."""
    pypdf = pytest.importorskip("pypdf")
    path = tmp_path / "scan.pdf"
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.add_blank_page(width=595, height=842)
    with path.open("wb") as handle:
        writer.write(handle)

    result = load_document(path)

    assert not result.ok
    assert result.diagnosis is Diagnosis.IMAGE_ONLY
    assert result.page_count == 2
    message = result.message()
    assert "2 page" in message
    assert "OCR" in message  # tells the user what would actually be required


def test_password_protected_pdf_is_identified(tmp_path):
    pypdf = pytest.importorskip("pypdf")
    path = tmp_path / "locked.pdf"
    reader = pypdf.PdfReader(_bytes_io(make_minimal_pdf(RESUME_LINES)))
    writer = pypdf.PdfWriter()
    writer.append_pages_from_reader(reader)
    writer.encrypt("hunter2")
    with path.open("wb") as handle:
        writer.write(handle)

    result = load_document(path)

    assert not result.ok
    assert result.diagnosis is Diagnosis.ENCRYPTED
    assert "password" in result.message().lower()


def test_corrupt_pdf_is_identified(tmp_path):
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"%PDF-1.4\n" + b"garbage" * 200)

    result = load_document(path)

    assert not result.ok
    assert result.diagnosis is Diagnosis.CORRUPT


def test_empty_file_is_rejected_before_parsing(tmp_path):
    path = tmp_path / "empty.pdf"
    path.write_bytes(b"")

    with pytest.raises(DocumentError, match="empty"):
        load_document(path)


def test_oversized_file_is_rejected(tmp_path):
    path = tmp_path / "huge.txt"
    path.write_bytes(b"x" * (10 * 1024 * 1024 + 1))

    with pytest.raises(DocumentError, match="too large"):
        load_document(path)


def test_unsupported_extension_is_rejected(tmp_path):
    path = tmp_path / "resume.pages"
    path.write_bytes(b"whatever")

    with pytest.raises(DocumentError, match="Unsupported file type"):
        load_document(path)


def test_legacy_doc_gets_a_specific_message(tmp_path):
    """An OLE2 .doc renamed to .docx should say so, not say 'corrupt'."""
    path = tmp_path / "resume.docx"
    path.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 512)

    with pytest.raises(DocumentError, match="legacy Word"):
        load_document(path)


def test_content_wins_over_extension(tmp_path):
    """A PDF renamed to .docx is detected by magic bytes, not the extension."""
    path = tmp_path / "resume.docx"
    path.write_bytes(make_minimal_pdf(RESUME_LINES))

    result = load_document(path)

    assert result.kind == "pdf"
    assert result.ok
    assert "Ada Lovelace" in result.text


def test_thin_extraction_is_flagged_but_still_usable(tmp_path):
    path = tmp_path / "stub.txt"
    path.write_text("Ada Lovelace")

    result = load_document(path)

    assert result.ok  # usable — the user may still want to proceed
    assert result.diagnosis is Diagnosis.THIN
    assert "small amount of text" in result.message()


def test_raise_if_unusable_raises_only_for_unusable(tmp_path, resume_pdf):
    load_document(resume_pdf).raise_if_unusable()  # must not raise

    scan = tmp_path / "scan.pdf"
    pypdf = pytest.importorskip("pypdf")
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=595, height=842)
    with scan.open("wb") as handle:
        writer.write(handle)
    with pytest.raises(DocumentError):
        load_document(scan).raise_if_unusable()


# --- detection ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("head", "name", "expected"),
    [
        (b"%PDF-1.7\n", "a.pdf", "pdf"),
        (b"PK\x03\x04\x14\x00\x00\x00", "a.docx", "docx"),
        (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "a.docx", "doc"),
        (b"{\\rtf1\\ansi", "a.txt", "rtf"),
        (b"Just some text\n", "a.md", "text"),
    ],
)
def test_detect_kind(tmp_path, head, name, expected):
    path = tmp_path / name
    path.write_bytes(head + b"\x00" * 64)
    assert detect_kind(path) == expected


# --- normalisation ------------------------------------------------------------


def test_hyphenated_line_breaks_are_rejoined():
    assert "engineering" in normalise("I did engi-\nneering work")
    # A genuine hyphenated compound must survive untouched.
    assert "full-stack" in normalise("full-stack developer")


def test_bullet_glyphs_become_markdown_dashes():
    text = normalise("• Built a pipeline\n▪ Led a team\n‣ Shipped it")
    assert text.splitlines() == ["- Built a pipeline", "- Led a team", "- Shipped it"]


def test_ligatures_and_smart_punctuation_are_folded():
    text = normalise("The oﬀice was eﬃcient — it's “done”")
    assert "office" in text
    assert "efficient" in text
    assert '"done"' in text
    assert "'" in text


def test_running_headers_are_removed_but_repeated_content_is_kept():
    page = "Ada Lovelace CV\nReal content line here that is long\n"
    assert "Ada Lovelace CV" not in normalise(page * 4)
    # Two occurrences is not a running header.
    assert normalise(page * 2).count("Ada Lovelace CV") == 2


def test_page_number_footers_are_removed():
    text = normalise("Content\nPage 1 of 3\nMore content\n- 2 -\nEnd")
    assert "Page 1 of 3" not in text
    assert "- 2 -" not in text
    assert "More content" in text


def test_excess_whitespace_is_collapsed():
    text = normalise("A\n\n\n\n\nB\nC    \t   D")
    assert "\n\n\n" not in text
    assert "C  D" in text


def test_normalise_is_idempotent():
    messy = "• engi-\nneering  \n\n\n\nPage 1 of 2\nThe oﬀice"
    once = normalise(messy)
    assert normalise(once) == once


def _bytes_io(data: bytes):
    import io

    return io.BytesIO(data)
