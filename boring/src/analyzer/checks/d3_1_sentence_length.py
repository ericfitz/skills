"""D3.1 — Sentence-length monotony.

Computes sentence-length distribution stats and detects long runs of
similar-length sentences. Provost's "this sentence has five words"
intuition operationalized.

Mechanical strength: very high. Pure arithmetic on token counts.

Outputs:
  - summary: coefficient_of_variation (low CV = monotonous)
  - measurements: full distribution stats, longest run length, count of runs
  - flags: locators for the longest similar-length runs
"""
from __future__ import annotations

import math
from typing import Any

from .. import locator as loc_mod
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


class SentenceLengthMonotonyCheck:
    code = "D3.1"
    name = "Sentence-length monotony"
    axis = "texture"

    def run(self, doc: Document, config: Any) -> Finding:
        warn_cv = config.get("texture.sentence_length.warn_cv_below", 0.35)
        severe_cv = config.get("texture.sentence_length.severe_cv_below", 0.20)
        warn_run = config.get("texture.sentence_length.warn_max_run", 6)
        severe_run = config.get("texture.sentence_length.severe_max_run", 10)
        sim_band = config.get("texture.sentence_length.similarity_band_pct", 0.20)

        # Compute per-sentence word counts using spaCy alpha-only tokens
        spacy_doc = doc.spacy_doc
        lengths: list[int] = []
        for sent_ref in doc.sentences:
            span = spacy_doc.char_span(sent_ref.char_start, sent_ref.char_end, alignment_mode="contract")
            if span is None:
                lengths.append(0)
                continue
            n = sum(1 for tok in span if tok.is_alpha)
            lengths.append(n)

        if not lengths:
            return Finding(
                code=self.code, name=self.name, axis=self.axis, checked=True,
                summary=Summary(metric_name="coefficient_of_variation", metric_value=0.0,
                                score="pass", rationale="No sentences to evaluate."),
                measurements={}, flags=[], notes=[],
            )

        mean = sum(lengths) / len(lengths)
        variance = sum((x - mean) ** 2 for x in lengths) / len(lengths)
        stdev = math.sqrt(variance)
        cv = stdev / mean if mean > 0 else 0.0
        sorted_lens = sorted(lengths)
        median = sorted_lens[len(sorted_lens) // 2]
        p10 = sorted_lens[max(0, int(0.10 * len(sorted_lens)) - 1)]
        p90 = sorted_lens[min(len(sorted_lens) - 1, int(0.90 * len(sorted_lens)))]

        # Find runs of consecutive sentences within the similarity band
        runs = self._find_similar_runs(lengths, sim_band)
        longest_run = max((r["length"] for r in runs), default=0)
        runs_over_warn = [r for r in runs if r["length"] >= warn_run]

        # CV-based score (lower is worse)
        cv_score = score_against_thresholds(cv, warn_cv, severe_cv, higher_is_worse=False)
        # Run-based score (higher is worse)
        run_score = score_against_thresholds(longest_run, warn_run, severe_run, higher_is_worse=True)

        # Final score: take the worse of the two
        order = {"pass": 0, "warn": 1, "severe": 2, "info": 0}
        score = cv_score if order[cv_score] >= order[run_score] else run_score

        rationale = (
            f"Sentence-length CV is {cv:.3f} (warn below {warn_cv}, severe below {severe_cv}). "
            f"Longest run of similar-length sentences (within \u00b1{int(sim_band*100)}%) is "
            f"{longest_run} (warn at {warn_run}, severe at {severe_run})."
        )

        # Emit flags for runs over warn threshold (top-N by length)
        flags: list[Flag] = []
        runs_over_warn.sort(key=lambda r: -r["length"])
        for idx, run in enumerate(runs_over_warn[:5], start=1):
            start_sent = doc.sentences[run["start"]]
            end_sent = doc.sentences[run["start"] + run["length"] - 1]
            severity = SEVERITY_SEVERE if run["length"] >= severe_run else SEVERITY_WARN
            flag_locator = loc_mod.make_span_locator(
                doc=doc,
                char_start=start_sent.char_start,
                char_end=end_sent.char_end,
                sentence_index_start=start_sent.index,
                sentence_index_end=end_sent.index,
            )
            flags.append(
                Flag(
                    flag_id=f"{self.code}-{idx:03d}",
                    severity=severity,
                    message=f"Run of {run['length']} sentences within \u00b1{int(sim_band*100)}% of each other in length",
                    locator=flag_locator,
                    evidence={
                        "run_length": run["length"],
                        "sentence_lengths_in_run": run["lengths"],
                    },
                )
            )

        return Finding(
            code=self.code,
            name=self.name,
            axis=self.axis,
            checked=True,
            summary=Summary(
                metric_name="coefficient_of_variation",
                metric_value=round(cv, 4),
                threshold_warn=warn_cv,
                threshold_severe=severe_cv,
                score=score,
                rationale=rationale,
            ),
            measurements={
                "mean": round(mean, 2),
                "median": median,
                "stdev": round(stdev, 2),
                "coefficient_of_variation": round(cv, 4),
                "p10": p10,
                "p90": p90,
                "longest_similar_length_run": longest_run,
                "similar_length_runs_above_warn": len(runs_over_warn),
                "warn_max_run": warn_run,
                "severe_max_run": severe_run,
                "similarity_band_pct": sim_band,
                "sentence_length_distribution": lengths,
            },
            flags=flags,
            notes=[],
        )

    @staticmethod
    def _find_similar_runs(lengths: list[int], band_pct: float) -> list[dict[str, Any]]:
        """Maximal runs of consecutive sentences whose lengths are pairwise
        within ``band_pct`` of each other (relative to the run's anchor).
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
                runs.append(
                    {
                        "start": i,
                        "length": run_len,
                        "lengths": lengths[i:j],
                    }
                )
            i = j if run_len >= 2 else i + 1
        return runs


register_check(SentenceLengthMonotonyCheck())
