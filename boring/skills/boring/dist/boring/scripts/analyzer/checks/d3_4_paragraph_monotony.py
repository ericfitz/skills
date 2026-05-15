"""D3.4 — Paragraph monotony.

Detects two related signals:

1. Coefficient of variation of paragraph word counts. Low CV = all
   paragraphs about the same length, no emphatic short paragraphs and no
   developed long ones. Provost's "this sentence has five words"
   intuition scaled up to paragraphs.

2. Wall-of-text paragraphs — paragraphs above the length thresholds. In
   business writing, ~200-word paragraphs strain attention; ~350+ are
   genuinely hard to read on a screen.

Plus an aggregate "longest run of similar-length paragraphs" measurement.

Mechanical strength: very high. Pure arithmetic on word counts.

Outputs:
  - summary: paragraph_length_coefficient_of_variation (lower is worse)
  - measurements: distribution stats, run length, wall-of-text counts
  - flags: each wall-of-text paragraph with its locator
"""
from __future__ import annotations

import math
import re
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

# Matches a paragraph whose only content is a markdown ATX heading line
# ("# Title", "## Subtitle"). Such paragraphs aren't body prose and would
# distort length stats if counted.
_HEADING_ONLY_RE = re.compile(r"^\s*#{1,6}\s+\S.*?\s*$")


