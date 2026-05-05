"""D1.1 — Buried thesis.

Locates the first "claim-shaped" sentence in the document and scores its
position. BLUF / Pyramid Principle says the answer should land in the
first ~15% of a business document; in an executive_brief it should land
within the first 5%. The deeper the first claim is buried, the more
work the reader has to do before knowing whether the document is worth
reading.

Detection: a sentence is "claim-shaped" if any of the following hold:
- It begins with a strong claim opener ("We recommend", "We conclude",
  "This document recommends", "The bottom line is", "TL;DR", etc.)
- It contains a first-person plural subject ("we") + a claim verb
  ("recommend", "propose", "find", "conclude", "argue", ...)
- It contains a modal of obligation ("must", "should", "needs to") with
  a real (non-expletive) subject

Mechanical strength: medium. The patterns are high precision but low
recall — a writer can make a strong claim with phrasing none of these
patterns catch. The LLM phase is the right place for residual judgment.

Outputs:
  - summary: position_of_first_claim_pct (lower = earlier = better)
  - measurements: all claim positions, summary-section detection
  - flags: first-claim sentence; "no claim found" doc-scope flag if absent
"""
from __future__ import annotations

import re
from typing import Any

from .. import locator as loc_mod
from ..common.word_lists import (
    CLAIM_OPENERS,
    CLAIM_VERBS,
    OBLIGATION_MODALS,
    find_phrase_matches,
)
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

_CLAIM_VERB_LEMMAS = {v.lower() for v in CLAIM_VERBS}
_OBLIGATION_LEMMAS = {m.split()[0].lower() for m in OBLIGATION_MODALS}

# Heading patterns that look like a top-of-doc summary or recommendation.
_SUMMARY_HEADING_RE = re.compile(
    r"\b(summary|recommendation|recommendations|tl;?dr|bottom line|conclusion|abstract)\b",
    re.IGNORECASE,
)


def _claim_in_sentence(sent: Any, claim_opener_starts: set[int]) -> tuple[bool, str | None]:
    """Return (is_claim, kind). kind ∈ {"opener", "we_verb", "obligation"} or None.

    Detection is conservative: "we" + claim verb is more reliable than
    obligation alone. Expletive-subject sentences ("It is critical that...")
    are NOT claims for this purpose — they're meta-commentary, and D1.6
    flags them anyway.
    """
    # Opener match: any opener phrase starting within the first ~16 chars
    # of the sentence (allowing punctuation / leading whitespace).
    if sent.start_char in claim_opener_starts:
        return True, "opener"

    has_we_subj = False
    has_claim_verb = False
    has_obligation = False
    has_real_subject = False
    has_expletive = False
    for tok in sent:
        if tok.dep_ in ("nsubj", "nsubjpass"):
            if tok.lemma_.lower() == "we":
                has_we_subj = True
                has_real_subject = True
            elif tok.lemma_.lower() == "it" and tok.head.lemma_.lower() in ("be", "appear", "seem"):
                # "It is important..." — expletive-style, not a claim
                has_expletive = True
            else:
                has_real_subject = True
        if tok.dep_ == "expl":
            has_expletive = True
        if tok.lemma_.lower() in _CLAIM_VERB_LEMMAS and tok.pos_ in ("VERB", "AUX"):
            has_claim_verb = True
        if tok.lemma_.lower() in _OBLIGATION_LEMMAS and tok.pos_ in ("AUX", "VERB"):
            has_obligation = True

    if has_we_subj and has_claim_verb:
        return True, "we_verb"
    if has_obligation and has_real_subject and not has_expletive:
        return True, "obligation"
    return False, None


