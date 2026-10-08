# Bump Adapter Contracts

This document defines the JSON shapes that all bump adapters emit. Every adapter verb returns one of these shapes as a JSON value to stdout.

## Adapter Output Rule

All adapters follow this strict contract:
- **Exactly one JSON value per invocation** — the shape specified in the verb table below (a dict, array, or the exact empty-contract shapes for `none` adapters)
- **Warnings to stderr + `warnings` field** — adapter-specific warnings go to stderr; fatal issues raise ValueError. Some verbs (notably `cache-clear`) return a dict with a `warnings` field for structured output
- **Never mix formats** — always emit valid JSON for the specific verb, never mix JSON with warnings or multiple values

The CLI (`bump.py`) parses the result via `contracts.dump()` (JSON with sorted keys) and ensures all fields serialize correctly. Parsers like the orchestrator and skill read only the exact shape for the requested verb; extra fields are preserved but optional.

---

## Data Classes

### UpdateRecord

Represents a dependency update opportunity.

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `name` | string | yes | Package name (e.g., "requests", "lodash", "github.com/foo/bar") |
| `current` | string | yes | Currently installed/locked version |
| `latest` | string | yes | Latest available version |
| `wanted` | string | yes | Desired version to upgrade to (often same as `latest`) |
| `bump` | string | yes | Semver bump class: "major", "minor", "patch", or "none" (from `classify_bump`) |
| `kind` | string | yes | Dependency kind: "direct", "transitive", or other ecosystem-specific value |
| `location` | string | yes | File where the dependency is declared (e.g., "pyproject.toml", "go.mod", "package.json") |
| `pinned` | boolean | no | (default: false) Whether the package is pinned and cannot be upgraded |
| `ecosystem` | string | no | (default: "") Ecosystem name for context (e.g., "python", "go", "node") |
| `meta` | dict | no | (default: {}) Ecosystem-specific metadata (e.g., `{"dependencyType": "dev"}` for Node) |

For Node, `location` is the workspace manifest that actually declares the package (e.g.
`packages/viewer/package.json`), `kind` is `"transitive"` for anything no manifest declares, and
`meta` additionally carries `declaredRange` (the specifier as written, e.g. `"^0.184.0"`) and
`dependent` (the workspace npm attributed the entry to). `declaredRange` is what lets `apply`
tell an in-range target from one that needs the manifest widened.

**Example UpdateRecord (JSON):**
```json
{
  "bump": "minor",
  "current": "2.28.0",
  "ecosystem": "python",
  "kind": "direct",
  "latest": "2.31.0",
  "location": "pyproject.toml",
  "meta": {},
  "name": "requests",
  "pinned": false,
  "wanted": "2.31.0"
}
```

### Advisory

Represents a security vulnerability found by audit tools.

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `package` | string | yes | Package name affected by the vulnerability |
| `ecosystem` | string | yes | Ecosystem name (e.g., "python", "go", "node") |
| `severity` | string | yes | Severity level (often "CRITICAL", "HIGH", "MEDIUM", "LOW", or empty if unknown) |
| `current` | string | yes | Currently installed version (may be empty if unknown) |
| `fixed` | string | yes | First patched/fixed version (empty if no fix available) |
| `ids` | list | no | (default: []) List of CVE/advisory IDs (e.g., ["CVE-2024-1234", "GHSA-xxxx-yyyy-zzzz"]) |
| `summary` | string | no | (default: "") Human-readable description of the vulnerability |
| `source` | string | no | (default: "") Source of the advisory (e.g., "pip-audit", "govulncheck", "dependabot", "audit") |

**Example Advisory (JSON):**
```json
{
  "current": "0.2.8",
  "ecosystem": "python",
  "fixed": "0.3.0",
  "ids": ["CVE-2024-1234"],
  "package": "jinja2",
  "severity": "HIGH",
  "source": "pip-audit",
  "summary": "Cross-site scripting (XSS) vulnerability in template rendering"
}
```

### Context

Represents a collection of issues or pull requests in the code-host or issue-tracker.

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `issues` | list | no | (default: []) List of issue dicts from the tracker; each has `id`, `title`, `url`, `labels` |
| `pullRequests` | list | no | (default: []) List of PR dicts from the code host; each has `id`, `title`, `head`, `url` |

