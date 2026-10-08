"""Curated word and phrase lists used by multiple checks.

Each list is a tuple of lowercase strings. Multi-word phrases are matched
as whole-word sequences (case-insensitive, word-boundary aware) by the
helpers below.

When updating a list, prefer additions over deletions: a noisy match can
be filtered downstream by the LLM phase, but a missed match is invisible.
The lists are intentionally narrow (high-precision) rather than broad —
proselint covers the long tail of wordy/cliched phrasing (see
`proselint_wrap`); these lists target the specific patterns that show up
in technical business writing.
"""
from __future__ import annotations

import re
from typing import Iterable

# ---------------------------------------------------------------------------
# D2.7 — Hedging
# ---------------------------------------------------------------------------
#
# Single-word hedges and short hedge phrases. Detected as standalone tokens
# (or whole phrases). One occurrence in a sentence is usually fine; two or
# more in the same sentence is "stacked hedging" — almost always cuttable.

HEDGE_WORDS: tuple[str, ...] = (
    # epistemic adverbs
    "perhaps", "possibly", "probably", "arguably", "presumably",
    "apparently", "seemingly", "ostensibly", "supposedly",
    "maybe", "potentially", "conceivably",
    # epistemic adjectives / quantifiers of certainty
    "likely", "unlikely",
    # softeners
    "somewhat", "fairly", "rather", "quite", "relatively",
    "generally", "typically", "usually", "often", "sometimes",
    "broadly", "largely", "mostly",
    # approximate
    "approximately", "roughly", "about", "around",
    # epistemic verbs in light use
    "seems", "appears",
)

HEDGE_PHRASES: tuple[str, ...] = (
    "to some extent",
    "to some degree",
    "in some sense",
    "in many cases",
    "in some cases",
    "in certain cases",
    "in general",
    "for the most part",
    "more or less",
    "kind of",
    "sort of",
    "it could be argued",
    "it could be argued that",
    "it might be argued",
    "it might be argued that",
    "it has been suggested",
    "it has been suggested that",
    "there is some evidence",
    "there is evidence to suggest",
    "evidence suggests",
    "we believe",
    "we think",
    "we feel",
    "in our view",
    "in our opinion",
    "from our perspective",
    "as far as we can tell",
)


# ---------------------------------------------------------------------------
# D2.8 — Throat-clearing
# ---------------------------------------------------------------------------
#
# Phrases that exist only to introduce other content. Most damaging at the
# start of a sentence or paragraph; somewhat damaging mid-sentence.

THROAT_CLEARING_OPENERS: tuple[str, ...] = (
    # meta-commentary
    "it is important to note that",
    "it is worth noting that",
    "it is interesting to note that",
    "it should be noted that",
    "it must be noted that",
    "it bears mentioning that",
    "it bears noting that",
    "it goes without saying that",
    "it is worth pointing out that",
    "it is worth mentioning that",
    "needless to say",
    "as you may know",
    "as you might expect",
    "as we all know",
    "as is well known",
    "as previously mentioned",
    "as mentioned previously",
    "as mentioned earlier",
    "as mentioned above",
    "as discussed previously",
    "as discussed earlier",
    "as discussed above",
    "as noted previously",
    "as noted earlier",
    "as noted above",
    "as stated previously",
    "as stated earlier",
    "as stated above",
    # opening filler
    "in recent years",
    "in today's world",
    "in this day and age",
    "in modern times",
    "in the modern era",
    "in the world of today",
    "in the current landscape",
    "in the current environment",
    "in the current climate",
    "throughout history",
    "since the dawn of time",
    "since time immemorial",
    # roadmap throat-clearing (when it's redundant with the heading)
    "this section will discuss",
    "this section discusses",
    "this section will cover",
    "this section covers",
    "this section will describe",
    "this section describes",
    "this section will examine",
    "this section examines",
    "the following section will discuss",
    "the next section will discuss",
    "the next section will cover",
    "the next section will describe",
    "in this section we will discuss",
    "in this section we discuss",
    "in this section we will describe",
    "in this section we describe",
    "in this section we will examine",
    "in this section we examine",
    "the purpose of this section is",
    "the purpose of this document is",
    "the goal of this document is",
    "the aim of this document is",
    "this document will discuss",
    "this document discusses",
    "this document describes",
    "this document will describe",
    "this document covers",
    "this document will cover",
    # rhetorical filler
    "first and foremost",
    "last but not least",
    "without further ado",
    "with that being said",
    "with that said",
    "having said that",
    "that being said",
    "that said",
)


