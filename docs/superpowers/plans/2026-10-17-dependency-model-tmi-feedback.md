# dependency-model tmi-feedback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix issues #92–#95: shared id list and stricter slug rule, component → service edges feeding `required_for`, a collapsed Mermaid view over the cap, and a `--out` report path.

**Architecture:** A new `depgraphlib/ids.py` owns the slug rule and id assignment; a new `idmap.py` CLI writes `<run_dir>/ids.json` from the topology contract; `depgraph.py`'s resolver gains re-slug and name fallbacks and reads `details.used_by`; `health.py` fills `required_for`; `mermaid.py` gains a collapsed view. Skill and reference markdown carry the new rules.

**Tech Stack:** Python 3.11 stdlib only (scripts run via `uv run --script` or `python3`), `unittest`-style tests run by pytest, the repo's stdlib JSON-schema validator.

**Spec:** `docs/superpowers/specs/2026-10-17-dependency-model-tmi-feedback-design.md` (read it; it is authoritative where this plan is terse).

## Global Constraints

- Scripts stay stdlib-only and runnable as `uv run --script X.py` and `python3 X.py`.
- No plugin or contract version bumps (`plugin.json` stays `0.1.0`; schema `contract_version`s unchanged).
- Never invent a node to satisfy a link; never drop a link silently: unmatched links stay in `unresolved`.
- Tests: flat `tests/`, `unittest.TestCase` classes, `sys.path.insert` of `dependency-model/scripts` like `tests/test_depgraph_graph.py`.
- Done gate (run before claiming any task done): `uv run ruff check .`, `uv run pytest -q`, `uv run scripts/gen_codex_manifests.py --check`, `bash scripts/verify-marketplace.sh` — all pass.
- American English; conventional-commit messages ending with the session's attribution lines.

## Review Focus

1. A name that slugs to empty (all punctuation, all non-ASCII, `"()"`): `idmap.py` must exit 2 naming it, never a traceback. → Task 2 test `test_unsluggable_name_exits_2`.
2. Topology with `components`/`real_dependencies`/`external_third_parties` missing or `null`: treated as empty lists. → Task 2 test `test_missing_lists_are_empty`.
3. The same component named twice in one service's `used_by`, or two services' `used_by` naming one component: edges deduplicated, `required_for` sorted and unique. → Task 4 test `test_used_by_duplicates_collapse`.
4. An over-cap graph with no component or service nodes at all (only packages): collapsed view is rollup nodes only, not a crash. → Task 5 test `test_collapsed_with_only_rollups`.
5. A link whose re-slug matches a node in another category (`config:nats` vs `service:nats`) must not resolve across categories. → Task 3 test `test_fallbacks_never_cross_categories`.

---

### Task 1: Slug rule and id assignment in `depgraphlib/ids.py`

**Files:**
- Create: `dependency-model/scripts/depgraphlib/ids.py`
- Modify: `dependency-model/scripts/depgraphlib/graph.py` (remove `slug`, import from `ids`; `component_nodes` uses `assign_ids`)
- Modify: `dependency-model/scripts/depgraph.py` (component ids via `assign_ids`)
- Modify: `dependency-model/references/categories.md` (Ids section: new rule, spec §1 examples, drop `network:api-openai-com-443`)
- Test: `tests/test_depgraph_ids.py`; update `tests/test_depgraph_graph.py` slug imports/expectations

**Interfaces:**
- Produces: `slug(name: str) -> str` (raises `ValueError` naming the input when the result is empty after the fallback); `slug_keep_groups(name: str) -> str` (rule without step 2); `assign_ids(names: list[str], prefix: str) -> dict[str, str]` mapping each distinct name to `f"{prefix}:{id}"`, applying the spec's collision fallback, raising `IdCollisionError(ValueError)` naming both names when the fallback still collides. `graph.py` re-exports `slug` so existing imports keep working.

