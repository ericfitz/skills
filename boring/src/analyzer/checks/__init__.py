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

# Direction axis
# (none implemented in v1 scaffold yet — D1.1, D1.4, D1.6 to be added)

# Density axis
from . import d2_1_padding          # noqa: E402,F401
from . import d2_3_passive  # noqa: E402,F401
from . import d2_4_sv_gap   # noqa: E402,F401
from . import d2_7_hedging          # noqa: E402,F401
from . import d2_8_throat_clearing  # noqa: E402,F401

# Texture axis
from . import d3_1_sentence_length  # noqa: E402,F401

# Surprise axis
# (D4.4 to be added; D4.1 is medium priority)

# Deferred (LLM-only) sub-dimensions
from . import _deferred_decls  # noqa: E402,F401
