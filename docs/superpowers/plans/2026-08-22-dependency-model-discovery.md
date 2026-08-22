# dependency-model Layer 1 (Discovery Skills + Contract Schemas) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A new `dependency-model` plugin with six read-only dependency-discovery skills (package, service, config, security, platform, network), one shared deterministic scan script, and the versioned contract schemas that layers 2–4 of #46 will consume — closing #48.

**Architecture:** One `depscan.py` walks the repo once and emits a raw evidence index; the five file-scanning skills read that index instead of re-walking, and the `package` skill shells out to `syft` with the index's exclusion list. Each skill applies LLM judgment to the raw evidence and emits a full `discovery` envelope with exactly one category populated, so layer 2's merge is a key union. Schemas share one core via local-file `$ref`, which requires a small extension to the repo's stdlib schema validator.

**Tech Stack:** Python 3.11+ (stdlib only in `depscanlib` — no PyYAML), `uv run --script` with a documented `python3` fallback, `syft` 1.51+, `unittest`, `pytest`, `ruff`, Claude/Codex plugin manifests.

**Spec:** `docs/superpowers/specs/2026-08-22-dependency-model-discovery-design.md`

## Global Constraints

Copied verbatim from the spec; every task's requirements implicitly include these.

- **Plugin name `dependency-model`**, version `0.1.0`, marketplace category `development`.
- **Contract version `1.0.0`**; scan version `1.0.0`; `requirements_version` `1.0.0`.
- **Static discovery only (D3).** Nothing is executed against the target system: no DNS resolution, no port probing, no latency measurement, no container boot, no build. `syft` is the sole subprocess, and it only reads files.
- **Evidence or assumption, never a guess.** Every factual claim carries `file:line`. The `package` category carries a file path only, with no line number (D7 — `syft` `locations[].path` is file-level). Anything inferred but unconfirmed goes in `assumptions[]` with a `why_unconfirmed`.
- **`null` in `resilience` means "no declaration found", never "confirmed absent".** This sentence, or an equivalent one, appears in every sub-schema description and every SKILL.md.
- **The security skill records names and locations, never values.** Never read a secret's contents. Never open files under `~/.keys/`. The `security` sub-schema permits no value-shaped field; tests enforce this at both the schema and the scanner level.
- **Source-literal scanning covers Go, TypeScript/JavaScript, and Python only (D9).** Out-of-scope languages are reported in the scan's `coverage.skipped`, and each affected skill records an assumption naming the language and what went unscanned.
- **`depscanlib` is stdlib-only.** `depscan.py` declares `dependencies = []` in its `uv run --script` header and must import cleanly under bare `python3`. No PyYAML, no third-party parsers.
- **`depscanlib` never imports `inventorylib`.** Plugins install independently, so a cross-plugin Python import would break at install time. Walk logic is deliberately duplicated.
- **Skills call each other by name, never by path.** No skill mentions `profile/scripts/` or `profile_inventory.py`. Standalone invocation bootstraps its own topology by invoking `profile:topology`.
- **No test strategy, no remediation, no criticality judgment.** Layer 1 reports facts.
- **`profile` is not modified** (#48 AC 4).
- Repo checks that must pass before every commit:

```bash
uv run ruff check .
uv run pytest -q
uv run scripts/gen_codex_manifests.py --check
bash scripts/verify-marketplace.sh
```

### Gotchas that will bite you

- `tests/test_plugin_structure.py::test_dispatching_skills_declare_no_subagent_fallback` — any SKILL.md containing the word "subagent" (or "sub-agent") must also contain the literal string `**No-subagent fallback:**`. The six skills here do not dispatch subagents; **do not use the word** in a SKILL.md body. It is fine in `references/running-discovery.md`.
- `tests/test_plugin_structure.py::test_relative_markdown_links_resolve` — relative markdown links from a SKILL.md resolve against the *skill's own directory*. Always link bundled files as `${CLAUDE_PLUGIN_ROOT}/references/...` in backticks, never as a markdown link.
- `tests/test_plugin_structure.py::test_plugin_root_references_resolve` — every `${CLAUDE_PLUGIN_ROOT}/...` path in a SKILL.md must exist on disk. Do not reference a file a later task creates.
- Creating `dependency-model/.claude-plugin/plugin.json` immediately arms `verify-marketplace.sh` (`DIR_COUNT`) and `test_plugin_structure.py`. That file is created in Task 10 together with every derived artifact, deliberately — earlier tasks build the plugin's contents without registering it, and stay green.
- `tests/test_env_declarations.py` globs `*/requirements.json` repo-wide. Adding `dependency-model/requirements.json` before its schema keys are right will fail the suite; it lands in Task 10.

---

### Task 1: Local-file `$ref` support in the shared schema validator

The six sub-schemas share one dependency core (D2). Duplicating that core into six files reintroduces exactly the drift `$ref` exists to prevent, so the repo's stdlib validator gains local-file `$ref` resolution first.

**Files:**
- Modify: `tests/schema_check.py` (add `resolve_refs`, extend `validate`)
- Test: `tests/test_schema_check_refs.py` (create)

**Interfaces:**
- Produces: `resolve_refs(schema: dict|list, base_dir: str|Path, _seen=None) -> dict|list` — returns a copy of `schema` with every local-file `$ref` replaced by its resolved target.
- Produces: `validate(instance, schema, path="$", base_dir=None) -> list[str]` — the existing signature plus an optional `base_dir`; when given, the schema is resolved once before validation. Recursive calls do not re-resolve.
- Consumed by: Task 2's `tests/test_dependency_model_contracts.py`.

Merge semantics for keys sitting alongside a `$ref` (JSON Schema 2020-12 allows siblings):
`properties` merge key-by-key with the sibling winning on collisions; `required` unions with target order first; every other key overrides outright.

- [ ] **Step 1: Write the failing test**

Create `tests/test_schema_check_refs.py`:

```python
# tests/test_schema_check_refs.py
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from schema_check import resolve_refs, validate

CORE = {
    "type": "object",
    "required": ["id", "name"],
    "properties": {
        "id": {"type": "string"},
        "name": {"type": "string"},
        "details": {"type": "object"},
    },
}


def write_schemas(tmp, extra=None):
    base = Path(tmp)
    (base / "core.schema.json").write_text(json.dumps(CORE), encoding="utf-8")
    for name, body in (extra or {}).items():
        (base / name).write_text(json.dumps(body), encoding="utf-8")
    return base


class TestResolveRefs(unittest.TestCase):
    def test_resolves_a_same_directory_ref(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = write_schemas(tmp)
            resolved = resolve_refs({"$ref": "core.schema.json"}, base)
            self.assertEqual(resolved, CORE)

    def test_sibling_properties_merge_and_keep_the_core(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = write_schemas(tmp)
            resolved = resolve_refs({
                "$ref": "core.schema.json",
                "properties": {"details": {"type": "object",
                                           "required": ["kind"]}},
            }, base)
            self.assertIn("id", resolved["properties"])
            self.assertIn("name", resolved["properties"])
            self.assertEqual(resolved["properties"]["details"]["required"], ["kind"])

    def test_sibling_required_unions_without_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = write_schemas(tmp)
            resolved = resolve_refs({
                "$ref": "core.schema.json",
                "required": ["name", "details"],
            }, base)
            self.assertEqual(resolved["required"], ["id", "name", "details"])

    def test_resolves_refs_nested_under_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = write_schemas(tmp)
            resolved = resolve_refs(
                {"type": "array", "items": {"$ref": "core.schema.json"}}, base)
            self.assertEqual(resolved["items"]["properties"]["id"],
                             {"type": "string"})

    def test_resolves_a_ref_inside_a_ref(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = write_schemas(tmp, {"outer.schema.json": {
                "type": "object",
                "properties": {"dep": {"$ref": "core.schema.json"}},
            }})
            resolved = resolve_refs({"$ref": "outer.schema.json"}, base)
            self.assertEqual(resolved["properties"]["dep"]["required"],
                             ["id", "name"])

    def test_remote_ref_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = write_schemas(tmp)
            with self.assertRaises(ValueError):
                resolve_refs({"$ref": "https://example.com/a.json"}, base)

    def test_json_pointer_fragment_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = write_schemas(tmp)
            with self.assertRaises(ValueError):
                resolve_refs({"$ref": "#/$defs/thing"}, base)

    def test_circular_ref_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "a.schema.json").write_text(
                json.dumps({"$ref": "b.schema.json"}), encoding="utf-8")
            (base / "b.schema.json").write_text(
                json.dumps({"$ref": "a.schema.json"}), encoding="utf-8")
            with self.assertRaises(ValueError):
                resolve_refs({"$ref": "a.schema.json"}, base)


class TestValidateWithBaseDir(unittest.TestCase):
    def test_base_dir_resolves_before_validating(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = write_schemas(tmp)
            schema = {"type": "array", "items": {"$ref": "core.schema.json"}}
            self.assertEqual(
                validate([{"id": "a", "name": "b"}], schema, base_dir=base), [])

    def test_base_dir_reports_violations_inside_the_referenced_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = write_schemas(tmp)
            schema = {"type": "array", "items": {"$ref": "core.schema.json"}}
            errors = validate([{"id": "a"}], schema, base_dir=base)
            self.assertEqual(len(errors), 1)
            self.assertIn("name", errors[0])

    def test_without_base_dir_behaviour_is_unchanged(self):
        schema = {"type": "object", "required": ["a"],
                  "properties": {"a": {"type": "string"}}}
        self.assertEqual(validate({"a": "x"}, schema), [])
        self.assertEqual(len(validate({}, schema)), 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_schema_check_refs.py -q`
Expected: collection error — `ImportError: cannot import name 'resolve_refs' from 'schema_check'`.

- [ ] **Step 3: Implement `resolve_refs` and extend `validate`**

In `tests/schema_check.py`, replace the module docstring and add the imports and the new function above `TYPE_CHECKS`:

```python
"""Minimal JSON Schema subset validator.

Supports type, properties, required, items, enum, and local-file $ref — the
subset the profile, itest, and dependency-model contracts actually use.
Unknown keywords are ignored by design. Exists because jsonschema is not
installed and this repo is stdlib-only.
"""

import json
from pathlib import Path


def resolve_refs(schema, base_dir, _seen=None):
    """Return schema with local-file $ref pointers replaced by their targets.

    Only same-directory-relative file refs are supported ("core.schema.json").
    Remote refs and JSON-pointer fragments raise ValueError rather than being
    silently ignored: a $ref the validator skips is a schema that passes
    everything, which is worse than no schema at all.

    Keys sitting alongside a $ref are merged over the resolved target:
    `properties` merge key-by-key, `required` unions with the target's order
    first, everything else overrides.
    """
    if isinstance(schema, list):
        return [resolve_refs(item, base_dir, _seen) for item in schema]
    if not isinstance(schema, dict):
        return schema
    if "$ref" not in schema:
        return {key: resolve_refs(value, base_dir, _seen)
                for key, value in schema.items()}

    ref = schema["$ref"]
    if "://" in ref or ref.startswith("#"):
        raise ValueError(
            f"unsupported $ref {ref!r}: only local file refs are supported")
    seen = set(_seen or ())
    if ref in seen:
        raise ValueError(f"circular $ref: {ref!r}")

    target_path = Path(base_dir) / ref
    target = json.loads(target_path.read_text(encoding="utf-8"))
    merged = resolve_refs(target, target_path.parent, seen | {ref})
    if not isinstance(merged, dict):
        raise ValueError(f"$ref target is not an object: {ref!r}")

    for key, value in schema.items():
        if key == "$ref":
            continue
        value = resolve_refs(value, base_dir, _seen)
        current = merged.get(key)
        if key == "properties" and isinstance(current, dict) and isinstance(value, dict):
            merged[key] = {**current, **value}
        elif key == "required" and isinstance(current, list) and isinstance(value, list):
            merged[key] = current + [n for n in value if n not in current]
        else:
            merged[key] = value
    return merged
```

Then change the `validate` signature and add the resolve step as its first statement:

```python
def validate(instance, schema, path="$", base_dir=None):
    """Return a list of error strings; empty means the instance is valid.

    Pass base_dir to resolve local-file $ref pointers relative to it. The
    resolution happens once, at the top; recursive calls see a flat schema.
    """
    if base_dir is not None:
        schema = resolve_refs(schema, base_dir)
    errors = []
    ...
```

Leave the rest of `validate` exactly as it is.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_schema_check_refs.py tests/test_profile_contracts.py tests/test_itest_contracts.py tests/test_env_declarations.py -q`
Expected: all pass. The three existing suites are the regression check — they call `validate` without `base_dir` and must be unaffected.

- [ ] **Step 5: Run the full checks and commit**

```bash
uv run ruff check .
uv run pytest -q
git add tests/schema_check.py tests/test_schema_check_refs.py
git commit -m "test(schema_check): resolve local-file \$ref in the shared validator (#48)"
```

---

### Task 2: Contract schemas, examples, and contract tests

The whole plugin is downstream of these files. Build them before any skill or script so later tasks have something to emit against.

**Files:**
- Create: `dependency-model/references/contracts/dependency-core.schema.json`
- Create: `dependency-model/references/contracts/discovery.schema.json`
- Create: `dependency-model/references/contracts/{package,service,config,security,platform,network}.schema.json`
- Create: `dependency-model/references/contracts/examples/{package,service,config,security,platform,network}.example.json`
- Test: `tests/test_dependency_model_contracts.py`

**Interfaces:**
- Produces: the `discovery` envelope, `contract_version` `1.0.0`, consumed by every skill in Tasks 8–9 and by layers 2–4.
- Produces: `dependency-core.schema.json`, `$ref`d by all six category schemas as the `dependencies[]` item.
- Consumes: `resolve_refs` / `validate(base_dir=...)` from Task 1.

Each example is a **full envelope with exactly one category populated** (D6), so one file proves both the envelope and its category schema.

- [ ] **Step 1: Write the failing test**

Create `tests/test_dependency_model_contracts.py`:

```python
# tests/test_dependency_model_contracts.py
import json
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from schema_check import resolve_refs, validate

REPO = Path(__file__).resolve().parents[1]
CONTRACTS = REPO / "dependency-model" / "references" / "contracts"
EXAMPLES = CONTRACTS / "examples"
CATEGORIES = ["config", "network", "package", "platform", "security", "service"]

VALUE_SHAPED = ("value", "secret", "token", "password", "passwd",
                "credential", "content", "material")


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


class TestContractFilesExist(unittest.TestCase):
    def test_every_expected_schema_is_present(self):
        names = sorted(p.name for p in CONTRACTS.glob("*.schema.json"))
        expected = sorted(
            ["dependency-core.schema.json", "discovery.schema.json"]
            + [f"{c}.schema.json" for c in CATEGORIES])
        self.assertEqual(names, expected)

    def test_every_category_has_an_example(self):
        for category in CATEGORIES:
            with self.subTest(category=category):
                self.assertTrue((EXAMPLES / f"{category}.example.json").exists())


class TestEnvelope(unittest.TestCase):
    def test_envelope_requires_version_target_and_categories(self):
        schema = load(CONTRACTS / "discovery.schema.json")
        self.assertEqual(schema["type"], "object")
        for field in ("contract_version", "target", "categories"):
            self.assertIn(field, schema["required"])
            self.assertIn(field, schema["properties"])

    def test_envelope_references_all_six_category_schemas(self):
        schema = load(CONTRACTS / "discovery.schema.json")
        refs = schema["properties"]["categories"]["properties"]
        self.assertEqual(sorted(refs), CATEGORIES)
        for category in CATEGORIES:
            with self.subTest(category=category):
                self.assertEqual(refs[category]["$ref"],
                                 f"{category}.schema.json")

    def test_envelope_resolves_without_error(self):
        resolved = resolve_refs(load(CONTRACTS / "discovery.schema.json"), CONTRACTS)
        item = resolved["properties"]["categories"]["properties"]["service"]
        self.assertIn("dependencies", item["properties"])


class TestExamplesValidate(unittest.TestCase):
    def test_each_example_validates_against_the_envelope(self):
        schema = load(CONTRACTS / "discovery.schema.json")
        for category in CATEGORIES:
            with self.subTest(category=category):
                instance = load(EXAMPLES / f"{category}.example.json")
                self.assertEqual(validate(instance, schema, base_dir=CONTRACTS), [])

    def test_each_example_populates_exactly_its_own_category(self):
        """D6: one skill emits a full envelope with one category populated."""
        for category in CATEGORIES:
            with self.subTest(category=category):
                instance = load(EXAMPLES / f"{category}.example.json")
                self.assertEqual(list(instance["categories"]), [category])

    def test_each_example_has_at_least_one_dependency_with_evidence(self):
        for category in CATEGORIES:
            with self.subTest(category=category):
                instance = load(EXAMPLES / f"{category}.example.json")
                deps = instance["categories"][category]["dependencies"]
                self.assertTrue(deps, "example has no dependencies to prove shape")
                for dep in deps:
                    self.assertTrue(dep["evidence"])
                    self.assertTrue(dep["id"].startswith(f"{category}:"))

    def test_every_example_declares_contract_version_1_0_0(self):
        for category in CATEGORIES:
            with self.subTest(category=category):
                self.assertEqual(
                    load(EXAMPLES / f"{category}.example.json")["contract_version"],
                    "1.0.0")


class TestSharedCore(unittest.TestCase):
    def test_every_category_item_refs_the_shared_core(self):
        for category in CATEGORIES:
            with self.subTest(category=category):
                schema = load(CONTRACTS / f"{category}.schema.json")
                item = schema["properties"]["dependencies"]["items"]
                self.assertEqual(item["$ref"], "dependency-core.schema.json")

    def test_core_requires_all_five_resilience_facts(self):
        """A skill must state 'no declaration found' explicitly, not by omission."""
        core = load(CONTRACTS / "dependency-core.schema.json")
        resilience = core["properties"]["resilience"]
        self.assertEqual(sorted(resilience["required"]),
                         ["fallback", "health_check", "on_path", "retry", "timeout"])

    def test_each_resilience_fact_accepts_null(self):
        core = load(CONTRACTS / "dependency-core.schema.json")
        props = core["properties"]["resilience"]["properties"]
        for fact in ("timeout", "retry", "fallback", "health_check"):
            with self.subTest(fact=fact):
                self.assertIn("null", props[fact]["type"])

    def test_core_documents_that_null_is_not_confirmed_absent(self):
        text = (CONTRACTS / "dependency-core.schema.json").read_text(
            encoding="utf-8").lower()
        self.assertIn("no declaration was found", text)
        self.assertIn("never", text)

    def test_every_category_status_enum_is_the_same_three_values(self):
        for category in CATEGORIES:
            with self.subTest(category=category):
                schema = load(CONTRACTS / f"{category}.schema.json")
                self.assertEqual(schema["properties"]["status"]["enum"],
                                 ["discovered", "not-applicable", "failed"])

    def test_every_category_requires_assumptions(self):
        for category in CATEGORIES:
            with self.subTest(category=category):
                schema = load(CONTRACTS / f"{category}.schema.json")
                self.assertIn("assumptions", schema["required"])


class TestSecurityNeverCarriesValues(unittest.TestCase):
    """A discovery skill that writes credentials into a contract is a leak.
    The schema must give it nowhere to put one."""

    def test_security_details_declares_no_value_shaped_property(self):
        schema = load(CONTRACTS / "security.schema.json")
        details = schema["properties"]["dependencies"]["items"]["properties"]["details"]
        for name in details["properties"]:
            with self.subTest(field=name):
                self.assertNotIn(name.lower(), VALUE_SHAPED)

    def test_security_example_carries_no_value_shaped_key_anywhere(self):
        text = (EXAMPLES / "security.example.json").read_text(encoding="utf-8")
        for key in json.loads(text)["categories"]["security"]["dependencies"]:
            for field in key["details"]:
                with self.subTest(field=field):
                    self.assertNotIn(field.lower(), VALUE_SHAPED)


class TestContractStaysInItsLayer(unittest.TestCase):
    def test_no_criticality_or_remediation_vocabulary(self):
        """Layers 2-4 judge; layer 1 reports. Banned words keep that boundary
        visible in review."""
        banned = ("criticality", "severity", "blast_radius", "remediation",
                  "recommendation", "risk_score", "priority")
        for path in sorted(CONTRACTS.glob("*.schema.json")):
            text = path.read_text(encoding="utf-8").lower()
            for word in banned:
                with self.subTest(schema=path.name, word=word):
                    self.assertNotIn(word, text)

    def test_no_probing_vocabulary(self):
        """D3: nothing is measured, so nothing names a measurement."""
        banned = ("measured", "observed_latency", "reachable", "resolved_ip",
                  "ping", "probe_result")
        for path in sorted(CONTRACTS.glob("*.schema.json")):
            text = path.read_text(encoding="utf-8").lower()
            for word in banned:
                with self.subTest(schema=path.name, word=word):
                    self.assertNotIn(word, text)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_dependency_model_contracts.py -q`
Expected: FAIL — `test_every_expected_schema_is_present` reports an empty list against the expected eight names.

- [ ] **Step 3: Write the shared core schema**

Create `dependency-model/references/contracts/dependency-core.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "dependency-model shared dependency core",
  "description": "Fields every discovered dependency carries, whatever its category. Referenced by each category schema as the dependencies[] item; the category adds its own details object on top.",
  "type": "object",
  "required": ["id", "name", "evidence", "resilience", "details"],
  "properties": {
    "id": {
      "type": "string",
      "description": "Stable identifier, '<category>:<slug>'. Stable across runs so a consumer can key a graph on it."
    },
    "name": { "type": "string" },
    "evidence": {
      "type": "array",
      "description": "Locations that prove this dependency exists, as 'file:line'. The package category carries a bare file path instead: syft reports file-level locations only.",
      "items": { "type": "string" }
    },
    "related_ids": {
      "type": "array",
      "description": "Ids of this dependency's counterparts in other categories, so a consumer gets cross-category edges without re-inferring them by string-matching hostnames.",
      "items": { "type": "string" }
    },
    "resilience": {
      "type": "object",
      "description": "Failure-relevant declarations found in the repository. null in any field means no declaration was found — it never means the behaviour is confirmed absent. Consumers treat a null on a request-path dependency as a candidate gap, not a proven one.",
      "required": ["timeout", "retry", "fallback", "health_check", "on_path"],
      "properties": {
        "timeout": {
          "type": ["object", "null"],
          "required": ["value", "evidence"],
          "properties": {
            "value": { "type": "string" },
            "evidence": { "type": "array", "items": { "type": "string" } }
          }
        },
        "retry": {
          "type": ["object", "null"],
          "required": ["description", "evidence"],
          "properties": {
            "description": { "type": "string" },
            "evidence": { "type": "array", "items": { "type": "string" } }
          }
        },
        "fallback": {
          "type": ["object", "null"],
          "required": ["description", "evidence"],
          "properties": {
            "description": { "type": "string" },
            "evidence": { "type": "array", "items": { "type": "string" } }
          }
        },
        "health_check": {
          "type": ["object", "null"],
          "required": ["description", "evidence"],
          "properties": {
            "description": { "type": "string" },
            "evidence": { "type": "array", "items": { "type": "string" } }
          }
        },
        "on_path": {
          "type": "array",
          "description": "Where in the system's lifecycle this dependency is used. Empty means no path could be established from the repository.",
          "items": { "enum": ["startup", "request", "background", "build"] }
        }
      }
    },
    "details": { "type": "object" }
  }
}
```

- [ ] **Step 4: Write the envelope**

Create `dependency-model/references/contracts/discovery.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "dependency-model:discovery contract",
  "description": "The envelope every dependency-model discovery skill emits. A single skill populates exactly one key under categories; merging several skills' output is a key union.",
  "type": "object",
  "required": ["contract_version", "target", "categories"],
  "properties": {
    "contract_version": { "type": "string" },
    "target": {
      "type": "string",
      "description": "Absolute path of the repository this was discovered from."
    },
    "seeded_by": {
      "type": ["object", "null"],
      "description": "The contract this discovery was seeded from, normally profile:topology. null when the skill bootstrapped its own seed.",
      "required": ["contract", "contract_version"],
      "properties": {
        "contract": { "type": "string" },
        "contract_version": { "type": "string" }
      }
    },
    "scan": {
      "type": ["object", "null"],
      "description": "Provenance of the shared evidence index this skill read. null for the package category, which reads syft instead.",
      "required": ["scan_version", "confidence"],
      "properties": {
        "scan_version": { "type": "string" },
        "confidence": { "enum": ["high", "partial", "low"] }
      }
    },
    "categories": {
      "type": "object",
      "properties": {
        "config": { "$ref": "config.schema.json" },
        "network": { "$ref": "network.schema.json" },
        "package": { "$ref": "package.schema.json" },
        "platform": { "$ref": "platform.schema.json" },
        "security": { "$ref": "security.schema.json" },
        "service": { "$ref": "service.schema.json" }
      }
    }
  }
}
```

- [ ] **Step 5: Write the six category schemas**

Every one has the same skeleton. `dependency-model/references/contracts/service.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "dependency-model:service category",
  "description": "Out-of-project services the system needs: databases, caches, queues, object stores, search engines, and APIs. Records the thing depended on; the network category records the path used to reach it. The two link through related_ids.",
  "type": "object",
  "required": ["status", "dependencies", "assumptions"],
  "properties": {
    "status": {
      "enum": ["discovered", "not-applicable", "failed"],
      "description": "discovered: the scan ran and this list is what it found, empty included. not-applicable: the category cannot apply to this project. failed: the scan could not complete, so an empty list proves nothing."
    },
    "dependencies": {
      "type": "array",
      "items": {
        "$ref": "dependency-core.schema.json",
        "properties": {
          "details": {
            "type": "object",
            "required": ["kind"],
            "properties": {
              "kind": { "enum": ["database", "cache", "queue", "object-store", "search", "api"] },
              "protocol": { "type": ["string", "null"] },
              "client_library": { "type": ["string", "null"] },
              "managed_by": {
                "type": ["string", "null"],
                "description": "How the service is normally brought up: compose, kubernetes, terraform, managed-cloud, external, unknown."
              },
              "config_keys": {
                "type": "array",
                "description": "Configuration keys that point at this service. Each should match a config category id.",
                "items": { "type": "string" }
              }
            }
          }
        }
      }
    },
    "assumptions": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["claim", "why_unconfirmed"],
        "properties": {
          "claim": { "type": "string" },
          "why_unconfirmed": { "type": "string" }
        }
      }
    }
  }
}
```

Write the other five identically, changing only `title`, the category `description`, and the `details` block:

`package.schema.json` — description: "Libraries the system ships with, catalogued by syft. Evidence is a file path, not file:line: syft reports file-level locations only."

```json
"details": {
  "type": "object",
  "required": ["ecosystem", "resolution", "direct"],
  "properties": {
    "ecosystem": { "type": "string" },
    "package_manager": { "type": ["string", "null"] },
    "purl": { "type": ["string", "null"] },
    "version": { "type": ["string", "null"] },
    "version_constraint": { "type": ["string", "null"] },
    "pinned": { "type": ["boolean", "null"] },
    "resolution": {
      "enum": ["declared", "locked", "installed"],
      "description": "declared: named in a manifest. locked: pinned by a lockfile. installed: found in an installed tree. syft conflates these, so the skill must decide from the location it was catalogued at."
    },
    "direct": { "type": ["boolean", "null"] },
    "depends_on": {
      "type": "array",
      "description": "Ids of other package dependencies this one requires, from syft's dependency-of relationships.",
      "items": { "type": "string" }
    }
  }
}
```

`config.schema.json` — description: "Configuration the system must be supplied with in order to run."

```json
"details": {
  "type": "object",
  "required": ["mechanism", "key"],
  "properties": {
    "mechanism": { "enum": ["env", "file", "flag", "remote", "constant", "unknown"] },
    "key": { "type": "string" },
    "required": { "type": ["boolean", "null"] },
    "default": { "type": ["string", "null"] },
    "consumed_by": { "type": "array", "items": { "type": "string" } },
    "validated": {
      "type": ["boolean", "null"],
      "description": "Whether the repository declares a validation or parse step for this key."
    }
  }
}
```

`security.schema.json` — description: "Secrets and permissions the system requires. Records what a credential is named and where it is read, never its value. This schema deliberately declares no field a value could be written into."

```json
"details": {
  "type": "object",
  "required": ["kind"],
  "properties": {
    "kind": { "enum": ["secret", "credential-ref", "permission", "role", "policy", "certificate-ref"] },
    "provider": { "type": ["string", "null"] },
    "scope": { "type": ["string", "null"] },
    "granted_to": { "type": "array", "items": { "type": "string" } },
    "rotation_declared": { "type": ["boolean", "null"] }
  }
}
```

`platform.schema.json` — description: "OS and cloud resources the system declares a need for. Every figure is a declared one; nothing here was measured."

```json
"details": {
  "type": "object",
  "required": ["kind", "declared_value"],
  "properties": {
    "kind": { "enum": ["cpu", "memory", "disk", "gpu", "arch", "os", "runtime-version", "cloud-service"] },
    "declared_value": { "type": "string" },
    "source": { "enum": ["dockerfile", "compose", "kubernetes", "iac", "ci", "manifest", "docs"] },
    "component": { "type": ["string", "null"] }
  }
}
```

`network.schema.json` — description: "Names, hosts, and ports that must resolve and connect. Records the path used to reach a dependency; the service category records the thing itself. The two link through related_ids."

```json
"details": {
  "type": "object",
  "required": ["kind", "value", "direction"],
  "properties": {
    "kind": { "enum": ["hostname", "ip", "port", "dns", "egress", "proxy", "ingress"] },
    "value": { "type": "string" },
    "direction": { "enum": ["inbound", "outbound", "internal", "unknown"] },
    "protocol": { "type": ["string", "null"] },
    "resolution_mechanism": { "type": ["string", "null"] }
  }
}
```

- [ ] **Step 6: Write the six examples**

Each is a full envelope with one populated category. `examples/service.example.json`:

```json
{
  "contract_version": "1.0.0",
  "target": "/abs/path/to/repo",
  "seeded_by": { "contract": "profile:topology", "contract_version": "1.0.0" },
  "scan": { "scan_version": "1.0.0", "confidence": "high" },
  "categories": {
    "service": {
      "status": "discovered",
      "dependencies": [
        {
          "id": "service:postgres-primary",
          "name": "postgres",
          "evidence": ["docker-compose.yml:12", "internal/db/pool.go:41"],
          "related_ids": ["network:postgres-5432", "config:database-url"],
          "resilience": {
            "timeout": { "value": "5s", "evidence": ["internal/db/pool.go:44"] },
            "retry": null,
            "fallback": null,
            "health_check": { "description": "pg_isready", "evidence": ["docker-compose.yml:19"] },
            "on_path": ["startup", "request"]
          },
          "details": {
            "kind": "database",
            "protocol": "postgres",
            "client_library": "github.com/jackc/pgx/v5",
            "managed_by": "compose",
            "config_keys": ["DATABASE_URL"]
          }
        }
      ],
      "assumptions": [
        {
          "claim": "postgres is also the production database, not only the local compose one",
          "why_unconfirmed": "no production manifest is committed; DATABASE_URL is supplied externally"
        }
      ]
    }
  }
}
```

Write the other five in the same shape, each with at least one dependency, at least one `null` resilience fact, and at least one assumption:

- `package.example.json` — `id` `package:pgx-v5`, evidence `["go.mod"]` (bare path, no line), `details.resolution` `"locked"`, `direct` `true`, `depends_on` `["package:puddle-v2"]`, `resilience` all `null` with `on_path: ["build"]`.
- `config.example.json` — `id` `config:database-url`, `details.mechanism` `"env"`, `key` `"DATABASE_URL"`, `required` `true`, `default` `null`, `consumed_by` `["internal/db/pool.go"]`, `related_ids` `["service:postgres-primary"]`.
- `security.example.json` — `id` `security:stripe-api-key`, `name` `"STRIPE_API_KEY"`, evidence `["internal/billing/client.go:12", "deploy/k8s/secrets.yaml:8"]`, `details.kind` `"secret"`, `provider` `"kubernetes"`, `rotation_declared` `null`. **No value anywhere.**
- `platform.example.json` — `id` `platform:api-memory-limit`, `details.kind` `"memory"`, `declared_value` `"512Mi"`, `source` `"kubernetes"`, `component` `"api"`.
- `network.example.json` — `id` `network:postgres-5432`, `details.kind` `"port"`, `value` `"postgres:5432"`, `direction` `"outbound"`, `protocol` `"tcp"`, `related_ids` `["service:postgres-primary"]`.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/test_dependency_model_contracts.py -q`
Expected: PASS. If `test_no_criticality_or_remediation_vocabulary` fires, a description used a judgment word — reword it, do not weaken the test.