class BuriedThesisCheck:
    code = "D1.1"
    name = "Buried thesis"
    axis = "direction"

    def run(self, doc: Document, config: Any) -> Finding:
        warn_pct = config.get("direction.buried_thesis.warn_position_pct", 0.15)
        severe_pct = config.get("direction.buried_thesis.severe_position_pct", 0.30)

        text = doc.extracted_text
        char_count = len(text) or 1
        spacy_doc = doc.spacy_doc

        # Pre-compute the sentence start char-offsets where a claim-opener
        # phrase begins (so we don't recompute per sentence).
        opener_starts: set[int] = set()
        for s, _e, _t in find_phrase_matches(text, CLAIM_OPENERS):
            # An opener "starts" a sentence if it begins within ~16 chars of
            # one of our sentence char_starts.
            for sent_ref in doc.sentences:
                if 0 <= s - sent_ref.char_start <= 16:
                    opener_starts.add(sent_ref.char_start)
                    break

        # Find all claim-shaped sentences, in order.
        claim_positions: list[dict[str, Any]] = []
        for sent_ref in doc.sentences:
            span = spacy_doc.char_span(
                sent_ref.char_start, sent_ref.char_end, alignment_mode="contract"
            )
            if span is None:
                continue
            # The Span.start_char from char_span doesn't always equal the
            # sentence's char_start (due to whitespace contraction). Use the
            # sent_ref's char_start as the canonical anchor for opener match.
            opener_anchor = sent_ref.char_start in opener_starts
            is_claim, kind = _claim_in_sentence(
                span,
                claim_opener_starts={span.start_char} if opener_anchor else set(),
            )
            if is_claim:
                claim_positions.append({
                    "sentence_index": sent_ref.index,
                    "char_offset": sent_ref.char_start,
                    "position_pct": round(sent_ref.char_start / char_count, 4),
                    "kind": kind,
                })

        first_claim = claim_positions[0] if claim_positions else None

        # Summary-heading near the top: a heading matching _SUMMARY_HEADING_RE
        # within the first ~10% of the document.
        early_cutoff = int(char_count * 0.10)
        summary_heading = None
        for h in doc.headings:
            if h.char_start <= early_cutoff and _SUMMARY_HEADING_RE.search(h.text):
                summary_heading = {
                    "level": h.level,
                    "text": h.text,
                    "char_start": h.char_start,
                }
                break

        # Score
        if first_claim is not None:
            position_pct = first_claim["position_pct"]
            score = score_against_thresholds(
                position_pct, warn_pct, severe_pct, higher_is_worse=True
            )
        else:
            # No claim found at all: severe (the LLM phase may overrule).
            position_pct = 1.0
            score = SEVERITY_SEVERE

        # If a summary-heading is present near the top, soften by one level
        # (the document is structurally signaling its claim location even if
        # no individual sentence matched our patterns).
        if summary_heading is not None and score == SEVERITY_SEVERE:
            score = SEVERITY_WARN
        elif summary_heading is not None and score == SEVERITY_WARN:
            score = SEVERITY_INFO

        flags: list[Flag] = []
        if first_claim is not None:
            sent_ref = doc.sentences[first_claim["sentence_index"]]
            severity = (
                SEVERITY_SEVERE if score == SEVERITY_SEVERE
                else SEVERITY_WARN if score == SEVERITY_WARN
                else SEVERITY_INFO
            )
            flag_locator = loc_mod.make_span_locator(
                doc=doc,
                char_start=sent_ref.char_start,
                char_end=sent_ref.char_end,
                sentence_index_start=sent_ref.index,
                sentence_index_end=sent_ref.index,
            )
            flags.append(
                Flag(
                    flag_id=f"{self.code}-001",
                    severity=severity,
                    message=(
                        f"First claim-shaped sentence at {position_pct:.0%} of document "
                        f"(warn at {warn_pct:.0%}, severe at {severe_pct:.0%})"
                    ),
                    locator=flag_locator,
                    evidence={
                        "kind": first_claim["kind"],
                        "position_pct": position_pct,
                        "summary_heading_present": summary_heading is not None,
                    },
                )
            )
        else:
            doc_loc = loc_mod.make_document_locator(doc)
            flags.append(
                Flag(
                    flag_id=f"{self.code}-001",
                    severity=SEVERITY_SEVERE,
                    message="No claim-shaped sentence detected anywhere in the document",
                    locator=doc_loc,
                    evidence={
                        "summary_heading_present": summary_heading is not None,
                    },
                )
            )

        if first_claim is not None:
            rationale = (
                f"First claim-shaped sentence ({first_claim['kind']}) at "
                f"char offset {first_claim['char_offset']} = {position_pct:.0%} of "
                f"document (warn at {warn_pct:.0%}, severe at {severe_pct:.0%}). "
                f"{len(claim_positions)} claim-shaped sentences total. "
                f"Summary heading near top: "
                f"{'yes (' + summary_heading['text'] + ')' if summary_heading else 'no'}."
            )
        else:
            rationale = (
                "No claim-shaped sentence detected. "
                f"Summary heading near top: "
                f"{'yes (' + summary_heading['text'] + ')' if summary_heading else 'no'}."
            )

        return Finding(
            code=self.code,
            name=self.name,
            axis=self.axis,
            checked=True,
            summary=Summary(
                metric_name="position_of_first_claim_pct",
                metric_value=round(position_pct, 4),
                threshold_warn=warn_pct,
                threshold_severe=severe_pct,
                score=score,
                rationale=rationale,
            ),
            measurements={
                "first_claim_found": first_claim is not None,
                "first_claim": first_claim,
                "claim_count": len(claim_positions),
                "all_claim_positions": claim_positions,
                "summary_heading_near_top": summary_heading,
                "early_cutoff_chars": early_cutoff,
                "warn_position_pct": warn_pct,
                "severe_position_pct": severe_pct,
            },
            flags=flags,
            notes=[],
        )


register_check(BuriedThesisCheck())
