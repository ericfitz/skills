"""Census of test files, with the signals behind each kind guess."""

import fnmatch
from pathlib import Path, PurePosixPath

TEST_DIR_NAMES = {
    "test", "tests", "spec", "specs", "__tests__", "testing",
    "e2e", "integration", "it", "itest", "functional", "acceptance",
    "contract", "endtoend", "end_to_end",
}

INTEGRATION_DIRS = {"integration", "it", "itest", "functional", "acceptance", "contract"}
E2E_DIRS = {"e2e", "endtoend", "end_to_end"}

# (glob, language)
NAME_PATTERNS = (
    ("test_*.py", "python"), ("*_test.py", "python"),
    ("*_test.go", "go"),
    ("*.test.ts", "typescript"), ("*.test.tsx", "typescript"),
    ("*.spec.ts", "typescript"), ("*.spec.tsx", "typescript"),
    ("*.test.js", "javascript"), ("*.spec.js", "javascript"),
    ("*Test.java", "java"), ("*Tests.java", "java"),
    ("*Tests.cs", "csharp"),
    ("*_spec.rb", "ruby"), ("*_test.rb", "ruby"),
    ("*_test.rs", "rust"),
    ("*_test.exs", "elixir"),
)

# (signal name, kind, substrings that trigger it)
CONTENT_MARKERS = (
    ("marker:pytest.mark.integration", "integration", ("pytest.mark.integration",)),
    ("marker:pytest.mark.e2e", "e2e", ("pytest.mark.e2e",)),
    ("buildtag:integration", "integration",
     ("//go:build integration", "// +build integration")),
    ("buildtag:e2e", "e2e", ("//go:build e2e", "// +build e2e")),
    ("marker:testcontainers", "integration", ("testcontainers",)),
)

_KIND_BY_SIGNAL = {name: kind for name, kind, _ in CONTENT_MARKERS}


def _name_signals(path):
    """Return (signals, language) for path, or ([], None) if it is not a test file."""
    parsed = PurePosixPath(path)
    signals = [
        "dir:%s" % part for part in parsed.parts[:-1] if part in TEST_DIR_NAMES
    ]
    language = None
    for pattern, pattern_language in NAME_PATTERNS:
        if fnmatch.fnmatch(parsed.name, pattern):
            signals.append("name:%s" % pattern)
            language = pattern_language
            break
    if not signals:
        return [], None
    return signals, language


def _content_signals(full_path, max_bytes):
    try:
        text = Path(full_path).read_text(encoding="utf-8", errors="replace")[:max_bytes]
    except OSError:
        return []
    return [
        name for name, _, needles in CONTENT_MARKERS
        if any(needle in text for needle in needles)
    ]


def _resolve_kind(signals):
    dirs = {signal.split(":", 1)[1] for signal in signals if signal.startswith("dir:")}
    kinds = {_KIND_BY_SIGNAL[s] for s in signals if s in _KIND_BY_SIGNAL}
    if dirs & E2E_DIRS or "e2e" in kinds:
        return "e2e"
    if dirs & INTEGRATION_DIRS or "integration" in kinds:
        return "integration"
    if any(signal.startswith("name:") for signal in signals):
        return "unit"
    return "unknown"


def classify_test_files(root, paths, max_bytes=4096):
    """Return one record per test file, with the signals behind its kind."""
    root = Path(root)
    records = []
    for path in paths:
        signals, language = _name_signals(path)
        if not signals:
            continue
        signals = signals + _content_signals(root / path, max_bytes)
        records.append({
            "path": path,
            "language": language,
            "kind": _resolve_kind(signals),
            "signals": sorted(set(signals)),
        })
    return records


def test_dirs(records):
    """Return the unique sorted parent directories of test-file records."""
    return sorted({PurePosixPath(r["path"]).parent.as_posix() for r in records})
