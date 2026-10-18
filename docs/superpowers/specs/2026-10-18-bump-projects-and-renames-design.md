# deps:bump nested projects, dependency kinds and renamed modules — design

Date: 2026-10-18. Issues: #98 (nested uv projects), #57 (transitive dependencies
classified as direct), #58 (renamed Go modules). Follows
`2026-10-18-bump-advisory-gaps-design.md`.

## Decisions

The user asked for these issues to be handled autonomously (2026-10-18). Every decision
below was made by Claude under that instruction, not by the user; each is easy to revisit.

1. **Projects are explicit.** Each ecosystem's `detect` adds `projects`: a list of
   `{"dir": <repo-relative dir, "." for the root>, "members": [<dirs whose manifests
   belong to this project>]}`.
   - Python/uv: one project per tracked `uv.lock` (`git ls-files -- '*uv.lock'`, or the
     root `uv.lock` alone when git is unavailable); `members` is `[dir]`. Python/pip:
     `[{"dir": ".", "members": ["."]}]`.
   - Node: one root project; `members` is `.` plus every workspace manifest directory
     the adapter already walks.
   - Go: one root project; `members` is `.` plus each `go.work` `use` directory.
2. **Categorize keys on (project, package).** The payload gains an optional `projects`
   list (the union of every ecosystem's `detect.projects`, merged by `dir`). Absent, it
   defaults to `[{"dir": ".", "members": ["."]}]`, which reproduces today's behavior.
   `project_of(location)` maps the location's parent directory through the members to
   a project dir; an empty location is the root.
   - An update record whose parent is not a member keeps its own parent dir as its
     project (an adapter only emits records for projects it covers).
   - An advisory whose parent is not a member is the "separate project this run does
     not cover" case and goes to Needs Plan, as now.
   - Every categorized item gains a `project` key, which the skill uses to group
     `apply` and `validate` calls.
3. **Python outdated reads the lockfile, not the venv.** For uv, `outdated` runs
   `uv tree --outdated --frozen --all-groups` in each project and parses the text
   output. Depth 1 is `kind: "direct"`, deeper is `"transitive"` (a package seen at
   several depths takes its shallowest); `location` is the project's `uv.lock`
   (`uv.lock` at the root, `writing/skills/boring/uv.lock` nested). This replaces
   `uv sync --frozen` + `uv pip list --outdated`: it needs no venv per project, cannot
   be fooled by the PEP 723 ephemeral env (#28) or venv/lock drift (#37), and gives the
   direct/transitive split #57 asked for. The text format is used because
   `--format json` is marked experimental by uv 0.13. A failing `uv tree` warns on
   stderr and yields no records for that project. pip mode is unchanged.
4. **Transitive Python records stay auto-applicable.** `uv lock --upgrade-package` on
   a transitive package is a lockfile refresh within its dependents' constraints,
   which is what the Safe bucket is for. Go `// indirect` requires likewise stay
   auto-applicable: they are written in go.mod. Graph-only Go modules were already
   excluded before this repo's initial commit (`required_modules`); verified against
   `ericfitz/tmi` on 2026-10-18 — 8 records (3 direct, 5 indirect), neither
   `github.com/ThalesGroup/crypto11` nor `github.com/google/cel-go` among them.
5. **`audit`, `apply`, `validate` per project.** Python `audit` audits every project
   and sets each advisory's `location` to that project's `uv.lock`. `apply` and
   `validate` take `--project DIR` (default `.`); `apply` runs `uv lock` and `uv sync`
   with `--project DIR` and reports `filesModified` repo-relative (e.g.
   `writing/skills/boring/uv.lock`). Go and Node accept only `--project .` and reject
   any other value.
6. **Validate runs only what a project declares.** Python `validate` runs pytest when
   the project's `pyproject.toml` names pytest (a dependency, extra, group or a
   `[tool.pytest...]` table) and ruff when it names ruff (likewise, or `[tool.ruff]`).
   A step not declared is `"skipped"` with `<step>_output` saying none is declared.
   `"skipped"` never triggers bisect.
7. **Renamed Go modules are found in `outdated`, not in `apply`.** For every outdated
   record, one batched `go list -m -json <mod>@<latest> ...` call returns each target's
   cached `GoMod` path; its `module` line is compared with the requested path (the
   proxy-served `.mod` file only: no source zip). On a mismatch the record gets
   `meta.renamedTo` (the declared path) and `meta.lastVersionWithPath` (the highest
   version above current whose `.mod` still declares the old path, or `""`), found
   with `go list -m -versions` and a second batched `go list -m -json`. A `go list`
   failure leaves the record unchanged. Categorize routes any record with
   `meta.renamedTo` to Needs Plan, before the security, major or safe checks:
   `Renamed (<old> -> <new> at <latest>); <v> is the last version under the old path`
   (or `...; no newer version keeps the old path`).
8. **`apply` reports a rename it hits anyway.** When `go get` fails with
   `module declares its path as: X ... but was required as: Y`, the error result also
   carries `renamed: [{"required": Y, "declared": X}]`.

## Contract changes (additive)

- `detect.projects` as above.
- Categorize payload `projects`; every categorized item carries `project`.
- `UpdateRecord.location` for Python/uv is the project's `uv.lock` (was
  `pyproject.toml`).
- `UpdateRecord.meta.renamedTo` / `meta.lastVersionWithPath` (Go).
- `apply` / `validate` accept `--project DIR`; validate step value `"skipped"`;
  Go `apply` error result may carry `renamed`.
