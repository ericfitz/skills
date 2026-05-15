"""D1.6 — Topic-position drift.

Detects two related Gopen-and-Swan failures:

1. **Expletive subjects** — "It is...", "There are...", "It was found
   that...". These constructions waste the topic position (the start of
   the sentence, where readers expect old/familiar information). Some
   occurrences are unavoidable; many in a row signal a writer who's lost
   the thread.

2. **Subject continuity within paragraphs** — between consecutive
   sentences in the same paragraph, does the subject of N+1 link back
   to the content of N? Low continuity means the paragraph is
   topic-hopping.

Continuity scoring is a soft proxy: for each adjacent sentence pair in
a paragraph, the second sentence's subject is "continuous" if its lemma
is (a) a pronoun, (b) one of the lemmas in the previous sentence, or
(c) the previous sentence's subject. Otherwise it's "drift" (score 0).

Mechanical strength: high for the expletive ratio (clean spaCy dep
detection); medium for the continuity score (the proxy is rough — this
metric needs corpus calibration most of all).

Outputs:
  - summary: expletive_subject_ratio
  - measurements: per-sentence subjects, expletive count, per-paragraph
    continuity scores
  - flags: sentences with expletive subjects; paragraphs with low
    continuity
"""
from __future__ import annotations

from typing import Any

from .. import locator as loc_mod
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


def _is_expletive_subject(sent: Any) -> bool:
    """True if the sentence has an expletive subject ('it', 'there', 'this'
    in the topic position with no real referent)."""
    for tok in sent:
        if tok.dep_ == "expl":
            return True
        if tok.dep_ in ("nsubj", "nsubjpass") and tok.lemma_.lower() == "it":
            # Check if "it" is a pronominal subject of a copula or passive
            # ("It is important that...", "It was determined that...")
            head = tok.head
            if head is not None and head.lemma_.lower() in ("be", "appear", "seem"):
                return True
        # Also catch "There are X" / "There were Y" via expl dep, already above.
    return False


def _content_lemmas(sent: Any) -> set[str]:
    """Lower-cased content-word lemmas in a sentence (NOUN/PROPN/VERB/ADJ)."""
    return {
        tok.lemma_.lower()
        for tok in sent
        if tok.is_alpha and tok.pos_ in ("NOUN", "PROPN", "VERB", "ADJ")
    }


def _subject_lemma(sent: Any) -> str | None:
    """Return the lemma of the sentence's grammatical subject, or None."""
    for tok in sent:
        if tok.dep_ in ("nsubj", "nsubjpass"):
            return tok.lemma_.lower()
    return None


def _is_pronoun(lemma: str | None, sent: Any) -> bool:
    if lemma is None:
        return False
    for tok in sent:
        if tok.dep_ in ("nsubj", "nsubjpass") and tok.pos_ == "PRON":
            return True
    return False