- [ ] **Step 8: Run the full checks and commit**

```bash
uv run ruff check .
uv run pytest -q
git add dependency-model/references/contracts tests/test_dependency_model_contracts.py
git commit -m "feat(dependency-model): discovery contract envelope and six category schemas (#48)"
```

---

### Task 3: `depscan.py` skeleton — walk, exclusions, file classification, CLI

The scan script's spine. No findings extractors yet: `findings` comes back with every key present and empty, so the output shape is stable from the first commit and Tasks 4–6 only fill it in.

**Files:**
- Create: `dependency-model/scripts/depscan.py`
- Create: `dependency-model/scripts/depscanlib/__init__.py`
- Create: `dependency-model/scripts/depscanlib/walk.py`
- Create: `dependency-model/scripts/depscanlib/files.py`
- Create: `dependency-model/scripts/depscanlib/report.py`
- Modify: `pyproject.toml` (ruff `known-first-party`, ty `extra-paths`)
- Test: `tests/test_depscan_walk.py`, `tests/test_depscan_files.py`, `tests/test_depscan_cli.py`

**Interfaces:**
- Produces: `depscanlib.VERSION = "1.0.0"`.
- Produces: `depscanlib.walk.EXCLUDE_DIRS: set[str]`, `walk_repo(root) -> tuple[list[str], str]` returning sorted repo-relative POSIX paths and the method `"git"` or `"walk"`.
- Produces: `depscanlib.files.classify_files(root, paths) -> dict[str, list[str]]` with keys `compose`, `k8s`, `iac`, `env`, `ci`.
- Produces: `depscanlib.report.build_scan(root) -> dict` — the full scan document.
- Produces: CLI `uv run --script dependency-model/scripts/depscan.py [PATH] [--json] [--indent N]`, exit `0` on success, `2` when PATH is not a directory.
- Consumed by: Tasks 4, 5, 6 (they add extractors to `build_scan`), and Tasks 8–9 (the skills read the emitted JSON).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_depscan_walk.py`:

```python
# tests/test_depscan_walk.py
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dependency-model" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from depscanlib.walk import EXCLUDE_DIRS, walk_repo
from repobuilder import build_repo, git_commit_all, git_init


