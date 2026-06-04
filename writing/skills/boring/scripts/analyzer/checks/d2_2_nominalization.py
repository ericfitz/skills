"""D2.2 — Nominalization fog.

Detects two related signals:

1. Nominalization density — nouns derived from verbs/adjectives via a
   small set of suffixes (-tion, -ment, -ance, -ence, -ity, -ness,
   -sion, -cy, -ism). Williams' *Style* identifies sustained density
   here as the dominant texture of "Official Style" prose.

2. Light verb + nominalization patterns — constructions like "performed
   an analysis of", "made a determination", "conducted an examination
   of". This is the highest-precision signal: nearly every match is a
   real fix (rewrite to a strong verb).

Mechanical strength: high for #1 (suffix matching with POS filter), high
for #2 (spaCy dep parse). The judgment of whether any individual
nominalization is *appropriate* (e.g., a domain term that resists
verbing) is left to the LLM phase.

Outputs:
  - summary: nominalizations_per_sentence
  - measurements: suffix breakdown, light-verb pattern count, "to be"
    main-verb ratio
  - flags: every light-verb + nominalization construction (precision-first)
"""
from __future__ import annotations

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

# Suffixes that mark deverbal/deadjectival nouns. Order matters only for
# breakdown reporting (longest-first avoids "ity" inside "tion-ity"
# style false counts; not actually a problem because we match the noun's
# *trailing* characters).
_NOMINAL_SUFFIXES: tuple[str, ...] = (
    "tion", "sion", "ment", "ance", "ence", "ity", "ness", "ism", "cy",
    # Greek-origin -sis (analysis, diagnosis, synthesis, hypothesis, emphasis)
    "sis",
    # -ure (failure, departure, exposure, pressure, procedure, structure)
    "ure",
    # -al deverbal nouns (arrival, refusal, denial, approval, removal,
    # dismissal, betrayal). The POS=NOUN gate filters out the much commoner
    # adjectival -al ("critical", "general", "central", "natural").
    "al",
)
_NOMINAL_SUFFIX_RE = re.compile(
    r"(?:" + "|".join(_NOMINAL_SUFFIXES) + r")$",
    re.IGNORECASE,
)

# Light/empty verbs that carry no real action — they exist mainly to host
# a nominalized object. The verb's lemma is what we match. spaCy lemmatizes
# "performed" -> "perform", "made" -> "make", etc.
_LIGHT_VERB_LEMMAS: frozenset[str] = frozenset({
    "make", "do", "perform", "conduct", "carry", "give", "take",
    "provide", "achieve", "effect", "undertake", "have",
    "complete", "execute", "engage", "render", "offer",
})

# Forms of "to be" — counted separately for the "main verb is mostly 'to be'"
# signal that complements the nominalization density metric.
_BE_LEMMAS: frozenset[str] = frozenset({"be"})

# Minimum word length to count as a nominalization. Very short matches
# ("ice", "fly", "icy") are almost always false positives.
_MIN_NOM_LENGTH = 6


def _is_nominalization(token: Any) -> str | None:
    """Return the matched suffix if `token` looks like a nominalization, else None.

    Filters: must be a noun (NOUN/PROPN), at least _MIN_NOM_LENGTH characters,
    and end in one of _NOMINAL_SUFFIXES.
    """
    if token.pos_ not in ("NOUN", "PROPN"):
        return None
    text = token.text
    if len(text) < _MIN_NOM_LENGTH:
        return None
    m = _NOMINAL_SUFFIX_RE.search(text.lower())
    return m.group(0) if m else None


