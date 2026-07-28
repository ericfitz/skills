"""Thin wrapper around proselint 0.16.

proselint 0.16 separated registry construction from registration: importing
the checks package only *builds* the tuple of checks; you still have to
register them on the singleton. We do that once on first use and cache
the lint results per Document so multiple checks can share one pass.

We disable proselint's own checks for hedging, weasel_words, and a few
others where our curated lists are tighter and we'd otherwise double-flag
the same span. See `_DISABLED_CHECK_PATHS`.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

# Names of proselint checks (matched as prefixes by proselint itself) we want
# to suppress because our curated lists in `word_lists` cover the same ground
# and we don't want both flagging the same span.
_DISABLED_CHECK_PATHS: tuple[str, ...] = (
    "hedging",  # ours: HEDGE_WORDS / HEDGE_PHRASES (D2.7)
    "weasel_words",  # ours: VAGUE_QUANTIFIERS / VAGUE_INTENSIFIERS (D4.4)
)

_registered = False


def _ensure_registered() -> None:
    """Populate proselint's singleton registry. Idempotent."""
    global _registered
    if _registered:
        return
    from proselint.checks import __register__ as built_checks  # ty:ignore[unresolved-import]
    from proselint.registry import (  # ty:ignore[unresolved-import]
        CheckRegistry,  # ty:ignore[unresolved-import]
    )

    reg = CheckRegistry()
    # Avoid double-registering across runs in the same process
    if not reg.checks:
        reg.register_many(built_checks)
    _registered = True


@dataclass
class ProselintHit:
    """A single proselint match, normalized for our use."""

    check_path: str  # e.g., "cliches.misc.write_good"
    message: str
    char_start: int
    char_end: int
    line: int
    col: int
    replacements: Any | None = None

    @property
    def category(self) -> str:
        """The top-level proselint check group (e.g., "cliches", "redundancy")."""
        return self.check_path.split(".", 1)[0]


def lint_text(text: str) -> list[ProselintHit]:
    """Run proselint over `text` and return normalized hits.

    Disabled check categories (see `_DISABLED_CHECK_PATHS`) are filtered
    out. Hits are returned in document order.
    """
    _ensure_registered()
    from proselint.tools import (  # ty:ignore[unresolved-import]
        DEFAULT,
        LintFile,
    )

    cfg = copy.deepcopy(DEFAULT)
    for path in _DISABLED_CHECK_PATHS:
        cfg["checks"][path] = False

    lf = LintFile("input.txt", text)
    raw = lf.lint(cfg)

    # proselint 0.16 returns spans that are shifted +1 relative to the input
    # (see proselint/tools.py find_spans / check_with_flags). We compensate
    # so callers get spans that index directly into the original text.
    hits: list[ProselintHit] = []
    for r in raw:
        cr = r.check_result
        line, col = r.pos
        start = max(0, cr.span[0] - 1)
        end = max(start, cr.span[1] - 1)
        hits.append(
            ProselintHit(
                check_path=cr.check_path,
                message=cr.message,
                char_start=start,
                char_end=end,
                line=line,
                col=col,
                replacements=cr.replacements,
            )
        )
    return hits


# A small Document-keyed cache. Checks that share the same Document instance
# in a single run will only invoke proselint once.
_doc_cache: dict[int, list[ProselintHit]] = {}


def lint_document(doc: Any) -> list[ProselintHit]:
    """Cached lint of `doc.extracted_text` keyed by id(doc)."""
    key = id(doc)
    if key in _doc_cache:
        return _doc_cache[key]
    hits = lint_text(doc.extracted_text)
    _doc_cache[key] = hits
    return hits


def filter_by_category(
    hits: list[ProselintHit], categories: tuple[str, ...]
) -> list[ProselintHit]:
    """Subset of hits whose top-level category is in `categories`."""
    cat_set = set(categories)
    return [h for h in hits if h.category in cat_set]