class TestWalkRepo(unittest.TestCase):
    def test_lists_files_relative_and_sorted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {"b.py": "x = 1\n", "a.py": "y = 2\n",
                                    "pkg/c.py": "z = 3\n"})
            files, method = walk_repo(root)
            self.assertEqual(files, ["a.py", "b.py", "pkg/c.py"])
            self.assertEqual(method, "walk")

    def test_excludes_vendored_and_installed_trees(self):
        """D7: an unscoped scan of this repo reported 270 packages against 2
        declared deps, 188 of them from a nested virtualenv."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {
                "app.py": "x = 1\n",
                "node_modules/left-pad/index.js": "//\n",
                ".venv/lib/python3.11/site-packages/thing.py": "x = 1\n",
                "sub/.venv/lib/other.py": "x = 1\n",
                "vendor/lib/thing.go": "package lib\n",
                "dist/bundle.js": "//\n",
            })
            files, _ = walk_repo(root)
            self.assertEqual(files, ["app.py"])

    def test_uses_git_listing_and_honors_gitignore(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {".gitignore": "ignored.txt\n",
                                    "app.py": "x = 1\n", "ignored.txt": "x\n"})
            git_init(root)
            files, method = walk_repo(root)
            self.assertEqual(method, "git")
            self.assertIn("app.py", files)
            self.assertNotIn("ignored.txt", files)

    def test_git_listing_still_filters_excluded_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {"app.py": "x = 1\n",
                                    "vendor/lib/thing.go": "package lib\n"})
            git_init(root)
            git_commit_all(root)
            files, method = walk_repo(root)
            self.assertEqual(method, "git")
            self.assertEqual(files, ["app.py"])

    def test_exclude_dirs_covers_the_trees_syft_would_otherwise_catalogue(self):
        for name in (".venv", "venv", "node_modules", "vendor",
                     "site-packages", "dist", ".git"):
            with self.subTest(directory=name):
                self.assertIn(name, EXCLUDE_DIRS)


if __name__ == "__main__":
    unittest.main()
```

Create `tests/test_depscan_files.py`:

```python
# tests/test_depscan_files.py
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dependency-model" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from depscanlib.files import classify_files
from depscanlib.walk import walk_repo
from repobuilder import build_repo

K8S_DEPLOYMENT = "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: api\n"
COMPOSE = "services:\n  db:\n    image: postgres:16\n"
WORKFLOW = "name: ci\non: [push]\njobs:\n  test:\n    runs-on: ubuntu-latest\n"
SAM = "AWSTemplateFormatVersion: '2010-09-09'\nTransform: AWS::Serverless-2016-10-31\n"
ISSUE_FORM = "name: Bug report\ndescription: file a bug\nbody:\n  - type: input\n"


def classify(files):
    with tempfile.TemporaryDirectory() as tmp:
        root = build_repo(tmp, files)
        paths, _ = walk_repo(root)
        return classify_files(root, paths)


class TestClassifyFiles(unittest.TestCase):
    def test_returns_all_five_keys_even_when_empty(self):
        result = classify({"README.md": "# hi\n"})
        self.assertEqual(sorted(result), ["ci", "compose", "env", "iac", "k8s"])
        self.assertEqual(result["compose"], [])

    def test_detects_compose_by_name(self):
        for name in ("docker-compose.yml", "docker-compose.yaml",
                     "compose.yml", "compose.yaml"):
            with self.subTest(name=name):
                self.assertEqual(classify({name: COMPOSE})["compose"], [name])

    def test_detects_kubernetes_by_content_not_name(self):
        result = classify({"deploy/api.yaml": K8S_DEPLOYMENT,
                           "config/settings.yaml": "debug: true\n"})
        self.assertEqual(result["k8s"], ["deploy/api.yaml"])

    def test_compose_is_never_also_classified_as_kubernetes(self):
        result = classify({"docker-compose.yml": COMPOSE})
        self.assertEqual(result["compose"], ["docker-compose.yml"])
        self.assertEqual(result["k8s"], [])

    def test_detects_iac_by_extension_and_by_name(self):
        result = classify({"infra/main.tf": "resource \"aws_db_instance\" \"x\" {}\n",
                           "infra/vars.tfvars": "region = \"us-east-1\"\n",
                           "chart/Chart.yaml": "name: api\nversion: 0.1.0\n",
                           "cdk.json": "{\"app\": \"node bin/app.js\"}\n"})
        self.assertEqual(result["iac"],
                         ["cdk.json", "chart/Chart.yaml", "infra/main.tf",
                          "infra/vars.tfvars"])

    def test_template_yaml_is_iac_only_when_its_content_says_so(self):
        self.assertEqual(classify({"template.yaml": SAM})["iac"], ["template.yaml"])
        self.assertEqual(
            classify({".github/ISSUE_TEMPLATE/template.yaml": ISSUE_FORM})["iac"], [])

    def test_detects_env_files(self):
        result = classify({".env": "A=1\n", ".env.example": "A=\n",
                           "config/local.env": "B=2\n", "environment.md": "# no\n"})
        self.assertEqual(result["env"],
                         [".env", ".env.example", "config/local.env"])

    def test_detects_ci_config(self):
        result = classify({".github/workflows/ci.yml": WORKFLOW,
                           ".gitlab-ci.yml": "stages: [test]\n",
                           "Jenkinsfile": "pipeline {}\n"})
        self.assertEqual(result["ci"],
                         [".github/workflows/ci.yml", ".gitlab-ci.yml", "Jenkinsfile"])

    def test_every_list_is_sorted(self):
        result = classify({"b/compose.yml": COMPOSE, "a/compose.yml": COMPOSE})
        self.assertEqual(result["compose"], ["a/compose.yml", "b/compose.yml"])


if __name__ == "__main__":
    unittest.main()
```

Create `tests/test_depscan_cli.py`:

```python
# tests/test_depscan_cli.py
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dependency-model" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import depscan
from depscanlib.report import build_scan
from repobuilder import build_repo

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "dependency-model" / "scripts" / "depscan.py"

FINDING_KEYS = ["env_refs", "host_port_literals", "resilience_calls",
                "resource_limits", "secret_shaped_keys", "url_literals"]


class TestBuildScan(unittest.TestCase):
    def test_emits_the_documented_top_level_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {"app.py": "x = 1\n"})
            scan = build_scan(root)
            self.assertEqual(sorted(scan),
                             ["coverage", "exclusions", "files", "findings",
                              "listing_method", "scan_version", "target"])
            self.assertEqual(scan["scan_version"], "1.0.0")
            self.assertEqual(scan["target"], str(Path(root).resolve()))

    def test_every_findings_key_is_present_even_when_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {"README.md": "# hi\n"})
            self.assertEqual(sorted(build_scan(root)["findings"]), FINDING_KEYS)

    def test_exclusions_are_sorted_and_are_the_shared_source_of_truth(self):
        """The package skill passes these to syft --exclude; the file-scanning
        skills inherit the same list. One list, two tools."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {"app.py": "x = 1\n"})
            exclusions = build_scan(root)["exclusions"]
            self.assertEqual(exclusions, sorted(exclusions))
            for name in (".venv", "node_modules", "vendor", "site-packages"):
                self.assertIn(name, exclusions)

    def test_coverage_counts_scanned_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {"a.py": "x = 1\n", "b.py": "y = 2\n"})
            coverage = build_scan(root)["coverage"]
            self.assertEqual(coverage["files_scanned"], 2)
            self.assertEqual(coverage["confidence"], "high")
            self.assertEqual(coverage["skipped"], [])

    def test_empty_repo_is_low_confidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {})
            self.assertEqual(build_scan(root)["coverage"]["confidence"], "low")

    def test_output_is_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {"a.py": "x = 1\n", "docker-compose.yml":
                                    "services:\n  db:\n    image: postgres:16\n"})
            self.assertEqual(json.dumps(build_scan(root), sort_keys=True),
                             json.dumps(build_scan(root), sort_keys=True))


class TestCli(unittest.TestCase):
    def test_returns_2_for_a_path_that_is_not_a_directory(self):
        self.assertEqual(depscan.main(["/definitely/not/here"]), 2)

    def test_runs_under_bare_python3_with_no_dependencies(self):
        """depscanlib is stdlib-only so the documented python3 fallback works."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {"app.py": "x = 1\n"})
            proc = subprocess.run(
                [sys.executable, str(SCRIPT), str(root)],
                capture_output=True, text=True, timeout=60, check=False)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(json.loads(proc.stdout)["scan_version"], "1.0.0")

    def test_indent_zero_emits_compact_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {"app.py": "x = 1\n"})
            proc = subprocess.run(
                [sys.executable, str(SCRIPT), str(root), "--indent", "0"],
                capture_output=True, text=True, timeout=60, check=False)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertNotIn("\n  ", proc.stdout)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_depscan_walk.py tests/test_depscan_files.py tests/test_depscan_cli.py -q`
Expected: collection errors — `ModuleNotFoundError: No module named 'depscanlib'`.

- [ ] **Step 3: Implement `depscanlib/__init__.py` and `walk.py`**

`dependency-model/scripts/depscanlib/__init__.py`:

```python
"""Deterministic dependency-evidence scan for the dependency-model plugin.

Stdlib only: depscan.py declares no dependencies so it runs under bare
python3 as well as `uv run --script`.
"""

VERSION = "1.0.0"
```

`dependency-model/scripts/depscanlib/walk.py`:

```python
"""Repo file listing: git-aware, with a filesystem fallback.

Deliberately duplicates profile's walk rather than importing inventorylib:
plugins install independently, so a cross-plugin Python import would break
at install time.
"""

import subprocess
from pathlib import Path

# The single source of truth for what neither this scanner nor syft looks at.
# Unscoped, syft catalogues an installed tree as though it were the project's
# dependency set — 270 packages against 2 declared ones, measured on this repo.
EXCLUDE_DIRS = {
    ".git", ".hg", ".svn", "node_modules", ".venv", "venv", "env",
    "vendor", "dist", "build", "target", "out", "__pycache__",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", ".next",
    ".gradle", "site-packages", ".idea", ".terraform", "Pods",
}


def _excluded(rel):
    return any(part in EXCLUDE_DIRS for part in Path(rel).parts)


def _git_files(root):
    """Return git's view of the repo, or None if root is not a usable git repo."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--cached", "--others",
             "--exclude-standard"],
            capture_output=True, text=True, timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return [line for line in proc.stdout.splitlines() if line]


def _walk_files(root):
    found = []
    for path in Path(root).rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if not _excluded(rel):
            found.append(rel)
    return found


def walk_repo(root):
    """Return (sorted repo-relative POSIX paths, method) where method is git|walk."""
    root = Path(root)
    files = _git_files(root)
    if files is None:
        return sorted(_walk_files(root)), "walk"
    return sorted(f for f in files if not _excluded(f)), "git"


def read_text(root, rel, limit=None):
    """Read a repo-relative file as text, or return '' if it cannot be read."""
    try:
        text = (Path(root) / rel).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text[:limit] if limit else text
```

- [ ] **Step 4: Implement `files.py`**

`dependency-model/scripts/depscanlib/files.py`:

```python
"""Classify repo files into the config surfaces the six categories read."""

from pathlib import PurePosixPath

from depscanlib.walk import read_text

COMPOSE_NAMES = {"docker-compose.yml", "docker-compose.yaml",
                 "compose.yml", "compose.yaml"}

IAC_NAMES = {"cdk.json", "serverless.yml", "serverless.yaml",
             "Chart.yaml", "kustomization.yaml", "kustomization.yml",
             "Pulumi.yaml"}
IAC_EXTS = {".tf", ".tfvars", ".bicep"}

# template.yaml proves nothing by its name — a GitHub issue form, a Backstage
# template, and a SAM stack all ship as one. The content decides.
TEMPLATE_NAMES = {"template.yaml", "template.yml"}
SAM_TRANSFORM = "AWS::Serverless-2016-10-31"
CFN_MARKER = "AWSTemplateFormatVersion"

CI_NAMES = {".gitlab-ci.yml", "azure-pipelines.yml", "Jenkinsfile",
            ".travis.yml", "bitbucket-pipelines.yml"}
CI_PATHS = {".circleci/config.yml", ".circleci/config.yaml"}

YAML_EXTS = {".yaml", ".yml"}
HEAD = 4096


def _is_kubernetes(root, path):
    text = read_text(root, path, HEAD)
    return "apiVersion:" in text and "kind:" in text


def _is_iac_template(root, path):
    text = read_text(root, path, HEAD)
    return SAM_TRANSFORM in text or CFN_MARKER in text


def _is_env_file(name):
    return name == ".env" or name.startswith(".env.") or name.endswith(".env")


def classify_files(root, paths):
    """Return repo-relative paths grouped by config surface, each list sorted.

    A path lands in at most one group. Order of the checks is the precedence:
    compose and CI names win over the content-based kubernetes test, so a
    compose file is never reported as a manifest.
    """
    groups = {"compose": [], "k8s": [], "iac": [], "env": [], "ci": []}

    for path in sorted(paths):
        parsed = PurePosixPath(path)
        name = parsed.name
        suffix = parsed.suffix

        if path.startswith(".github/workflows/") or name in CI_NAMES or path in CI_PATHS:
            groups["ci"].append(path)
        elif name in COMPOSE_NAMES:
            groups["compose"].append(path)
        elif _is_env_file(name):
            groups["env"].append(path)
        elif name in IAC_NAMES or suffix in IAC_EXTS:
            groups["iac"].append(path)
        elif name in TEMPLATE_NAMES and _is_iac_template(root, path):
            groups["iac"].append(path)
        elif suffix in YAML_EXTS and _is_kubernetes(root, path):
            groups["k8s"].append(path)

    return groups
```

- [ ] **Step 5: Implement `report.py`**

`dependency-model/scripts/depscanlib/report.py`:

```python
"""Assemble the shared evidence index the six discovery skills read."""

