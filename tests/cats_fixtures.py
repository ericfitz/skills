"""Shared fixtures for tests/test_cats_*.py.

Single source of truth for the CATS JSON record shape, the config YAML used to
build a `Config`, and the temp-directory helpers that every cats test module
was previously redefining (with subtly different payloads/signatures — see the
whole-branch review that asked for this consolidation).

This matters beyond ordinary DRY: `catslib.parse.record_from_json` and
`catslib.classify.record_from_db` must agree on the normalized record shape
for the same input — that agreement is this branch's central cross-module
invariant, and it can only be tested meaningfully if both sides start from the
same fixture data (see test_cats_classify.TestRecordEquivalence).
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from catslib import parse as P
from catslib import rules as R


def cats_json(**over: Any) -> dict[str, Any]:
    """Build one CATS report record; override any top-level field via kwargs.

    To change a single nested `request`/`response` field without losing the
    rest, spread the original, e.g.
    `cats_json(response={**cats_json()["response"], "responseCode": 500})`.
    """
    data: dict[str, Any] = {
        "testId": "Test 1", "traceId": "t-1", "fuzzer": "HappyPath",
        "path": "/things", "contractPath": "/things", "fullRequestPath": "/things",
        "scenario": "happy", "expectedResult": "Should return 200",
        "result": "error", "resultReason": "Unexpected Response Code: 400",
        "resultDetails": "details", "server": "http://h",
        "request": {"httpMethod": "POST", "url": "http://h/things",
                     "timestamp": "2026-07-26T00:00:00Z", "payload": '{"a":1}',
                     "headers": [{"key": "Accept", "value": "application/json"}]},
        "response": {"httpMethod": "POST", "responseCode": 400, "responseTimeInMs": 12,
                      "numberOfWordsInResponse": 3, "numberOfLinesInResponse": 1,
                      "contentLengthInBytes": 42, "responseContentType": "application/json",
                      "jsonBody": {"error": "bad", "error_description": "bad enum_values"},
                      "headers": [{"key": "Content-Type", "value": "application/json"}]},
    }
    data.update(over)
    return data


# A config.yaml body covering every `cats:` option, used by tests that only
# need *a* valid, loadable Config (most of test_cats_tool.py) as well as ones
# that exercise specific fields (test_cats_runner.py's argv-building and
# identity-switching tests, via CONFIG.replace(...)).
CONFIG = """
version: 1
spec: openapi.json
server: http://localhost:8080
results_dir: results
false_positives: fp.yaml
identities:
  admin: {token_cmd: "printf secret-token"}
  other: {token_cmd: "printf other-token"}
default_identity: admin
cats:
  max_requests_per_minute: 500
  skip_fuzzers: [DuplicateHeaders, EnumCaseVariantFields]
  skip_field_format: [uuid]
  skip_field: [offset]
  skip_fuzzers_for_extension:
    - {extension: x-public-endpoint, value: "true", fuzzers: [BypassAuthentication]}
  extra_args: ["--printExecutionStatistics"]
"""


def _tmp_dir(case: unittest.TestCase) -> Path:
    """A TemporaryDirectory cleaned up when `case` tears down."""
    d = tempfile.TemporaryDirectory()
    case.addCleanup(d.cleanup)
    return Path(d.name)


def _module_tmp_dir() -> Path:
    """A TemporaryDirectory whose cleanup is deferred to end-of-module.

    For plain module-level helpers (`build_db`, `write_rules`) that aren't
    TestCase methods and so have no `case` to register a per-test addCleanup
    against. `addModuleCleanup` is unittest's module-level equivalent and runs
    once after every test in the importing module has finished.
    """
    d = tempfile.TemporaryDirectory()
    unittest.addModuleCleanup(d.cleanup)
    return Path(d.name)


def make_config(case: unittest.TestCase, body: str = CONFIG):
    """Write `body` as .local/cats/config.yaml under a fresh temp repo root,
    with the spec and rules files it references, and load it."""
    from catslib import config as cfg

    root = _tmp_dir(case)
    (root / ".local" / "cats").mkdir(parents=True)
    p = root / ".local" / "cats" / "config.yaml"
    p.write_text(body)
    (root / "openapi.json").write_text("{}")
    (root / "fp.yaml").write_text("version: 1\nrules: []\n")
    return cfg.load_config(p)


def build_db(tests: list[dict[str, Any]]) -> Path:
    """Parse a list of CATS JSON records into a fresh SQLite database."""
    report = _module_tmp_dir()
    for i, data in enumerate(tests, 1):
        (report / f"Test{i}.json").write_text(json.dumps(data))
    db = _module_tmp_dir() / "r.db"
    P.parse_report(report, db, {"run_id": "R1"})
    return db


def write_rules(text: str) -> list[R.Rule]:
    path = _module_tmp_dir() / "rules.yaml"
    path.write_text(text)
    return R.load_rules(path)


ONE_RULE = (
    "version: 1\nrules:\n  - id: VALIDATION_400\n    why: correct rejection\n"
    "    when: {response_code: 400}\n"
)
