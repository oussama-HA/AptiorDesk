"""The resume import review screen.

Extraction is never trusted silently, so this is the mandatory step between
"the AI read your file" and "it is saved". It shows four things side by side:

* what the AI produced, editable;
* the text that was actually extracted from the file, so a bad result can be
  traced to a bad read rather than guessed at;
* the fields the AI produced that are *not* in that text, which are the ones
  worth checking;
* anything that failed, with the raw model output for the sections that did.
"""

from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QTabWidget,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from aptiordesk.database.models.extraction import ExtractionReport
from aptiordesk.database.models.resume import ResumeContent
from aptiordesk.documents.pipeline import ExtractionResult
from aptiordesk.ui.components.common import badge
from aptiordesk.ui.components.provenance_bar import ProvenanceBar
from aptiordesk.ui.components.resume_editor import ResumeEditorWidget
from aptiordesk.ui.components.rich_text import rich_document
from aptiordesk.ui.theme import current
from aptiordesk.ui.theme.tokens import SPACE


class ExtractionReviewDialog(QDialog):
    """Review, correct, and approve an extraction before anything is saved."""

    def __init__(
        self,
        content: ResumeContent,
        report: ExtractionReport,
        document: ExtractionResult,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Review what was read from your resume")
        self.resize(1080, 720)
        self._report = report

        layout = QVBoxLayout(self)
        layout.setSpacing(SPACE["md"])
        layout.addWidget(_header(report, document))

        tabs = QTabWidget()
        self._editor = ResumeEditorWidget(content)
        tabs.addTab(_scrolled(self._editor), "Extracted information")
        tabs.addTab(_review_tab(report), f"Needs checking ({len(report.inferred())})")
        tabs.addTab(_source_tab(document), "Text read from the file")
        problems = _problem_count(report, document)
        tabs.addTab(_problems_tab(report, document), f"Problems ({problems})")
        layout.addWidget(tabs, 1)

        note = QLabel(
            "Nothing is saved until you press Save. Correct anything that is "
            "wrong — the AI can misread layout, and fields it could not find in "
            "your file are marked in “Needs checking”."
        )
        note.setProperty("role", "hint")
        note.setWordWrap(True)
        layout.addWidget(note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Save resume")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def content(self) -> ResumeContent:
        """The corrected content. Read only after the dialog is accepted."""
        return self._editor.content()


# --- sections -----------------------------------------------------------------


def _header(report: ExtractionReport, document: ExtractionResult) -> QWidget:
    """Headline, status chips, and the provenance bar.

    The header's job is to leave no doubt about what happened: how many items
    were read, how many were verified against the document, and how many need
    a human eye — before the user scrolls into any detail.
    """
    box = QWidget()
    column = QVBoxLayout(box)
    column.setContentsMargins(0, 0, 0, 0)
    column.setSpacing(SPACE["sm"])

    row = QHBoxLayout()
    row.setSpacing(SPACE["sm"])
    headline = QLabel(_plain_headline(report))
    headline.setProperty("role", "sectionTitle")
    headline.setWordWrap(True)
    row.addWidget(headline, 1)
    if report.failed_sections():
        row.addWidget(badge(f"{len(report.failed_sections())} section(s) failed", "danger"))
    if document.diagnosis.value != "ok":
        row.addWidget(badge(document.diagnosis.value.replace("_", " "), "warning"))
    source = QLabel(f"{document.filename} · {document.char_count:,} characters")
    source.setProperty("role", "hint")
    row.addWidget(source)
    column.addLayout(row)

    column.addWidget(ProvenanceBar(report))
    return box


def _plain_headline(report: ExtractionReport) -> str:
    """One sentence in plain language, no hedging and no jargon."""
    if not report.any_content:
        return "Nothing could be read from this document."
    found = sum(s.item_count for s in report.sections if s.ok)
    to_check = len(report.inferred())
    if to_check == 0:
        return (
            f"Read {found} item(s) from your resume — every field was verified "
            "against the document itself."
        )
    return (
        f"Read {found} item(s) from your resume. {to_check} field(s) need a "
        "quick look before you save."
    )


def _review_tab(report: ExtractionReport) -> QWidget:
    page = QWidget()
    layout = QVBoxLayout(page)
    inferred = report.inferred()

    explanation = QLabel(
        "These values do not appear in the text extracted from your file. That "
        "usually means the AI reformatted something (a date, a rephrased "
        "summary) — but it can also mean it invented something. Check each one "
        "in the “Extracted information” tab before saving."
        if inferred
        else "Every extracted value was found in your document. Nothing here needs checking."
    )
    explanation.setWordWrap(True)
    explanation.setProperty("role", "hint")
    layout.addWidget(explanation)

    if inferred:
        tree = QTreeWidget()
        tree.setHeaderLabels(["Field", "Value the AI produced", "Why it is flagged"])
        tree.setRootIsDecorated(False)
        tree.setAlternatingRowColors(True)
        for note in inferred:
            item = QTreeWidgetItem([_humanise(note.path), note.value_preview, note.reason])
            item.setForeground(1, QColor(current().warning))
            tree.addTopLevelItem(item)
        for column in range(3):
            tree.resizeColumnToContents(column)
        layout.addWidget(tree, 1)
    else:
        layout.addStretch(1)
    return page


def _source_tab(document: ExtractionResult) -> QWidget:
    page = QWidget()
    layout = QVBoxLayout(page)

    caption = QLabel(
        f"Extracted with {document.method or 'the built-in reader'} from "
        f"{document.pages_with_text} of {document.page_count} page(s). "
        "If this text is wrong or incomplete, the structure above will be too — "
        "the file itself is the problem, not the AI."
    )
    caption.setWordWrap(True)
    caption.setProperty("role", "hint")
    layout.addWidget(caption)

    view = QPlainTextEdit(document.text)
    view.setReadOnly(True)
    view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
    layout.addWidget(view, 1)
    return page


def _problems_tab(report: ExtractionReport, document: ExtractionResult) -> QWidget:
    page = QWidget()
    layout = QVBoxLayout(page)
    browser = QTextBrowser()
    parts: list[str] = []

    if document.message():
        parts.append(f"<h3>The file</h3><p>{_escape(document.message())}</p>")
    for warning in document.warnings:
        parts.append(f"<p>⚠ {_escape(warning)}</p>")

    failed = report.failed_sections()
    if failed:
        parts.append("<h3>Sections that failed</h3>")
        for section in failed:
            parts.append(f"<p><b>{_escape(section.name)}</b><br>{_escape(section.error)}</p>")
            if section.raw_output:
                parts.append(
                    "<p>What the model actually returned:</p>"
                    f"<pre>{_escape(section.raw_output[:2000])}</pre>"
                )

    ok_sections = [s for s in report.sections if s.ok]
    if ok_sections:
        parts.append("<h3>Sections that succeeded</h3><ul>")
        parts.extend(f"<li>{_escape(s.summary())}</li>" for s in ok_sections)
        parts.append("</ul>")

    if report.model:
        parts.append(
            f"<p><small>Model: {_escape(report.model)} · "
            f"prompt v{report.prompt_version}</small></p>"
        )

    if not parts:
        parts.append("<p>No problems. Every section was extracted cleanly.</p>")

    browser.setHtml(rich_document("".join(parts)))
    layout.addWidget(browser, 1)
    return page


# --- helpers ------------------------------------------------------------------


def _problem_count(report: ExtractionReport, document: ExtractionResult) -> int:
    count = len(report.failed_sections()) + len(document.warnings)
    return count + (1 if document.message() else 0)


def _scrolled(widget: QWidget) -> QWidget:
    from PySide6.QtWidgets import QScrollArea

    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setWidget(widget)
    area.setFrameShape(QScrollArea.Shape.NoFrame)
    return area


def _humanise(path: str) -> str:
    """`experiences.0.organization` -> `Experience 1 › Organization`."""
    parts = path.split(".")
    out: list[str] = []
    for part in parts:
        if part.isdigit():
            out[-1] = f"{out[-1].rstrip('s')} {int(part) + 1}"
        else:
            out.append(part.replace("_", " ").capitalize())
    return " › ".join(out)


def _escape(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


__all__ = ["ExtractionReviewDialog"]
