"""Document importer tests. PDF/DOCX fixtures are generated at test time so
no binary blobs live in the repo."""

import pytest

from aptiordesk.core.errors import DocumentError
from aptiordesk.documents.importers import MAX_FILE_SIZE, import_document

RESUME_TEXT = "John Doe\nData Engineer\njohn@example.com\nBuilt pipelines with Python."


@pytest.fixture
def pdf_file(tmp_path):
    from tests.helpers import make_minimal_pdf

    path = tmp_path / "resume.pdf"
    path.write_bytes(make_minimal_pdf(RESUME_TEXT.splitlines()))
    return path


@pytest.fixture
def docx_file(tmp_path):
    import docx

    path = tmp_path / "resume.docx"
    document = docx.Document()
    for line in RESUME_TEXT.splitlines():
        document.add_paragraph(line)
    document.save(str(path))
    return path


def test_txt_import(tmp_path):
    path = tmp_path / "resume.txt"
    path.write_text(RESUME_TEXT, encoding="utf-8")
    assert "Data Engineer" in import_document(path)


def test_markdown_import(tmp_path):
    path = tmp_path / "resume.md"
    path.write_text("# John Doe\n\n**Data Engineer**", encoding="utf-8")
    assert "John Doe" in import_document(path)


def test_pdf_import(pdf_file):
    text = import_document(pdf_file)
    assert "John Doe" in text
    assert "pipelines" in text


def test_docx_import(docx_file):
    text = import_document(docx_file)
    assert "John Doe" in text
    assert "john@example.com" in text


def test_unsupported_extension(tmp_path):
    path = tmp_path / "resume.exe"
    path.write_bytes(b"MZ....")
    with pytest.raises(DocumentError, match="Unsupported"):
        import_document(path)


def test_missing_file(tmp_path):
    with pytest.raises(DocumentError, match="not found"):
        import_document(tmp_path / "nope.pdf")


def test_empty_file(tmp_path):
    path = tmp_path / "empty.txt"
    path.write_text("", encoding="utf-8")
    with pytest.raises(DocumentError, match="empty"):
        import_document(path)


def test_oversized_file(tmp_path):
    path = tmp_path / "big.txt"
    path.write_bytes(b"a" * (MAX_FILE_SIZE + 1))
    with pytest.raises(DocumentError, match="too large"):
        import_document(path)


def test_fake_pdf_magic_bytes_rejected(tmp_path):
    path = tmp_path / "fake.pdf"
    path.write_text("this is not a pdf", encoding="utf-8")
    with pytest.raises(DocumentError, match="valid PDF"):
        import_document(path)


def test_fake_docx_rejected(tmp_path):
    path = tmp_path / "fake.docx"
    path.write_bytes(b"garbage bytes here")
    with pytest.raises(DocumentError, match="valid DOCX"):
        import_document(path)