# ---------------------------------------------------------------------------
# D4.4 — Vague quantifiers / fuzzy modifiers
# ---------------------------------------------------------------------------
#
# Quantifiers and modifiers that promise specificity without delivering it.
# "We saw significant improvements" tells the reader nothing — "47%" tells
# them everything.

VAGUE_QUANTIFIERS: tuple[str, ...] = (
    "various", "several", "many", "numerous", "multiple",
    "different", "diverse", "varied",
    "some", "a number of", "a variety of", "a range of",
    "a few", "a handful of", "a couple of",
    "certain", "particular",
    "most", "much",
)

VAGUE_INTENSIFIERS: tuple[str, ...] = (
    "significant", "significantly",
    "substantial", "substantially",
    "considerable", "considerably",
    "meaningful", "meaningfully",
    "notable", "notably",
    "important", "importantly",
    "critical", "critically",
    "key",
    "major",
    "appreciable", "appreciably",
    "marked", "markedly",
    "dramatic", "dramatically",
    "tremendous", "tremendously",
    "enormous", "enormously",
)

VAGUE_MODIFIERS: tuple[str, ...] = (
    "modern", "contemporary", "current",
    "advanced", "sophisticated", "cutting-edge", "state-of-the-art",
    "robust", "scalable", "flexible", "powerful",
    "efficient", "effective",
    "appropriate", "suitable", "adequate",
    "various stakeholders", "key stakeholders", "relevant stakeholders",
    "industry-leading", "best-in-class", "world-class",
    "innovative", "novel",
)

# Combined for D4.4 detection. Categorized for measurements breakdown.
VAGUE_TERMS_BY_CATEGORY: dict[str, tuple[str, ...]] = {
    "quantifier": VAGUE_QUANTIFIERS,
    "intensifier": VAGUE_INTENSIFIERS,
    "modifier": VAGUE_MODIFIERS,
}


# ---------------------------------------------------------------------------
# D4.1 — Concrete-example markers
# ---------------------------------------------------------------------------
#
# Phrases that introduce a concrete instance. Their *presence* is the signal
# (a paragraph that contains "for example" is grounded; one that doesn't may
# not be — combined with entity/number checks).

EXAMPLE_MARKERS: tuple[str, ...] = (
    "for example",
    "for instance",
    "e.g.",
    "such as",
    "including",
    "in particular",
    "specifically",
    "to illustrate",
    "as an example",
    "as an illustration",
    "consider",
    "imagine",
    "suppose",
    "take the case of",
    "take for example",
    "take, for example",
    "case in point",
    "namely",
    "to wit",
    "viz.",
)


# ---------------------------------------------------------------------------
# D1.4 — Transition / signposting markers
# ---------------------------------------------------------------------------
#
# Words and phrases that cue logical structure. Their density at section
# boundaries is a primary signpost signal.

TRANSITION_MARKERS: tuple[str, ...] = (
    # contrast
    "however", "nevertheless", "nonetheless", "in contrast",
    "by contrast", "on the other hand", "on the contrary",
    "conversely", "instead", "yet",
    "despite", "in spite of", "although", "though",
    # cause/effect
    "therefore", "thus", "hence", "consequently",
    "as a result", "as a consequence", "because of this",
    "for this reason", "for these reasons",
    "accordingly", "so",
    # building / continuation
    "building on", "building on this", "extending this",
    "in addition", "additionally", "moreover", "furthermore",
    "what is more", "beyond this", "beyond that",
    # sequencing
    "first", "firstly", "second", "secondly", "third", "thirdly",
    "next", "then", "finally", "lastly",
    "to begin with", "to start", "in conclusion",
    # restating / clarifying
    "in other words", "that is to say", "put differently",
    "to put it another way", "in short", "in summary",
    "to summarize", "to sum up",
    # specifying
    "in particular", "specifically", "notably",
    # given/known
    "given this", "given that", "given these",
    "with this in mind", "with that in mind",
    # comparison
    "similarly", "likewise", "in the same way", "in the same vein",
    "by comparison",
)


# ---------------------------------------------------------------------------
# D1.1 — Claim markers
# ---------------------------------------------------------------------------
#
# Patterns that suggest a sentence is making a claim/recommendation/finding
# (rather than describing background or methods). Used to locate the first
# claim-shaped sentence for buried-thesis detection.