- [ ] **Step 1: Write failing tests** in `tests/test_depgraph_ids.py`:
  - `test_spec_examples`: `slug("nats (JetStream)") == "nats"`; `slug("OAuth 2.0 / OIDC identity providers (env-discovered; Google, GitHub, Microsoft etc.)") == "oauth-2.0-oidc-identity-providers"`; `slug("migrate / dbtool / genconfig") == "migrate-dbtool-genconfig"`; `slug("TMI_NATS_URL") == "tmi-nats-url"`; `slug("metadata 169.254.169.254") == "metadata-169.254.169.254"`.
  - `test_all_parenthesized_falls_back`: `slug("(JetStream)") == "jetstream"`.
  - `test_empty_raises`: `slug("()")`, `slug("!!")`, `slug("")` raise `ValueError` whose message contains the input repr.
  - `test_unbalanced_parens_are_punctuation`: `slug("a (b") == "a-b"`, `slug("a) b") == "a-b"`.
  - `test_nested_groups_removed`: `slug("x (a (b) c) y") == "x-y"`.
  - `test_assign_ids_collision_fallback`: `assign_ids(["redis (cache)", "redis (queue)"], "service") == {"redis (cache)": "service:redis-cache", "redis (queue)": "service:redis-queue"}`; a non-colliding third name keeps its stripped slug.
  - `test_assign_ids_unresolvable_collision`: `assign_ids(["a b", "a-b"], "service")` raises `IdCollisionError` mentioning both names.
  - In `tests/test_depgraph_graph.py`, the existing slug test keeps passing (`"tooling CLIs" → "tooling-clis"`, `"TMI_NATS/url.v2" → "tmi-nats-url.v2"`), and add `test_component_ids_use_assign_ids`: topology components `["migrate / dbtool"]` → `component:migrate-dbtool`.
- [ ] **Step 2: Run** `uv run pytest -q tests/test_depgraph_ids.py tests/test_depgraph_graph.py` — Expected: FAIL (no module `depgraphlib.ids`).
- [ ] **Step 3: Implement** `ids.py`. Group removal: repeat `re.sub(r"\([^()]*\)", " ", s)` until no change (handles nesting, leaves unbalanced parens). Then `re.sub(r"[^a-z0-9.]+", "-", s).strip("-")`. Wire `graph.component_nodes` and `depgraph.py` to `assign_ids([c["name"] ...], "component")`.
- [ ] **Step 4: Update** categories.md Ids section per spec §1 (rule, examples, edge cases in one line).
- [ ] **Step 5: Run** the done gate. Expected: all pass.
- [ ] **Step 6: Commit** `feat(dependency-model): stricter slug rule and shared id assignment (#92)`.

### Task 2: `idmap.py` writes the shared id list

**Files:**
- Create: `dependency-model/scripts/idmap.py` (uv script header like `depgraph.py`)
- Test: `tests/test_idmap_cli.py`; fixture `tests/fixtures/dependency_model/topology_tmi.json` (a trimmed copy of the tmi topology: all 8 `components`, all `real_dependencies` and `external_third_parties` with `name` plus one evidence string each; other keys dropped)

**Interfaces:**
- Consumes: `assign_ids`, `IdCollisionError`, `slug` from Task 1.
- Produces: CLI `idmap.py TOPOLOGY.json [--write]`. Output document `{"components": [{"id","name"}], "services": [{"id","name","source"}], "skipped": [{"name","reason"}]}`, lists sorted by `id` (`skipped` by `name`), JSON `indent=2, sort_keys=True`, trailing newline. `--write` writes `ids.json` beside the topology file via temp file + `os.replace` and prints the absolute path; without it, prints the document. Exit 2 with `{"error": ...}` on stderr and nothing written for: unreadable/invalid JSON, non-object top level, an entry without a string `name`, an unsluggable name, an unresolvable collision.

