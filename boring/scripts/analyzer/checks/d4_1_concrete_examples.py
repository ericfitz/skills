"""D4.1 — No concrete examples.

Detects long stretches of pure abstraction. For each body paragraph, we
look for any of three concreteness signals:

1. Named entities (spaCy NER: PERSON, ORG, GPE, PRODUCT, EVENT, DATE,
   PERCENT, MONEY, QUANTITY, CARDINAL, ORDINAL, NORP, FAC, LOC, WORK_OF_ART)
2. Numbers, percentages, currency amounts (LIKE_NUM tokens or NER hits)
3. Example markers — phrases that introduce a concrete instance ("for
   example", "such as", "consider", "imagine", "e.g.")

A paragraph with none of these is "abstract". A run of ≥3 abstract body
paragraphs is the warn signal; ≥6 is severe. Plus a document-level check:
at least one example marker per N words.

Mechanical strength: medium. NER is decent but not perfect on technical
text; example-marker matching is high precision. The judgment of whether
a paragraph *needs* a concrete example (some genuinely don't) is left to
the LLM phase.

Outputs:
  - summary: max_paragraph_run_without_concreteness
  - measurements: per-paragraph concreteness signals, document-level marker
    count, words-per-marker
  - flags: each abstract-paragraph run over the warn threshold
"""
from __future__ import annotations

import re
from typing import Any

from .. import locator as loc_mod
from ..common.word_lists import EXAMPLE_MARKERS, find_phrase_matches
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

# spaCy NER labels we count as "concrete" — a real-world entity grounds prose.
_CONCRETE_NER_LABELS = {
    "PERSON", "ORG", "GPE", "LOC", "FAC", "PRODUCT", "EVENT", "WORK_OF_ART",
    "DATE", "TIME", "PERCENT", "MONEY", "QUANTITY", "CARDINAL", "ORDINAL", "NORP",
}

_HEADING_ONLY_RE = re.compile(r"^\s*#{1,6}\s+\S.*?\s*$")