**Example Context (JSON):**
```json
{
  "issues": [
    {
      "id": "#42",
      "labels": ["dependencies", "bug"],
      "title": "Upgrade requests to 2.31.0",
      "url": "https://github.com/org/repo/issues/42"
    }
  ],
  "pullRequests": [
    {
      "head": "bump/requests-2.31.0",
      "id": "#137",
      "title": "chore: bump requests to 2.31.0",
      "url": "https://github.com/org/repo/pull/137"
    }
  ]
}
```

### Categories

Represents the outcome of the categorization pass: buckets for security fixes, safe updates, updates needing a plan, and skipped updates.

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `securityFixes` | list | no | (default: []) List of UpdateRecord objects addressing known vulnerabilities |
| `safe` | list | no | (default: []) List of UpdateRecord objects classified as safe (patch/minor from stable source) |
| `needsPlan` | list | no | (default: []) List of UpdateRecord objects requiring review (major bump, transitive, etc.) |
| `skipped` | list | no | (default: []) List of UpdateRecord objects that cannot or should not be updated |

**Example Categories (JSON):**
```json
{
  "needsPlan": [
    {
      "bump": "major",
      "current": "1.5.0",
      "ecosystem": "node",
      "kind": "direct",
      "latest": "2.0.0",
      "location": "package.json",
      "meta": {"dependencyType": ""},
      "name": "webpack",
      "pinned": false,
      "wanted": "2.0.0"
    }
  ],
  "safe": [
    {
      "bump": "patch",
      "current": "3.9.1",
      "ecosystem": "node",
      "kind": "direct",
      "latest": "3.9.2",
      "location": "package.json",
      "meta": {"dependencyType": "dev"},
      "name": "eslint",
      "pinned": false,
      "wanted": "3.9.2"
    }
  ],
  "securityFixes": [],
  "skipped": []
}
```

---

## Verb → Output-Shape Mappings

Each axis (ecosystem, codeHost, issueTracker) supports a specific set of verbs. Below is the authoritative table from the implementation.

### Ecosystem Axis (`ecosystems/<name>.py`)

Adapters: `python`, `go`, `node`, or `none` (special case).

| Verb | Return Shape | Notes |
|------|--------------|-------|
| `detect` | dict | Detects if the ecosystem is present. When `present: true`, includes `ecosystem`, `packageManager` (string, may be empty for Go). When `present: false`, returns only `{"present": false, "ecosystem": "<name>"}` (packageManager omitted). Optional `workspace` field for Go (indicates go.work). For `none`: `{"present": false}` |
| `cache-clear` | dict | `{"warnings": []}` — clears package manager cache (no-op for some managers like Go) |
| `outdated` | list | `[UpdateRecord, ...]` — list of available updates; empty if no updates or if ecosystem not detected. Python/uv: when `uv.lock` exists the adapter first runs `uv sync --frozen` so the queried environment matches the lockfile (a stale venv otherwise reports phantom updates, a venv ahead of the lock hides real ones); `--frozen` guarantees the lockfile itself is never rewritten by this read verb, and a failed sync is warned on stderr and the existing environment queried as-is |
| `audit` | list | `[Advisory, ...]` — list of security vulnerabilities; empty if tool not installed or no vulns found. Python/uv audits the **lockfile**, not the installed environment: it exports `uv.lock` to a throwaway PEP 751 `pylock.toml` and runs `pip-audit --locked` on that. Environment mode cannot be trusted here — pip enumerates nothing inside a uv-created venv, so pip-audit scans an empty set and reports success. A project with no current `uv.lock` therefore audits as `[]` (`--frozen` never re-resolves to audit). Never commit the exported `pylock.toml`: uv treats it as an output only, and given one in place of `uv.lock` it silently re-resolves from `pyproject.toml`. |
| `apply` | dict | `{"applied": [spec, ...], "filesModified": [path, ...]}` on success — `filesModified` is verified against `git status` and lists only files that actually changed. Python/uv: when `filesModified` is empty (the lockfile already held every target) `applied` is `[]` too, so a commit message built from `applied` never claims a bump that did not happen. On any underlying package-manager command failing, returns `{"applied": [], "filesModified": [], "error": "<failed command>: <output tail>"}` — the working tree may hold partial changes from earlier commands in the batch; callers must treat `error` as "nothing durably applied" and revert before retrying. Pass fully-qualified specs (`name@X.Y.Z`); a bare name still works but only permits a within-range move. Node honors the version: a declared dependency whose target is provably outside its range is installed into its own workspace so the manifest range widens, while bare names, transitive packages and unrecognized range forms stay on `update` and touch only the lockfile. |
| `validate` | dict | Returns `{"<step>": "pass"/"fail", "<step>_output": "..."}` for each step. **Per-ecosystem shapes differ:** Go and Node include `build`, `test`, `lint` (all three); Python includes only `test` and `lint` (no build step). Output keys are literally `build_output`, `test_output`, `lint_output` for applicable steps. |