- [ ] **Step 1: Write failing tests** (run the script with `subprocess` and `sys.executable` like `tests/test_depmodel_validate.py`):
  - `test_tmi_topology`: services include `{"id": "service:nats", "name": "nats (JetStream)", "source": "real_dependencies"}` and `{"id": "service:oauth-2.0-oidc-identity-providers", ..., "source": "external_third_parties"}`; components include `component:tmi-server` and `component:migrate-dbtool-genconfig-worker-probe-dedup-group-members`.
  - `test_name_in_both_lists_appears_once_as_real_dependency`.
  - `test_service_matching_a_component_is_skipped`: a real dependency named `tmi-server` with a component `tmi-server` → not in `services`, in `skipped` with a reason containing `component:tmi-server`; exit 0.
  - `test_collision_fallback` and `test_unresolvable_collision_exits_2_and_writes_nothing` (temp dir, assert no `ids.json`).
  - `test_unsluggable_name_exits_2` (name `"()"`), `test_entry_without_name_exits_2`, `test_invalid_json_exits_2`, `test_non_object_exits_2`.
  - `test_missing_lists_are_empty`: `{}` → `{"components": [], "services": [], "skipped": []}`.
  - `test_write_is_deterministic`: two `--write` runs give identical bytes; stdout is the path; no stray temp files left in the dir.
- [ ] **Step 2: Run** `uv run pytest -q tests/test_idmap_cli.py` — Expected: FAIL (script missing).
- [ ] **Step 3: Implement** `idmap.py`. Service names: real_dependencies first, then external_third_parties not already seen (by exact name); assign ids over the combined service names in one `assign_ids` call; skip a service whose id part equals a component id part.
- [ ] **Step 4: Run** the done gate. Expected: all pass.
- [ ] **Step 5: Commit** `feat(dependency-model): idmap.py writes the shared id list (#92)`.

### Task 3: Resolver fallbacks and tmi regression

**Files:**
- Modify: `dependency-model/scripts/depgraphlib/graph.py` (`_resolver(nodes)` takes node dicts with `id`, `name`, `category`; `_build_edges` passes them)
- Test: `tests/test_depgraph_graph.py`; fixture `tests/fixtures/dependency_model/tmi_links.json`

**Interfaces:**
- Consumes: `slug` from Task 1.
- Produces: resolution order exact → canonical → `service:`→`component:` → re-slug → name match, each later step only within the target's category (prefix before the first `:`), each requiring exactly one candidate. Public `link_graph`/`build_graph` signatures unchanged. A target whose id part cannot be slugged (Task 1 `ValueError`) is simply unresolved.

