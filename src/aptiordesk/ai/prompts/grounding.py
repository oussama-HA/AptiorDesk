"""Verify that AI-extracted values actually occur in the source document.

This is the anti-fabrication mechanism for extraction. Rather than asking the
model how confident it is — models are poor judges of that — every produced
string is checked against the text it was supposedly read from. A value that
cannot be found is marked ``INFERRED`` and surfaced for the user to confirm.

Matching is deliberately tolerant of the things extraction legitimately
changes (whitespace, punctuation, bullet glyphs, date formats) and intolerant
of everything else. A false "inferred" costs the user a glance; a false
"extracted" would let an invented employer through unchallenged, so the bias
runs toward flagging.
"""

from __future__ import annotations

import re
import unicodedata

from pydantic import BaseModel

from aptiordesk.database.models.extraction import FieldNote, Provenance

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_SPACES = re.compile(r"\s+")
_TOKEN = re.compile(r"\w+", re.UNICODE)

_MONTHS = {
    "01": ("jan", "january"),
    "02": ("feb", "february"),
    "03": ("mar", "march"),
    "04": ("apr", "april"),
    "05": ("may",),
    "06": ("jun", "june"),
    "07": ("jul", "july"),
    "08": ("aug", "august"),
    "09": ("sep", "sept", "september"),
    "10": ("oct", "october"),
    "11": ("nov", "november"),
    "12": ("dec", "december"),
}
_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})(?:-\d{2})?$")

#: Values shorter than this are matched by substring only — token matching on
#: one- or two-character strings produces meaningless coincidental hits.
_MIN_TOKEN_LEN = 3

#: Fields whose content is expected to be the model's own phrasing rather than
#: a quotation, so grounding them verbatim would flag nearly everything.
#: They are still checked, but a miss is reported without alarm.
PARAPHRASE_PATHS = ("summary", "description", "details")


def normalise_for_match(text: str) -> str:
    """Fold away everything extraction is allowed to change."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = _PUNCT.sub(" ", text.lower())
    return _SPACES.sub(" ", text).strip()


class SourceIndex:
    """A source document prepared for repeated containment checks."""

    def __init__(self, text: str):
        self.raw = text or ""
        self.normalised = normalise_for_match(self.raw)
        self.tokens = set(_TOKEN.findall(self.normalised))
        self.month_years = _month_years(self.normalised)

    def contains(self, value: str) -> bool:
        """True when `value` is present in the source, allowing for reformatting."""
        if not value or not value.strip():
            return False
        needle = normalise_for_match(value)
        if not needle:
            return False
        if needle in self.normalised:
            return True
        # An ISO date is decided by the date rule alone. Falling through to
        # token matching would ground "2017-12" on any stray "2017" elsewhere
        # in the document (a graduation year, say), which is exactly the kind
        # of coincidence that lets an invented role look verified.
        if _ISO_DATE.match(value.strip()):
            return _date_matches(value, self)
        tokens = [t for t in _TOKEN.findall(needle) if len(t) >= _MIN_TOKEN_LEN]
        if not tokens:
            # Too short to token-match; substring was the only honest test.
            return False
        # Every significant token must appear. This catches reordering and
        # dropped punctuation ("Analytical Engines, Ltd." -> "Analytical
        # Engines Ltd") without accepting a different employer entirely.
        return all(token in self.tokens for token in tokens)


def _date_matches(value: str, index: SourceIndex) -> bool:
    """Accept ISO dates the model normalised from a written month name.

    The month and year must occur *together* in the source. Checking them
    independently would ground "2021-07" on a document that mentions "March
    2021" somewhere and "July 2023" somewhere else.
    """
    match = _ISO_DATE.match(value.strip())
    if not match:
        return False
    return (match.group(1), match.group(2)) in index.month_years


_MONTH_TO_NUMBER = {name: number for number, names in _MONTHS.items() for name in names}
#: "march 2021" or "2021 march" in the normalised (punctuation-free) text.
_WRITTEN_DATE = re.compile(
    r"\b(" + "|".join(sorted(_MONTH_TO_NUMBER, key=len, reverse=True)) + r")\w*\s+(\d{4})\b"
)
_WRITTEN_DATE_REVERSED = re.compile(
    r"\b(\d{4})\s+(" + "|".join(sorted(_MONTH_TO_NUMBER, key=len, reverse=True)) + r")\w*\b"
)
_ISO_IN_TEXT = re.compile(r"\b(\d{4})[-/ ](\d{2})\b")


def _month_years(normalised: str) -> set[tuple[str, str]]:
    """Every (year, month) pair the source actually states, as ISO components."""
    pairs: set[tuple[str, str]] = set()
    for month_name, year in _WRITTEN_DATE.findall(normalised):
        pairs.add((year, _MONTH_TO_NUMBER[month_name]))
    for year, month_name in _WRITTEN_DATE_REVERSED.findall(normalised):
        pairs.add((year, _MONTH_TO_NUMBER[month_name]))
    for year, month in _ISO_IN_TEXT.findall(normalised):
        if "01" <= month <= "12":
            pairs.add((year, month))
    return pairs


# --- walking a model ----------------------------------------------------------


def walk_strings(value: object, prefix: str = "") -> list[tuple[str, str]]:
    """Yield ``(dotted_path, string_value)`` for every string in a model tree."""
    found: list[tuple[str, str]] = []
    if isinstance(value, BaseModel):
        for name in type(value).model_fields:
            found.extend(walk_strings(getattr(value, name), _join(prefix, name)))
    elif isinstance(value, dict):
        for key, item in value.items():
            found.extend(walk_strings(item, _join(prefix, str(key))))
    elif isinstance(value, (list, tuple)):
        for i, item in enumerate(value):
            found.extend(walk_strings(item, _join(prefix, str(i))))
    elif isinstance(value, str):
        found.append((prefix, value))
    return found


def _join(prefix: str, part: str) -> str:
    return f"{prefix}.{part}" if prefix else part


def classify(content: BaseModel, source_text: str) -> list[FieldNote]:
    """Produce a provenance note for every string field in `content`."""
    index = SourceIndex(source_text)
    notes: list[FieldNote] = []
    for path, value in walk_strings(content):
        if not value.strip():
            notes.append(FieldNote(path=path, provenance=Provenance.MISSING))
            continue
        if index.contains(value):
            notes.append(
                FieldNote(
                    path=path,
                    provenance=Provenance.EXTRACTED,
                    value_preview=_preview(value),
                )
            )
            continue
        notes.append(
            FieldNote(
                path=path,
                provenance=Provenance.INFERRED,
                value_preview=_preview(value),
                reason=(
                    "Rephrased rather than copied — check it still reflects what you wrote."
                    if path.split(".")[-1] in PARAPHRASE_PATHS
                    else "This text does not appear in your document. Confirm or correct it."
                ),
            )
        )
    return notes


def _preview(value: str, limit: int = 120) -> str:
    collapsed = _SPACES.sub(" ", value).strip()
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1] + "…"
