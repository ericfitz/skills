"""D4.4 — No specificity.

Detects vague quantifiers, intensifiers, and modifiers — words that
*promise* specificity without delivering it. "Significant improvements"
tells the reader nothing; "47% reduction" tells them everything.
"Various stakeholders" should usually be "the security team and finance".

Mechanical strength: high. Curated phrase lookup; the judgment about
whether any single occurrence is "earned" by context (e.g., "various"
is fine when an exhaustive list would be tedious) is left to the LLM
phase.

Outputs:
  - summary: vague_quantifier_density_per_1000_words
  - measurements: counts by category (quantifier / intensifier / modifier)
  - flags: every match with locator and matched phrase
"""
from __future__ import annotations

from typing import Any

from .. import locator as loc_mod
from ..common.word_lists import VAGUE_TERMS_BY_CATEGORY, find_phrase_matches
from ..document import Document
from . import register_check
from .base import (
    SEVERITY_INFO,
    SEVERITY_SEVERE,
    SEVERITY_WARN,
    Finding,
    Flag,
    Summary,
    score_against_thresholds,
)


class SpecificityCheck:
    code = "D4.4"
    name = "No specificity"
    axis = "surprise"

    def run(self, doc: Document, config: Any) -> Finding:
        warn = config.get("surprise.no_specificity.warn_per_1000_words", 6.0)
        severe = config.get("surprise.no_specificity.severe_per_1000_words", 12.0)

        text = doc.extracted_text
        word_count = doc.word_count or 1

        # Collect matches per category, then merge & dedupe.
        per_category: dict[str, list[tuple[int, int, str]]] = {}
        all_hits: list[tuple[int, int, str, str]] = []  # (start, end, text, category)
        for category, phrases in VAGUE_TERMS_BY_CATEGORY.items():
            hits = find_phrase_matches(text, phrases)
            per_category[category] = hits
            for s, e, t in hits:
                all_hits.append((s, e, t, category))

        # Sort by position; drop overlaps (longer / earlier wins).
        all_hits.sort(key=lambda h: (h[0], -(h[1] - h[0])))
        deduped: list[tuple[int, int, str, str]] = []
        last_end = -1
        for s, e, t, cat in all_hits:
            if s < last_end:
                continue
            deduped.append((s, e, t, cat))
            last_end = e

        total_count = len(deduped)
        rate = (total_count / word_count) * 1000

        score = score_against_thresholds(rate, warn, severe, higher_is_worse=True)

        flags: list[Flag] = []
        for idx, (s, e, t, cat) in enumerate(deduped, start=1):
            sent_idx = self._sentence_index_at(doc, s)
            sent = doc.sentences[sent_idx] if sent_idx is not None else None
            # Per-flag severity follows the document score:
            #   doc severe -> all flags severe
            #   doc warn   -> all flags warn
            #   doc pass   -> info (still surfaced, low priority)
            if score == SEVERITY_SEVERE:
                severity = SEVERITY_SEVERE
            elif score == SEVERITY_WARN:
                severity = SEVERITY_WARN
            else:
                severity = SEVERITY_INFO
            flag_locator = loc_mod.make_span_locator(
                doc=doc,
                char_start=s,
                char_end=e,
                sentence_index_start=sent.index if sent else None,
                sentence_index_end=sent.index if sent else None,
            )
            flags.append(
                Flag(
                    flag_id=f"{self.code}-{idx:03d}",
                    severity=severity,
                    message=f"Vague {cat}: '{t}'",
                    locator=flag_locator,
                    evidence={"phrase": t, "category": cat},
                )
            )

        # Counts per category (post-dedup so the numbers add up to total_count).
        deduped_counts: dict[str, int] = {cat: 0 for cat in VAGUE_TERMS_BY_CATEGORY}
        for _, _, _, cat in deduped:
            deduped_counts[cat] = deduped_counts.get(cat, 0) + 1

        rationale = (
            f"{total_count} vague terms in {word_count} words "
            f"({rate:.1f} per 1000 words; warn at {warn}, severe at {severe}). "
            f"By category: " + ", ".join(f"{c}={deduped_counts[c]}" for c in deduped_counts) + "."
        )

        return Finding(
            code=self.code,
            name=self.name,
            axis=self.axis,
            checked=True,
            summary=Summary(
                metric_name="vague_terms_per_1000_words",
                metric_value=round(rate, 2),
                threshold_warn=warn,
                threshold_severe=severe,
                score=score,
                rationale=rationale,
            ),
            measurements={
                "total_matches": total_count,
                "matches_by_category": deduped_counts,
                "vague_terms_per_1000_words": round(rate, 4),
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


register_check(SpecificityCheck())