- [ ] **Step 1: Build the fixture** `tmi_links.json` = `{"nodes": [{"id","name","category"}...], "links": [{"from","to","kind"}...]}` from `~/Downloads/tmi-dependency-model-2026-10-17/`: nodes = every `service:`, `network:` and `config:` node plus the 8 components from a `depgraph.py ... --topology` run over `work/synthesize/*.orig.json`; links = that run's 48 `unresolved` entries, with the security-sourced ones (`service:openai`, `service:google-oauth` etc.) present (they are already in the `*.orig.json` unresolved list; cross-check with `work/security/gen.py`). Only node ids/names that appear as a link endpoint or as a resolution candidate are needed; trim the rest. Commit the script you used only if it is under `tests/`; otherwise do not commit it.
- [ ] **Step 2: Write failing tests**:
  - `test_reslug_match`: link to `service:nats-(jetstream)` resolves to node `service:nats`.
  - `test_name_match`: link to `service:google-drive-google-workspace-apis` resolves to node `service:gdrive` named `Google Drive / Google Workspace APIs`.
  - `test_ambiguous_fallback_stays_unresolved`: two service nodes both re-slugging to the target → unresolved.
  - `test_fallbacks_never_cross_categories`: link `service:nats-(jetstream)` with only `config:nats` present → unresolved.
  - `test_tmi_regression`: build a merged inventory from the fixture (one dependency per node, links as `related_ids`/`depends_on` per `kind`, components via `link_graph`'s components arg); assert exactly 26 resolve and the sorted list of 22 unresolved `to` targets equals a literal list in the test (google-drive ×9, the webhook-receivers split ×1, `service:openai` ×3, google/github/microsoft-oauth ×3, `network:localhost-6379` ×2, `network:localhost-8080` ×1, and the 3 no-node links). If your count differs, stop and report it with the differing links rather than adjusting the rule.
- [ ] **Step 3: Run** `uv run pytest -q tests/test_depgraph_graph.py` — Expected: the new tests FAIL.
- [ ] **Step 4: Implement** the two fallbacks in `_resolver`.
- [ ] **Step 5: Run** the done gate. Expected: all pass.
- [ ] **Step 6: Commit** `feat(dependency-model): resolve links by re-slug and node name (#92)`.

### Task 4: `used_by` edges and `required_for` (#93)

**Files:**
- Modify: `dependency-model/scripts/validate.py` (support `minItems` on arrays)
- Modify: `dependency-model/references/contracts/service.schema.json` (`details.used_by`)
- Modify: `dependency-model/references/contracts/examples/service.example.json` and `examples/synthesis.example.json` (one `used_by` entry and the matching `required_for`, keeping both valid)
- Modify: `dependency-model/scripts/depgraphlib/graph.py` (`_build_edges`), `dependency-model/scripts/depgraphlib/health.py` (`required_for`, docstring)
- Modify: `dependency-model/skills/service/SKILL.md` (ask for `used_by`), `dependency-model/skills/synthesize/SKILL.md` step 4 wording per spec §4
- Test: `tests/test_depmodel_validate.py`, `tests/test_depgraph_graph.py`, `tests/test_depgraph_health.py`

**Interfaces:**
- Produces: schema `used_by: {"type": "array", "items": {"type": "object", "required": ["component_id", "evidence"], "additionalProperties": false, "properties": {"component_id": {"type": "string"}, "evidence": {"type": "array", "minItems": 1, "items": {"type": "string"}}}}}`. Graph edge `{"from": <component id>, "to": <service id>, "kind": "depends_on", "lifecycle": "run"}`; unresolved entry `{"from": <service id>, "to": <component_id as written>, "kind": "used_by"}`. Health: service-anchor conditions get `required_for` = sorted unique component ids with a `depends_on` edge to that service; component-anchor conditions get `[component id]`.

- [ ] **Step 1: Write failing tests**:
  - validate: `test_min_items_rejects_empty_evidence` (service example with `used_by: [{"component_id": "component:api", "evidence": []}]` → exit non-zero, message mentions `minItems` or "at least 1"); `test_used_by_extra_property_rejected`; examples still validate.
  - graph: `test_used_by_becomes_component_edge`; `test_used_by_unknown_component_is_unresolved` (kind `used_by`); `test_used_by_duplicates_collapse` (same component twice in one `used_by`, and two services naming it → one edge per pair).
  - health: `test_required_for_from_used_by` (service:pg used_by component:api and component:worker → every pg condition has `required_for == ["component:api", "component:worker"]`); `test_component_conditions_required_for_itself`; `test_component_gets_upstream_health_on_used_service`; `test_no_used_by_leaves_required_for_empty`.
- [ ] **Step 2: Run** the three test files — Expected: new tests FAIL.
- [ ] **Step 3: Implement** `minItems` in `validate()` (arrays only, message `"{path}: expected at least N items"`), the schema property, the edges, and `required_for` (computed in `derive_health` from `graph.edges` after conditions are built).
- [ ] **Step 4: Update** the service and synthesize SKILL.md text and both examples.
- [ ] **Step 5: Run** the done gate. Expected: all pass.
- [ ] **Step 6: Commit** `feat(dependency-model): component to service edges fill required_for (#93)`.

### Task 5: Collapsed Mermaid view (#94)

**Files:**
- Modify: `dependency-model/scripts/depgraphlib/mermaid.py`
- Modify: `dependency-model/skills/report/SKILL.md` step 3
- Test: `tests/test_depgraph_mermaid.py`

**Interfaces:**
- Produces: `to_mermaid(graph, cap=CAP_DEFAULT)` returns `{"mermaid", "degraded", "node_count", "reason", "view", "collapsed"}`: under cap `view: "full"`, `collapsed: {}`; over cap with ≤ cap collapsed nodes `view: "collapsed"`, `collapsed: {category: count}` (only rolled-up categories), `degraded: false`, `node_count` = full count, `reason` a sentence naming both counts; still over cap `mermaid: null`, `degraded: true`, `view: null`, `collapsed: {}`. Rollup label `"<category> (<count>)"`; rollup nodes sort after kept nodes by category name.

- [ ] **Step 1: Write failing tests**: `test_full_view_flag`; `test_collapsed_keeps_components_and_services` (61 packages + 1 component + 2 services, edges package→service and package→package; assert one `package (61)` node, the package→service edge appears once, no self-loop, `collapsed == {"package": 61}`); `test_collapsed_with_only_rollups` (70 packages only → one rollup node, `view == "collapsed"`); `test_still_over_cap_degrades` (cap=3 with 4 services); existing tests updated only for the new keys.
- [ ] **Step 2: Run** `uv run pytest -q tests/test_depgraph_mermaid.py` — Expected: new tests FAIL.
- [ ] **Step 3: Implement**; reuse the existing label escaping and shapes.
- [ ] **Step 4: Update** report SKILL.md step 3 per spec §5 (collapsed: emit the fence plus a note naming rolled-up categories, counts, and that the full graph is in the contract; degraded: unchanged).
- [ ] **Step 5: Verify** one collapsed output renders: write it to the scratchpad and run `npx -y -p @mermaid-js/mermaid-cli mmdc -i <file>.mmd -o <file>.svg`; if `npx` is unavailable, say so in the report.
- [ ] **Step 6: Run** the done gate. Expected: all pass.
- [ ] **Step 7: Commit** `feat(dependency-model): collapsed diagram over the node cap (#94)`.

### Task 6: Report `--out`, sequence and skill-rule docs (#95, #92 docs)

**Files:**
- Modify: `dependency-model/skills/report/SKILL.md` (usage line, `--out` rules per spec §6, frontmatter description), `docs/ARCHITECTURE.md` (report row; `ids.json` and `idmap.py` where run-dir artifacts and synthesize inputs are listed)
- Modify: `dependency-model/references/running-discovery.md` (reordered sequence and commands per spec §2), `dependency-model/skills/synthesize/SKILL.md` (standalone invocation gains `idmap.py --write` after saving `topology.json`)
- Modify: the six discovery `SKILL.md` files (one pointer line: read `<run_dir>/ids.json` when it exists and use its ids; categories.md Ids has the rule); `references/categories.md` Ids gains the shared-list rule from spec §2 (service skill never shortens; link to listed ids; finer parts link to the listed id)
- Modify: `README.md` only if it names the report path or the discovery sequence
- Test: `tests/test_dependency_model_coupling.py`, `tests/test_dependency_model_references.py`

- [ ] **Step 1: Write failing tests**: `test_every_discovery_skill_points_at_ids_json` (the six SKILL.md contain `ids.json`); `test_synthesize_runs_idmap`; `test_running_discovery_order` (in running-discovery.md, `depscan.py` appears before `profile:topology` before `idmap.py`); `test_report_documents_out` (`--out` present, plus the `.md` and parent-directory rejection rule); `test_categories_ids_rule` (categories.md mentions `ids.json` and the parenthesized-group rule).
- [ ] **Step 2: Run** the two test files — Expected: new tests FAIL.
- [ ] **Step 3: Edit** the markdown per the spec sections named above.
- [ ] **Step 4: Run** the done gate. Expected: all pass.
- [ ] **Step 5: Commit** `docs(dependency-model): shared id list sequence and report --out (#92, #95)`.