class ConcreteExamplesCheck:
    code = "D4.1"
    name = "No concrete examples"
    axis = "surprise"

    def run(self, doc: Document, config: Any) -> Finding:
        # Genre profiles can disable this check entirely (e.g., status_update).
        if config.is_check_disabled(check_path="surprise.no_concrete_examples"):
            return Finding(
                code=self.code,
                name=self.name,
                axis=self.axis,
                checked=False,
                summary=None,
                measurements={"reason": "disabled by genre profile"},
                flags=[],
                notes=["Check disabled by genre profile."],
            )

        warn_run = config.get(
            "surprise.no_concrete_examples.warn_max_paragraphs_without_concreteness", 3
        )
        severe_run = config.get(
            "surprise.no_concrete_examples.severe_max_paragraphs_without_concreteness", 6
        )
        warn_words_per_marker = config.get(
            "surprise.no_concrete_examples.warn_word_count_per_example_marker_above", 500
        )
        severe_words_per_marker = config.get(
            "surprise.no_concrete_examples.severe_word_count_per_example_marker_above", 1500
        )

        text = doc.extracted_text
        spacy_doc = doc.spacy_doc
        word_count = doc.word_count or 1

        # Build a per-character map of NER concrete spans for fast lookup.
        ner_spans: list[tuple[int, int, str]] = []
        for ent in spacy_doc.ents:
            if ent.label_ in _CONCRETE_NER_LABELS:
                ner_spans.append((ent.start_char, ent.end_char, ent.label_))

        # Per-paragraph: count concreteness signals. Skip heading-only paragraphs.
        body_paragraphs: list[tuple[int, dict[str, int]]] = []
        # entries: (paragraph_index, {"ner": int, "numbers": int, "markers": int})
        for p in doc.paragraphs:
            if _HEADING_ONLY_RE.match(p.text.strip()):
                continue

            ner_count = sum(1 for s, e, _ in ner_spans if s >= p.char_start and e <= p.char_end)

            # Numbers via spaCy LIKE_NUM tokens within the paragraph.
            number_count = 0
            span = spacy_doc.char_span(p.char_start, p.char_end, alignment_mode="contract")
            if span is not None:
                number_count = sum(1 for tok in span if tok.like_num)

            marker_hits = find_phrase_matches(p.text, EXAMPLE_MARKERS)
            marker_count = len(marker_hits)

            body_paragraphs.append(
                (p.index, {"ner": ner_count, "numbers": number_count, "markers": marker_count})
            )

        # Walk body paragraphs and find runs where all three signals are zero.
        runs: list[dict[str, Any]] = []
        cur_run_start: int | None = None
        cur_run_len = 0
        for body_pos, (orig_p_idx, sig) in enumerate(body_paragraphs):
            is_abstract = sig["ner"] + sig["numbers"] + sig["markers"] == 0
            if is_abstract:
                if cur_run_start is None:
                    cur_run_start = body_pos
                cur_run_len += 1
            else:
                if cur_run_start is not None and cur_run_len >= 2:
                    runs.append({"start": cur_run_start, "length": cur_run_len})
                cur_run_start = None
                cur_run_len = 0
        if cur_run_start is not None and cur_run_len >= 2:
            runs.append({"start": cur_run_start, "length": cur_run_len})

        longest_run = max((r["length"] for r in runs), default=0)

        # Document-level: words per example marker.
        all_marker_hits = find_phrase_matches(text, EXAMPLE_MARKERS)
        marker_total = len(all_marker_hits)
        words_per_marker = (word_count / marker_total) if marker_total else float("inf")

        # Component scores.
        run_score = score_against_thresholds(
            longest_run, warn_run, severe_run, higher_is_worse=True
        )
        # Words-per-marker: higher (sparser) is worse. inf > any threshold.
        marker_score = score_against_thresholds(
            words_per_marker if words_per_marker != float("inf") else 1e18,
            warn_words_per_marker,
            severe_words_per_marker,
            higher_is_worse=True,
        )

        order = {"pass": 0, "info": 0, "warn": 1, "severe": 2}
        score = max((run_score, marker_score), key=lambda s: order[s])

        # Flags: each abstract-paragraph run at or over warn threshold.
        flags: list[Flag] = []
        flag_idx = 0
        for run in runs:
            if run["length"] < warn_run:
                continue
            flag_idx += 1
            severity = SEVERITY_SEVERE if run["length"] >= severe_run else SEVERITY_WARN
            start_p_idx = body_paragraphs[run["start"]][0]
            end_p_idx = body_paragraphs[run["start"] + run["length"] - 1][0]
            start_p = doc.paragraphs[start_p_idx]
            end_p = doc.paragraphs[end_p_idx]
            # Build a span locator covering the whole abstract stretch.
            flag_locator = loc_mod.make_span_locator(
                doc=doc,
                char_start=start_p.char_start,
                char_end=end_p.char_end,
            )
            flags.append(
                Flag(
                    flag_id=f"{self.code}-{flag_idx:03d}",
                    severity=severity,
                    message=(
                        f"Run of {run['length']} paragraphs with no "
                        f"entities, numbers, or example markers"
                    ),
                    locator=flag_locator,
                    evidence={
                        "abstract_paragraph_count": run["length"],
                        "first_paragraph_index": start_p_idx,
                        "last_paragraph_index": end_p_idx,
                    },
                )
            )

        rationale = (
            f"Longest run of paragraphs without concreteness signals: "
            f"{longest_run} (warn at {warn_run}, severe at {severe_run}). "
            f"{marker_total} example markers in {word_count} words "
            f"({words_per_marker:.0f} words per marker; warn above "
            f"{warn_words_per_marker}, severe above {severe_words_per_marker})."
        ) if words_per_marker != float("inf") else (
            f"Longest run of paragraphs without concreteness signals: "
            f"{longest_run} (warn at {warn_run}, severe at {severe_run}). "
            f"No example markers found in {word_count} words "
            f"(warn above {warn_words_per_marker} words/marker, "
            f"severe above {severe_words_per_marker})."
        )

        return Finding(
            code=self.code,
            name=self.name,
            axis=self.axis,
            checked=True,
            summary=Summary(
                metric_name="longest_abstract_paragraph_run",
                metric_value=longest_run,
                threshold_warn=warn_run,
                threshold_severe=severe_run,
                score=score,
                rationale=rationale,
            ),
            measurements={
                "body_paragraph_count": len(body_paragraphs),
                "longest_abstract_paragraph_run": longest_run,
                "abstract_runs_above_warn": sum(1 for r in runs if r["length"] >= warn_run),
                "example_marker_count": marker_total,
                "words_per_example_marker": (
                    None if words_per_marker == float("inf") else round(words_per_marker, 1)
                ),
                "per_paragraph_signals": [
                    {"paragraph_index": p_idx, **sig} for p_idx, sig in body_paragraphs
                ],
                "warn_max_paragraphs_without_concreteness": warn_run,
                "severe_max_paragraphs_without_concreteness": severe_run,
                "warn_word_count_per_example_marker_above": warn_words_per_marker,
                "severe_word_count_per_example_marker_above": severe_words_per_marker,
                "word_count": word_count,
            },
            flags=flags,
            notes=[],
        )


register_check(ConcreteExamplesCheck())
