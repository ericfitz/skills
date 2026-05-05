"""D2.1 — Padding / wordiness.

Detects wordy phrases via proselint plus a small supplemental list. The
core engine is proselint's redundancy / needless_variants / cliches /
misc checks (Garner, Strunk, Pinker patterns). proselint's hedging and
weasel_words checks are disabled in our wrapper because D2.7 and D4.4
own those signals.

Mechanical strength: high. The judgment about whether a flagged phrase
is appropriate in context is left to the LLM phase.

Outputs:
  - summary: wordy_phrases_per_1000_words
  - measurements: counts by proselint category, plus our own counts
  - flags: every wordy-phrase match with locator
"""
from __future__ import annotations

from typing import Any

from .. import locator as loc_mod
from ..common.proselint_wrap import lint_document
from ..common.word_lists import find_phrase_matches
from ..document import Document
from . import register_check
from .base import (
    SEVERITY_SEVERE,
    SEVERITY_WARN,
    Finding,
    Flag,
    Summary,
    score_against_thresholds,
)

# proselint top-level categories that we count as "padding/wordiness".
# Skipped entirely (handled in our wrapper): hedging, weasel_words.
# Also excluded here: typography, spelling, dates_times — not padding.
PADDING_CATEGORIES: tuple[str, ...] = (
    "redundancy",
    "needless_variants",
    "cliches",
    "misc",
    "nonwords",
    "lexical_illusions",
    "skunked_terms",
    "industrial_language",
    "archaism",
    "oxymorons",
)

# Supplemental wordy phrases not reliably caught by proselint. Kept short
# on purpose — proselint covers the long tail.
SUPPLEMENTAL_WORDY: tuple[str, ...] = (
    "due to the fact that",
    "in order to",
    "in order for",
    "for the purpose of",
    "with the intention of",
    "with the goal of",
    "for the reason that",
    "owing to the fact that",
    "in spite of the fact that",
    "in the event that",
    "in the event of",
    "at this point in time",
    "at the present time",
    "at this moment in time",
    "in close proximity to",
    "in the vicinity of",
    "a large number of",
    "a small number of",
    "a great deal of",
    "a great many",
    "the majority of",
    "the minority of",
    "a substantial portion of",
    "a significant proportion of",
    "in the case of",
    "in many instances",
    "in most instances",
    "on a regular basis",
    "on a daily basis",
    "with regard to",
    "with regards to",
    "in regard to",
    "in regards to",
    "with respect to",
    "in respect of",
    "in connection with",
    "in conjunction with",
    "in collaboration with",
    "in cooperation with",
    "by virtue of",
    "by means of",
    "for all intents and purposes",
    "in the final analysis",
    "in the last analysis",
    "as a matter of fact",
    "the fact of the matter is",
    "the fact that",
    "in light of the fact that",
    "given the fact that",
    "despite the fact that",
    "regardless of the fact that",
    "until such time as",
    "subsequent to",
    "prior to",
    "previous to",
)


class PaddingCheck:
    code = "D2.1"
    name = "Padding / wordiness"
    axis = "density"

    def run(self, doc: Document, config: Any) -> Finding:
        warn = config.get("density.padding.warn_phrases_per_1000_words", 4.0)
        severe = config.get("density.padding.severe_phrases_per_1000_words", 8.0)

        text = doc.extracted_text
        word_count = doc.word_count or 1

        # proselint pass (cached by id(doc))
        prose_hits = [
            h for h in lint_document(doc) if h.category in PADDING_CATEGORIES
        ]

        # Supplemental matches
        supplemental = find_phrase_matches(text, SUPPLEMENTAL_WORDY)
        # Drop supplemental hits that overlap proselint hits (proselint wins
        # because it has a richer message string).
        prose_spans = [(h.char_start, h.char_end) for h in prose_hits]
        supplemental = [
            (s, e, t) for s, e, t in supplemental if not _overlaps_any(s, e, prose_spans)
        ]

        # Count by proselint category
        by_category: dict[str, int] = {}
        for h in prose_hits:
            by_category[h.category] = by_category.get(h.category, 0) + 1
        by_category["supplemental"] = len(supplemental)

        total_count = len(prose_hits) + len(supplemental)
        rate = (total_count / word_count) * 1000

        score = score_against_thresholds(rate, warn, severe, higher_is_worse=True)

        flags: list[Flag] = []
        flag_idx = 0
        for h in prose_hits:
            flag_idx += 1
            sent_idx = self._sentence_index_at(doc, h.char_start)
            sent = doc.sentences[sent_idx] if sent_idx is not None else None
            severity = SEVERITY_SEVERE if score == SEVERITY_SEVERE else SEVERITY_WARN
            flag_locator = loc_mod.make_span_locator(
                doc=doc,
                char_start=h.char_start,
                char_end=h.char_end,
                sentence_index_start=sent.index if sent else None,
                sentence_index_end=sent.index if sent else None,
            )
            flags.append(
                Flag(
                    flag_id=f"{self.code}-{flag_idx:03d}",
                    severity=severity,
                    message=h.message,
                    locator=flag_locator,
                    evidence={
                        "source": "proselint",
                        "check_path": h.check_path,
                        # Stringify replacements: proselint sometimes returns a
                        # compiled Pattern or other non-JSON-serializable value.
                        "replacements": (
                            None if h.replacements is None else str(h.replacements)
                        ),
                    },
                )
            )
        for s, e, t in supplemental:
            flag_idx += 1
            sent_idx = self._sentence_index_at(doc, s)
            sent = doc.sentences[sent_idx] if sent_idx is not None else None
            severity = SEVERITY_SEVERE if score == SEVERITY_SEVERE else SEVERITY_WARN
            flag_locator = loc_mod.make_span_locator(
                doc=doc,
                char_start=s,
                char_end=e,
                sentence_index_start=sent.index if sent else None,
                sentence_index_end=sent.index if sent else None,
            )
            flags.append(
                Flag(
                    flag_id=f"{self.code}-{flag_idx:03d}",
                    severity=severity,
                    message=f"Wordy phrase: '{t}'",
                    locator=flag_locator,
                    evidence={
                        "source": "supplemental",
                        "phrase": t,
                    },
                )
            )

        # Sort flags by char position
        flags.sort(key=lambda f: f.locator.char_start)
        # Re-number after sort for stable display ordering
        for i, f in enumerate(flags, start=1):
            f.flag_id = f"{self.code}-{i:03d}"

        rationale = (
            f"{total_count} wordy/padding phrases in {word_count} words "
            f"({rate:.1f} per 1000 words; warn at {warn}, severe at {severe}). "
            f"Sources: {len(prose_hits)} proselint, {len(supplemental)} supplemental."
        )

        return Finding(
            code=self.code,
            name=self.name,
            axis=self.axis,
            checked=True,
            summary=Summary(
                metric_name="wordy_phrases_per_1000_words",
                metric_value=round(rate, 2),
                threshold_warn=warn,
                threshold_severe=severe,
                score=score,
                rationale=rationale,
            ),
            measurements={
                "total_matches": total_count,
                "matches_by_category": by_category,
                "wordy_phrases_per_1000_words": round(rate, 4),
                "word_count": word_count,
            },
            flags=flags,
            notes=[],
        )

    @staticmethod
    def _sentence_index_at(doc: Document, char_offset: int) -> int | None:
        for s in doc.sentences:
            if s.char_start <= char_offset < s.char_end:
                return s.index
        return None


def _overlaps_any(start: int, end: int, spans: list[tuple[int, int]]) -> bool:
    for ps, pe in spans:
        if start < pe and end > ps:
            return True
    return False


register_check(PaddingCheck())
