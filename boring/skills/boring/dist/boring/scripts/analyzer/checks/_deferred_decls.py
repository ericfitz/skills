"""Declarations of sub-dimensions the script intentionally does not check.

These are the LLM-only checks. The script emits them in the
`deferred_to_llm` block of the JSON output, so the LLM phase knows which
sub-dimensions it owns.

Some carry cheap "hints" — signals the script can compute that may help
the LLM's judgment. Hints are suggestive, not authoritative.
"""
from __future__ import annotations

from . import register_deferred
from .base import DeferredCheck

register_deferred(
    DeferredCheck(
        code="D1.2",
        name="Missing stakes",
        axis="direction",
        reason="semantic_judgment_required",
    )
)

register_deferred(
    DeferredCheck(
        code="D1.5",
        name="Flat tension",
        axis="direction",
        reason="semantic_judgment_required",
    )
)

register_deferred(
    DeferredCheck(
        code="D2.5",
        name="Obvious claims",
        axis="density",
        reason="semantic_judgment_required",
    )
)

register_deferred(
    DeferredCheck(
        code="D4.2",
        name="No vivid imagery or analogy",
        axis="surprise",
        reason="semantic_judgment_required",
    )
)

register_deferred(
    DeferredCheck(
        code="D4.3",
        name="No counterintuitive claims",
        axis="surprise",
        reason="semantic_judgment_required",
    )
)