from pathlib import Path

from depscanlib import VERSION
from depscanlib.files import classify_files
from depscanlib.walk import EXCLUDE_DIRS, walk_repo

EMPTY_FINDINGS = ("env_refs", "url_literals", "host_port_literals",
                  "secret_shaped_keys", "resource_limits", "resilience_calls")


def build_coverage(paths, skipped):
    """Return files_scanned / skipped / confidence for the scan.

    confidence is about what the scan could see, not about what it found:
    an empty repo is low, an unscanned language is partial, everything else
    is high.
    """
    if not paths:
        return {"files_scanned": 0, "skipped": skipped, "confidence": "low"}
    confidence = "partial" if skipped else "high"
    return {"files_scanned": len(paths), "skipped": skipped,
            "confidence": confidence}


def build_scan(root):
    """Walk root and return the complete evidence index."""
    root = Path(root)
    paths, method = walk_repo(root)
    files = classify_files(root, paths)
    findings = {key: [] for key in EMPTY_FINDINGS}
    skipped = []

    return {
        "scan_version": VERSION,
        "target": str(root.resolve()),
        "listing_method": method,
        "exclusions": sorted(EXCLUDE_DIRS),
        "files": files,
        "findings": findings,
        "coverage": build_coverage(paths, skipped),
    }
```

- [ ] **Step 6: Implement the CLI**

`dependency-model/scripts/depscan.py`:

```python
#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Emit a deterministic JSON evidence index of a repository's dependencies.

Read-only: this walks and reads files. It resolves no names, opens no
sockets, boots no containers, and runs no build.

Usage:
    uv run --script depscan.py [PATH] [--json] [--indent N]
    python3 depscan.py [PATH] [--json] [--indent N]   # fallback; no deps

Exit codes:
    0  index emitted (possibly partial; see coverage.confidence)
    2  PATH is not a usable directory
"""

import argparse
import json
import sys
from pathlib import Path

from depscanlib.report import build_scan


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="depscan.py",
        description="Emit a deterministic JSON dependency-evidence index.")
    parser.add_argument("path", nargs="?", default=".",
                        help="repo root to scan (default: current directory)")
    parser.add_argument("--json", action="store_true",
                        help="emit JSON (default; accepted for explicitness)")
    parser.add_argument("--indent", type=int, default=2,
                        help="JSON indent; 0 for compact output")
    args = parser.parse_args(argv)

    root = Path(args.path)
    if not root.is_dir():
        json.dump({"error": f"not a directory: {args.path}"}, sys.stderr)
        sys.stderr.write("\n")
        return 2

    indent = args.indent if args.indent > 0 else None
    print(json.dumps(build_scan(root), indent=indent, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Make it executable: `chmod +x dependency-model/scripts/depscan.py`

- [ ] **Step 7: Register the new script tree with the repo tooling**

In `pyproject.toml`, add `depscanlib` to ruff's first-party list and the script dir to ty's search path:

```toml
[tool.ruff.lint.isort]
# inventorylib and depscanlib are invoked by path from their plugins' scripts
# dirs, not installed; without this, isort treats them as third-party in the
# test modules.
known-first-party = ["inventorylib", "depscanlib"]
```

```toml
[tool.ty.environment]
extra-paths = [
    "cats/scripts",
    "deps/scripts",
    "logseq/scripts",
    "dev/scripts",
    "dependency-model/scripts",
    "tests",
]
```

Leave `[tool.pytest.ini_options] pythonpath` alone — the depscan tests use the explicit `sys.path.insert` preamble, matching `test_profile_walk.py`.

- [ ] **Step 8: Run the tests to verify they pass**

Run: `uv run pytest tests/test_depscan_walk.py tests/test_depscan_files.py tests/test_depscan_cli.py -q`
Expected: PASS.

Then sanity-check it against a real repo:

```bash
uv run --script dependency-model/scripts/depscan.py . | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['listing_method'], d['coverage'], {k: len(v) for k, v in d['files'].items()})"
```
Expected: `git`, high confidence, and non-zero `ci` and `compose`/`iac` counts for this repo.

- [ ] **Step 9: Run the full checks and commit**

```bash
uv run ruff check .
uv run pytest -q
git add dependency-model/scripts pyproject.toml tests/test_depscan_walk.py tests/test_depscan_files.py tests/test_depscan_cli.py
git commit -m "feat(dependency-model): depscan walk, file classification, and CLI (#48)"
```

---

### Task 4: Source-literal extractors — `env_refs` and `resilience_calls` (D9)

This is the D9 task. Go, TypeScript/JavaScript, and Python only, with every other language reported in `coverage.skipped` so the gap is visible in the contract rather than silently absent.

**Files:**
- Create: `dependency-model/scripts/depscanlib/source.py`
- Modify: `dependency-model/scripts/depscanlib/report.py`
- Test: `tests/test_depscan_source.py`
- Test: `tests/test_depscan_cli.py` (extend with the coverage-skipped case)

**Interfaces:**
- Produces: `SOURCE_LANGUAGES: dict[str, str]` mapping file suffix to language (`go`, `ts`, `js`, `python`).
- Produces: `scan_source(root, paths) -> tuple[dict[str, list], list[dict]]` returning `{"env_refs": [...], "resilience_calls": [...]}` and the `skipped` records for `coverage`.
- `env_refs` items: `{"name", "file", "line"}`. `resilience_calls` items: `{"kind", "raw", "file", "line", "language"}` with `kind` in `timeout`, `retry`, `circuit-breaker`, `deadline`, `fallback`.
- `skipped` items: `{"reason", "language", "count"}`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_depscan_source.py`:

```python
# tests/test_depscan_source.py
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dependency-model" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from depscanlib.source import SOURCE_LANGUAGES, scan_source
from depscanlib.walk import walk_repo
from repobuilder import build_repo


def scan(files):
    with tempfile.TemporaryDirectory() as tmp:
        root = build_repo(tmp, files)
        paths, _ = walk_repo(root)
        return scan_source(root, paths)


def names(findings, key):
    return sorted(item["name"] for item in findings[key])


def kinds(findings):
    return sorted({item["kind"] for item in findings["resilience_calls"]})


class TestEnvRefs(unittest.TestCase):
    def test_go_getenv_and_lookupenv(self):
        findings, _ = scan({"main.go":
            'package main\n\nfunc a() {\n\tx := os.Getenv("DATABASE_URL")\n'
            '\ty, ok := os.LookupEnv("REDIS_ADDR")\n}\n'})
        self.assertEqual(names(findings, "env_refs"), ["DATABASE_URL", "REDIS_ADDR"])

    def test_python_environ_forms(self):
        findings, _ = scan({"app.py":
            'import os\nA = os.environ["DATABASE_URL"]\n'
            'B = os.environ.get("REDIS_ADDR")\nC = os.getenv("QUEUE_URL")\n'})
        self.assertEqual(names(findings, "env_refs"),
                         ["DATABASE_URL", "QUEUE_URL", "REDIS_ADDR"])

    def test_javascript_process_env_forms(self):
        findings, _ = scan({"server.js":
            'const a = process.env.DATABASE_URL;\n'
            'const b = process.env["REDIS_ADDR"];\n'})
        self.assertEqual(names(findings, "env_refs"), ["DATABASE_URL", "REDIS_ADDR"])

    def test_typescript_is_scanned_like_javascript(self):
        findings, _ = scan({"src/config.ts": 'export const u = process.env.API_URL;\n'})
        self.assertEqual(names(findings, "env_refs"), ["API_URL"])

    def test_records_file_and_one_indexed_line(self):
        findings, _ = scan({"app.py": 'import os\n\nX = os.getenv("A_KEY")\n'})
        self.assertEqual(findings["env_refs"],
                         [{"name": "A_KEY", "file": "app.py", "line": 3}])

    def test_same_name_twice_is_two_records(self):
        findings, _ = scan({"app.py": 'os.getenv("A")\nos.getenv("A")\n'})
        self.assertEqual(len(findings["env_refs"]), 2)

    def test_out_of_scope_language_yields_no_env_refs(self):
        findings, _ = scan({"main.rs": 'let x = std::env::var("DATABASE_URL");\n'})
        self.assertEqual(findings["env_refs"], [])


class TestResilienceCalls(unittest.TestCase):
    def test_go_context_with_timeout_and_deadline(self):
        findings, _ = scan({"db.go":
            'ctx, cancel := context.WithTimeout(parent, 5*time.Second)\n'
            'ctx2, c2 := context.WithDeadline(parent, t)\n'})
        self.assertEqual(kinds(findings), ["deadline", "timeout"])

    def test_go_struct_timeout_field(self):
        findings, _ = scan({"client.go": 'c := &http.Client{Timeout: 3 * time.Second}\n'})
        self.assertIn("timeout", kinds(findings))

    def test_python_timeout_kwarg_and_retry_decorator(self):
        findings, _ = scan({"client.py":
            'import requests\nfrom tenacity import retry\n\n'
            '@retry\ndef get():\n    return requests.get(url, timeout=5)\n'})
        self.assertEqual(kinds(findings), ["retry", "timeout"])

    def test_javascript_abort_signal_and_axios_timeout(self):
        findings, _ = scan({"api.ts":
            'const s = AbortSignal.timeout(2000);\n'
            'const c = axios.create({ timeout: 3000 });\n'})
        self.assertEqual(kinds(findings), ["timeout"])

    def test_circuit_breaker_libraries_are_recognised(self):
        findings, _ = scan({
            "b.go": 'import "github.com/sony/gobreaker"\n',
            "b.py": 'import pybreaker\n',
            "b.js": 'const CircuitBreaker = require("opossum");\n',
        })
        self.assertEqual(kinds(findings), ["circuit-breaker"])

    def test_records_the_matched_text_verbatim_as_raw(self):
        findings, _ = scan({"db.go": 'context.WithTimeout(parent, 5*time.Second)\n'})
        record = findings["resilience_calls"][0]
        self.assertIn("WithTimeout", record["raw"])
        self.assertEqual(record["file"], "db.go")
        self.assertEqual(record["line"], 1)
        self.assertEqual(record["language"], "go")

    def test_findings_are_sorted_by_file_then_line(self):
        findings, _ = scan({"b.py": 'requests.get(u, timeout=1)\n',
                            "a.py": 'requests.get(u, timeout=2)\n'})
        files = [r["file"] for r in findings["resilience_calls"]]
        self.assertEqual(files, ["a.py", "b.py"])


class TestSkippedLanguages(unittest.TestCase):
    def test_out_of_scope_source_is_reported_not_silently_dropped(self):
        """D9: the gap must be visible in the contract."""
        _, skipped = scan({"main.rs": "fn main() {}\n", "lib.rs": "pub fn a() {}\n",
                           "app.py": "x = 1\n"})
        self.assertEqual(skipped, [{
            "reason": "source-literal scanning covers go, js, python, and ts only",
            "language": "rust", "count": 2}])

    def test_in_scope_only_repo_reports_nothing_skipped(self):
        _, skipped = scan({"app.py": "x = 1\n", "main.go": "package main\n"})
        self.assertEqual(skipped, [])

    def test_non_source_files_are_not_reported_as_skipped(self):
        _, skipped = scan({"README.md": "# hi\n", "data.json": "{}\n"})
        self.assertEqual(skipped, [])

    def test_the_three_in_scope_ecosystems_are_the_documented_ones(self):
        self.assertEqual(sorted(set(SOURCE_LANGUAGES.values())),
                         ["go", "js", "python", "ts"])


if __name__ == "__main__":
    unittest.main()
```

Append to `tests/test_depscan_cli.py`:

```python
class TestCoverageReportsUnscannedLanguages(unittest.TestCase):
    def test_partial_confidence_when_a_language_is_out_of_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {"app.py": "x = 1\n", "main.rs": "fn main() {}\n"})
            coverage = build_scan(root)["coverage"]
            self.assertEqual(coverage["confidence"], "partial")
            self.assertEqual(coverage["skipped"][0]["language"], "rust")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_depscan_source.py tests/test_depscan_cli.py -q`
Expected: collection error on `depscanlib.source`.

- [ ] **Step 3: Implement `source.py`**

`dependency-model/scripts/depscanlib/source.py`:

```python
"""Source-literal extraction for Go, TypeScript/JavaScript, and Python.

