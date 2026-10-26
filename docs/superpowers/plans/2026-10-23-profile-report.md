# Profile HTML Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. SDD is already required by the user; do not ask for an execution-method choice.

**Goal:** Render saved profile artifacts as a complete, readable, offline HTML report with in-page evidence, useful visuals, explicit output placement and default browser opening through the skill.

**Architecture:** A stdlib input module validates the four saved contracts and optional explicit support files. A pure renderer creates self-contained HTML. A small CLI controls atomic writing and optional browser opening; the skill orchestrates only these operations.

**Tech Stack:** Python 3.11+ standard library, native HTML details, inline CSS/SVG and optional inline JavaScript, existing pytest/ruff tooling.

**Spec:** `docs/superpowers/specs/2026-10-23-profile-report-design.md`

## Global Constraints

- No plugin or contract version bump is authorized.
- Require `stack.json`, `docs.json`, `journeys.json`, and `topology.json` from the supplied directory.
- Support contract version `1.0.0`; reject unsupported versions.
- No target execution, repository scan, environment or secret inspection, network access, server, runtime CDN, or additional runtime dependency.
- All private examples remain outside the repository; tests use public examples and synthetic data.
- Default output is `<artifact_dir>/profile-report.html`; explicit `--out` takes precedence.
- The script opens only with `--open`; the skill passes `--open` unless the caller requests `--no-open`.
- Invalid inputs and write failures exit 2; opener failure after successful generation remains exit 0 with a warning.
- No commits in these tasks; root controls review, integration, gates and handoff.

## Review Focus

- A support file or record contains closing script tags or unsafe URLs: all content stays inert and evidence remains readable (Task 2).
- Optional fields are missing versus recorded empty lists: different meanings survive rendering (Tasks 1–2).
- Duplicate/dangling IDs and cyclic journey dependencies: unique HTML IDs, explicit gaps, complete tables, no crash (Tasks 1–2).
- Output points to an input via a symlink or has a failed replacement: input and previous report survive (Task 3).
- Browser opening is unsupported or blocked after writing: report path remains successful and opening failure is reported accurately (Task 3).

---

## File ownership and shared interface

Run tasks sequentially, assigning each to one implementation owner. Each owner must preserve others' edits. Root owns the spec/plan, HANDOFF and global validation artifacts. Do not modify existing `inventorylib/report.py` or `tests/test_profile_report.py` for this feature.

Task 1 owns `profile/scripts/reportlib/__init__.py`, `profile/scripts/reportlib/inputs.py`, and `tests/test_profile_html_inputs.py`.
Task 2 owns `profile/scripts/reportlib/render.py`, `profile/scripts/reportlib/assets.py`, and `tests/test_profile_html_report.py`.
Task 3 owns `profile/scripts/profile_report.py`, `profile/skills/report/SKILL.md`, `tests/test_profile_html_cli.py`, marketplace registration/docs and generated manifests.

The shared types live in `reportlib.inputs`:

- `ReportInputError(ValueError)` for input validation errors.
- `Artifact` dataclass: `name: str`, `path: Path`, `sha256: str`, `media_type: str`, `text: str`, `data: object | None`.
- `ProfileBundle` dataclass: `contracts: dict[str, Artifact]`, `support: list[Artifact]`, `diagnostics: list[str]`.
- `load_profile(artifact_dir: Path, support_paths: list[Path] | None = None) -> ProfileBundle`.

Contract dictionary keys are `stack`, `docs`, `journeys`, `topology`; each corresponding `data` is the validated object. Artifact text remains the original decoded content; hashes cover input bytes. Paths are resolved for collision checks, not followed as source references. Diagnostics include duplicate identifiers and unresolved cross references; contract/schema failure raises an error.

Task 2 exports `render_report(bundle: ProfileBundle, title: str | None = None) -> str`, a pure function with no filesystem access. Task 3 exports `main(argv: list[str] | None = None) -> int` and `write_report(output: Path, html: str, input_paths: list[Path]) -> None`; use the standard `webbrowser.open` dependency so tests can replace it. Caller-provided title is escaped, never interpreted as HTML.

### Task 1: Load and validate saved inputs

**Files:** Create the Task 1 files above. Read existing `profile/references/contracts/*.schema.json` and `examples/*.example.json`; do not alter their versions or source contracts.

**Interfaces:** Produces `ReportInputError`, `Artifact`, `ProfileBundle`, and `load_profile` exactly as defined above. No renderer or CLI import is allowed here.

