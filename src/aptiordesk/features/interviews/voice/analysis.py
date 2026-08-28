"""Delivery analysis for spoken answers: pace, filler words, pauses.

Pure functions over a transcript and a duration — no audio, no models — so
this is cheap and fully testable. English filler list for the MVP; the
language is configurable so other lists can be added without changing
callers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Multi-word fillers must be checked before single words so "you know" is not
# counted as "know".
FILLER_PHRASES: dict[str, list[str]] = {
    "en": [
        "you know",
        "i mean",
        "sort of",
        "kind of",
        "or something",
        "or whatever",
        "um",
        "uh",
        "erm",
        "ah",
        "like",
        "basically",
        "actually",
        "literally",
        "honestly",
        "obviously",
        "just",
        "really",
        "stuff",
    ]
}

# Words that are only fillers as discourse markers are still counted; the UI
# presents them as "worth noticing", not errors.
_WORD = re.compile(r"[A-Za-z']+")

SLOW_WPM = 110
FAST_WPM = 170


@dataclass
class DeliveryStats:
    word_count: int = 0
    duration_s: float = 0.0
    words_per_minute: float | None = None
    filler_counts: dict[str, int] = field(default_factory=dict)
    filler_total: int = 0
    filler_rate_per_100: float = 0.0
    pace_comment: str = ""
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "word_count": self.word_count,
            "duration_s": round(self.duration_s, 1),
            "words_per_minute": round(self.words_per_minute, 1) if self.words_per_minute else None,
            "filler_counts": self.filler_counts,
            "filler_total": self.filler_total,
            "filler_rate_per_100": round(self.filler_rate_per_100, 1),
            "pace_comment": self.pace_comment,
            "notes": self.notes,
        }


def count_words(text: str) -> int:
    return len(_WORD.findall(text or ""))


def count_fillers(text: str, language: str = "en") -> dict[str, int]:
    """Count filler phrases. Longer phrases are matched first and removed so
    their component words are not double-counted."""
    remaining = (text or "").lower()
    counts: dict[str, int] = {}
    for phrase in sorted(FILLER_PHRASES.get(language, []), key=len, reverse=True):
        pattern = re.compile(rf"\b{re.escape(phrase)}\b")
        found = pattern.findall(remaining)
        if found:
            counts[phrase] = len(found)
            remaining = pattern.sub(" ", remaining)
    return counts


def analyze_delivery(
    text: str, duration_s: float | None = None, language: str = "en"
) -> DeliveryStats:
    stats = DeliveryStats(word_count=count_words(text), duration_s=duration_s or 0.0)
    stats.filler_counts = count_fillers(text, language)
    stats.filler_total = sum(stats.filler_counts.values())
    if stats.word_count:
        stats.filler_rate_per_100 = stats.filler_total / stats.word_count * 100

    if duration_s and duration_s > 0 and stats.word_count:
        stats.words_per_minute = stats.word_count / (duration_s / 60)
        if stats.words_per_minute < SLOW_WPM:
            stats.pace_comment = (
                f"{stats.words_per_minute:.0f} words/min — slower than a typical "
                "interview pace; consider tightening pauses."
            )
        elif stats.words_per_minute > FAST_WPM:
            stats.pace_comment = (
                f"{stats.words_per_minute:.0f} words/min — quite fast; slowing down "
                "helps the interviewer follow you."
            )
        else:
            stats.pace_comment = f"{stats.words_per_minute:.0f} words/min — a comfortable pace."

    if stats.filler_rate_per_100 > 5:
        top = ", ".join(
            f"“{word}” ×{count}"
            for word, count in sorted(
                stats.filler_counts.items(), key=lambda kv: kv[1], reverse=True
            )[:3]
        )
        stats.notes.append(f"Filler words are frequent ({stats.filler_total} total): {top}.")
    if duration_s:
        if duration_s < 30 and stats.word_count < 60:
            stats.notes.append(
                "Very short answer — most interview answers benefit from 60-120 seconds."
            )
        elif duration_s > 180:
            stats.notes.append(
                "Over three minutes — interviewers usually prefer answers under two."
            )
    return stats
