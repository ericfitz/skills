"""D1.4 — No signposting.

Detects whether the document gives the reader structural cues:

1. **Transition markers at section boundaries.** Between section N and
   section N+1, the first sentence of N+1 should usually carry a
   transition word/phrase that links it to what came before ("However,
   ...", "Building on this, ...", "Given these results, ...").
   Not every boundary needs one — a fresh topic is fine — but a
   document where most boundaries have no linkage reads as a series of
   disconnected fragments.

2. **Roadmap presence in the intro.** Longer documents benefit from a
   forward-pointing structural sentence ("This document covers... first
   X, then Y, then Z."). Whether a roadmap is *required* is genre-
   dependent (architecture_doc / technical_report / proposal / rfc:
   yes; executive_brief / status_update: no).

Mechanical strength: high for transitions (curated phrase lookup at
known anchors); medium for roadmap detection (heuristic).

Outputs:
  - summary: transition_marker_ratio_at_section_boundaries
  - measurements: per-boundary marker presence, roadmap detection,
    counts
  - flags: section boundaries lacking transitions; missing-roadmap flag
    when required-but-absent
"""
from __future__ import annotations

import re
from typing import Any

from .. import locator as loc_mod
from ..common.word_lists import TRANSITION_MARKERS, find_phrase_matches
from ..document import Document, Heading
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

# Forward-pointing roadmap patterns. Detected in the first ~600 chars of body
# text (or up to the second heading, whichever is closer).
_ROADMAP_PATTERNS: tuple[str, ...] = (
    "this document covers",
    "this document describes",
    "this document discusses",
    "this document presents",
    "this document outlines",
    "this document explains",
    "this report covers",
    "this report describes",
    "this report discusses",
    "this report presents",
    "this paper covers",
    "this paper describes",
    "this paper presents",
    "this rfc proposes",
    "this rfc describes",
    "we begin by",
    "we start by",
    "we first",
    "first, we",
    "first we",
    "the structure of this document",
    "the rest of this document",
    "the remainder of this document",
    "the following sections",
    "in what follows",
    "the next section",
    "section 1",
    "section 2",
)
_ENUMERATION_HINT_RE = re.compile(
    r"\b(first|second|third|then|next|finally|lastly)\b.*?\b(then|next|finally|lastly)\b",
    re.IGNORECASE | re.DOTALL,
)


def _first_sentence_after_heading(doc: Document, heading: Heading) -> Any:
    """Return the SentenceRef whose start is at-or-after the heading's char_end,
    skipping any leading whitespace/markdown. Returns None if not found.
    """
    boundary = heading.char_end
    for s in doc.sentences:
        if s.char_start >= boundary:
            return s
    return None


