"""D2.7 — Hedging clutter.

Counts hedge words/phrases. Flags sentences that stack two or more hedges,
since one hedge is usually fine but stacked hedges almost always dilute
the claim past usefulness.

Mechanical strength: high. Curated phrase/word lookup; the *appropriateness*
of any single hedge is left to the LLM phase.

Outputs:
  - summary: hedges_per_100_sentences
  - measurements: total hedge count, breakdown by word vs phrase, stacked
    sentence count
  - flags: sentences with stacked hedges (>= stack_minimum_count)
"""
from __future__ import annotations

from typing import Any

from .. import locator as loc_mod
from ..common.word_lists import (
    HEDGE_PHRASES,
    HEDGE_WORDS,
    find_phrase_matches,
)
from ..document import Document
from .base import (
    Finding,
    Flag,
    Summary,
    SEVERITY_SEVERE,
    SEVERITY_WARN,
    score_against_thresholds,
)
from . import register_check


class HedgingCheck:
    code = "D2.7"
    name = "Hedging clutter"
    axis = "density"

    def run(self, doc: Document, config: Any) -> Finding:
        warn = config.get("density.hedging.warn_per_100_sentences", 30)
        severe = config.get("density.hedging.severe_per_100_sentences", 60)
        stack_min = config.get("density.hedging.stack_minimum_count", 2)

        text = doc.extracted_text

        word_hits = find_phrase_matches(text, HEDGE_WORDS)
        phrase_hits = find_phrase_matches(text, HEDGE_PHRASES)

        # Phrase hits subsume any word hits that fall inside their span.
        phrase_spans = [(s, e) for s, e, _ in phrase_hits]
        word_hits = [(s, e, t) for s, e, t in word_hits if not _within_any(s, e, phrase_spans)]

        all_hits = sorted(word_hits + phrase_hits, key=lambda h: h[0])

        # Group by sentence
        per_sentence: dict[int, list[tuple[int, int, str]]] = {}
        for s, e, t in all_hits:
            sent_idx = self._sentence_index_at(doc, s)
            if sent_idx is None:
                continue
            per_sentence.setdefault(sent_idx, []).append((s, e, t))

        total_sentences = len(doc.sentences) or 1
        total_hedges = len(all_hits)
        rate = (total_hedges / total_sentences) * 100

        stacked_sentences = [
            (idx, hits) for idx, hits in per_sentence.items() if len(hits) >= stack_min
        ]
        stacked_count = len(stacked_sentences)

        score = score_against_thresholds(rate, warn, severe, higher_is_worse=True)

        # If we have stacked sentences but the document overall is "pass",
        # leave score as pass — the rate is the document signal — but still
        # emit the stacked-sentence flags as warn.
        flags: list[Flag] = []
        for idx, (sent_idx, hits) in enumerate(sorted(stacked_sentences), start=1):
            sent_ref = doc.sentences[sent_idx]
            severity = SEVERITY_SEVERE if score == SEVERITY_SEVERE else SEVERITY_WARN
            flag_locator = loc_mod.make_span_locator(
                doc=doc,
                char_start=sent_ref.char_start,
                char_end=sent_ref.char_end,
                sentence_index_start=sent_ref.index,
                sentence_index_end=sent_ref.index,
            )
            flags.append(
                Flag(
                    flag_id=f"{self.code}-{idx:03d}",
                    severity=severity,
                    message=f"Stacked hedging ({len(hits)} hedges in one sentence)",
                    locator=flag_locator,
                    evidence={
                        "hedge_count": len(hits),
                        "hedges": [t for _, _, t in hits],
                    },
                )
            )

        rationale = (
            f"{total_hedges} hedges across {total_sentences} sentences "
            f"({rate:.1f} per 100 sentences; warn at {warn}, severe at {severe}). "
            f"{stacked_count} sentences stack {stack_min}+ hedges."
        )

        return Finding(
            code=self.code,
            name=self.name,
            axis=self.axis,
            checked=True,
            summary=Summary(
                metric_name="hedges_per_100_sentences",
                metric_value=round(rate, 2),
                threshold_warn=warn,
                threshold_severe=severe,
                score=score,
                rationale=rationale,
            ),
            measurements={
                "total_hedges": total_hedges,
                "hedge_word_count": len(word_hits),
                "hedge_phrase_count": len(phrase_hits),
                "stacked_hedge_sentences": stacked_count,
                "hedges_per_100_sentences": round(rate, 4),
                "total_sentences": total_sentences,
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


def _within_any(start: int, end: int, spans: list[tuple[int, int]]) -> bool:
    for ps, pe in spans:
        if start >= ps and end <= pe:
            return True
    return False


register_check(HedgingCheck())
