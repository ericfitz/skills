# tests/test_dependency_model_references.py
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                       / "dependency-model" / "scripts"))

from depscanlib.source import RESILIENCE_PATTERNS

REPO = Path(__file__).resolve().parents[1]
REFERENCES = REPO / "dependency-model" / "references"
CATEGORIES = ["config", "network", "package", "platform", "security", "service"]


class TestReferencesExist(unittest.TestCase):
    def test_the_three_references_are_present(self):
        for name in ("categories.md", "resilience-signatures.md",
                     "running-discovery.md"):
            with self.subTest(reference=name):
                self.assertTrue((REFERENCES / name).exists())


class TestCategoriesReference(unittest.TestCase):
    def test_names_every_category(self):
        text = (REFERENCES / "categories.md").read_text(encoding="utf-8").lower()
        for category in CATEGORIES:
            with self.subTest(category=category):
                self.assertIn(category, text)

    def test_carries_the_service_network_adjudication_rule(self):
        text = (REFERENCES / "categories.md").read_text(encoding="utf-8").lower()
        self.assertIn("related_ids", text)
        self.assertIn("the thing depended on", text)
        self.assertIn("the path used to reach it", text)


class TestResilienceSignatures(unittest.TestCase):
    def test_documents_all_three_in_scope_ecosystems(self):
        text = (REFERENCES / "resilience-signatures.md").read_text(
            encoding="utf-8").lower()
        for language in ("go", "typescript", "python"):
            with self.subTest(language=language):
                self.assertIn(language, text)

    def test_states_that_null_is_not_confirmed_absent(self):
        text = (REFERENCES / "resilience-signatures.md").read_text(
            encoding="utf-8").lower()
        self.assertIn("no declaration was found", text)


# One sample source line per documented row, keyed by the row's pattern cell
# exactly as written in resilience-signatures.md.
DOC_SAMPLES = {
    "go": {
        "`context.WithTimeout`": "ctx, c := context.WithTimeout(p, time.Second)",
        "`context.WithDeadline`": "ctx, c := context.WithDeadline(p, d)",
        "A `Timeout:` struct field (e.g. `http.Client{Timeout: ...}`)":
            "c := http.Client{Timeout: 5 * time.Second}",
        "`backoff.*` (e.g. `backoff.Retry`, `cenkalti/backoff`)":
            "err := backoff.Retry(op, b)",
        "`retry.*` (e.g. `avast/retry-go`)": "err := retry.Do(fn)",
        "`gobreaker` (`sony/gobreaker`)": 'import "github.com/sony/gobreaker"',
    },
    "python": {
        "`timeout=` keyword argument (e.g. `requests.get(url, timeout=5)`, "
        "`httpx.Client(timeout=...)`)": "requests.get(url, timeout=5)",
        "`@retry` decorator": "@retry(stop=stop_after_attempt(3))",
        "`tenacity` (import or `Retrying(...)` construction)":
            "import tenacity",
        "`pybreaker` (`CircuitBreaker(...)`)": "import pybreaker",
    },
    "js": {
        "`AbortSignal.timeout(...)`": "const s = AbortSignal.timeout(2000)",
        "A `timeout:` option (e.g. in an axios or fetch-wrapper config object)":
            "axios.create({ timeout: 3000 })",
        "`p-retry` (import or `pRetry(...)` call)":
            "import pRetry from 'p-retry'",
        "`opossum` (circuit breaker construction)":
            "const b = new CircuitBreaker(fn) // opossum",
    },
}
DOC_HEADINGS = {"Go": "go", "Python": "python", "TypeScript / JavaScript": "js"}


def doc_rows():
    """Return {language: [(pattern cell, kind), ...]} from the three tables."""
    rows, language = {}, None
    text = (REFERENCES / "resilience-signatures.md").read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith("## "):
            language = DOC_HEADINGS.get(line[3:].strip())
            if language:
                rows[language] = []
        elif language and line.startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) == 2 and cells[0] != "Pattern" and \
                    not set(cells[0]) <= {"-"}:
                rows[language].append((cells[0], cells[1].strip("`")))
    return rows


class TestResilienceSignaturesMatchCode(unittest.TestCase):
    def test_every_language_table_is_parsed(self):
        self.assertEqual(sorted(doc_rows()), sorted(DOC_SAMPLES))

    def test_ts_aliases_js(self):
        self.assertIs(RESILIENCE_PATTERNS["ts"], RESILIENCE_PATTERNS["js"])

    def test_each_row_has_a_sample_and_each_sample_a_row(self):
        for language, rows in doc_rows().items():
            with self.subTest(language=language):
                self.assertEqual({cell for cell, _ in rows},
                                 set(DOC_SAMPLES[language]))
                self.assertEqual(len(rows), len({cell for cell, _ in rows}))

    def test_each_row_sample_matches_exactly_one_pattern_with_the_kind(self):
        for language, rows in doc_rows().items():
            for cell, kind in rows:
                with self.subTest(language=language, row=cell):
                    sample = DOC_SAMPLES[language][cell]
                    hits = [k for pattern, k in RESILIENCE_PATTERNS[language]
                            if pattern.search(sample)]
                    self.assertEqual(hits, [kind])

    def test_every_pattern_is_documented_by_some_row(self):
        for language, rows in doc_rows().items():
            with self.subTest(language=language):
                covered = set()
                for cell, _ in rows:
                    sample = DOC_SAMPLES[language][cell]
                    covered.update(
                        i for i, (pattern, _) in
                        enumerate(RESILIENCE_PATTERNS[language])
                        if pattern.search(sample))
                self.assertEqual(covered,
                                 set(range(len(RESILIENCE_PATTERNS[language]))))


class TestRunningDiscovery(unittest.TestCase):
    def test_documents_the_sequence_and_the_deferred_orchestrator(self):
        text = (REFERENCES / "running-discovery.md").read_text(encoding="utf-8")
        self.assertIn("profile:topology", text)
        self.assertIn("depscan.py", text)
        for category in CATEGORIES:
            with self.subTest(category=category):
                self.assertIn(f"/dependency-model:{category}", text)
        self.assertIn("no orchestrator", text.lower())

    def test_documents_the_python3_fallback(self):
        text = (REFERENCES / "running-discovery.md").read_text(encoding="utf-8")
        self.assertIn("python3", text)


class TestDefinitions(unittest.TestCase):
    def test_definitions_exists(self):
        self.assertTrue((REFERENCES / "definitions.md").exists())

    def test_states_the_two_senses_and_the_superset_relation(self):
        text = (REFERENCES / "definitions.md").read_text(encoding="utf-8").lower()
        self.assertIn("build", text)
        self.assertIn("run", text)
        self.assertIn("superset", text)
        self.assertIn("devdependencies", text)

    def test_states_the_failability_test_for_health(self):
        text = (REFERENCES / "definitions.md").read_text(encoding="utf-8").lower()
        self.assertIn("fail independently while the process is up", text)

    def test_carries_the_taxonomy_as_prose_and_marks_it_undefined(self):
        text = (REFERENCES / "definitions.md").read_text(encoding="utf-8").lower()
        for word in ("healthy", "degraded", "unhealthy"):
            self.assertIn(word, text)
        self.assertIn("not yet technically defined", text)


class TestCategoriesIdsRule(unittest.TestCase):
    def test_categories_ids_rule(self):
        text = (REFERENCES / "categories.md").read_text(encoding="utf-8")
        self.assertIn("ids.json", text)
        self.assertIn("parenthesized group", text)
        flat = " ".join(text.split())
        self.assertIn("never shortens", flat)


if __name__ == "__main__":
    unittest.main()