Per D9 these three ecosystems are the whole scope: per-language literal
matching does not generalise the way manifest detection does. Every other
language's source files are counted and reported in coverage.skipped so the
gap lands in the contract instead of vanishing.
"""

import re
from collections import Counter

from depscanlib.walk import read_text

SOURCE_LANGUAGES = {
    ".go": "go",
    ".ts": "ts", ".tsx": "ts",
    ".js": "js", ".jsx": "js", ".mjs": "js", ".cjs": "js",
    ".py": "python", ".pyi": "python",
}

# Languages we can name but deliberately do not scan. Anything not listed
# here and not in SOURCE_LANGUAGES is not source, so it is not "skipped".
OTHER_LANGUAGES = {
    ".rs": "rust", ".java": "java", ".kt": "kotlin", ".rb": "ruby",
    ".php": "php", ".cs": "csharp", ".swift": "swift", ".scala": "scala",
    ".c": "c", ".h": "c", ".cc": "cpp", ".cpp": "cpp", ".hpp": "cpp",
    ".ex": "elixir", ".exs": "elixir", ".erl": "erlang", ".dart": "dart",
    ".pl": "perl", ".lua": "lua", ".r": "r", ".m": "objc",
}

SKIP_REASON = "source-literal scanning covers go, js, python, and ts only"

ENV_PATTERNS = {
    "go": [
        re.compile(r'os\.(?:Getenv|LookupEnv)\(\s*"([A-Za-z_][A-Za-z0-9_]*)"'),
    ],
    "python": [
        re.compile(r'os\.environ\[\s*["\']([A-Za-z_][A-Za-z0-9_]*)["\']'),
        re.compile(r'os\.environ\.get\(\s*["\']([A-Za-z_][A-Za-z0-9_]*)["\']'),
        re.compile(r'os\.getenv\(\s*["\']([A-Za-z_][A-Za-z0-9_]*)["\']'),
    ],
    "js": [
        re.compile(r'process\.env\.([A-Za-z_][A-Za-z0-9_]*)'),
        re.compile(r'process\.env\[\s*["\']([A-Za-z_][A-Za-z0-9_]*)["\']'),
    ],
}
ENV_PATTERNS["ts"] = ENV_PATTERNS["js"]

# (compiled pattern, kind). Documented for humans in
# references/resilience-signatures.md — keep the two in step.
RESILIENCE_PATTERNS = {
    "go": [
        (re.compile(r'context\.WithTimeout\([^)]*\)'), "timeout"),
        (re.compile(r'context\.WithDeadline\([^)]*\)'), "deadline"),
        (re.compile(r'\bTimeout:\s*[^,\n}]+'), "timeout"),
        (re.compile(r'\b(?:backoff|retry)\.[A-Za-z]+\([^)]*\)'), "retry"),
        (re.compile(r'\bgobreaker\b[^\n]*'), "circuit-breaker"),
    ],
    "python": [
        (re.compile(r'\btimeout\s*=\s*[^,)\n]+'), "timeout"),
        (re.compile(r'@retry\b[^\n]*'), "retry"),
        (re.compile(r'\btenacity\b[^\n]*'), "retry"),
        (re.compile(r'\bpybreaker\b[^\n]*'), "circuit-breaker"),
    ],
    "js": [
        (re.compile(r'AbortSignal\.timeout\([^)]*\)'), "timeout"),
        (re.compile(r'\btimeout\s*:\s*[^,\n}]+'), "timeout"),
        (re.compile(r'\bp-retry\b[^\n]*'), "retry"),
        (re.compile(r'\bopossum\b[^\n]*'), "circuit-breaker"),
    ],
}
RESILIENCE_PATTERNS["ts"] = RESILIENCE_PATTERNS["js"]


def _suffix(path):
    dot = path.rfind(".")
    return path[dot:].lower() if dot > 0 else ""


def _scan_file(root, path, language, env_out, resilience_out):
    text = read_text(root, path)
    if not text:
        return
    for number, line in enumerate(text.splitlines(), start=1):
        for pattern in ENV_PATTERNS.get(language, []):
            for match in pattern.finditer(line):
                env_out.append({"name": match.group(1), "file": path,
                                "line": number})
        for pattern, kind in RESILIENCE_PATTERNS.get(language, []):
            for match in pattern.finditer(line):
                resilience_out.append({"kind": kind, "raw": match.group(0).strip(),
                                       "file": path, "line": number,
                                       "language": language})


def scan_source(root, paths):
    """Return ({"env_refs": [...], "resilience_calls": [...]}, skipped).

    skipped carries one record per out-of-scope language actually present,
    so each skill can turn it into a named assumption.
    """
    env_refs, resilience_calls = [], []
    unscanned = Counter()

    for path in sorted(paths):
        suffix = _suffix(path)
        language = SOURCE_LANGUAGES.get(suffix)
        if language:
            _scan_file(root, path, language, env_refs, resilience_calls)
        elif suffix in OTHER_LANGUAGES:
            unscanned[OTHER_LANGUAGES[suffix]] += 1

    skipped = [{"reason": SKIP_REASON, "language": language, "count": count}
               for language, count in sorted(unscanned.items())]
    return {"env_refs": env_refs, "resilience_calls": resilience_calls}, skipped
```

- [ ] **Step 4: Wire it into `report.py`**

In `dependency-model/scripts/depscanlib/report.py`, import `scan_source` and merge its output:

```python
from depscanlib.source import scan_source
```

and in `build_scan`, replace the `skipped = []` placeholder with the real call:

```python
    findings = {key: [] for key in EMPTY_FINDINGS}
    source_findings, skipped = scan_source(root, paths)
    findings.update(source_findings)
```

`build_coverage(paths, skipped)` already receives it, so nothing else changes.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_depscan_source.py tests/test_depscan_cli.py -q`
Expected: PASS.

- [ ] **Step 6: Run the full checks and commit**

```bash
uv run ruff check .
uv run pytest -q
git add dependency-model/scripts/depscanlib/source.py dependency-model/scripts/depscanlib/report.py tests/test_depscan_source.py tests/test_depscan_cli.py
git commit -m "feat(dependency-model): env-ref and resilience-call extraction for go/ts/js/python (#48)"
```

---

### Task 5: Literal extractors — URLs, host:port, and secret-shaped key names

Language-agnostic regex over every text file, source and config alike. This is where the credential rule gets its scanner-level enforcement: `secret_shaped_keys` records key **names** and nothing else, and a test proves a planted secret value never reaches the output.

**Files:**
- Create: `dependency-model/scripts/depscanlib/literals.py`
- Modify: `dependency-model/scripts/depscanlib/report.py`
- Test: `tests/test_depscan_literals.py`

**Interfaces:**
- Produces: `scan_literals(root, paths) -> dict[str, list]` with keys `url_literals`, `host_port_literals`, `secret_shaped_keys`.
- `url_literals` items: `{"value", "scheme", "host", "file", "line"}`.
- `host_port_literals` items: `{"host", "port", "file", "line"}`.
- `secret_shaped_keys` items: `{"name", "file", "line"}` — **name only, never a value**.

- [ ] **Step 1: Write the failing test**

Create `tests/test_depscan_literals.py`:

```python
# tests/test_depscan_literals.py
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dependency-model" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from depscanlib.literals import scan_literals
from depscanlib.walk import walk_repo
from repobuilder import build_repo


def scan(files):
    with tempfile.TemporaryDirectory() as tmp:
        root = build_repo(tmp, files)
        paths, _ = walk_repo(root)
        return scan_literals(root, paths)


class TestUrlLiterals(unittest.TestCase):
    def test_extracts_scheme_and_host(self):
        findings = scan({"client.go": 'const base = "https://api.stripe.com/v1"\n'})
        self.assertEqual(findings["url_literals"], [{
            "value": "https://api.stripe.com/v1", "scheme": "https",
            "host": "api.stripe.com", "file": "client.go", "line": 1}])

    def test_extracts_non_http_schemes(self):
        findings = scan({".env": "DATABASE_URL=postgres://user@db:5432/app\n"
                                 "AMQP=amqp://guest@rabbit:5672\n"})
        self.assertEqual(sorted(u["scheme"] for u in findings["url_literals"]),
                         ["amqp", "postgres"])

    def test_strips_trailing_quotes_and_punctuation(self):
        findings = scan({"a.py": 'URL = "https://example.com/x",\n'})
        self.assertEqual(findings["url_literals"][0]["value"],
                         "https://example.com/x")

    def test_ignores_schema_urls_in_json_documents(self):
        """A $schema pointer is a document identifier, not a dependency."""
        findings = scan({"c.json": json.dumps(
            {"$schema": "https://json-schema.org/draft/2020-12/schema"}) + "\n"})
        self.assertEqual(findings["url_literals"], [])


class TestHostPortLiterals(unittest.TestCase):
    def test_extracts_hostname_and_port(self):
        findings = scan({"docker-compose.yml":
            'services:\n  app:\n    environment:\n      REDIS: "redis:6379"\n'})
        self.assertEqual(findings["host_port_literals"], [{
            "host": "redis", "port": 6379,
            "file": "docker-compose.yml", "line": 4}])

    def test_extracts_ipv4_and_port(self):
        findings = scan({"conf.ini": "backend = 10.0.1.5:8080\n"})
        self.assertEqual(findings["host_port_literals"][0]["host"], "10.0.1.5")

    def test_ignores_a_bare_time_of_day(self):
        findings = scan({"README.md": "The standup is at 09:30 every day.\n"})
        self.assertEqual(findings["host_port_literals"], [])

    def test_ignores_an_image_tag(self):
        """postgres:16 is a version, not an endpoint."""
        findings = scan({"docker-compose.yml":
            "services:\n  db:\n    image: postgres:16\n"})
        self.assertEqual(findings["host_port_literals"], [])

    def test_port_is_an_integer_not_a_string(self):
        findings = scan({"a.env": "ADDR=db:5432\n"})
        self.assertIsInstance(findings["host_port_literals"][0]["port"], int)


class TestSecretShapedKeys(unittest.TestCase):
    def test_finds_secret_shaped_env_keys(self):
        findings = scan({".env": "STRIPE_API_KEY=sk_live_abc123\n"
                                 "DB_PASSWORD=hunter2\n"
                                 "LOG_LEVEL=debug\n"})
        self.assertEqual(sorted(k["name"] for k in findings["secret_shaped_keys"]),
                         ["DB_PASSWORD", "STRIPE_API_KEY"])

    def test_never_records_the_value(self):
        """A discovery skill that writes credentials into a contract is a leak.
        The scanner must not hand it one to write."""
        findings = scan({".env": "STRIPE_API_KEY=sk_live_abc123\n",
                         "app.py": 'TOKEN = "ghp_realtokenvalue"\n',
                         "k8s.yaml": "apiVersion: v1\nkind: Secret\n"
                                     "data:\n  password: aHVudGVyMg==\n"})
        blob = json.dumps(findings)
        for secret in ("sk_live_abc123", "ghp_realtokenvalue", "aHVudGVyMg=="):
            with self.subTest(secret=secret):
                self.assertNotIn(secret, blob)

    def test_records_only_name_file_and_line(self):
        findings = scan({".env": "API_KEY=x\n"})
        self.assertEqual(sorted(findings["secret_shaped_keys"][0]),
                         ["file", "line", "name"])

    def test_matches_yaml_and_source_keys_not_only_env_files(self):
        findings = scan({"k8s.yaml": "apiVersion: v1\nkind: Secret\n"
                                     "stringData:\n  client_secret: x\n",
                         "app.py": 'PRIVATE_KEY = load()\n'})
        self.assertEqual(sorted(k["name"] for k in findings["secret_shaped_keys"]),
                         ["PRIVATE_KEY", "client_secret"])

    def test_key_shaped_words_in_prose_are_not_matched(self):
        findings = scan({"README.md":
            "The api key is supplied by the operator at deploy time.\n"})
        self.assertEqual(findings["secret_shaped_keys"], [])

    def test_findings_are_sorted_by_file_then_line(self):
        findings = scan({"b.env": "API_KEY=1\n", "a.env": "API_KEY=2\n"})
        self.assertEqual([k["file"] for k in findings["secret_shaped_keys"]],
                         ["a.env", "b.env"])


class TestBinaryAndLargeFiles(unittest.TestCase):
    def test_unreadable_bytes_do_not_crash_the_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {"a.py": "x = 1\n"})
            (Path(root) / "blob.bin").write_bytes(b"\x00\xff\xfe" * 100)
            paths, _ = walk_repo(root)
            self.assertEqual(scan_literals(root, paths)["url_literals"], [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_depscan_literals.py -q`
Expected: collection error on `depscanlib.literals`.

- [ ] **Step 3: Implement `literals.py`**

`dependency-model/scripts/depscanlib/literals.py`:

```python
"""Language-agnostic literal extraction over every readable text file.

secret_shaped_keys records key NAMES and locations only. It never captures a
value, in any form, from any file. A discovery contract carrying a credential
is a leak, and the cheapest place to make that impossible is here, where the
value would first be read.
"""

import re

from depscanlib.walk import read_text

TEXT_SUFFIXES_SKIPPED = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".gz", ".tar",
    ".woff", ".woff2", ".ttf", ".eot", ".so", ".dylib", ".dll", ".exe",
    ".class", ".jar", ".wasm", ".bin", ".db", ".sqlite", ".sqlite3",
}

URL_RE = re.compile(r'\b([a-z][a-z0-9+.\-]{1,15})://([^\s"\'`<>,)\]}]+)')

# host:port, not image:tag and not a clock. The port must be 2-5 digits and
# the whole match must not be followed by another colon-separated token.
HOST_PORT_RE = re.compile(
    r'(?<![\w.:/@-])'
    r'((?:\d{1,3}(?:\.\d{1,3}){3})|(?:[a-z][a-z0-9\-]*(?:\.[a-z0-9\-]+)*))'
    r':(\d{2,5})(?![\w.:])',
    re.IGNORECASE)

# A port is a port. 16 is an image tag, 30 is half past the hour.
MIN_PORT = 80
MAX_PORT = 65535

# The leading prefix is OPTIONAL: a key is very often the bare keyword
# (`password:`, `PRIVATE_KEY =`), and a mandatory prefix would match
# STRIPE_API_KEY while silently missing API_KEY. "AUTH" is deliberately not in
# the list -- it fires on `authors = [...]` in every pyproject.toml, and
# AUTH_TOKEN is already caught by TOKEN.
SECRET_NAME_RE = re.compile(
    r'\b((?:[A-Za-z][A-Za-z0-9_]*?)?'
    r'(?:SECRET|TOKEN|PASSWORD|PASSWD|API[_]?KEY|APIKEY|CREDENTIAL|'
    r'PRIVATE[_]?KEY|ACCESS[_]?KEY|CLIENT[_]?SECRET)'
    r'[A-Za-z0-9_]*)\b'
    r'(?=\s*[:=])',
    re.IGNORECASE)

SCHEMA_KEYS = ('"$schema"', "'$schema'", "$schema:")


def _is_text(path):
    dot = path.rfind(".")
    return dot < 0 or path[dot:].lower() not in TEXT_SUFFIXES_SKIPPED


def _url_host(rest):
    authority = rest.split("/", 1)[0]
    authority = authority.rsplit("@", 1)[-1]
    return authority.split(":", 1)[0]


def _strip_trailing(value):
    return value.rstrip('.,;:"\'`)]}>')


def scan_literals(root, paths):
    """Return URL, host:port, and secret-shaped-key findings across the repo."""
    urls, host_ports, secret_keys = [], [], []

    for path in sorted(paths):
        if not _is_text(path):
            continue
        text = read_text(root, path)
        if not text:
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if not any(marker in line for marker in SCHEMA_KEYS):
                for match in URL_RE.finditer(line):
                    value = _strip_trailing(match.group(0))
                    urls.append({"value": value, "scheme": match.group(1),
                                 "host": _url_host(match.group(2)),
                                 "file": path, "line": number})
            for match in HOST_PORT_RE.finditer(line):
                port = int(match.group(2))
                if MIN_PORT <= port <= MAX_PORT:
                    host_ports.append({"host": match.group(1), "port": port,
                                       "file": path, "line": number})
            for match in SECRET_NAME_RE.finditer(line):
                secret_keys.append({"name": match.group(1), "file": path,
                                    "line": number})

    return {"url_literals": urls, "host_port_literals": host_ports,
            "secret_shaped_keys": secret_keys}
```

Note on `HOST_PORT_RE`: URLs are matched by `URL_RE` as well and will also produce a `host_port_literals` record when they carry an explicit port. That is intentional — the network skill wants both readings and correlates them by `file:line`.

- [ ] **Step 4: Wire it into `report.py`**

```python
from depscanlib.literals import scan_literals
```

and in `build_scan`, after the source merge:

```python
    findings.update(scan_literals(root, paths))
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_depscan_literals.py tests/test_depscan_cli.py -q`
Expected: PASS. If `test_ignores_an_image_tag` fails, `MIN_PORT` is doing the work — do not lower it below 80 to make some other case pass; add a targeted exclusion instead.

- [ ] **Step 6: Run the full checks and commit**

```bash
uv run ruff check .
uv run pytest -q
git add dependency-model/scripts/depscanlib/literals.py dependency-model/scripts/depscanlib/report.py tests/test_depscan_literals.py
git commit -m "feat(dependency-model): url, host:port, and secret-shaped-key extraction (#48)"
```

---

### Task 6: Resource-limit extractor

The last findings key. Reads declared CPU, memory, disk, GPU, and platform figures out of Dockerfiles, compose files, and Kubernetes manifests. Text and regex only — `depscanlib` is stdlib-only, so there is no YAML parser to reach for.

**Files:**
- Create: `dependency-model/scripts/depscanlib/resources.py`
- Modify: `dependency-model/scripts/depscanlib/report.py`
- Test: `tests/test_depscan_resources.py`

**Interfaces:**
- Produces: `scan_resources(root, paths, files) -> list[dict]` where `files` is the `classify_files` result.
- Items: `{"kind", "raw", "file", "line", "source"}` with `kind` in `cpu`, `memory`, `disk`, `gpu`, `arch`, `os`, `runtime-version` and `source` in `dockerfile`, `compose`, `kubernetes`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_depscan_resources.py`:

```python
# tests/test_depscan_resources.py
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dependency-model" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from depscanlib.files import classify_files
from depscanlib.resources import scan_resources
from depscanlib.walk import walk_repo
from repobuilder import build_repo

K8S = (
    "apiVersion: apps/v1\n"
    "kind: Deployment\n"
    "spec:\n"
    "  template:\n"
    "    spec:\n"
    "      containers:\n"
    "        - name: api\n"
    "          resources:\n"
    "            limits:\n"
    "              cpu: \"2\"\n"
    "              memory: 512Mi\n"
    "              nvidia.com/gpu: 1\n"
    "            requests:\n"
    "              cpu: 500m\n"
)

COMPOSE = (
    "services:\n"
    "  app:\n"
    "    image: api:latest\n"
    "    mem_limit: 1g\n"
    "    cpus: 1.5\n"
    "    deploy:\n"
    "      resources:\n"
    "        limits:\n"
    "          memory: 2G\n"
)

DOCKERFILE = (
    "FROM --platform=linux/amd64 python:3.11-slim\n"
    "RUN pip install -r requirements.txt\n"
)


def scan(files):
    with tempfile.TemporaryDirectory() as tmp:
        root = build_repo(tmp, files)
        paths, _ = walk_repo(root)
        return scan_resources(root, paths, classify_files(root, paths))


def kinds(records):
    return sorted({r["kind"] for r in records})


class TestKubernetesResources(unittest.TestCase):
    def test_extracts_cpu_memory_and_gpu_limits(self):
        records = scan({"deploy/api.yaml": K8S})
        self.assertEqual(kinds(records), ["cpu", "gpu", "memory"])

    def test_records_the_declared_figure_verbatim(self):
        records = scan({"deploy/api.yaml": K8S})
        memory = [r for r in records if r["kind"] == "memory"]
        self.assertEqual(memory[0]["raw"], "512Mi")

    def test_records_source_and_one_indexed_line(self):
        records = scan({"deploy/api.yaml": K8S})
        self.assertTrue(all(r["source"] == "kubernetes" for r in records))
        self.assertTrue(all(r["line"] >= 1 for r in records))

    def test_requests_are_captured_as_well_as_limits(self):
        records = scan({"deploy/api.yaml": K8S})
        self.assertEqual(len([r for r in records if r["kind"] == "cpu"]), 2)


class TestComposeResources(unittest.TestCase):
    def test_extracts_short_form_and_deploy_form(self):
        records = scan({"docker-compose.yml": COMPOSE})
        self.assertEqual(kinds(records), ["cpu", "memory"])
        self.assertEqual(sorted(r["raw"] for r in records if r["kind"] == "memory"),
                         ["1g", "2G"])

    def test_source_is_compose(self):
        records = scan({"docker-compose.yml": COMPOSE})
        self.assertTrue(all(r["source"] == "compose" for r in records))


class TestDockerfileResources(unittest.TestCase):
    def test_extracts_platform_and_runtime_version(self):
        records = scan({"Dockerfile": DOCKERFILE})
        self.assertEqual(kinds(records), ["arch", "runtime-version"])
        arch = [r for r in records if r["kind"] == "arch"][0]
        self.assertEqual(arch["raw"], "linux/amd64")
        self.assertEqual(arch["source"], "dockerfile")

    def test_base_image_without_platform_still_yields_runtime_version(self):
        records = scan({"Dockerfile": "FROM golang:1.23-alpine AS build\n"})
        self.assertEqual(kinds(records), ["runtime-version"])
        self.assertEqual(records[0]["raw"], "golang:1.23-alpine")


class TestNoise(unittest.TestCase):
    def test_a_yaml_that_is_not_a_manifest_yields_nothing(self):
        records = scan({"config/app.yaml": "cpu: 2\nmemory: 512Mi\n"})
        self.assertEqual(records, [])

    def test_sorted_by_file_then_line(self):
        records = scan({"b/Dockerfile": DOCKERFILE, "a/Dockerfile": DOCKERFILE})
        self.assertEqual([r["file"] for r in records][:2],
                         ["a/Dockerfile", "a/Dockerfile"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_depscan_resources.py -q`
Expected: collection error on `depscanlib.resources`.

- [ ] **Step 3: Implement `resources.py`**

`dependency-model/scripts/depscanlib/resources.py`:

```python
"""Extract declared resource figures from Dockerfiles, compose, and k8s.

