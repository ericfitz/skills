"""Minimal JSON Schema subset validator, shared by the contract tests.

The implementation lives in discover/scripts/validate.py so the plugin
can ship it; this module re-exports it.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "discover" / "scripts"))

from validate import TYPE_CHECKS, resolve_refs, validate  # noqa: F401
