"""D2.8 — Throat-clearing.

Detects phrases that exist only to introduce other content. Most damaging
at the start of a sentence or paragraph (the reader has to wade through
filler before reaching the real content); somewhat damaging mid-sentence.

Mechanical strength: high. The matching is curated phrase lookup; the
judgment about whether a given phrase is "earned" by context is left to
the LLM phase.

Outputs:
  - summary: throat_clearing_phrases_per_1000_words
  - measurements: counts by position (sentence-opener / paragraph-opener / mid)
  - flags: every match with locator and matched phrase
"""
from __future__ import annotations

from typing import Any

from .. import locator as loc_mod
from ..common.word_lists import (
    THROAT_CLEARING_OPENERS,
    find_phrase_matches,
    find_phrase_matches_at_starts,
)
from ..document import Document
from .base import (
    Finding,
    Flag,
    Summary,
    SEVERITY_INFO,
    SEVERITY_SEVERE,
    SEVERITY_WARN,
    score_against_thresholds,
)
from . import register_check


class ThroatClearingCheck:
    code = "D2.8"
    name = "Throat-clearing"
    axis = "density"

    def run(self, doc: Document, config: Any) -> Finding:
        warn = config.get("density.throat_clearing.warn_phrases_per_1000_words", 2.0)
        severe = config.get("density.throat_clearing.severe_phrases_per_1000_words", 5.0)
        flag_section_openers = config.get("density.throat_clearing.flag_section_openers", True)

        text = doc.extracted_text
        word_count = doc.word_count or 1

        # All matches, anywhere in the document.
        all_matches = find_phrase_matches(text, THROAT_CLEARING_OPENERS)

        # Classify each match by position relative to its sentence and paragraph.
        sentence_starts = {s.char_start for s in doc.sentences}
        paragraph_starts = {p.char_start for p in doc.paragraphs}
        # Allow a small fudge: a phrase that starts within ~6 chars of a
        # sentence/paragraph start (after whitespace and any markdown heading
        # prefix) counts as an opener.
        sentence_opener_anchors = {
            m[3] for m in find_phrase_matches_at_starts(
                text, THROAT_CLEARING_OPENERS, sentence_starts
            )
        }
        paragraph_opener_anchors = {
            m[3] for m in find_phrase_matches_at_starts(
                text, THROAT_CLEARING_OPENERS, paragraph_starts
            )
        }

        sentence_opener_count = 0
        paragraph_opener_count = 0
        mid_sentence_count = 0
        flags: list[Flag] = []

        for idx, (c_start, c_end, phrase) in enumerate(all_matches, start=1):
            sent_idx = self._sentence_index_at(doc, c_start)
            sent_ref = doc.sentences[sent_idx] if sent_idx is not None else None

            # Position classification: paragraph opener > sentence opener > mid
            position = "mid_sentence"
            is_para_opener = sent_ref is not None and sent_ref.char_start in paragraph_opener_anchors and self._is_first_match_for_anchor(c_start, sent_ref.char_start, all_matches)
            is_sent_opener = sent_ref is not None and sent_ref.char_start in sentence_opener_anchors and self._is_first_match_for_anchor(c_start, sent_ref.char_start, all_matches)
            if is_para_opener:
                position = "paragraph_opener"
                paragraph_opener_count += 1
            elif is_sent_opener:
                position = "sentence_opener"
                sentence_opener_count += 1
            else:
                mid_sentence_count += 1

            # Severity: openers always at WARN; mid-sentence at INFO unless
            # the document-wide rate is at warn/severe (promoted below).
            severity = SEVERITY_INFO if position == "mid_sentence" else SEVERITY_WARN

            flag_locator = loc_mod.make_span_locator(
                doc=doc,
                char_start=c_start,
                char_end=c_end,
                sentence_index_start=sent_ref.index if sent_ref else None,
                sentence_index_end=sent_ref.index if sent_ref else None,
            )
            flags.append(
                Flag(
                    flag_id=f"{self.code}-{idx:03d}",
                    severity=severity,
                    message=f"Throat-clearing phrase ({position.replace('_', ' ')})",
                    locator=flag_locator,
                    evidence={
                        "phrase": phrase,
                        "position": position,
                    },
                )
            )

        total_count = len(all_matches)
        rate = (total_count / word_count) * 1000

        # Document-level severity: based on rate. If section/paragraph-opener
        # flagging is enabled and we have any opener hits, escalate from pass
        # to at least warn even when the rate is low.
        score = score_against_thresholds(rate, warn, severe, higher_is_worse=True)
        if score == "pass" and flag_section_openers and paragraph_opener_count > 0:
            score = SEVERITY_WARN

        # Promote flag severities based on document-wide score:
        #   doc severe -> all flags severe
        #   doc warn   -> mid-sentence INFO -> WARN
        if score == SEVERITY_SEVERE:
            for f in flags:
                f.severity = SEVERITY_SEVERE
        elif score == SEVERITY_WARN:
            for f in flags:
                if f.severity == SEVERITY_INFO:
                    f.severity = SEVERITY_WARN

        rationale = (
            f"{total_count} throat-clearing phrases in {word_count} words "
            f"({rate:.1f} per 1000 words; warn at {warn}, severe at {severe}). "
            f"Of those, {paragraph_opener_count} open paragraphs, "
            f"{sentence_opener_count} open sentences, "
            f"{mid_sentence_count} are mid-sentence."
        )

        return Finding(
            code=self.code,
            name=self.name,
            axis=self.axis,
            checked=True,
            summary=Summary(
                metric_name="throat_clearing_phrases_per_1000_words",
                metric_value=round(rate, 2),
                threshold_warn=warn,
                threshold_severe=severe,
                score=score,
                rationale=rationale,
            ),
            measurements={
                "total_matches": total_count,
                "paragraph_opener_count": paragraph_opener_count,
                "sentence_opener_count": sentence_opener_count,
                "mid_sentence_count": mid_sentence_count,
                "throat_clearing_per_1000_words": round(rate, 4),
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

    @staticmethod
    def _is_first_match_for_anchor(
        match_start: int,
        anchor: int,
        all_matches: list[tuple[int, int, str]],
    ) -> bool:
        """True if `match_start` is the earliest match within ~30 chars after the anchor."""
        # We only count an opener once per sentence; the match closest to the
        # anchor wins. Compute the earliest match start within a small window.
        candidates = [c for c, _, _ in all_matches if anchor <= c < anchor + 80]
        return bool(candidates) and match_start == min(candidates)


register_check(ThroatClearingCheck())