class TopicDriftCheck:
    code = "D1.6"
    name = "Topic-position drift"
    axis = "direction"

    def run(self, doc: Document, config: Any) -> Finding:
        warn_expl = config.get("direction.topic_position_drift.warn_expletive_subject_ratio", 0.10)
        severe_expl = config.get("direction.topic_position_drift.severe_expletive_subject_ratio", 0.20)
        warn_cont = config.get("direction.topic_position_drift.warn_mean_continuity_below", 0.40)
        severe_cont = config.get("direction.topic_position_drift.severe_mean_continuity_below", 0.25)

        spacy_doc = doc.spacy_doc

        # Pass 1: expletive subjects
        expletive_sentence_indices: list[int] = []
        for sent_ref in doc.sentences:
            span = spacy_doc.char_span(
                sent_ref.char_start, sent_ref.char_end, alignment_mode="contract"
            )
            if span is None:
                continue
            if _is_expletive_subject(span):
                expletive_sentence_indices.append(sent_ref.index)

        total_sentences = len(doc.sentences) or 1
        expletive_count = len(expletive_sentence_indices)
        expletive_ratio = expletive_count / total_sentences

        # Pass 2: per-paragraph subject continuity
        paragraphs_with_pairs: list[tuple[int, float, int]] = []
        # entries: (paragraph_index, mean_continuity, pair_count)
        for p in doc.paragraphs:
            sents_in_p = [s for s in doc.sentences if s.paragraph_index == p.index]
            if len(sents_in_p) < 2:
                continue
            scores: list[float] = []
            for prev, curr in zip(sents_in_p, sents_in_p[1:]):
                prev_span = spacy_doc.char_span(
                    prev.char_start, prev.char_end, alignment_mode="contract"
                )
                curr_span = spacy_doc.char_span(
                    curr.char_start, curr.char_end, alignment_mode="contract"
                )
                if prev_span is None or curr_span is None:
                    continue
                prev_lemmas = _content_lemmas(prev_span)
                curr_subj = _subject_lemma(curr_span)
                if curr_subj is None:
                    # No detectable subject — neutral, skip
                    continue
                if _is_pronoun(curr_subj, curr_span):
                    scores.append(1.0)
                elif curr_subj in prev_lemmas:
                    scores.append(1.0)
                else:
                    scores.append(0.0)
            if scores:
                mean_c = sum(scores) / len(scores)
                paragraphs_with_pairs.append((p.index, mean_c, len(scores)))

        # Document-level mean continuity (weighted by pair count)
        if paragraphs_with_pairs:
            total_pairs = sum(n for _, _, n in paragraphs_with_pairs)
            mean_continuity = (
                sum(mc * n for _, mc, n in paragraphs_with_pairs) / total_pairs
            )
        else:
            mean_continuity = 1.0  # no pairs to evaluate; assume no drift

        # Component scores
        expl_score = score_against_thresholds(
            expletive_ratio, warn_expl, severe_expl, higher_is_worse=True
        )
        cont_score = score_against_thresholds(
            mean_continuity, warn_cont, severe_cont, higher_is_worse=False
        )
        order = {"pass": 0, "info": 0, "warn": 1, "severe": 2}
        score = max((expl_score, cont_score), key=lambda s: order[s])

        # Flags
        flags: list[Flag] = []
        flag_idx = 0
        # Expletive-subject sentences
        for sent_idx in expletive_sentence_indices:
            flag_idx += 1
            sent_ref = doc.sentences[sent_idx]
            if score == SEVERITY_SEVERE:
                severity = SEVERITY_SEVERE
            elif score == SEVERITY_WARN or expl_score == SEVERITY_WARN:
                severity = SEVERITY_WARN
            else:
                severity = SEVERITY_INFO
            flag_locator = loc_mod.make_span_locator(
                doc=doc,
                char_start=sent_ref.char_start,
                char_end=sent_ref.char_end,
                sentence_index_start=sent_ref.index,
                sentence_index_end=sent_ref.index,
            )
            flags.append(
                Flag(
                    flag_id=f"{self.code}-{flag_idx:03d}",
                    severity=severity,
                    message="Expletive subject in topic position",
                    locator=flag_locator,
                    evidence={"sentence_index": sent_ref.index},
                )
            )
        # Low-continuity paragraphs (only those at or below warn threshold)
        for p_idx, mc, n in paragraphs_with_pairs:
            if mc > warn_cont:
                continue
            flag_idx += 1
            severity = SEVERITY_SEVERE if mc <= severe_cont else SEVERITY_WARN
            flag_locator = loc_mod.make_paragraph_locator(doc, p_idx)
            flags.append(
                Flag(
                    flag_id=f"{self.code}-{flag_idx:03d}",
                    severity=severity,
                    message=f"Low subject continuity ({mc:.2f}) across {n} sentence pair(s)",
                    locator=flag_locator,
                    evidence={
                        "paragraph_index": p_idx,
                        "mean_continuity": round(mc, 3),
                        "pair_count": n,
                    },
                )
            )

        rationale = (
            f"{expletive_count}/{total_sentences} sentences ({expletive_ratio:.0%}) "
            f"have an expletive subject (warn at {warn_expl:.0%}, severe at {severe_expl:.0%}). "
            f"Mean within-paragraph subject continuity is {mean_continuity:.2f} "
            f"(warn below {warn_cont}, severe below {severe_cont})."
        )

        return Finding(
            code=self.code,
            name=self.name,
            axis=self.axis,
            checked=True,
            summary=Summary(
                metric_name="expletive_subject_ratio",
                metric_value=round(expletive_ratio, 4),
                threshold_warn=warn_expl,
                threshold_severe=severe_expl,
                score=score,
                rationale=rationale,
            ),
            measurements={
                "total_sentences": total_sentences,
                "expletive_subject_count": expletive_count,
                "expletive_subject_ratio": round(expletive_ratio, 4),
                "mean_subject_continuity": round(mean_continuity, 4),
                "per_paragraph_continuity": [
                    {"paragraph_index": p, "mean_continuity": round(mc, 3), "pair_count": n}
                    for p, mc, n in paragraphs_with_pairs
                ],
                "warn_expletive_subject_ratio": warn_expl,
                "severe_expletive_subject_ratio": severe_expl,
                "warn_mean_continuity_below": warn_cont,
                "severe_mean_continuity_below": severe_cont,
            },
            flags=flags,
            notes=[],
        )


register_check(TopicDriftCheck())