Every figure here is a declared one. Per D3 nothing is measured, so a value
this module cannot find in a file simply is not reported.

Text and regex, not a YAML parse: depscanlib is stdlib-only so depscan.py
runs under bare python3 with no dependencies.
"""

import re
from pathlib import PurePosixPath

from depscanlib.walk import read_text

DOCKERFILE_NAMES = {"Dockerfile", "Containerfile"}

K8S_CPU_RE = re.compile(r'^\s*cpu:\s*["\']?([^"\'\n#]+?)["\']?\s*$')
K8S_MEMORY_RE = re.compile(r'^\s*memory:\s*["\']?([^"\'\n#]+?)["\']?\s*$')
K8S_GPU_RE = re.compile(r'^\s*[\w.\-/]*gpu:\s*["\']?([^"\'\n#]+?)["\']?\s*$',
                        re.IGNORECASE)
K8S_STORAGE_RE = re.compile(r'^\s*(?:ephemeral-)?storage:\s*["\']?([^"\'\n#]+?)["\']?\s*$')

COMPOSE_RES_RES = (
    (re.compile(r'^\s*mem_limit:\s*["\']?([^"\'\n#]+?)["\']?\s*$'), "memory"),
    (re.compile(r'^\s*mem_reservation:\s*["\']?([^"\'\n#]+?)["\']?\s*$'), "memory"),
    (re.compile(r'^\s*memory:\s*["\']?([^"\'\n#]+?)["\']?\s*$'), "memory"),
    (re.compile(r'^\s*cpus:\s*["\']?([^"\'\n#]+?)["\']?\s*$'), "cpu"),
    (re.compile(r'^\s*cpu_shares:\s*["\']?([^"\'\n#]+?)["\']?\s*$'), "cpu"),
    (re.compile(r'^\s*shm_size:\s*["\']?([^"\'\n#]+?)["\']?\s*$'), "memory"),
)

FROM_RE = re.compile(
    r'^\s*FROM\s+(?:--platform=(?P<platform>\S+)\s+)?(?P<image>\S+)',
    re.IGNORECASE)


def _record(kind, raw, path, line, source):
    return {"kind": kind, "raw": raw.strip(), "file": path, "line": line,
            "source": source}


def _scan_dockerfile(root, path, out):
    for number, line in enumerate(read_text(root, path).splitlines(), start=1):
        match = FROM_RE.match(line)
        if not match:
            continue
        if match.group("platform"):
            out.append(_record("arch", match.group("platform"), path, number,
                               "dockerfile"))
        out.append(_record("runtime-version", match.group("image"), path, number,
                           "dockerfile"))


def _scan_kubernetes(root, path, out):
    for number, line in enumerate(read_text(root, path).splitlines(), start=1):
        for pattern, kind in ((K8S_GPU_RE, "gpu"), (K8S_CPU_RE, "cpu"),
                              (K8S_MEMORY_RE, "memory"), (K8S_STORAGE_RE, "disk")):
            match = pattern.match(line)
            if match:
                out.append(_record(kind, match.group(1), path, number,
                                   "kubernetes"))
                break


def _scan_compose(root, path, out):
    for number, line in enumerate(read_text(root, path).splitlines(), start=1):
        for pattern, kind in COMPOSE_RES_RES:
            match = pattern.match(line)
            if match:
                out.append(_record(kind, match.group(1), path, number, "compose"))
                break


def scan_resources(root, paths, files):
    """Return declared resource figures, sorted by file then line.

    files is classify_files()'s result: only files it recognised as compose or
    kubernetes are read that way, so an ordinary config.yaml with a `cpu:` key
    is never mistaken for a manifest.
    """
    out = []
    for path in sorted(files.get("k8s", [])):
        _scan_kubernetes(root, path, out)
    for path in sorted(files.get("compose", [])):
        _scan_compose(root, path, out)
    for path in sorted(paths):
        if PurePosixPath(path).name in DOCKERFILE_NAMES:
            _scan_dockerfile(root, path, out)
    return sorted(out, key=lambda r: (r["file"], r["line"], r["kind"]))
```

- [ ] **Step 4: Wire it into `report.py`**

```python
from depscanlib.resources import scan_resources
```

In `build_scan`, `files` is already held in a local from Task 3, so this is one added line after the literals merge:

```python
    findings["resource_limits"] = scan_resources(root, paths, files)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_depscan_resources.py tests/test_depscan_cli.py -q`
Expected: PASS.

Then run the scanner against this repo end to end:

```bash
uv run --script dependency-model/scripts/depscan.py . | python3 -c "import json,sys; d=json.load(sys.stdin); print({k: len(v) for k, v in d['findings'].items()}); print(d['coverage'])"
```
Expected: non-zero `env_refs`, `url_literals`, and `secret_shaped_keys`; every key present.

- [ ] **Step 6: Run the full checks and commit**

```bash
uv run ruff check .
uv run pytest -q
git add dependency-model/scripts/depscanlib/resources.py dependency-model/scripts/depscanlib/report.py tests/test_depscan_resources.py
git commit -m "feat(dependency-model): declared resource-limit extraction (#48)"
```

---

### Task 7: Reference documents

The three prose references the six SKILL.md files point at. They must exist before any skill references them, or `test_plugin_root_references_resolve` fails.

**Files:**
- Create: `dependency-model/references/categories.md`
- Create: `dependency-model/references/resilience-signatures.md`
- Create: `dependency-model/references/running-discovery.md`
- Test: `tests/test_dependency_model_references.py`

**Interfaces:**
- Produces: three reference files, each referenced from at least one SKILL.md in Tasks 8–9 as `${CLAUDE_PLUGIN_ROOT}/references/<name>.md`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_dependency_model_references.py`:

```python
# tests/test_dependency_model_references.py
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

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


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_dependency_model_references.py -q`
Expected: FAIL — `test_the_three_references_are_present`.

- [ ] **Step 3: Write `categories.md`**

Create `dependency-model/references/categories.md`. It must contain, in prose:

- A section per category stating what belongs in it and what does not, matching the six one-line questions in the spec's scope table.
- The adjudication rule, verbatim in substance: **`service` records the thing depended on; `network` records the path used to reach it.** Both will see the same `postgres:5432`. Both record it, and they link through `related_ids`.
- Worked adjudications for the ambiguous cases: a hostname in a connection string (both — `service` for the database, `network` for the name that must resolve); an API base URL (`service` when the system calls it, `network` for the egress it implies); a container port a service listens on (`network` only, `direction: inbound`); a config key naming an endpoint (`config` for the key, `network` for the value, linked); a Kubernetes secret holding a database password (`security` for the secret reference, `config` for the key that reads it — never the value).
- The rule that a dependency appears in more than one category only when each category records a genuinely different fact about it, never as a duplicate.

- [ ] **Step 4: Write `resilience-signatures.md`**

Create `dependency-model/references/resilience-signatures.md`, documenting for a human what `depscanlib/source.py` matches for a machine. It must contain:

- A table per ecosystem — Go, TypeScript/JavaScript, Python — listing the patterns and the `kind` each maps to, kept in step with `RESILIENCE_PATTERNS` in `source.py`.
- Go: `context.WithTimeout` → timeout, `context.WithDeadline` → deadline, a `Timeout:` struct field → timeout, `backoff.*` / `retry.*` → retry, `gobreaker` → circuit-breaker.
- Python: `timeout=` kwarg → timeout, `@retry` and `tenacity` → retry, `pybreaker` → circuit-breaker.
- TypeScript/JavaScript: `AbortSignal.timeout(...)` → timeout, a `timeout:` option → timeout, `p-retry` → retry, `opossum` → circuit-breaker.
- The correlation instruction: a `resilience_calls` record belongs to a dependency when it sits in a file that also carries that dependency's client construction or its config key, and the skill records the `file:line` of the call as the resilience evidence.
- The load-bearing sentence: **`null` means no declaration was found in the repository — never that the behaviour is confirmed absent.** A downstream layer reads a null on a request-path dependency as a candidate gap; layer 1 must not have decided for it.
- The D9 boundary: a repository whose primary language is outside these three still gets full file-based coverage, and each skill records an assumption naming the language and what went unscanned, drawn from the scan's `coverage.skipped`.

- [ ] **Step 5: Write `running-discovery.md`**

Create `dependency-model/references/running-discovery.md`. It must contain:

- The sequence: invoke `profile:topology` to get the seed contract; run `depscan.py` once; then run the six skills in any order, or concurrently, each reading the same scan output.
- The exact commands:

```bash
uv run --script ${CLAUDE_PLUGIN_ROOT}/scripts/depscan.py <repo> > /tmp/depscan.json
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/depscan.py <repo> > /tmp/depscan.json   # fallback, no deps
```

- Each of the six invocations named explicitly: `/dependency-model:package`, `/dependency-model:service`, `/dependency-model:config`, `/dependency-model:security`, `/dependency-model:platform`, `/dependency-model:network`.
- Why there is **no orchestrator** in this layer (D8): layer 2's report skill must gather all six contracts to render anything, so it becomes the orchestrator; building one here would mean building it twice.
- How the six envelopes merge: a key union under `categories`, because each skill emits a full envelope with exactly one category populated.
- The `exclusions[]` note: it is the single source of truth for both tools. The `package` skill passes each entry to `syft --exclude`; the five file-scanning skills inherit the same list by reading the index. Without it, syft reports a nested virtualenv as the project's dependency set.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_dependency_model_references.py -q`
Expected: PASS.

- [ ] **Step 7: Run the full checks and commit**

```bash
uv run ruff check .
uv run pytest -q
git add dependency-model/references tests/test_dependency_model_references.py
git commit -m "docs(dependency-model): category adjudication, resilience signatures, run sequence (#48)"
```

---

### Task 8: The `package` and `service` skills

Two skills, written together because they are the pair that differ most from the rest and from each other: `package` is the only one that shells out to `syft` and the only one whose evidence is a bare file path; `service` is the hub the other four link to.

**Files:**
- Create: `dependency-model/skills/package/SKILL.md`
- Create: `dependency-model/skills/service/SKILL.md`

**Interfaces:**
- Consumes: `${CLAUDE_PLUGIN_ROOT}/references/contracts/{package,service}.schema.json`, `.../examples/{package,service}.example.json`, `${CLAUDE_PLUGIN_ROOT}/references/categories.md`, `${CLAUDE_PLUGIN_ROOT}/references/resilience-signatures.md`, `${CLAUDE_PLUGIN_ROOT}/references/running-discovery.md`, `${CLAUDE_PLUGIN_ROOT}/scripts/depscan.py`.
- Produces: `/dependency-model:package` and `/dependency-model:service`, each emitting a `discovery` envelope with its own category populated.

Frontmatter for every skill in this plugin follows the repo rule: `name` equals the directory name, a `description` beginning with the value produced and ending with `Emits the dependency-model:discovery contract.`, and **no `version:` field**.

- [ ] **Step 1: Write `dependency-model/skills/package/SKILL.md`**

```markdown
---
name: package
description: Inventory the libraries a project ships with and at what versions — every ecosystem syft catalogues, with declared/locked/installed resolution and the dependency edges between them. Read-only. Use when auditing dependencies, planning an upgrade, or building a dependency graph. Emits the dependency-model:discovery contract.
---

# package

Inventory what a project ships with. Emits the `discovery` contract with the
`package` category populated.

**This skill never executes the project.** `syft` reads files; nothing is built,
installed, resolved over the network, or run.

Contract: `${CLAUDE_PLUGIN_ROOT}/references/contracts/package.schema.json`
Envelope: `${CLAUDE_PLUGIN_ROOT}/references/contracts/discovery.schema.json`
Example: `${CLAUDE_PLUGIN_ROOT}/references/contracts/examples/package.example.json`
Categories: `${CLAUDE_PLUGIN_ROOT}/references/categories.md`
Sequence: `${CLAUDE_PLUGIN_ROOT}/references/running-discovery.md`

## Usage

    /dependency-model:package [path]

Standalone invocation: if you were not handed a `profile:topology` contract,
invoke `profile:topology` first and use its output as `seeded_by`. Never invoke
another plugin's script by path.

`syft` is required. If it is not on PATH, emit the envelope with
`status: "failed"`, an assumption saying so, and stop — do not substitute a
hand-rolled lockfile parse.

## Procedure

1. Run the shared scan once to get the exclusion list:

       uv run --script ${CLAUDE_PLUGIN_ROOT}/scripts/depscan.py <path>

   Use `python3` in place of `uv run --script` if `uv` is unavailable.

2. Run syft with every entry from the scan's `exclusions[]` passed as
   `--exclude`:

       syft scan dir:<path> -o syft-json --quiet --exclude './node_modules' --exclude './.venv' ...

   **The exclusions are not optional.** Unscoped, syft catalogues installed
   trees as though they were the project's dependency set: measured on this
   marketplace, an unscoped scan reported 270 packages against 2 declared
   direct dependencies, 188 of them from a nested virtualenv.

3. For each syft artifact, emit one dependency:
   - `id` is `package:<name>-<major-or-version-slug>`, stable across runs.
   - `name`, `details.version`, `details.purl`, `details.ecosystem` come
     straight from the artifact.
   - `evidence` is `locations[].path` — **a bare file path, no line number.**
     syft reports file-level locations only; do not invent a line.
   - `details.resolution` is your judgment from the location it was catalogued
     at: `declared` for a manifest, `locked` for a lockfile, `installed` for an
     installed tree. syft conflates the three; you must not.
   - `details.direct` is true when the package is named in a manifest the
     project owns, false when it is only reachable through another package,
     null when you cannot tell.
   - `details.pinned` is true when the version is exact, false for a range.
4. Read syft's `artifactRelationships` and fill `details.depends_on[]` from the
   `dependency-of` edges, mapping syft artifact ids to your `package:` ids.
   Ignore `contains` and `evident-by`.
5. Set `resilience` on every package entry: all four facts `null` and
   `on_path: ["build"]`. A library declaration carries no timeout or retry of
   its own; the code that calls it does, and that belongs to `service`.
6. Link `related_ids` to `service` entries where a package is unmistakably a
   client for a discovered service, and say so in an assumption if the link is
   an inference rather than a fact.
7. Emit the full envelope, then a short prose summary: package count by
   ecosystem, how many are direct, and how many are pinned.

## Rules

- Read-only. Nothing is installed, built, or resolved over the network.
- Evidence for this category is a **file path**, not `file:line`. Every other
  category carries `file:line`.
- `null` in `resilience` means no declaration was found — never that the
  behaviour is confirmed absent.
- If syft returns zero artifacts for a repository that plainly has manifests,
  that is a `failed` status with an assumption, not a `discovered` empty list.
- An empty list with `status: "discovered"` is a legitimate finding for a
  project with no third-party dependencies.
- Do not report vulnerabilities, licences as findings, or upgrade advice. This
  layer reports what is there.
```

- [ ] **Step 2: Write `dependency-model/skills/service/SKILL.md`**

Same structure, with this body:

```markdown
---
name: service
description: Identify the out-of-project services a system needs — databases, caches, queues, object stores, search engines, and APIs — with the timeout, retry, fallback, and health-check declarations that bear on how each one fails. Read-only. Use when mapping a system's runtime dependencies or planning failure testing. Emits the dependency-model:discovery contract.
---
```

Body sections, in this order:

- A one-paragraph statement of what the skill emits, and the read-only sentence: nothing resolves a name, opens a socket, or boots a container.
- The five `${CLAUDE_PLUGIN_ROOT}` pointers: the `service` schema, the envelope, the `service` example, `categories.md`, `resilience-signatures.md`.
- `## Usage` — `/dependency-model:service [path]`, plus the standalone bootstrap: invoke `profile:topology` by name if you were not handed its contract.
- `## Procedure`, numbered:
  1. Run `depscan.py` once (with the `python3` fallback documented) and read the index.
  2. Seed from the `topology` contract's `real_dependencies` and `external_third_parties`. These are coarse by design — refine them, do not simply copy them.
  3. Read every file under the index's `files.compose`, `files.k8s`, and `files.iac` for service declarations: images, chart dependencies, managed-service resources.
  4. Read `findings.url_literals` and `findings.host_port_literals` for services the config files do not declare, and the manifests from the `package` category for client libraries that imply one.
  5. Assign `details.kind` from the enumerated set, and `details.managed_by` from how it is brought up.
  6. Fill `details.config_keys[]` from `findings.env_refs` whose name plainly points at this service, and link each to its `config:` id in `related_ids`.
  7. Fill `resilience` per `resilience-signatures.md`: correlate `findings.resilience_calls` in the files that construct this service's client, record the call's `file:line` as evidence, and set every fact you cannot find to `null`.
  8. Set `resilience.on_path` from where the client is constructed — startup wiring, a request handler, a background worker, or a build step. Leave it empty when the repository does not say.
  9. Link `related_ids` to the `network:` entry for the host and port this service is reached on. Both categories record it; `categories.md` has the rule.
  10. If the index's `coverage.skipped` is non-empty, record one assumption per skipped language naming it and what went unscanned.
  11. Emit the full envelope, then a short prose summary.
- `## Rules`:
  - Read-only; an unconfirmable claim becomes an assumption, never a probe.
  - `null` in `resilience` means no declaration was found — never confirmed absent.
  - An empty `dependencies` list with `status: "discovered"` is a legitimate finding for a pure library or CLI. A scan that could not complete is `failed`.
  - `service` records the thing depended on; `network` records the path used to reach it. Both record the same `postgres:5432` and link through `related_ids`.
  - No criticality, no blast radius, no monitoring-gap judgment, no test strategy. This layer reports facts.
  - Never invoke `profile`'s scripts by path; invoke `profile:topology` by name.

- [ ] **Step 3: Run the structural checks**

Run: `uv run pytest tests/test_plugin_structure.py -q`
Expected: PASS. Both new SKILL.md files must satisfy `test_skill_frontmatter_name_matches_directory`, `test_skill_frontmatter_has_no_version_field`, and `test_plugin_root_references_resolve`.

If `test_dispatching_skills_declare_no_subagent_fallback` fires, a SKILL.md used the word "subagent" — remove it. These skills do not dispatch.

- [ ] **Step 4: Run the full checks and commit**

```bash
uv run ruff check .
uv run pytest -q
git add dependency-model/skills/package dependency-model/skills/service
git commit -m "feat(dependency-model): package and service discovery skills (#48)"
```

---

### Task 9: The `config`, `security`, `platform`, and `network` skills

The remaining four. Same skeleton as `service`; the differences are which findings each reads and what it must refuse to record.

**Files:**
- Create: `dependency-model/skills/config/SKILL.md`
- Create: `dependency-model/skills/security/SKILL.md`
- Create: `dependency-model/skills/platform/SKILL.md`
- Create: `dependency-model/skills/network/SKILL.md`

**Interfaces:**
- Consumes: the same references and contracts as Task 8, plus each category's own schema and example.
- Produces: `/dependency-model:config`, `/dependency-model:security`, `/dependency-model:platform`, `/dependency-model:network`.

Every one of the four carries the same skeleton as `service`: frontmatter, the pointers, `## Usage`, `## Procedure`, `## Rules`. Five sentences are **load-bearing and asserted by `tests/test_dependency_model_coupling.py` in Task 10** — write them into each of the four, near-verbatim, not paraphrased:

1. `Read-only.` in the frontmatter description and again in `## Rules`.
2. `` `null` in `resilience` means no declaration was found — never that the behaviour is confirmed absent. `` (the test greps for both `no declaration was found` and `confirmed absent`).
3. `An empty `dependencies` list with `status: "discovered"` is a legitimate finding for a project this category does not apply to. A scan that could not complete is `failed`.` (the test greps for both `legitimate finding` and `failed`).
4. `Standalone invocation: if you were not handed a `profile:topology` contract, invoke `profile:topology` first and use its output as `seeded_by`. Never invoke another plugin's script by path.` (the test greps for `profile:topology`, and separately asserts no skill contains `profile/scripts` or `profile_inventory.py`).
5. `No criticality, no blast radius, no monitoring-gap judgment, no test strategy. This layer reports facts.` (the test allows a banned word only on a line that disclaims it).

Each also carries the three `${CLAUDE_PLUGIN_ROOT}` pointers the test checks — its own `contracts/<category>.schema.json`, its own `examples/<category>.example.json`, and `contracts/discovery.schema.json` — plus `references/categories.md`.

And each ends its procedure with the shared D9 step: **if the index's `coverage.skipped` is non-empty, record one assumption per skipped language, naming the language and what went unscanned.**

- [ ] **Step 1: Write `config/SKILL.md`**

Frontmatter description: "Enumerate the configuration a system must be supplied with to run — environment variables, config files, flags, and remote config — with what reads each key, whether it is required, and what default it declares. Read-only. Use when documenting deployment requirements or planning test environments. Emits the dependency-model:discovery contract."

Procedure, beyond the shared skeleton:
1. Read `findings.env_refs` — each is a `{name, file, line}` triple; that is your primary evidence and the `file:line` goes straight into `evidence`.
2. Read every file under `files.env` for declared keys and their presence, and every config loader in the repository for keys the literal scan missed.
3. Set `details.mechanism` from where the key is read: `env`, `file`, `flag`, `remote`, `constant`, or `unknown`.
4. Set `details.required` from whether the code fails without it — a lookup with no default is required, a `.get(name, default)` is not. Set it `null` when the repository does not say.
5. Record `details.default` only when the repository declares one literally.
6. Fill `details.consumed_by[]` from the files the key is read in.
7. Set `details.validated` true only when the repository declares a parse or validation step for the key.
8. Link `related_ids` to the `service:` or `network:` entry the key points at.
9. `resilience` on a config entry: all four facts `null`, `on_path` from where the key is read.

Rule specific to this skill: **record a key's name, its location, and its declared default — never a value read from a `.env` file that is not a committed placeholder.** If a `.env` file carries a real-looking value, record the key and add an assumption; do not copy the value.

- [ ] **Step 2: Write `security/SKILL.md`**

Frontmatter description: "Enumerate the secrets and permissions a system requires — what each credential is named, where it is read, and which policies grant what. Records names and locations only, never values. Read-only. Use when auditing a system's credential surface or planning least-privilege review. Emits the dependency-model:discovery contract."

Procedure, beyond the shared skeleton:
1. Read `findings.secret_shaped_keys` — the scanner records key names and locations and deliberately never captures a value.
2. Read IAM, RBAC, and policy files under `files.iac` and `files.k8s` for grants, roles, and scopes.
3. Read auth middleware and client construction for the credentials they consume.
4. Set `details.kind` from the enumerated set, `details.provider` from where the credential lives (kubernetes, vault, aws-secrets-manager, env, file, unknown), `details.scope` from what it authorises, and `details.granted_to[]` from the principals a policy names.
5. Set `details.rotation_declared` true only when the repository declares a rotation mechanism.
6. `resilience` on a security entry: all four facts `null`, `on_path` from where the credential is read.

Rules specific to this skill, stated as their own section:

```markdown
## The credential rule

This skill records that a secret exists, what it is called, and where it is
read. It does not record what it is.

- **Never read a secret's value.** Not from a `.env` file, not from a
  Kubernetes manifest's `data:` or `stringData:` block, not from a committed
  config file, not from a fixture.
- **Never open a file under `~/.keys/`.** Not to check its format, not to
  confirm it exists.
- The `security` sub-schema declares no field a value could be written into,
  and a test enforces that. If you find yourself wanting one, the answer is an
  assumption, not a new field.
- A value that appears in the repository by accident is a finding about the
  repository — record the key and its location, add an assumption saying a
  literal-looking value is committed there, and do not reproduce it.
```

- [ ] **Step 3: Write `platform/SKILL.md`**

Frontmatter description: "Enumerate the OS and cloud resources a system declares a need for — CPU, memory, disk, GPU, architecture, runtime versions, and managed cloud services. Every figure is a declared one; nothing is measured. Read-only. Use when sizing an environment or planning capacity review. Emits the dependency-model:discovery contract."

Procedure, beyond the shared skeleton:
1. Read `findings.resource_limits` — each record carries `kind`, the declared figure as `raw`, `file:line`, and the `source` it came from.
2. Read `files.iac` for managed cloud services the system provisions, and `files.ci` for runner and image declarations.
3. Read language manifests for declared runtime version floors.
4. Set `details.declared_value` to the figure **exactly as the repository writes it** — `512Mi`, not `512 MiB`, not `536870912`.
5. Set `details.component` to the container or service the figure applies to, `null` when it is repository-wide.
6. `resilience` on a platform entry: all four facts `null`, `on_path` from the stage the figure applies to.

Rule specific to this skill: **latency and bandwidth come only from declared timeouts and documented SLOs.** Per D3 there is nothing to measure from here, and a figure measured on a developer's machine would be a confidently wrong figure.

- [ ] **Step 4: Write `network/SKILL.md`**

Frontmatter description: "Enumerate the names, hosts, and ports a system must resolve and connect to — inbound listeners, outbound endpoints, DNS, proxies, and ingress. Nothing is resolved or probed. Read-only. Use when mapping a system's network surface or planning egress policy. Emits the dependency-model:discovery contract."

Procedure, beyond the shared skeleton:
1. Read `findings.host_port_literals` and `findings.url_literals` — both carry `file:line`.
2. Read `files.compose` and `files.k8s` for published ports, services, and ingress; `files.iac` for security groups, egress rules, and DNS records; and proxy configuration wherever it lives.
3. Set `details.kind` and `details.direction` from what the declaration is: a published container port is `port` / `inbound`; a connection string host is `hostname` / `outbound`; an ingress host is `ingress` / `inbound`.
4. Set `details.value` to the literal as written, and `details.resolution_mechanism` to how the name is expected to resolve (compose service name, kubernetes DNS, public DNS, hosts file, environment-supplied), `null` when the repository does not say.
5. Link `related_ids` to the `service:` entry this path reaches and the `config:` key that supplies it.
6. `resilience` on a network entry: correlate `findings.resilience_calls` in the same file where the endpoint is used, exactly as `service` does.

Rules specific to this skill:
- **Nothing is resolved and nothing is probed.** A hostname that resolves on your workstation may not resolve where the system runs; a port that answers here proves nothing there. Record what is declared.
- `network` records the path used to reach a dependency; `service` records the thing itself. Both record the same `postgres:5432` and link through `related_ids`.

- [ ] **Step 5: Run the structural checks**

Run: `uv run pytest tests/test_plugin_structure.py -q`
Expected: PASS for all six skills.

- [ ] **Step 6: Run the full checks and commit**

```bash
uv run ruff check .
uv run pytest -q
git add dependency-model/skills/config dependency-model/skills/security dependency-model/skills/platform dependency-model/skills/network
git commit -m "feat(dependency-model): config, security, platform, and network discovery skills (#48)"
```

---

### Task 10: Register the plugin and pin its coupling

Everything the plugin needs to be installable, plus the tests that keep the discipline the spec argues for from eroding. This is the task where the derived artifacts named in `CLAUDE.md` are updated — all of them, in one commit.

**Files:**
- Create: `dependency-model/.claude-plugin/plugin.json`
- Create: `dependency-model/requirements.json`
- Create: `dependency-model/.codex-plugin/plugin.json` (generated — do not hand-write)
- Modify: `.claude-plugin/marketplace.json`
- Modify: `.agents/plugins/marketplace.json` (generated)
- Modify: `scripts/verify-marketplace.sh` (`PLUGINS` and `SCRIPTS` arrays)
- Modify: `README.md` (plugin count, new `### dependency-model` section)
- Test: `tests/test_dependency_model_coupling.py`

**Interfaces:**
- Produces: `dependency-model` v0.1.0 in category `development`, with skills `config,network,package,platform,security,service`.
- Consumes: nothing new.

- [ ] **Step 1: Write the failing test**

Create `tests/test_dependency_model_coupling.py`:

```python
# tests/test_dependency_model_coupling.py
import json
import re
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "dependency-model"
SKILLS = sorted((PLUGIN / "skills").glob("*/SKILL.md"))
CATEGORIES = ["config", "network", "package", "platform", "security", "service"]
PLUGIN_ROOT_REF = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}(/[A-Za-z0-9_./-]+)")


def body(skill):
    return skill.read_text(encoding="utf-8")


class TestSkillSet(unittest.TestCase):
    def test_all_six_category_skills_exist(self):
        self.assertEqual([p.parent.name for p in SKILLS], CATEGORIES)


class TestNoCrossPluginPathCoupling(unittest.TestCase):
    def test_no_skill_reaches_into_profile_by_path(self):
        for skill in SKILLS:
            with self.subTest(skill=skill.parent.name):
                text = body(skill)
                self.assertNotIn("profile/scripts", text)
                self.assertNotIn("profile_inventory.py", text)

    def test_every_skill_names_profile_topology_as_a_skill(self):
        for skill in SKILLS:
            with self.subTest(skill=skill.parent.name):
                self.assertIn("profile:topology", body(skill))

    def test_plugin_root_refs_stay_inside_this_plugin(self):
        for skill in SKILLS:
            for ref in PLUGIN_ROOT_REF.findall(body(skill)):
                with self.subTest(skill=skill.parent.name, ref=ref):
                    # Without this, ../profile/... resolves and passes exists().
                    self.assertNotIn("..", ref)
                    self.assertTrue((PLUGIN / ref.lstrip("/")).exists())

    def test_profile_skills_are_not_modified_to_know_about_this_plugin(self):
        """#48 AC 4: the dependency direction is one-way."""
        for skill in sorted((REPO / "profile" / "skills").glob("*/SKILL.md")):
            with self.subTest(skill=skill.parent.name):
                self.assertNotIn("dependency-model", body(skill))