CLAIM_VERBS: tuple[str, ...] = (
    # recommendation
    "recommend", "propose", "suggest", "advise", "advocate",
    "urge", "call for",
    # finding
    "find", "found", "conclude", "determined", "discovered",
    "show", "shows", "showed", "demonstrate", "demonstrates", "demonstrated",
    "argue", "argues", "argued", "contend", "contends", "claim", "claims",
    "establish", "establishes", "established",
    # decision
    "decided", "selected", "chose", "chosen",
    "adopt", "adopts", "adopted",
)

# Strong-claim openers (sentence-initial constructions that signal a thesis).
CLAIM_OPENERS: tuple[str, ...] = (
    "we recommend",
    "we propose",
    "we suggest",
    "we advise",
    "we conclude",
    "we find",
    "we found",
    "we determined",
    "we discovered",
    "we argue",
    "we contend",
    "we claim",
    "we believe",
    "we will",
    "we should",
    "we must",
    "this document recommends",
    "this report recommends",
    "this report concludes",
    "this report finds",
    "this paper argues",
    "this paper concludes",
    "the recommendation is",
    "our recommendation is",
    "our finding is",
    "the bottom line is",
    "in short,",
    "in summary,",
    "tl;dr",
    "tldr",
)

# Modal-of-obligation patterns (indirect claims).
OBLIGATION_MODALS: tuple[str, ...] = (
    "must", "should", "ought to", "needs to", "need to",
    "has to", "have to",
)


# ---------------------------------------------------------------------------
# Matching helpers
# ---------------------------------------------------------------------------
#
# All matching is case-insensitive and respects word boundaries. Phrases
# may contain punctuation (e.g., "e.g.", "tldr") — we escape and use \b
# only where it makes sense.


def _phrase_pattern(phrases: Iterable[str]) -> re.Pattern[str]:
    """Compile a regex that matches any of the given phrases as whole words.

    Phrases are sorted longest-first so multi-word phrases win over their
    single-word prefixes.
    """
    sorted_phrases = sorted(set(phrases), key=lambda s: -len(s))
    parts: list[str] = []
    for phrase in sorted_phrases:
        # Escape, then convert internal whitespace to \s+ (one or more spaces)
        escaped = re.escape(phrase)
        escaped = re.sub(r"\\\s+", r"\\s+", escaped)
        # Add word boundaries only where the phrase starts/ends with a word char
        prefix = r"(?<!\w)" if phrase[:1].isalnum() else ""
        suffix = r"(?!\w)" if phrase[-1:].isalnum() else ""
        parts.append(f"{prefix}{escaped}{suffix}")
    pattern = "|".join(parts)
    return re.compile(pattern, re.IGNORECASE)


def find_phrase_matches(text: str, phrases: Iterable[str]) -> list[tuple[int, int, str]]:
    """Return (char_start, char_end, matched_text) for each phrase match in text.

    Matches are non-overlapping and returned in document order.
    """
    pat = _phrase_pattern(phrases)
    out: list[tuple[int, int, str]] = []
    for m in pat.finditer(text):
        out.append((m.start(), m.end(), m.group(0)))
    return out


def find_phrase_matches_at_starts(
    text: str,
    phrases: Iterable[str],
    starts: Iterable[int],
    max_lookahead: int = 80,
) -> list[tuple[int, int, str, int]]:
    """Return matches that begin within max_lookahead chars of one of the
    given start offsets, after skipping leading whitespace and (optional)
    markdown heading prefix.

    Used for "phrases at sentence/paragraph openers". Returns
    (char_start, char_end, matched_text, anchor_start) per hit.
    """
    pat = _phrase_pattern(phrases)
    out: list[tuple[int, int, str, int]] = []
    for anchor in starts:
        # Skip leading whitespace
        cur = anchor
        n = len(text)
        while cur < n and text[cur].isspace():
            cur += 1
        # Skip a leading markdown heading prefix (#, ##, ...) if present
        if cur < n and text[cur] == "#":
            while cur < n and text[cur] == "#":
                cur += 1
            while cur < n and text[cur] == " ":
                cur += 1
        # Search a small window after the anchor
        window_end = min(n, cur + max_lookahead)
        for m in pat.finditer(text, cur, window_end):
            # Only count matches that start at or very near the anchor (within
            # one or two leading words of filler).
            if m.start() - cur <= 24:
                out.append((m.start(), m.end(), m.group(0), anchor))
                break
    return out