**Example invocation & output:**
```bash
python bump.py ecosystem python outdated
# -> [{"name": "requests", "current": "2.28.0", "latest": "2.31.0", ...}]
```

### Code Host Axis (`codehosts/<name>.py`)

Adapters: `github`, or `none` (special case).

| Verb | Return Shape | Notes |
|------|--------------|-------|
| `detect` | dict | `{"present": bool}` — detects if the repository is hosted on this code host (e.g., GitHub via `git remote get-url origin`). For `none`: `{"present": false}` |
| `alerts` | list | `[Advisory, ...]` — list of security alerts from the code host (e.g., Dependabot alerts); empty if code host not detected or no alerts. Returns `[]` if tool (gh) not installed |
| `prs` | Context | `Context(pullRequests=[...])` — dependency-related PRs; empty list if no PRs or tool not installed |
| `open-pr` | dict | `{"ok": bool, "output": str}` — creates a new PR; `ok` is true if successful. argv: `[branch, title, body]` |
| `pr-status` | dict | PR status information; shape depends on code host. GitHub returns `{"state": ..., "mergeable": ..., "mergeStateStatus": ..., "reviewDecision": ...}` on success. On error (tool missing or command fails): `{"error": "error message"}`. argv: `[pr_number]` |
| `merge-pr` | dict | `{"ok": bool, "output": str}` — merges and deletes the PR. argv: `[pr_number]` |

**Example invocation & output:**
```bash
python bump.py codeHost github prs
# -> {"issues": [], "pullRequests": [{"id": "#42", "title": "bump requests", ...}]}
```

### Issue Tracker Axis (`trackers/<name>.py`)

Adapters: `github`, or `none` (special case).

| Verb | Return Shape | Notes |
|------|--------------|-------|
| `issues` | Context | `Context(issues=[...])` — dependency-related issues; empty list if none. Returns empty Context if tool not installed. Required verb — all trackers must implement. |
| `advisories` | list | `[Advisory, ...]` — *optional* verb; not all trackers implement it. GitHub tracker does NOT support this verb and raises `ValueError` for it. |

**Example invocation & output:**
```bash
python bump.py issueTracker github issues
# -> {"issues": [{"id": "#42", "title": "Upgrade requests", ...}], "pullRequests": []}
```

### None Provider (Special Case)

The `none` adapter is a no-op for all axes. It returns fixed empty shapes:

| Verb | Return Shape |
|------|--------------|
| `detect` | `{"present": false}` |
| `outdated` | `[]` |
| `audit` | `[]` |
| `alerts` | `[]` |
| `prs` | `Context()` (empty) |
| `issues` | `Context()` (empty) |

Any verb not listed raises `ValueError: 'none' adapter has no verb '<verb>' on axis <axis>`.

---

## Notes for Adapter Implementers

1. **Subprocess Safety** — See `adding-adapters.md` for detailed rules.
2. **Missing Tools** — When an external tool is required (e.g., `pip-audit`, `gh`, `govulncheck`), use `shutil.which(tool_name)` to check if it's installed. If not, return the empty contract shape for that verb (usually `[]` or an empty dict) rather than raising an error. This ensures graceful degradation.
3. **Warnings** — Use stderr for non-fatal warnings; they're not part of the JSON contract. Raise ValueError for actual errors.
4. **Field Preservation** — Adapters should populate only the required fields for a shape. Extra fields in the dataclass (with defaults) are preserved during serialization but not required in output.
5. **Error Handling** — If a verb fails (e.g., subprocess crashes), raise ValueError with a clear message. The orchestrator will catch and handle it appropriately.

