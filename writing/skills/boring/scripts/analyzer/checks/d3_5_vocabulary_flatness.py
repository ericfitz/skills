"""D3.5 — Vocabulary flatness.

Detects a limited verb/noun palette via three signals:

1. MATTR (Moving-Average Type-Token Ratio) over a sliding window of 100
   tokens. Higher = more diverse vocabulary across the document.
   Technical writing legitimately repeats domain terms, so we don't
   expect literary-grade MATTR (~0.75) — but below ~0.45 suggests a
   small effective vocabulary.

2. Verb-lemma diversity ratio: unique verb lemmas / total verb tokens.
   This catches the "uses / provides / enables" pattern even when overall
   MATTR is fine because of high noun variety.

3. Top-verb share: if the single most-repeated verb lemma accounts for
   more than ~10% of all verb tokens, the verb palette has collapsed.

Mechanical strength: high. Pure counting and ratio computation over the
spaCy lemmatized doc.

Outputs:
  - summary: mattr (lower is worse)
  - measurements: MATTR, verb diversity ratio, top verb/noun lemmas
  - flags: top over-used verbs/nouns as document-scope info flags (no
    spans — this is a document-level signal)
"""
from __future__ import annotations

from collections import Counter
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

# MATTR window size (Covington & McFall 2010 default)
_MATTR_WINDOW = 100

# spaCy POS tags we count as "content" for the MATTR computation. Excluding
# determiners, punctuation, particles, etc. avoids overweighting function
# words (which have low diversity by nature).
_CONTENT_POS = {"NOUN", "PROPN", "VERB", "ADJ", "ADV"}


def _moving_average_ttr(tokens: list[str], window: int) -> float:
    """MATTR: mean of TTR computed over each sliding window of `window` tokens.

    For documents shorter than `window`, returns the single-window TTR.
    """
    n = len(tokens)
    if n == 0:
        return 0.0
    if n <= window:
        return len(set(tokens)) / n
    ttrs: list[float] = []
    # Slide the window one token at a time. With a content-only token list
    # of a few thousand tokens this is fast.
    for start in range(0, n - window + 1):
        slice_ = tokens[start : start + window]
        ttrs.append(len(set(slice_)) / window)
    return sum(ttrs) / len(ttrs)