class TestEachSkillOwnsItsCategory(unittest.TestCase):
    def test_each_skill_names_its_own_contract_and_example(self):
        for skill in SKILLS:
            category = skill.parent.name
            with self.subTest(skill=category):
                text = body(skill)
                self.assertIn(f"contracts/{category}.schema.json", text)
                self.assertIn(f"examples/{category}.example.json", text)

    def test_each_skill_names_the_shared_envelope(self):
        for skill in SKILLS:
            with self.subTest(skill=skill.parent.name):
                self.assertIn("discovery.schema.json", body(skill))


class TestDisciplineIsStatedInEverySkill(unittest.TestCase):
    def test_every_skill_states_it_is_read_only(self):
        for skill in SKILLS:
            with self.subTest(skill=skill.parent.name):
                self.assertIn("read-only", body(skill).lower())

    def test_every_skill_states_null_is_not_confirmed_absent(self):
        """D1: layer 3 reads a null as a candidate gap. Layer 1 must not have
        decided it is a real one."""
        for skill in SKILLS:
            with self.subTest(skill=skill.parent.name):
                text = body(skill).lower()
                self.assertIn("no declaration was found", text)
                self.assertIn("confirmed absent", text)

    def test_every_skill_distinguishes_an_empty_list_from_a_failed_scan(self):
        for skill in SKILLS:
            with self.subTest(skill=skill.parent.name):
                text = body(skill).lower()
                self.assertIn("failed", text)
                self.assertIn("legitimate finding", text)

    def test_no_skill_promises_criticality_or_remediation(self):
        banned = ("criticality", "blast radius", "remediation",
                  "monitoring gap", "chaos test")
        for skill in SKILLS:
            text = body(skill).lower()
            for word in banned:
                with self.subTest(skill=skill.parent.name, word=word):
                    # Allowed only in a sentence that disclaims it.
                    if word in text:
                        line = next(ln for ln in text.splitlines() if word in ln)
                        self.assertTrue(
                            any(marker in line
                                for marker in ("no ", "not ", "never", "do not")),
                            f"{skill.parent.name} promises {word!r}: {line}")