- [ ] **Step 1: Write failing fixture-based input tests.** Build a temporary directory from the four public examples inside this test module; do not create a shared fixture API. `test_loads_four_contracts_and_support` asserts the four dictionary keys, original byte SHA-256, parsed JSON support, and exact text support. `test_missing_invalid_or_unsupported_contract_fails` parametrizes missing file, malformed JSON, missing required field, wrong nested type, invalid enum and `contract_version: "9.0.0"`, asserting `ReportInputError` with filename and field context. `test_optional_fields_preserve_absence_and_empty` asserts absent keys remain absent and empty lists remain empty. `test_cross_reference_diagnostics` asserts duplicate corpus/journey IDs and unknown corpus/dependency IDs are recorded without losing records. `test_explicit_support_only` asserts unrelated adjacent files and paths named inside evidence are never read; unsupported support format and malformed support JSON fail.
- [ ] **Step 2: Observe red.** Run `uv run pytest -q tests/test_profile_html_inputs.py`, capturing stdout/stderr and exit status in a task artifact. Confirm missing module/API failures before implementation.
- [ ] **Step 3: Implement the input API.** Read only the four required files and explicitly supplied support paths. Validate the subset used by bundled schemas (object/array/string/integer/number/boolean/null, required, properties, items, enum); reject bool as integer/number. Keep permitted unknown fields. Use UTF-8 and hash original bytes. Accept support `.json`, `.txt`, `.md` only. Do not import the sibling dependency-model validator at runtime. No support envelope or new support schema is required because support files have no new imposed data structure.
- [ ] **Step 4: Verify green and syntax.** Run `uv run pytest -q tests/test_profile_html_inputs.py`, `uv run ruff check profile/scripts/reportlib tests/test_profile_html_inputs.py`, and `uv run python -m compileall -q profile/scripts/reportlib`. Capture commands, statuses and summaries. Root reviews this independently before Task 2 begins.

### Task 2: Render the human summary and in-page evidence

**Files:** Create the Task 2 files above. Read Task 1 API only; ask root before changing Task 1 ownership files.

**Interfaces:** Consumes `ProfileBundle`; produces `render_report(bundle: ProfileBundle, title: str | None = None) -> str`. Own assets are static strings. The renderer performs no reads, subprocess calls or browser operations.

- [ ] **Step 1: Write failing report tests.** `test_full_profile_summary_and_evidence` asserts section headings and all sentinel records from synthetic full contracts appear, each displayed record has a provenance route, all HTML IDs are unique and fragment targets resolve. `test_missing_empty_and_confidence_fidelity` asserts distinct missing/empty labels, confidence values, unconfirmed candidates, documentary requirements and declared topology labels. `test_gaps_and_unsupported_proof` asserts all unknowns, deferred/unavailable sources, questions and assumptions remain accessible and validation support does not confer runtime-proof status. `test_hostile_strings_are_inert` uses title, evidence, raw JSON and support containing `</script>`, HTML handlers, quotes and unsafe schemes; parse HTML and assert no injected elements/attributes or external asset loads. `test_journey_edges_and_topology_groups` asserts exact declared dependency edges, complete cyclic/dangling edge tables, no invented topology relationships, and more than 24 nodes yields table fallback. `test_optional_artifacts_and_determinism` asserts supplied text remains exact after HTML decoding, no fabricated excerpts, same input yields identical HTML, and unknown fields remain inspectable.
- [ ] **Step 2: Observe red.** Run `uv run pytest -q tests/test_profile_html_report.py`, capture results and confirm missing renderer failures.
- [ ] **Step 3: Implement the renderer and assets.** Implement the seven sections and coverage specified in the design. Generate unique stable internal IDs independent of record IDs; escape every input. Evidence uses artifact name/hash/JSON pointer plus exact source references. Show native details closed by default; place concise facts/gaps in overview. Add grouped deployment visual, declared startup order, exact language bars and bounded inline SVG journey graph with complete textual alternatives. Optional filtering/navigation script must use safe DOM APIs. Add responsive/print/focus styles and restrictive CSP for renderer-owned assets. All supplied text is inert and the page needs no external assets.
- [ ] **Step 4: Verify green and syntax.** Run `uv run pytest -q tests/test_profile_html_inputs.py tests/test_profile_html_report.py`, `uv run ruff check profile/scripts/reportlib tests/test_profile_html_inputs.py tests/test_profile_html_report.py`, and `uv run python -m compileall -q profile/scripts/reportlib`. Record evidence. Root independently reviews before Task 3 begins; browser smoke verification belongs to final integration.