class NominalizationCheck:
    code = "D2.2"
    name = "Nominalization fog"
    axis = "density"

    def run(self, doc: Document, config: Any) -> Finding:
        warn_per_sent = config.get("density.nominalization.warn_per_sentence", 1.5)
        severe_per_sent = config.get("density.nominalization.severe_per_sentence", 2.5)
        warn_lv = config.get("density.nominalization.warn_light_verb_nom_per_1000_words", 2.0)
        severe_lv = config.get("density.nominalization.severe_light_verb_nom_per_1000_words", 5.0)

        spacy_doc = doc.spacy_doc
        word_count = doc.word_count or 1

        # Pass 1: suffix-based nominalization counts (whole document).
        # Bucket by longest matching suffix so "foundation" -> "tion" not "ion"
        # (and -al doesn't shadow longer endings).
        suffix_counts: dict[str, int] = {s: 0 for s in _NOMINAL_SUFFIXES}
        suffixes_by_length: list[str] = sorted(_NOMINAL_SUFFIXES, key=lambda s: len(s), reverse=True)
        total_nominalizations = 0
        for tok in spacy_doc:
            if _is_nominalization(tok) is None:
                continue
            text_low = tok.text.lower()
            for s in suffixes_by_length:
                if text_low.endswith(s):
                    suffix_counts[s] += 1
                    break
            total_nominalizations += 1

        total_sentences = len(doc.sentences) or 1
        nom_per_sent = total_nominalizations / total_sentences

        # Pass 2: "to be" main-verb ratio — proportion of sentences whose ROOT
        # is a form of "be". A high ratio combined with high nominalization
        # density is the Lanham/Williams "Official Style" fingerprint.
        be_root_count = 0
        sents_with_root = 0
        for sent in spacy_doc.sents:
            root = sent.root
            if root is None:
                continue
            sents_with_root += 1
            if root.lemma_ in _BE_LEMMAS:
                be_root_count += 1
        be_root_ratio = be_root_count / sents_with_root if sents_with_root else 0.0

        # Pass 3: light-verb + nominalization patterns. Walk sentences,
        # find verbs with light-verb lemma, look at their direct objects,
        # and check if the dobj (or a noun chunk headed at it) is a
        # nominalization.
        light_verb_hits: list[tuple[int, int, str, str]] = []
        # tuples: (char_start, char_end, verb_text, nom_text)
        for tok in spacy_doc:
            if tok.pos_ != "VERB" or tok.lemma_ not in _LIGHT_VERB_LEMMAS:
                continue
            # Find a direct object that's a nominalization
            for child in tok.children:
                if child.dep_ != "dobj":
                    continue
                # The nominalization may be the head noun of a noun chunk
                # ("an analysis of the costs") — check the noun head and any
                # of-prep children.
                nom_token = None
                if _is_nominalization(child):
                    nom_token = child
                else:
                    # Sometimes spaCy parses "perform an analysis of X" with
                    # 'analysis' as dobj head; if not, search noun chunk.
                    for cc in child.subtree:
                        if _is_nominalization(cc):
                            nom_token = cc
                            break
                if nom_token is None:
                    continue
                # Span: from the verb to the nominalization (inclusive of
                # any intervening determiner/adjective).
                start = min(tok.i, nom_token.i)
                end = max(tok.i, nom_token.i)
                span = spacy_doc[start : end + 1]
                light_verb_hits.append(
                    (span.start_char, span.end_char, tok.text, nom_token.text)
                )
                break  # one hit per verb is enough

        light_verb_count = len(light_verb_hits)
        lv_per_1000 = (light_verb_count / word_count) * 1000

        # Score: take the *worse* of the two signals.
        density_score = score_against_thresholds(
            nom_per_sent, warn_per_sent, severe_per_sent, higher_is_worse=True
        )
        lv_score = score_against_thresholds(
            lv_per_1000, warn_lv, severe_lv, higher_is_worse=True
        )
        order = {"pass": 0, "info": 0, "warn": 1, "severe": 2}
        score = density_score if order[density_score] >= order[lv_score] else lv_score

        # Build flags from light-verb hits (highest-precision signal).
        flags: list[Flag] = []
        for idx, (c_start, c_end, verb_text, nom_text) in enumerate(light_verb_hits, start=1):
            sent_idx = self._sentence_index_at(doc, c_start)
            sent_ref = doc.sentences[sent_idx] if sent_idx is not None else None
            severity = SEVERITY_SEVERE if score == SEVERITY_SEVERE else SEVERITY_WARN
            flag_locator = loc_mod.make_span_locator(
                doc=doc,
                char_start=c_start,
                char_end=c_end,
                sentence_index_start=sent_ref.index if sent_ref else None,
                sentence_index_end=sent_ref.index if sent_ref else None,
            )
            flags.append(
                Flag(
                    flag_id=f"{self.code}-{idx:03d}",
                    severity=severity,
                    message=f"Light verb + nominalization: '{verb_text} ... {nom_text}'",
                    locator=flag_locator,
                    evidence={
                        "verb": verb_text,
                        "nominalization": nom_text,
                    },
                )
            )

        rationale = (
            f"{total_nominalizations} nominalizations across {total_sentences} sentences "
            f"({nom_per_sent:.2f}/sentence; warn at {warn_per_sent}, severe at {severe_per_sent}). "
            f"{light_verb_count} light-verb + nominalization patterns "
            f"({lv_per_1000:.1f}/1000 words; warn at {warn_lv}, severe at {severe_lv}). "
            f"{be_root_count}/{sents_with_root} sentences ({be_root_ratio:.0%}) "
            f"have 'to be' as the main verb."
        )

        return Finding(
            code=self.code,
            name=self.name,
            axis=self.axis,
            checked=True,
            summary=Summary(
                metric_name="nominalizations_per_sentence",
                metric_value=round(nom_per_sent, 3),
                threshold_warn=warn_per_sent,
                threshold_severe=severe_per_sent,
                score=score,
                rationale=rationale,
            ),
            measurements={
                "total_nominalizations": total_nominalizations,
                "nominalizations_per_sentence": round(nom_per_sent, 4),
                "suffix_breakdown": suffix_counts,
                "light_verb_nominalization_count": light_verb_count,
                "light_verb_nom_per_1000_words": round(lv_per_1000, 4),
                "be_main_verb_count": be_root_count,
                "be_main_verb_ratio": round(be_root_ratio, 4),
                "total_sentences": total_sentences,
                "word_count": word_count,
            },
            flags=flags,
            notes=[],
        )

    @staticmethod
    def _sentence_index_at(doc: Document, char_offset: int) -> int | None:
        for s in doc.sentences:
            if s.char_start <= char_offset < s.char_end:
                return s.index
        return None


register_check(NominalizationCheck())