class ParagraphMonotonyCheck:
    code = "D3.4"
    name = "Paragraph monotony"
    axis = "texture"

    def run(self, doc: Document, config: Any) -> Finding:
        warn_cv = config.get("texture.paragraph_monotony.warn_cv_below", 0.40)
        severe_cv = config.get("texture.paragraph_monotony.severe_cv_below", 0.25)
        warn_run = config.get("texture.paragraph_monotony.warn_max_run", 5)
        severe_run = config.get("texture.paragraph_monotony.severe_max_run", 8)
        warn_words = config.get("texture.paragraph_monotony.warn_paragraph_words_above", 200)
        severe_words = config.get("texture.paragraph_monotony.severe_paragraph_words_above", 350)
        sim_band = 0.25  # ±25% to count as "similar length"; matches calibration prose

        # Compute word counts per body paragraph (alpha tokens only). Skip
        # heading-only paragraphs — they'd distort the length distribution
        # without representing real prose.
        body_paragraphs: list[tuple[int, int]] = []  # (paragraph_index, word_count)
        for p in doc.paragraphs:
            if _HEADING_ONLY_RE.match(p.text.strip()):
                continue
            n = sum(1 for w in p.text.split() if any(c.isalpha() for c in w))
            body_paragraphs.append((p.index, n))
        lengths = [n for _, n in body_paragraphs]

        if not lengths:
            return Finding(
                code=self.code,
                name=self.name,
                axis=self.axis,
                checked=True,
                summary=Summary(
                    metric_name="paragraph_length_coefficient_of_variation",
                    metric_value=0.0,
                    score="pass",
                    rationale="No paragraphs to evaluate.",
                ),
                measurements={},
                flags=[],
                notes=[],
            )

        mean = sum(lengths) / len(lengths)
        variance = sum((x - mean) ** 2 for x in lengths) / len(lengths)
        stdev = math.sqrt(variance)
        cv = stdev / mean if mean > 0 else 0.0

        # Longest run of similar-length paragraphs (within ±sim_band of run anchor)
        runs = _find_similar_runs(lengths, sim_band)
        longest_run = max((r["length"] for r in runs), default=0)

        # Wall-of-text paragraphs
        warn_walls = [i for i, n in enumerate(lengths) if n >= warn_words]
        severe_walls = [i for i, n in enumerate(lengths) if n >= severe_words]

        # Component scores
        cv_score = score_against_thresholds(cv, warn_cv, severe_cv, higher_is_worse=False)
        run_score = score_against_thresholds(
            longest_run, warn_run, severe_run, higher_is_worse=True
        )
        # Wall score: severe if any paragraph is over severe_words; warn if any
        # paragraph is over warn_words; pass otherwise.
        if severe_walls:
            wall_score = SEVERITY_SEVERE
        elif warn_walls:
            wall_score = SEVERITY_WARN
        else:
            wall_score = "pass"

        order = {"pass": 0, "info": 0, "warn": 1, "severe": 2}
        score = max(
            (cv_score, run_score, wall_score),
            key=lambda s: order[s],
        )

        # Flags: emit each wall-of-text paragraph as a paragraph-scope locator.
        # warn_walls / severe_walls are positions in the *body_paragraphs*
        # filtered list — translate back to the original paragraph index.
        flags: list[Flag] = []
        for idx, body_pos in enumerate(warn_walls, start=1):
            original_p_idx, n = body_paragraphs[body_pos]
            severity = SEVERITY_SEVERE if n >= severe_words else SEVERITY_WARN
            flag_locator = loc_mod.make_paragraph_locator(doc, original_p_idx)
            flags.append(
                Flag(
                    flag_id=f"{self.code}-{idx:03d}",
                    severity=severity,
                    message=f"Wall-of-text paragraph ({n} words)",
                    locator=flag_locator,
                    evidence={"paragraph_word_count": n},
                )
            )

        rationale = (
            f"Paragraph-length CV is {cv:.3f} (warn below {warn_cv}, severe below {severe_cv}). "
            f"Longest run of similar-length paragraphs (±{int(sim_band * 100)}%) is "
            f"{longest_run} (warn at {warn_run}, severe at {severe_run}). "
            f"{len(warn_walls)} paragraphs ≥ {warn_words} words "
            f"({len(severe_walls)} ≥ {severe_words})."
        )

        sorted_lens = sorted(lengths)
        median = sorted_lens[len(sorted_lens) // 2]
        p10 = sorted_lens[max(0, int(0.10 * len(sorted_lens)) - 1)]
        p90 = sorted_lens[min(len(sorted_lens) - 1, int(0.90 * len(sorted_lens)))]

        return Finding(
            code=self.code,
            name=self.name,
            axis=self.axis,
            checked=True,
            summary=Summary(
                metric_name="paragraph_length_coefficient_of_variation",
                metric_value=round(cv, 4),
                threshold_warn=warn_cv,
                threshold_severe=severe_cv,
                score=score,
                rationale=rationale,
            ),
            measurements={
                "paragraph_count": len(lengths),
                "mean_words": round(mean, 2),
                "median_words": median,
                "stdev_words": round(stdev, 2),
                "coefficient_of_variation": round(cv, 4),
                "p10_words": p10,
                "p90_words": p90,
                "longest_similar_length_run": longest_run,
                "wall_of_text_warn_count": len(warn_walls),
                "wall_of_text_severe_count": len(severe_walls),
                "paragraph_length_distribution": lengths,
                "warn_cv_below": warn_cv,
                "severe_cv_below": severe_cv,
                "warn_max_run": warn_run,
                "severe_max_run": severe_run,
                "warn_paragraph_words_above": warn_words,
                "severe_paragraph_words_above": severe_words,
            },
            flags=flags,
            notes=[],
        )


def _find_similar_runs(lengths: list[int], band_pct: float) -> list[dict[str, Any]]:
    """Maximal runs of consecutive paragraphs whose lengths are within ±band_pct
    of the run's anchor (first paragraph in the run).
    """
    if not lengths:
        return []
    runs: list[dict[str, Any]] = []
    i = 0
    n = len(lengths)
    while i < n:
        anchor = lengths[i]
        j = i + 1
        while j < n:
            if anchor == 0:
                break
            ratio = lengths[j] / anchor
            if 1 - band_pct <= ratio <= 1 + band_pct:
                j += 1
            else:
                break
        run_len = j - i
        if run_len >= 2:
            runs.append({"start": i, "length": run_len, "lengths": lengths[i:j]})
        i = j if run_len >= 2 else i + 1
    return runs


register_check(ParagraphMonotonyCheck())