### Task 3: CLI, skill and marketplace integration

**Files:** Create the Task 3 files above; modify `scripts/verify-marketplace.sh`, `README.md`, `docs/ARCHITECTURE.md`, generated Codex manifests via `scripts/gen_codex_manifests.py`, and `profile/requirements.json` only if metadata needs adjustment. Discover generated output paths by running the generator, not guessing. Preserve all versions and unrelated generated changes.

**Interfaces:** Consumes Tasks 1–2 APIs; produces `main` and `write_report` above. CLI accepts positional artifact directory, repeatable `--support`, optional `--out`, `--title`, and `--open`. Script uses dependency-free PEP 723 metadata.

- [ ] **Step 1: Write failing CLI tests.** `test_cli_default_and_explicit_output` asserts default path, explicit path with spaces, expanded home, relative caller-CWD behavior and `.html`/`.htm` support. `test_invalid_input_preserves_output` asserts exit 2 and byte-identical existing destination for validation errors, absent parent, bad suffix and input alias collision. `test_atomic_write_failure_preserves_output` injects replacement failure and checks old contents and temporary-file cleanup. `test_browser_open_success_failure_and_no_open` asserts only explicit `--open` triggers `webbrowser.open` with the final file URI, no call precedes writing, false return/exception gives generation exit 0 and warning, and ordinary generation never opens. Use mocked opener and failures, not the real user browser in automated tests.
- [ ] **Step 2: Observe red.** Run `uv run pytest -q tests/test_profile_html_cli.py` and record the failing missing CLI/API evidence.
- [ ] **Step 3: Implement CLI writing/open behavior.** Validate destination and all inputs before writing; use a same-directory temporary file and atomic replacement. Resolve collision aliases and clean temporary files on failure. Report the final path and separate opener status; no shell commands, servers or target execution. Never conceal denied destinations by choosing an alternate path.
- [ ] **Step 4: Write skill and integration documentation.** Skill describes artifact-only input, explicit optional support, output precedence, default browser opening via script `--open`, `--no-open`, data/evidence limits, secret-safe approved artifacts, and exact invocation using `uv run --script`. Add `report` in directory-listing order to marketplace verification and README. Add architecture consumer node/edges and catalog entry; the renderer consumes saved contracts rather than discovering. Run `uv run scripts/gen_codex_manifests.py` and inspect the diff. Do not bump versions. If architecture Mermaid changes, render-verify it using repository guidance and record any unavailable-tool blocker.
- [ ] **Step 5: Verify focused behavior and syntax.** Run `uv run pytest -q tests/test_profile_html_inputs.py tests/test_profile_html_report.py tests/test_profile_html_cli.py`, `uv run ruff check profile/scripts/reportlib profile/scripts/profile_report.py tests/test_profile_html_inputs.py tests/test_profile_html_report.py tests/test_profile_html_cli.py`, and `uv run python -m compileall -q profile/scripts/reportlib profile/scripts/profile_report.py`. Validate changed JSON with `jq empty` on the exact changed JSON paths. Capture artifacts and exit statuses.
- [ ] **Step 6: Root performs full integration gates.** Run `uv run ruff check .`, `uv run pytest -q`, `uv run scripts/gen_codex_manifests.py --check`, and `bash scripts/verify-marketplace.sh`. Write full stdout/stderr to separate task logs; report counts, duration, exit status and paths. Resolve failures before completion.
- [ ] **Step 7: Root performs visual/offline verification and independent review.** Generate a sanitized report, move the single file, and inspect desktop/narrow layout, native keyboard details, evidence navigation, optional filters, offline/no-JavaScript behavior and print layout. Record precisely what was checked. Independently review fidelity, evidence boundary, active-content handling, output safety and registration. Address findings within ownership boundaries.
- [ ] **Step 8: Root records completion evidence.** Update active HANDOFF with changed files, exact commands/results, browser verification and review state, remaining limitations and next boundary. Provide the user a concise report. No commits or productionization/version changes unless separately authorized.

## Plan self-review

Requirements 1 and 3 are covered by Tasks 1–2; requirements 2, 4 and 5 by Task 2; requirement 6 by Task 3. All review-focus cases have explicit tests. API names and types are shared above and repeated only where ownership requires them. Supporting artifacts use explicit existing files instead of a new envelope. No implementation or private fixture content is embedded in this plan. User approval and SDD method are already recorded; execution proceeds under root coordination.