class TestSecuritySkillCarriesTheCredentialRule(unittest.TestCase):
    def test_security_skill_forbids_reading_values_and_keys_dir(self):
        text = body(PLUGIN / "skills" / "security" / "SKILL.md")
        self.assertIn("~/.keys/", text)
        lower = text.lower()
        self.assertIn("never read a secret", lower)
        self.assertIn("stringdata", lower)


class TestPackageSkillHonoursSyftsLimits(unittest.TestCase):
    def test_package_skill_requires_the_exclusions(self):
        text = body(PLUGIN / "skills" / "package" / "SKILL.md")
        self.assertIn("--exclude", text)
        self.assertIn("270", text)

    def test_package_skill_documents_file_level_evidence(self):
        text = body(PLUGIN / "skills" / "package" / "SKILL.md").lower()
        self.assertIn("no line number", text)


class TestRegistration(unittest.TestCase):
    def test_plugin_manifest_is_semver_and_named_for_its_directory(self):
        data = json.loads(
            (PLUGIN / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(data["name"], "dependency-model")
        self.assertRegex(data["version"], r"^\d+\.\d+\.\d+$")

    def test_marketplace_entry_exists_in_the_development_category(self):
        data = json.loads(
            (REPO / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
        entry = next(p for p in data["plugins"] if p["name"] == "dependency-model")
        self.assertEqual(entry["source"], "./dependency-model")
        self.assertEqual(entry["category"], "development")

    def test_verify_script_declares_the_plugin_with_all_six_skills(self):
        text = (REPO / "scripts" / "verify-marketplace.sh").read_text(encoding="utf-8")
        self.assertIn(
            '"dependency-model:development:config,network,package,platform,security,service"',
            text)
        self.assertIn("dependency-model/scripts/depscan.py", text)

    def test_requirements_declare_syft_as_required(self):
        data = json.loads((PLUGIN / "requirements.json").read_text(encoding="utf-8"))
        self.assertEqual(data["plugin"], "dependency-model")
        syft = next(t for t in data["tools"] if t["name"] == "syft")
        self.assertTrue(syft["required"])
        self.assertIsInstance(syft["probe"], list)

    def test_readme_documents_the_plugin(self):
        text = (REPO / "README.md").read_text(encoding="utf-8")
        self.assertIn("### dependency-model", text)
        self.assertIn("Fifteen plugins", text)
        for category in CATEGORIES:
            with self.subTest(category=category):
                self.assertIn(f"**{category}**", text)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_dependency_model_coupling.py -q`
Expected: FAIL — `test_plugin_manifest_is_semver_and_named_for_its_directory` cannot read a missing `plugin.json`.

- [ ] **Step 3: Write the plugin manifest and requirements declaration**

`dependency-model/.claude-plugin/plugin.json`:

```json
{
  "name": "dependency-model",
  "version": "0.1.0",
  "description": "Dependency discovery toolkit: enumerate what a system depends on across six categories — packages (package), out-of-project services (service), configuration (config), secrets and permissions (security), OS and cloud resources (platform), and network paths (network) — each with the timeout, retry, fallback, and health-check declarations that bear on how it fails. Static and read-only; nothing is executed, resolved, or probed. Emits one versioned JSON contract for downstream consumers.",
  "author": { "name": "efitz" }
}
```

`dependency-model/requirements.json`:

```json
{
  "requirements_version": "1.0.0",
  "plugin": "dependency-model",
  "tools": [
    {
      "name": "syft",
      "required": true,
      "why": "package is the only category with no fallback: syft is the sole source of the package inventory and the dependency-of edges, across ~30 ecosystems",
      "probe": ["syft", "version"],
      "install": {
        "macos": "brew install syft",
        "docs": "https://github.com/anchore/syft#installation"
      }
    },
    {
      "name": "uv",
      "required": false,
      "why": "the five file-scanning skills run the bundled depscan.py via `uv run --script`; each skill documents a python3 fallback, and depscan.py declares no dependencies so the fallback works",
      "probe": ["uv", "--version"],
      "install": {
        "macos": "brew install uv",
        "docs": "https://docs.astral.sh/uv/getting-started/installation/"
      }
    },
    {
      "name": "git",
      "required": false,
      "why": "depscan.py prefers `git ls-files` so .gitignore is honoured; it falls back to a filesystem walk when git is unavailable or the target is not a repo",
      "probe": ["git", "--version"],
      "install": {
        "macos": "xcode-select --install",
        "docs": "https://git-scm.com/downloads"
      }
    }
  ]
}
```

- [ ] **Step 4: Add the marketplace entry**

In `.claude-plugin/marketplace.json`, append to the `plugins` array (after the `env` entry):

```json
{
  "name": "dependency-model",
  "description": "Dependency discovery toolkit: enumerate what a system depends on across six categories — packages, out-of-project services, configuration, secrets and permissions, OS and cloud resources, and network paths — each with the failure-relevant declarations (timeout, retry, fallback, health check) found for it. Static and read-only; emits a versioned JSON contract consumed by downstream analysis.",
  "source": "./dependency-model",
  "category": "development"
}
```

- [ ] **Step 5: Update `scripts/verify-marketplace.sh`**

Add to the `PLUGINS` array, after the `env` entry — skills in the order `ls dependency-model/skills/` gives, which is alphabetical:

```bash
  "dependency-model:development:config,network,package,platform,security,service"
```

Add to the `SCRIPTS` array:

```bash
  "dependency-model/scripts/depscan.py"
```

- [ ] **Step 6: Regenerate the Codex manifests**

```bash
uv run scripts/gen_codex_manifests.py
```

This writes `dependency-model/.codex-plugin/plugin.json` and updates `.agents/plugins/marketplace.json`. **Commit what it wrote; never hand-edit either file.**

- [ ] **Step 7: Update `README.md`**

Change the opening paragraph's plugin count from `Fourteen plugins` to `Fifteen plugins`.

Add a section after `### env`, before the trailing `---`:

```markdown
### dependency-model — dependency discovery

- **package** — Inventory the libraries the project ships with, across every ecosystem syft catalogues, with declared/locked/installed resolution and the dependency edges between them.
- **service** — Identify out-of-project services: databases, caches, queues, object stores, search engines, and APIs, with how each is brought up and what config points at it.
- **config** — Enumerate the configuration the system must be supplied with: environment variables, files, flags, and remote config, with what reads each key and what default it declares.
- **security** — Enumerate the secrets and permissions the system requires, recording what each credential is named and where it is read — never its value.
- **platform** — Enumerate the declared OS and cloud resources: CPU, memory, disk, GPU, architecture, runtime versions, and managed services.
- **network** — Enumerate the names, hosts, and ports that must resolve and connect, inbound and outbound, with how each name is expected to resolve.

Static and read-only: nothing is executed, resolved, or probed, because these
skills run on a developer's machine or in CI rather than inside the environment
the code runs in — a measured latency or a resolved hostname would be
confidently wrong. Each dependency carries the timeout, retry, fallback, and
health-check declarations found for it; a `null` means no declaration was found,
never that the behaviour is confirmed absent. All six emit the same
`discovery` envelope with one category populated, so their output merges by key
union. Requires `syft`; seeded by the `profile:topology` contract.
```

- [ ] **Step 8: Run the full checks**

```bash
uv run ruff check .
uv run pytest -q
uv run scripts/gen_codex_manifests.py --check
bash scripts/verify-marketplace.sh
```

Expected: ruff clean; pytest green; the generator reports no drift; `verify-marketplace.sh` reports `PASS 40 / FAIL 0` or higher with `FAIL: 0`, including a line for `dependency-model (category=development, skills: config,network,package,platform,security,service)`.

- [ ] **Step 9: Commit**

```bash
git add dependency-model/.claude-plugin dependency-model/.codex-plugin dependency-model/requirements.json .claude-plugin/marketplace.json .agents/plugins/marketplace.json scripts/verify-marketplace.sh README.md tests/test_dependency_model_coupling.py
git commit -m "feat(dependency-model): register the plugin v0.1.0 and pin its coupling (#48)"
```

---

### Task 11: Architecture documentation and close-out

The last derived artifact. `docs/ARCHITECTURE.md` currently carries a placeholder `planned — issue 46` subgraph; layer 1 replaces it with the real one. The Mermaid graph is re-rendered, not eyeballed — that is the rule the previous session established after landing it.

**Files:**
- Modify: `docs/ARCHITECTURE.md` (Mermaid graph, skill catalog, `env:check` note)

**Interfaces:**
- Consumes: nothing. This is documentation of what Tasks 1–10 built.

- [ ] **Step 1: Replace the placeholder subgraph**

In the Mermaid block in `docs/ARCHITECTURE.md`, replace:

```
  subgraph planned["planned — issue 46"]
    x_disc["dependency discovery"]
  end
```

with:

```
  subgraph depmodel["dependency-model — dependency discovery"]
    x_pkg["package"]
    x_svc["service"]
    x_cfg["config"]
    x_sec["security"]
    x_plat["platform"]
    x_net["network"]
  end
```

- [ ] **Step 2: Replace the placeholder edge**

Replace the single line:

```
  p_topo -- "topology" --> x_disc
```

with the six seeding edges and the two cross-category links:

```
  p_topo -- "topology" --> x_pkg
  p_topo -- "topology" --> x_svc
  p_topo -- "topology" --> x_cfg
  p_topo -- "topology" --> x_sec
  p_topo -- "topology" --> x_plat
  p_topo -- "topology" --> x_net

  x_svc -. "related_ids" .-> x_net
  x_cfg -. "related_ids" .-> x_svc
```

And add to the `env:check` block:

```
  envchk -. "requirements.json" .-> depmodel
```

- [ ] **Step 3: Re-render the graph rather than eyeballing it**

```bash
python3 - <<'PY' > /tmp/arch.mmd
import re, pathlib
text = pathlib.Path("docs/ARCHITECTURE.md").read_text(encoding="utf-8")
print(re.search(r"```mermaid\n(.*?)```", text, re.S).group(1), end="")
PY
npx -y -p @mermaid-js/mermaid-cli mmdc -i /tmp/arch.mmd -o /tmp/arch.svg
```

Expected: `mmdc` exits 0 and writes `/tmp/arch.svg`. A syntax error here is a broken graph on `main` — fix the Mermaid, do not skip the render.

- [ ] **Step 4: Add the skill catalog section**

After the `### cats` table in `## Skill catalog`, add:

```markdown
### dependency-model

| Skill | Value produced | Outputs | Consumes |
|---|---|---|---|
| `package` | The libraries the system ships with, with declared/locked/installed resolution and the dependency edges between them | `discovery` contract, `package` category | `topology`; `syft` |
| `service` | Out-of-project services — databases, caches, queues, object stores, search, APIs — with how each is brought up and how it is declared to fail | `discovery` contract, `service` category | `topology`, `depscan.py` index |
| `config` | The configuration the system must be supplied with, with what reads each key and what it declares as required or defaulted | `discovery` contract, `config` category | `topology`, `depscan.py` index |
| `security` | The credential and permission surface — what each secret is named and where it is read, never its value | `discovery` contract, `security` category | `topology`, `depscan.py` index |
| `platform` | Declared OS and cloud resources — CPU, memory, disk, GPU, architecture, runtime versions, managed services | `discovery` contract, `platform` category | `topology`, `depscan.py` index |
| `network` | The names, hosts, and ports that must resolve and connect, inbound and outbound | `discovery` contract, `network` category | `topology`, `depscan.py` index |

All six emit the same `discovery` envelope with exactly one key under `categories`
populated, so merging them is a key union rather than a transform. There is no
orchestrator in this layer by decision: the report skill in #49 must gather all six
contracts to render anything, so it becomes the orchestrator, and building one here
would mean building it twice.
```

- [ ] **Step 5: Update the prose around the graph**

In the paragraph following the Mermaid block, add `dependency-model` to the list of plugins `env:check` is drawn against. In `### Reading the core chain`, add a sentence: `profile:topology` is the seed for all six `dependency-model` discovery skills — the same refinement-tier relationship `stack` has to `topology`, and the same one-way direction `itest` has to `profile`.

- [ ] **Step 6: Run every check, one final time**

```bash
uv run ruff check .
uv run pytest -q
uv run scripts/gen_codex_manifests.py --check
bash scripts/verify-marketplace.sh
```

Expected: all four clean. Read the output; do not infer it from the edits.

- [ ] **Step 7: Prove the plugin works end to end on a real repository**

```bash
uv run --script dependency-model/scripts/depscan.py . > /tmp/depscan.json
python3 -c "
import json
d = json.load(open('/tmp/depscan.json'))
print('method   ', d['listing_method'])
print('coverage ', d['coverage'])
print('files    ', {k: len(v) for k, v in d['files'].items()})
print('findings ', {k: len(v) for k, v in d['findings'].items()})
"
syft scan dir:. -o syft-json --quiet $(python3 -c "
import json
print(' '.join(f\"--exclude './{e}'\" for e in json.load(open('/tmp/depscan.json'))['exclusions']))
") | python3 -c "import json,sys; d=json.load(sys.stdin); print('syft artifacts', len(d['artifacts']))"
```

Expected: the scan reports `git` listing and high or partial confidence with every findings key present, and syft with the exclusions applied reports far fewer artifacts than the 270 an unscoped scan gives for this repository.

- [ ] **Step 8: Delete the handoff file and commit**

`HANDOFF.md` is working state, not documentation. Its own header says to delete it once #48's plan is written; by this point the plan is not only written but executed.

```bash
git rm HANDOFF.md
git add docs/ARCHITECTURE.md
git commit -m "docs(architecture): map dependency-model into the plugin graph and catalog (#48)"
```

- [ ] **Step 9: Push and close the issue**

```bash
git push origin main
gh issue close 48 --comment "Layer 1 landed: six discovery skills, the shared discovery contract with a referenced dependency core, and depscan.py. Spec: docs/superpowers/specs/2026-08-22-dependency-model-discovery-design.md. Plan: docs/superpowers/plans/2026-08-22-dependency-model-discovery.md."
```

Leave #46, #49, #50, and #51 open — each later layer gets its own brainstorm → spec → plan → implement cycle.

---

## Notes for the executor

**What this layer deliberately does not build**, so you do not add it back:

- An orchestrator (D8) — #49's report skill becomes one.
- Vulnerability data — `grype` and `trivy` are adjacent but #46 does not scope CVEs.
- Criticality, blast radius, or monitoring-gap judgment (D1) — layer 3.
- Any live probing: name resolution, reachability, measurement (D3) — never, at any layer.
- `graphify`/`sem` reachability for journey exposure — folded into layer 2's design.

**If a task's tests will not go green**, the failure is information about the design, not only about the code. Two cases the spec anticipates:

- The `host_port_literals` regex fighting image tags and clock times is a known tension. `MIN_PORT = 80` is the chosen resolution. Add targeted exclusions rather than widening the range.
- `resilience_calls` is deliberately over-inclusive: the scanner finds every timeout literal once and each skill correlates the ones belonging to its own dependencies. A finding the scanner surfaces that no skill claims is expected, not a bug.
