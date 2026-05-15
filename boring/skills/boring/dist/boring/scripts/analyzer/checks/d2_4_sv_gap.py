"""D2.4 — Subject-Verb Gap.

Detects sentences where the grammatical subject is far from its main verb.
Long S-V gaps tax working memory; the reader has to hold the subject in
mind across intervening modifiers before learning what the subject does.

Mechanical strength: high. spaCy's dependency parser exposes nsubj and the
governing verb directly. The metric is just token distance.

Outputs:
  - summary: pct_sentences_over_warn_threshold
  - measurements: distribution of S-V gaps, mean, max
  - flags: every sentence above the warn threshold
"""
from __future__ import annotations

from typing import Any

from .. import locator as loc_mod
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


class SubjectVerbGapCheck:
    code = "D2.4"
    name = "Subject-verb separation"
    axis = "density"

    def run(self, doc: Document, config: Any) -> Finding:
        warn = config.get("density.subject_verb_gap.warn_token_distance", 7)
        severe = config.get("density.subject_verb_gap.severe_token_distance", 12)
        warn_pct = config.get("density.subject_verb_gap.warn_pct_sentences_over", 0.15)
        severe_pct = config.get("density.subject_verb_gap.severe_pct_sentences_over", 0.30)

        # Per-sentence S-V gaps. None when no subject-verb pair found.
        per_sentence_gaps: list[int | None] = []
        flags: list[Flag] = []

        for sent_ref in doc.sentences:
            # Get the spaCy span for this sentence
            spacy_doc = doc.spacy_doc
            span = spacy_doc.char_span(sent_ref.char_start, sent_ref.char_end, alignment_mode="contract")
            if span is None:
                per_sentence_gaps.append(None)
                continue

            # Find subject and its head verb
            gap = self._compute_gap(span)
            per_sentence_gaps.append(gap)

            if gap is not None and gap >= warn:
                severity = SEVERITY_SEVERE if gap >= severe else SEVERITY_WARN
                flag_locator = loc_mod.make_span_locator(
                    doc=doc,
                    char_start=sent_ref.char_start,
                    char_end=sent_ref.char_end,
                    sentence_index_start=sent_ref.index,
                    sentence_index_end=sent_ref.index,
                )
                flags.append(
                    Flag(
                        flag_id=f"{self.code}-{len(flags) + 1:03d}",
                        severity=severity,
                        message=f"Subject-verb gap of {gap} tokens",
                        locator=flag_locator,
                        evidence={"subject_verb_gap_tokens": gap},
                    )
                )

        # Aggregate stats (only over sentences where we found a pair)
        valid_gaps = [g for g in per_sentence_gaps if g is not None]
        total_with_pair = len(valid_gaps)
        over_warn = sum(1 for g in valid_gaps if g >= warn)
        pct_over = over_warn / total_with_pair if total_with_pair else 0.0

        mean_gap = sum(valid_gaps) / total_with_pair if total_with_pair else 0.0
        max_gap = max(valid_gaps) if valid_gaps else 0

        score = score_against_thresholds(pct_over, warn_pct, severe_pct, higher_is_worse=True)
        rationale = (
            f"{over_warn} of {total_with_pair} sentences ({pct_over:.0%}) have a "
            f"subject-verb gap >= {warn} tokens. Threshold for severe is "
            f"{severe_pct:.0%}, for warn is {warn_pct:.0%}."
        )

        return Finding(
            code=self.code,
            name=self.name,
            axis=self.axis,
            checked=True,
            summary=Summary(
                metric_name="pct_sentences_over_warn_threshold",
                metric_value=round(pct_over, 4),
                threshold_warn=warn_pct,
                threshold_severe=severe_pct,
                score=score,
                rationale=rationale,
            ),
            measurements={
                "total_sentences_evaluated": total_with_pair,
                "sentences_over_warn_threshold": over_warn,
                "mean_subject_verb_gap_tokens": round(mean_gap, 2),
                "max_subject_verb_gap_tokens": max_gap,
                "warn_token_distance": warn,
                "severe_token_distance": severe,
            },
            flags=flags,
            notes=[],
        )

    @staticmethod
    def _compute_gap(span: Any) -> int | None:
        """Return tokens between (the rightmost token of) the subject and the verb.

        Returns None when no nsubj/nsubjpass + ROOT verb pair is found.
        """
        subj_token = None
        verb_token = None
        for tok in span:
            if tok.dep_ in ("nsubj", "nsubjpass") and tok.head.pos_ in ("VERB", "AUX"):
                subj_token = tok
                verb_token = tok.head
                break
        if subj_token is None or verb_token is None:
            return None
        # If verb is to the LEFT of subject (e.g. inverted), report 0
        if verb_token.i <= subj_token.i:
            return 0
        # Distance = tokens strictly between them (not counting subject or verb)
        return verb_token.i - subj_token.i - 1


register_check(SubjectVerbGapCheck())
