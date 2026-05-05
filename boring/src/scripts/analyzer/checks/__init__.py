"""Check registry.

The registry is the extensibility seam. Each check module registers itself
on import via `register_check`. The pipeline iterates the registry in
deterministic order (by check code) and runs each check.

Adding a new check:
    1. Create a new file in this package: e.g. `d2_5_obvious_claims.py`.
    2. Define a class with class-level `code`, `name`, `axis` attributes
       and a `run(doc, config)` method returning a Finding.
    3. At the bottom of the file, call `register_check(MyCheck())`.
    4. Import the module from this __init__.py so it loads.
    5. Add corresponding thresholds to calibration.toml.
"""
from __future__ import annotations

from .base import Check, DeferredCheck

_registry: dict[str, Check] = {}
_deferred: dict[str, DeferredCheck] = {}


def register_check(check: Check) -> None:
    """Register a check. Idempotent within a process."""
    if check.code in _registry:
        if _registry[check.code] is check:
            return
        raise ValueError(
            f"Check code {check.code!r} already registered with a different instance"
        )
    _registry[check.code] = check


def register_deferred(deferred: DeferredCheck) -> None:
    """Register a sub-dimension the script intentionally does not check."""
    if deferred.code in _deferred:
        return
    _deferred[deferred.code] = deferred


def all_checks() -> list[Check]:
    """Return all registered checks in deterministic (code-sorted) order."""
    return [_registry[k] for k in sorted(_registry)]


def all_deferred() -> list[DeferredCheck]:
    """Return all registered deferred sub-dimensions in code-sorted order."""
    return [_deferred[k] for k in sorted(_deferred)]


# ---------------------------------------------------------------------------
# Import all check modules here so they self-register on package import.
# ---------------------------------------------------------------------------

# Direction axis: D1.1, D1.4, D1.6 to be added.
# Density axis: D2.1, D2.2, D2.3, D2.4, D2.7, D2.8.
# Texture axis: D3.1; D3.3, D3.4, D3.5 to be added.
# Surprise axis: D4.4 to be added; D4.1 is medium priority.
# Deferred (LLM-only) sub-dimensions: _deferred_decls.
from . import (  # noqa: E402, F401
    _deferred_decls,
    d1_1_buried_thesis,
    d1_4_signposting,
    d1_6_topic_drift,
    d2_1_padding,
    d2_2_nominalization,
    d2_3_passive,
    d2_4_sv_gap,
    d2_7_hedging,
    d2_8_throat_clearing,
    d3_1_sentence_length,
    d3_3_opener_monotony,
    d3_4_paragraph_monotony,
    d3_5_vocabulary_flatness,
    d4_1_concrete_examples,
    d4_4_specificity,
)
