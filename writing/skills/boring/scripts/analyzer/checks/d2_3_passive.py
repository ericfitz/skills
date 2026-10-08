"""D2.3 — Passive overhang.

Detects passive voice constructions and reports the rate. Tracks agentless
passives (no "by X" agent) separately because they're a stronger signal
of agency-hiding.

Mechanical strength: high. spaCy exposes nsubjpass and auxpass directly.
The judgment about whether each passive is *appropriate* in context is
left to the LLM phase.

Outputs:
  - summary: passive_sentence_ratio
  - measurements: counts and ratios; agentless breakout
  - flags: every passive sentence (severity by agent presence + threshold)
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


class PassiveOverhangCheck:
    code = "D2.3"
    name = "Passive overhang"
    axis = "density"

    def run(self, doc: Document, config: Any) -> Finding:
        warn = config.get("density.passive.warn_ratio", 0.25)
        severe = config.get("density.passive.severe_ratio", 0.40)
        warn_agentless = config.get("density.passive.warn_agentless_ratio_of_passives", 0.60)
        severe_agentless = config.get("density.passive.severe_agentless_ratio_of_passives", 0.80)

        passive_sentences: list[tuple[int, int, int, bool]] = []
        # tuples: (sent_index, char_start, char_end, agent_present)

        for sent_ref in doc.sentences:
            spacy_doc = doc.spacy_doc
            span = spacy_doc.char_span(sent_ref.char_start, sent_ref.char_end, alignment_mode="contract")
            if span is None:
                continue
            is_passive, agent_present, evidence = self._detect_passive(span)
            if is_passive:
                passive_sentences.append(
                    (sent_ref.index, sent_ref.char_start, sent_ref.char_end, agent_present)
                )

        total = len(doc.sentences)
        passive_count = len(passive_sentences)
        agentless_count = sum(1 for *_, agented in passive_sentences if not agented)
        ratio = passive_count / total if total else 0.0
        agentless_ratio_of_passives = (
            agentless_count / passive_count if passive_count else 0.0
        )

        flags: list[Flag] = []
        for idx, (sent_idx, c_start, c_end, agent_present) in enumerate(passive_sentences, start=1):
            # Severity: agentless OR over severe ratio threshold => warn at minimum
            if ratio >= severe:
                severity = SEVERITY_SEVERE
            elif ratio >= warn or not agent_present:
                severity = SEVERITY_WARN
            else:
                severity = SEVERITY_INFO

            flag_locator = loc_mod.make_span_locator(
                doc=doc,
                char_start=c_start,
                char_end=c_end,
                sentence_index_start=sent_idx,
                sentence_index_end=sent_idx,
            )
            msg = "Agentless passive" if not agent_present else "Passive voice"
            flags.append(
                Flag(
                    flag_id=f"{self.code}-{idx:03d}",
                    severity=severity,
                    message=msg,
                    locator=flag_locator,
                    evidence={"agent_present": agent_present},
                )
            )

        score = score_against_thresholds(ratio, warn, severe, higher_is_worse=True)
        rationale = (
            f"{passive_count} of {total} sentences ({ratio:.0%}) use passive voice. "
            f"Threshold warn {warn:.0%}, severe {severe:.0%}. "
            f"{agentless_count} ({agentless_ratio_of_passives:.0%} of passives) are agentless."
        )

        return Finding(
            code=self.code,
            name=self.name,
            axis=self.axis,
            checked=True,
            summary=Summary(
                metric_name="passive_sentence_ratio",
                metric_value=round(ratio, 4),
                threshold_warn=warn,
                threshold_severe=severe,
                score=score,
                rationale=rationale,
            ),
            measurements={
                "total_sentence_count": total,
                "passive_sentence_count": passive_count,
                "agentless_passive_count": agentless_count,
                "passive_sentence_ratio": round(ratio, 4),
                "agentless_ratio_of_passives": round(agentless_ratio_of_passives, 4),
                "warn_agentless_ratio_of_passives": warn_agentless,
                "severe_agentless_ratio_of_passives": severe_agentless,
            },
            flags=flags,
            notes=[],
        )

    @staticmethod
    def _detect_passive(span: Any) -> tuple[bool, bool, dict[str, Any]]:
        """Return (is_passive, agent_present, evidence_dict).

        Detection: presence of nsubjpass or auxpass in the span.
        Agent detection: a token with dep_=='agent' (the "by" preposition
        introducing the agent in a "X was done BY Y" construction).
        """
        is_passive = False
        agent_present = False
        passive_aux = None
        passive_verb = None

        for tok in span:
            if tok.dep_ == "nsubjpass":
                is_passive = True
                passive_verb = tok.head.lemma_ if tok.head else None
            elif tok.dep_ == "auxpass":
                is_passive = True
                passive_aux = tok.text
            elif tok.dep_ == "agent":
                agent_present = True

        evidence: dict[str, Any] = {}
        if passive_aux:
            evidence["passive_aux"] = passive_aux
        if passive_verb:
            evidence["passive_verb"] = passive_verb
        evidence["agent_present"] = agent_present
        return is_passive, agent_present, evidence


register_check(PassiveOverhangCheck())
