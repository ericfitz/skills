"""D3.3 — Opener monotony.

Detects sentences that start the same way. Three signals:

1. Longest run of consecutive sentences starting with the same first
   alphabetic token (case-insensitive). "The system... The system... The
   system..." three times in a row is noticeable; five is a pattern.

2. Longest run of consecutive sentences with the same first POS tag.
   Loosens the signal: "The system... A user... The team..." is all
   DET-NOUN openers even though the tokens differ. POS-run thresholds
   are higher than token-run thresholds because POS overlap is common.

3. First-token entropy across the whole document. Low entropy =
   repetitive openers overall, even when no single run is long. Bits:
   roughly log2(effective vocabulary of openers).

Mechanical strength: high. POS comes from spaCy; the rest is arithmetic.

Outputs:
  - summary: combined score from the three signals (worst wins)
  - measurements: distributions, run lengths, entropy
  - flags: locators for the longest same-first-token runs over warn
"""
from __future__ import annotations

import math
from collections import Counter
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


class OpenerMonotonyCheck:
    code = "D3.3"
    name = "Opener monotony"
    axis = "texture"

    def run(self, doc: Document, config: Any) -> Finding:
        warn_tok_run = config.get("texture.opener_monotony.warn_max_run_same_first_token", 3)
        severe_tok_run = config.get("texture.opener_monotony.severe_max_run_same_first_token", 5)
        warn_pos_run = config.get("texture.opener_monotony.warn_max_run_same_first_pos", 5)
        severe_pos_run = config.get("texture.opener_monotony.severe_max_run_same_first_pos", 9)
        warn_entropy = config.get("texture.opener_monotony.warn_first_token_entropy_below", 4.0)
        severe_entropy = config.get("texture.opener_monotony.severe_first_token_entropy_below", 3.0)

        spacy_doc = doc.spacy_doc

        # Collect (first_token_lower, first_pos) for each sentence. Skip
        # sentences whose first content is non-alphabetic (markdown headings,
        # bullet markers, etc.); they aren't opener-monotony evidence.
        first_tokens: list[str | None] = []
        first_pos: list[str | None] = []
        for sent_ref in doc.sentences:
            span = spacy_doc.char_span(
                sent_ref.char_start, sent_ref.char_end, alignment_mode="contract"
            )
            if span is None:
                first_tokens.append(None)
                first_pos.append(None)
                continue
            first_alpha = next((tok for tok in span if tok.is_alpha), None)
            if first_alpha is None:
                first_tokens.append(None)
                first_pos.append(None)
                continue
            first_tokens.append(first_alpha.text.lower())
            first_pos.append(first_alpha.pos_)

        # Same-token runs (consecutive sentences with identical first lower-cased token)
        token_runs = _find_same_value_runs(first_tokens)
        longest_token_run = max((r["length"] for r in token_runs), default=0)

        # Same-POS runs
        pos_runs = _find_same_value_runs(first_pos)
        longest_pos_run = max((r["length"] for r in pos_runs), default=0)

        # First-token entropy (Shannon, bits) over non-None first tokens
        token_distribution = Counter(t for t in first_tokens if t is not None)
        total_first_tokens = sum(token_distribution.values())
        if total_first_tokens > 0:
            entropy = 0.0
            for count in token_distribution.values():
                p = count / total_first_tokens
                entropy -= p * math.log2(p)
        else:
            entropy = 0.0

        # First-POS distribution (descriptive)
        pos_distribution = Counter(p for p in first_pos if p is not None)

        # Score: worst of the three signals.
        # Lower entropy = worse, so higher_is_worse=False for entropy.
        token_run_score = score_against_thresholds(
            longest_token_run, warn_tok_run, severe_tok_run, higher_is_worse=True
        )
        pos_run_score = score_against_thresholds(
            longest_pos_run, warn_pos_run, severe_pos_run, higher_is_worse=True
        )
        entropy_score = score_against_thresholds(
            entropy, warn_entropy, severe_entropy, higher_is_worse=False
        )
        order = {"pass": 0, "info": 0, "warn": 1, "severe": 2}
        score = max(
            (token_run_score, pos_run_score, entropy_score),
            key=lambda s: order[s],
        )

        # Flags: emit the top-N longest same-token runs over the warn threshold.
        flags: list[Flag] = []
        runs_over_warn = [r for r in token_runs if r["length"] >= warn_tok_run]
        runs_over_warn.sort(key=lambda r: -r["length"])
        for idx, run in enumerate(runs_over_warn[:5], start=1):
            start_sent = doc.sentences[run["start"]]
            end_sent = doc.sentences[run["start"] + run["length"] - 1]
            severity = SEVERITY_SEVERE if run["length"] >= severe_tok_run else SEVERITY_WARN
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
                    message=(
                        f"Run of {run['length']} sentences starting with "
                        f"'{run['value']}'"
                    ),
                    locator=flag_locator,
                    evidence={
                        "first_token": run["value"],
                        "run_length": run["length"],
                    },
                )
            )

        rationale = (
            f"Longest same-first-token run: {longest_token_run} "
            f"(warn at {warn_tok_run}, severe at {severe_tok_run}). "
            f"Longest same-first-POS run: {longest_pos_run} "
            f"(warn at {warn_pos_run}, severe at {severe_pos_run}). "
            f"First-token entropy: {entropy:.2f} bits "
            f"(warn below {warn_entropy}, severe below {severe_entropy})."
        )

        return Finding(
            code=self.code,
            name=self.name,
            axis=self.axis,
            checked=True,
            summary=Summary(
                metric_name="longest_same_first_token_run",
                metric_value=longest_token_run,
                threshold_warn=warn_tok_run,
                threshold_severe=severe_tok_run,
                score=score,
                rationale=rationale,
            ),
            measurements={
                "longest_same_first_token_run": longest_token_run,
                "longest_same_first_pos_run": longest_pos_run,
                "first_token_entropy_bits": round(entropy, 4),
                "total_sentences_evaluated": total_first_tokens,
                "top_first_tokens": token_distribution.most_common(10),
                "first_pos_distribution": dict(pos_distribution),
                "warn_max_run_same_first_token": warn_tok_run,
                "severe_max_run_same_first_token": severe_tok_run,
                "warn_max_run_same_first_pos": warn_pos_run,
                "severe_max_run_same_first_pos": severe_pos_run,
                "warn_first_token_entropy_below": warn_entropy,
                "severe_first_token_entropy_below": severe_entropy,
            },
            flags=flags,
            notes=[],
        )


def _find_same_value_runs(values: list[Any]) -> list[dict[str, Any]]:
    """Maximal runs (length >= 2) of consecutive equal, non-None values.

    Returns dicts with keys: start, length, value.
    """
    runs: list[dict[str, Any]] = []
    n = len(values)
    i = 0
    while i < n:
        v = values[i]
        if v is None:
            i += 1
            continue
        j = i + 1
        while j < n and values[j] == v:
            j += 1
        run_len = j - i
        if run_len >= 2:
            runs.append({"start": i, "length": run_len, "value": v})
        i = j
    return runs


register_check(OpenerMonotonyCheck())
