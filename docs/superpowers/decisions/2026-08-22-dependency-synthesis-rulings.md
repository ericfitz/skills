# Rulings — dependency-model layer 2 (#49)

Spec: `docs/superpowers/specs/2026-08-22-dependency-synthesis-design.md`
Plan: `docs/superpowers/plans/2026-08-22-dependency-synthesis.md`
Merged: `ab0d079`, 2026-08-23. Branch `feat/dependency-model-layer2`, 20 commits.

Decisions taken during execution that the spec and plan do not record. Most matter only as
history; the ones under "Do not undo these" describe code that looks wrong until you know why.

---

## Decisions made by the repository owner

**`platform`'s `lifecycle` is `run` for every `details.kind`.** The original D3 table mapped
`arch` / `os` / `runtime-version` to `build`. That was incoherent: `lifecycle` records which
environment must *contain* a dependency, and an architecture, an OS, and a `requires-python`
floor are all constraints on the **runtime** environment. `build` only reads correctly when the
artifact bakes the runtime in — one deployment shape among several.

Consequence: `cpu`/`memory`/`disk`/`gpu`/`cloud-service` were already `run`, so all eight kinds
are now `run`. The per-kind split collapsed entirely. `platform` is a constant-`run` category
alongside `service`, `network`, `config` and `security`, and **`package` is the only category
with a derived lifecycle.**

**An edge's `lifecycle` is the source node's lifecycle, propagated — not a constant per
`kind`.** The spec originally said `depends_on` edges carry `build` and `relates_to` carry
`run`. `graph.py` propagates instead, and that is the rule that ships. A constant `build` on
every package edge would carry no information and would contradict D3's per-package derivation.
The spec text was amended to match; `synthesis.schema.json`'s edge `lifecycle` now carries a
description saying so.

**Follow-ups filed rather than built:** [#55](https://github.com/ericfitz/skills/issues/55)
(the merge drops `scan.confidence` / `seeded_by` / `target`, so a report can never state a
low-confidence scan) and [#56](https://github.com/ericfitz/skills/issues/56) (nothing in layer 1
records that a package is dynamically loaded, which is why `synthesize`'s dynamic-loading rule
is scoped to available evidence).

---

## Do not undo these

Each of these looks like an oversight and is not.

| What | Why it is deliberate |
|---|---|
| Cycle detection walks `depends_on` edges only | `related_ids` links are routinely symmetric, so a combined-edge walk would report a 2-cycle for *every* service↔network association. The spec constrains no edge set; the plan's "combined edge set" was the plan's own invention. A test pins that a symmetric `relates_to` pair is not a cycle. |
| `graph.cycles` is not an exhaustive enumeration | A DFS back-edge walk reports a representative cycle per exploration. Full simple-cycle enumeration needs Tarjan SCC + Johnson, out of proportion when the spec asks only to "detect cycles". The limit is stated in `graph.py`'s docstring and in `report`'s cycles section rather than papered over. |
| `depgraph.py` emits a `mermaid` key that no skill consumes | `report` regenerates its fence from the contract's `graph`, which is correct — the contract is its stated interface and deliberately excludes presentation. The key remains useful to a human running the script directly. |
| `mermaid` is absent from `synthesis.schema.json` | A Mermaid string is presentation. The contract is the interface that #50/#51 will consume; putting rendering into it would be the wrong boundary. |
| `report`'s frontmatter description ends "Writes docs/dependencies.md." where `synthesize`'s ends "Emits the … contract." | `report` renders a contract; it does not emit one. Matching the sibling's wording would have made the skill state something false. |
| `on_path: ["build"]` on packages the example marks `lifecycle: run` | `package/SKILL.md` mandates `on_path: ["build"]` on every package entry unconditionally. Not an inconsistency. |
| The example's `graph` is generated, never hand-written | `tests/test_dependency_model_contracts.py` asserts `example["graph"] == build_graph(example["inventory"])`. Example/script drift was hand-fixed twice before this guard existed. Regenerate; do not edit. |

---

## Process rulings

Recorded briefly; none affects the shipped code.

- **Reviewed as combined units** where two tasks were halves of one mechanism (lifecycle
  derivation + declaration; the merge + the schema it produces). A reviewer holding one half
  cannot check that the halves agree.
- **Tasks 7, 9, 10 and 11 missed their per-task review gate** and received one catch-up review
  rather than being absorbed into the final whole-branch review. It found four Important issues
  the final review would have seen only in aggregate.
- **Minor findings were folded into fix rounds already underway** rather than deferred, when
  they sat in a file already being opened. Minors never *extended* a loop.
- **Reviews ran on Opus rather than Fable 5**, which `CLAUDE.md` prescribes, because the Fable
  credit pool was exhausted mid-session. Revert to Fable when credits return.
- **Guarding malformed manifests was extended to all four passes** in `pkglifecycle.py`
  (`[project]`, `dependency-groups`, `package.json`, `Cargo.toml`), not just the one reviewed.
  Guarding two of four would have recreated the asymmetry the fix existed to remove. The guards
  are identity functions on spec-valid input; this repo's own `pyproject.toml` classifies
  identically before and after.

---

## Two things that cost real time

**`rg` with colour highlighting eats the matched text in piped output.** It rendered
`platform.schema.json`'s eight-value `details.kind` enum as six values, which looks exactly like
the enum having been damaged. Use `rg --color=never`, or read JSON with Python, whenever the
matched text itself is what you are inspecting.

**Diff adjacency is not evidence of change.** A ruling was made ratifying an "improvement" to a
test helper that had never happened — unchanged context sitting beside lines that did change.
Verify with `git show <commit>:<path>`. That ruling is void; nothing was altered on its account.

---

## Known limits carried forward

Not defects, but do not mistake them for solved:

- **The two new skills are prose that nothing executes end to end.** Tests assert the rules are
  *written*, not that following them produces a valid artifact. A green suite is not a walked
  procedure.
- **The `mmdc` requirement probes for the binary on `PATH`**, while `report` invokes it via
  `npx -y -p @mermaid-js/mermaid-cli`. `/env:check` therefore errs toward reporting `mmdc`
  absent on machines where the documented invocation would succeed. The previous probe erred
  toward false-present, which was worse.
- **The example-vs-script guard pins `graph` against `inventory` only.** It cannot catch a
  hand-edited inventory `lifecycle` followed by an honest regeneration.
- **Lifecycle classification misclassifies toward `run`** in several known gaps (PEP 503
  name normalization, Cargo `[build-dependencies]`, cross-file precedence between
  `dev-dependencies` and `optional-dependencies`). `run` is the safe direction.
