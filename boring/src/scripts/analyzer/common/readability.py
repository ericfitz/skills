"""Readability scores via textstat.

Computed for the document overall and for the longest paragraphs (where
variance signals overload-pocket risk). Reported in the JSON output but
not used for scoring — readability formulas are descriptive only.
"""

from __future__ import annotations

from typing import Any

from .. import locator as loc_mod
from ..document import Document


def compute_readability(
    doc: Document, top_n_long_paragraphs: int = 5
) -> dict[str, Any]:
    """Compute document-level and per-long-paragraph readability scores."""
    import textstat  # type: ignore

    text = doc.extracted_text

    document_scores = {
        "flesch_reading_ease": _safe(lambda: textstat.flesch_reading_ease(text)),
        "flesch_kincaid_grade": _safe(lambda: textstat.flesch_kincaid_grade(text)),
        "gunning_fog": _safe(lambda: textstat.gunning_fog(text)),
        "smog_index": _safe(lambda: textstat.smog_index(text)),
        "dale_chall": _safe(lambda: textstat.dale_chall_readability_score(text)),
        "automated_readability_index": _safe(
            lambda: textstat.automated_readability_index(text)
        ),
    }

    # Per-paragraph: pick longest N paragraphs by word count
    paragraphs_with_lengths: list[tuple[Any, int]] = []
    for p in doc.paragraphs:
        word_count = len([w for w in p.text.split() if any(c.isalpha() for c in w)])
        paragraphs_with_lengths.append((p, word_count))

    paragraphs_with_lengths.sort(key=lambda pair: -pair[1])
    longest = paragraphs_with_lengths[:top_n_long_paragraphs]

    long_para_scores: list[dict[str, Any]] = []
    for p, word_count in longest:
        if word_count < 30:
            # readability formulas are unreliable on very short text
            continue
        long_para_scores.append(
            {
                "paragraph_index": p.index,
                "word_count": word_count,
                "flesch_reading_ease": _safe(
                    lambda t=p.text: textstat.flesch_reading_ease(t)
                ),
                "flesch_kincaid_grade": _safe(
                    lambda t=p.text: textstat.flesch_kincaid_grade(t)
                ),
                "locator": loc_mod.make_paragraph_locator(doc, p.index).to_dict(),
            }
        )

    return {
        "document": document_scores,
        "longest_paragraphs": long_para_scores,
    }


def _safe(fn: Any) -> float | None:
    """Run a textstat call and return its rounded float result, or None.

    textstat raises a variety of exceptions on degenerate inputs (empty
    text, no syllables, etc.). We treat any of those as "metric not
    computable" and return None — readability scores are descriptive,
    so a missing one shouldn't fail the run.
    """
    try:
        v = fn()
        if v is None:
            return None
        return round(float(v), 2)
    except (ZeroDivisionError, ValueError, IndexError, KeyError, AttributeError, TypeError):
        return None