class VocabularyFlatnessCheck:
    code = "D3.5"
    name = "Vocabulary flatness"
    axis = "texture"

    def run(self, doc: Document, config: Any) -> Finding:
        warn_mattr = config.get("texture.vocabulary_flatness.warn_mattr_below", 0.55)
        severe_mattr = config.get("texture.vocabulary_flatness.severe_mattr_below", 0.45)
        warn_vdiv = config.get("texture.vocabulary_flatness.warn_verb_diversity_below", 0.35)
        severe_vdiv = config.get("texture.vocabulary_flatness.severe_verb_diversity_below", 0.25)
        warn_top_v = config.get("texture.vocabulary_flatness.warn_top_verb_share", 0.10)
        severe_top_v = config.get("texture.vocabulary_flatness.severe_top_verb_share", 0.20)

        spacy_doc = doc.spacy_doc

        # MATTR over content-word lemmas (lowercased). Using lemmas instead of
        # surface forms is the right thing for "did the writer use varied
        # vocabulary" — "system / systems" should count as one type.
        content_lemmas: list[str] = [
            tok.lemma_.lower()
            for tok in spacy_doc
            if tok.is_alpha and tok.pos_ in _CONTENT_POS
        ]
        mattr = _moving_average_ttr(content_lemmas, _MATTR_WINDOW)

        # Verb diversity
        verb_lemmas: list[str] = [
            tok.lemma_.lower()
            for tok in spacy_doc
            if tok.is_alpha and tok.pos_ == "VERB"
        ]
        verb_lemma_counts = Counter(verb_lemmas)
        total_verbs = len(verb_lemmas)
        unique_verbs = len(verb_lemma_counts)
        verb_diversity = unique_verbs / total_verbs if total_verbs else 0.0

        # Top-verb share: most-repeated verb / total verbs
        top_verb_share = 0.0
        top_verb: str | None = None
        if verb_lemma_counts:
            top_verb, top_count = verb_lemma_counts.most_common(1)[0]
            top_verb_share = top_count / total_verbs

        # Noun diversity (descriptive)
        noun_lemmas: list[str] = [
            tok.lemma_.lower()
            for tok in spacy_doc
            if tok.is_alpha and tok.pos_ in ("NOUN", "PROPN")
        ]
        noun_lemma_counts = Counter(noun_lemmas)
        total_nouns = len(noun_lemmas)
        unique_nouns = len(noun_lemma_counts)
        noun_diversity = unique_nouns / total_nouns if total_nouns else 0.0

        # Component scores. MATTR and verb-diversity: lower is worse.
        # top-verb share: higher is worse.
        mattr_score = score_against_thresholds(mattr, warn_mattr, severe_mattr, higher_is_worse=False)
        vdiv_score = score_against_thresholds(verb_diversity, warn_vdiv, severe_vdiv, higher_is_worse=False)
        top_v_score = score_against_thresholds(top_verb_share, warn_top_v, severe_top_v, higher_is_worse=True)

        order = {"pass": 0, "info": 0, "warn": 1, "severe": 2}
        score = max(
            (mattr_score, vdiv_score, top_v_score),
            key=lambda s: order[s],
        )

        # Flags: top 10 over-used verb/noun lemmas, surfaced as document-scope
        # info-or-warn flags. These have no spans (the signal is document-wide)
        # so we emit them with a document locator.
        flags: list[Flag] = []
        # Severity: warn if the count alone makes the lemma's share over the
        # warn threshold; otherwise info.
        doc_locator = loc_mod.make_document_locator(doc)
        for idx, (lemma, count) in enumerate(verb_lemma_counts.most_common(5), start=1):
            share = count / total_verbs if total_verbs else 0.0
            if share >= severe_top_v:
                severity = SEVERITY_SEVERE
            elif share >= warn_top_v:
                severity = SEVERITY_WARN
            else:
                severity = SEVERITY_INFO
            flags.append(
                Flag(
                    flag_id=f"{self.code}-V{idx:02d}",
                    severity=severity,
                    message=f"Over-used verb '{lemma}' ({count} occurrences, {share:.0%} of all verbs)",
                    locator=doc_locator,
                    evidence={"lemma": lemma, "count": count, "share": round(share, 4), "pos": "VERB"},
                )
            )
        for idx, (lemma, count) in enumerate(noun_lemma_counts.most_common(5), start=1):
            share = count / total_nouns if total_nouns else 0.0
            # Nouns: only flag at info — domain nouns repeat legitimately.
            flags.append(
                Flag(
                    flag_id=f"{self.code}-N{idx:02d}",
                    severity=SEVERITY_INFO,
                    message=f"Most-used noun '{lemma}' ({count} occurrences, {share:.0%} of all nouns)",
                    locator=doc_locator,
                    evidence={"lemma": lemma, "count": count, "share": round(share, 4), "pos": "NOUN"},
                )
            )

        rationale = (
            f"MATTR (window {_MATTR_WINDOW}) is {mattr:.3f} (warn below {warn_mattr}, "
            f"severe below {severe_mattr}). Verb diversity is {verb_diversity:.3f} "
            f"({unique_verbs} unique / {total_verbs} total; warn below {warn_vdiv}, "
            f"severe below {severe_vdiv}). Top verb '{top_verb}' is {top_verb_share:.0%} "
            f"of all verbs (warn at {warn_top_v:.0%}, severe at {severe_top_v:.0%})."
        )

        return Finding(
            code=self.code,
            name=self.name,
            axis=self.axis,
            checked=True,
            summary=Summary(
                metric_name="mattr",
                metric_value=round(mattr, 4),
                threshold_warn=warn_mattr,
                threshold_severe=severe_mattr,
                score=score,
                rationale=rationale,
            ),
            measurements={
                "mattr": round(mattr, 4),
                "mattr_window": _MATTR_WINDOW,
                "content_token_count": len(content_lemmas),
                "verb_count": total_verbs,
                "unique_verb_lemmas": unique_verbs,
                "verb_diversity_ratio": round(verb_diversity, 4),
                "top_verb_lemma": top_verb,
                "top_verb_share": round(top_verb_share, 4),
                "top_verbs": verb_lemma_counts.most_common(10),
                "noun_count": total_nouns,
                "unique_noun_lemmas": unique_nouns,
                "noun_diversity_ratio": round(noun_diversity, 4),
                "top_nouns": noun_lemma_counts.most_common(10),
                "warn_mattr_below": warn_mattr,
                "severe_mattr_below": severe_mattr,
                "warn_verb_diversity_below": warn_vdiv,
                "severe_verb_diversity_below": severe_vdiv,
                "warn_top_verb_share": warn_top_v,
                "severe_top_verb_share": severe_top_v,
            },
            flags=flags,
            notes=[],
        )


register_check(VocabularyFlatnessCheck())
