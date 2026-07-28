"""Test package.

Each tool tree keeps its library under `<tool>/scripts/`, and the tests import
those libraries by name (`catslib`, `bumplib`, `logseqlib`, `sem_*`). Putting
those directories on `sys.path` here means the individual test modules do not
each need a `sys.path.insert()` preamble before their imports.

pytest is additionally told about these paths via `[tool.pytest.ini_options]
pythonpath` in pyproject.toml, but unittest honours no such setting -- it does
import this package first, though, so doing the work here covers both runners.

Because the setup runs on *package import*, every entry point has to import
the modules as `tests.<name>` rather than as top-level modules:

    uv run pytest
    uv run python -m unittest discover                  # from the repo root
    uv run python -m unittest discover -s tests -t .    # explicit top-level dir
    uv run python -m unittest tests.test_cats_rules     # single module

`discover -s tests` *without* `-t .` does not work: unittest then treats
tests/ as the top-level directory and imports the modules as top-level names,
so this file never runs and every `catslib`/`bumplib`/... import fails.
Likewise `python tests/test_cats_rules.py` no longer works on its own; use
the `-m tests.test_cats_rules` form above.
"""

import sys
from pathlib import Path

# Process-global, and set here rather than per-module so that test files can
# keep an unbroken import block at the top (no E402).
sys.dont_write_bytecode = True

_ROOT = Path(__file__).resolve().parents[1]

# `tests` itself is included so modules can `import cats_fixtures` directly.
for _rel in ("cats/scripts", "deps/scripts", "logseq/scripts", "dev/scripts", "tests"):
    _path = str(_ROOT / _rel)
    if _path not in sys.path:
        sys.path.insert(0, _path)