class SignpostingCheck:
    code = "D1.4"
    name = "No signposting"
    axis = "direction"

    def run(self, doc: Document, config: Any) -> Finding:
        warn_ratio = config.get(
            "direction.no_signposting.warn_transition_marker_ratio_below", 0.40
        )
        severe_ratio = config.get(
            "direction.no_signposting.severe_transition_marker_ratio_below", 0.20
        )
        roadmap_required = config.is_required("roadmap", default=False)

        text = doc.extracted_text

        # ----- Transition markers at section boundaries -----
        # We only consider top-level headings (level 1) as the "section
        # boundaries" worth checking — sub-heading transitions matter less.
        # If a doc has no level-1 headings, fall back to all headings.
        top_headings = [h for h in doc.headings if h.level == 1]
        if not top_headings:
            top_headings = doc.headings

        # Skip the very first heading (it has no "previous section" to link to).
        boundaries = top_headings[1:]
        boundary_results: list[dict[str, Any]] = []
        # entries: {heading_text, has_transition, first_sentence_index}
        for h in boundaries:
            sent = _first_sentence_after_heading(doc, h)
            if sent is None:
                continue
            # Look for any transition marker in the first ~60 chars of the
            # sentence (allowing one or two leading filler words).
            sent_text = sent.text
            check_text = sent_text[:80]
            hits = find_phrase_matches(check_text, TRANSITION_MARKERS)
            # A transition is "at the start" if it appears in the first 24 chars
            # of the sentence.
            has_transition = any(s <= 24 for s, _, _ in hits)
            boundary_results.append({
                "heading_text": h.text,
                "has_transition": has_transition,
                "sentence_index": sent.index,
                "char_start": sent.char_start,
                "char_end": sent.char_end,
            })

        total_boundaries = len(boundary_results)
        with_transitions = sum(1 for b in boundary_results if b["has_transition"])
        ratio = with_transitions / total_boundaries if total_boundaries else 1.0

        # ----- Roadmap detection -----
        # Look in the first ~600 chars of body text (or up to the first
        # level-1 heading, if there is one — that's typically where intro
        # ends).
        intro_end = 600
        if top_headings and len(top_headings) >= 2:
            intro_end = min(intro_end, top_headings[1].char_start)
        intro_text = text[:intro_end]
        roadmap_phrase_hits = find_phrase_matches(intro_text, _ROADMAP_PATTERNS)
        enumeration_match = _ENUMERATION_HINT_RE.search(intro_text)
        has_roadmap = bool(roadmap_phrase_hits) or bool(enumeration_match)

        # ----- Scoring -----
        # Transition ratio: lower is worse (higher_is_worse=False).
        # If there are no boundaries to evaluate, this signal is "pass" by
        # construction.
        if total_boundaries == 0:
            ratio_score = "pass"
        else:
            ratio_score = score_against_thresholds(
                ratio, warn_ratio, severe_ratio, higher_is_worse=False
            )

        # Roadmap score: warn if required but absent.
        roadmap_score = "pass"
        if roadmap_required and not has_roadmap:
            roadmap_score = SEVERITY_WARN

        order = {"pass": 0, "info": 0, "warn": 1, "severe": 2}
        score = max((ratio_score, roadmap_score), key=lambda s: order[s])

        # ----- Flags -----
        flags: list[Flag] = []
        flag_idx = 0
        for b in boundary_results:
            if b["has_transition"]:
                continue
            flag_idx += 1
            severity = (
                SEVERITY_SEVERE if score == SEVERITY_SEVERE
                else SEVERITY_WARN if score == SEVERITY_WARN
                else SEVERITY_INFO
            )
            flag_locator = loc_mod.make_span_locator(
                doc=doc,
                char_start=b["char_start"],
                char_end=b["char_end"],
                sentence_index_start=b["sentence_index"],
                sentence_index_end=b["sentence_index"],
            )
            flags.append(
                Flag(
                    flag_id=f"{self.code}-{flag_idx:03d}",
                    severity=severity,
                    message=f"Section '{b['heading_text']}' opens without a transition marker",
                    locator=flag_locator,
                    evidence={"heading_text": b["heading_text"]},
                )
            )
        if roadmap_required and not has_roadmap:
            flag_idx += 1
            doc_loc = loc_mod.make_document_locator(doc)
            flags.append(
                Flag(
                    flag_id=f"{self.code}-{flag_idx:03d}",
                    severity=SEVERITY_WARN,
                    message="No roadmap detected in document intro (genre profile expects one)",
                    locator=doc_loc,
                    evidence={"roadmap_required": True, "intro_chars_examined": intro_end},
                )
            )

        rationale = (
            f"{with_transitions}/{total_boundaries} section boundaries "
            f"({ratio:.0%}) have a transition marker (warn below {warn_ratio:.0%}, "
            f"severe below {severe_ratio:.0%}). "
            f"Roadmap "
            f"{'detected' if has_roadmap else 'not detected'}; "
            f"{'required' if roadmap_required else 'not required'} by genre."
        )

        return Finding(
            code=self.code,
            name=self.name,
            axis=self.axis,
            checked=True,
            summary=Summary(
                metric_name="transition_marker_ratio_at_section_boundaries",
                metric_value=round(ratio, 4),
                threshold_warn=warn_ratio,
                threshold_severe=severe_ratio,
                score=score,
                rationale=rationale,
            ),
            measurements={
                "section_boundary_count": total_boundaries,
                "boundaries_with_transition": with_transitions,
                "transition_marker_ratio": round(ratio, 4),
                "per_boundary": boundary_results,
                "roadmap_detected": has_roadmap,
                "roadmap_required": roadmap_required,
                "roadmap_phrase_hit_count": len(roadmap_phrase_hits),
                "roadmap_enumeration_detected": bool(enumeration_match),
                "warn_transition_marker_ratio_below": warn_ratio,
                "severe_transition_marker_ratio_below": severe_ratio,
            },
            flags=flags,
            notes=[],
        )


register_check(SignpostingCheck())
