# Adding a New Bump Adapter

This guide walks you through adding a new adapter for an ecosystem, code host, or issue tracker to the bump system.

---

## Step 1: Pick Your Axis

Decide which axis your adapter belongs to:

- **Ecosystem** (`deps/scripts/bumplib/ecosystems/<name>.py`) — for package managers (e.g., Python's `uv`/`pip`, Go's `go get`, Node's `pnpm`/`npm`)
- **Code Host** (`deps/scripts/bumplib/codehosts/<name>.py`) — for version control platforms (e.g., GitHub, GitLab, Gitea)
- **Issue Tracker** (`deps/scripts/bumplib/trackers/<name>.py`) — for issue/project management (e.g., GitHub Issues, Jira)

All three follow the same adapter pattern. The example below uses an ecosystem adapter; codeHost and tracker adapters work identically, just with different verb sets.

---

## Step 2: Create the Adapter Module

Create `<name>.py` in the appropriate directory and expose a `handle(verb, argv)` function:

```python
from .. import contracts as c

def handle(verb, argv):
    """Main entry point for <name> adapter.
    
    Args:
        verb: Operation verb (e.g., "detect", "outdated", "audit", ...)
        argv: List of string arguments specific to the verb
    
    Returns:
        The contract shape for the verb (see contracts.md)
    """
    if verb == "detect":
        # Return detect shape: {"present": bool, "ecosystem": str, "packageManager": str, ...}
        return {"present": False, "ecosystem": "my_ecosystem"}
    
    if verb == "outdated":
        # Return list of UpdateRecord objects
        return []
    
    if verb == "audit":
        # Return list of Advisory objects
        return []
    
    raise ValueError(f"<name>: unknown verb {verb}")
```

---

## Step 3: Implement Verbs for Your Axis

Reference the verb table in `contracts.md` for your axis. Implement **all** required verbs, or raise `ValueError` for unsupported ones.

### Ecosystem Verbs

Required: `detect`, `cache-clear`, `outdated`, `audit`, `apply`, `validate`.

```python
def handle(verb, argv):
    if verb == "detect":
        # Return: {"present": bool, "ecosystem": str, "packageManager": str, "workspace"?: bool}
        ...
    
    if verb == "cache-clear":
        # Return: {"warnings": []}
        return {"warnings": []}
    
    if verb == "outdated":
        # Return: [UpdateRecord, ...]
        ...
    
    if verb == "audit":
        # Return: [Advisory, ...]
        ...
    
    if verb == "apply":
        # argv: list of specs to apply (e.g., ["requests==2.31.0", "flask==3.0.0"])
        # Return: {"applied": [spec, ...], "filesModified": [path, ...]}
        ...
    
    if verb == "validate":
        # Return: {"build": "pass"/"fail", "build_output": "...", 
        #          "test": "pass"/"fail", "test_output": "...",
        #          "lint": "pass"/"fail", "lint_output": "..."}
        ...
    
    raise ValueError(f"<name>: unknown verb {verb}")
```

### Code Host Verbs

Required: `detect`, `alerts`, `prs`, `open-pr`, `pr-status`, `merge-pr`.

### Tracker Verbs

Required: `issues`. Optional: `advisories`.

---

## Step 4: Emit Only Contract Shapes

Every verb must return **exactly** the shape defined in `contracts.md` for that verb:

- Use `c.UpdateRecord(...)` for ecosystem `outdated` results
- Use `c.Advisory(...)` for audit/alert results
- Use `c.Context(...)` for tracker/codeHost context results
- Use dict for `detect`, `open-pr`, `pr-status`, `merge-pr`, `validate`, `cache-clear`
- Use list `[]` for empty `outdated` or `audit` results

**Do not** add extra fields or invent new shapes. The orchestrator and categorizer depend on precise contracts.

```python
from .. import contracts as c

# CORRECT: Returns the exact UpdateRecord shape
return [c.UpdateRecord(name="pkg", current="1.0", latest="2.0", wanted="2.0",
                       bump="major", kind="direct", location="file.txt",
                       ecosystem="myeco")]

# WRONG: Extra fields or wrong types
return {"packages": [{"name": "pkg", ...}]}  # Wrong shape
return [{"name": "pkg", ...}]  # Missing UpdateRecord fields
```

---

## Step 5: Register via `.bump-config.json`

The CLI reads `.bump-config.json` to select adapters. **Ecosystems are ALWAYS auto-detected** by each ecosystem's `detect` verb — you do not and cannot configure them in `.bump-config.json`. Configure only `codeHost` and `issueTracker`:

```json
{
  "codeHost": "github",
  "issueTracker": "github",
  "exclude": ["package1", "package2"],
  "hold": {"package3": "1.0.0"},
  "ecosystems": {
    "python": {"test": "pytest --cov"},
    "go": {"lint": "golangci-lint run"}
  }
}
```

- **Ecosystems**: Auto-detected by calling each ecosystem's `detect` verb (Python, Go, Node are built-in). OMIT the ecosystem key entirely — there is no `"ecosystem"` config key.
- **codeHost** and **issueTracker**: Specify the adapter name (e.g., `"github"`, `"gitlab"`, `"none"`). OMIT the key to auto-detect GitHub (when git remote is github.com) or fall back to `"none"`.
- **exclude**: Patterns to skip (optional)
- **hold**: Version pins (optional)
- **ecosystems**: Per-ecosystem command overrides (optional)

The special `"none"` adapter is always available and returns empty shapes for all verbs.

---

## Step 6: Add Tests

Create `deps/scripts/tests/test_bump_<axis>_<name>.py` with:

1. **A recorded fixture** — JSON output from a real invocation of your adapter (or a mock ecosystem)
2. **Pure parse-function tests** — isolated tests for parsing functions (e.g., `parse_outdated`, `parse_audit`)

### Test Structure Example

```python
import json
from pathlib import Path
from bumplib.ecosystems.my_ecosystem import parse_outdated, handle

# Recorded fixture
OUTDATED_JSON_FIXTURE = """
[
  {"name": "pkg1", "current": "1.0.0", "latest": "2.0.0"},
  {"name": "pkg2", "current": "1.5.0", "latest": "1.6.0"}
]
"""

def test_parse_outdated():
    """Test parse_outdated handles valid JSON."""
    records = parse_outdated(OUTDATED_JSON_FIXTURE)
    assert len(records) == 2
    assert records[0].name == "pkg1"
    assert records[0].bump == "major"

def test_parse_outdated_empty():
    """Test parse_outdated handles empty input."""
    records = parse_outdated("[]")
    assert records == []

def test_handle_detect(tmp_path, monkeypatch):
    """Test detect verb returns correct shape."""
    monkeypatch.chdir(tmp_path)
    result = handle("detect", [])
    assert isinstance(result, dict)
    assert "present" in result
    assert "ecosystem" in result
```

**Conventions:**
- Use `tmp_path` fixture for filesystem tests
- Mock external tools or use recorded fixtures
- Test both happy paths and error cases (missing files, empty output, etc.)
- Keep parse functions pure (no side effects)

---

## Step 7: Subprocess Safety (CRITICAL)

**This is non-negotiable.** All subprocess calls must follow these rules to prevent injection attacks:

### Rule 1: Use `subprocess.run(list, ...)` with No `shell=True`

For anything that interpolates **package specs, versions, branch names, or PR text**, always:

```python
import subprocess

def _run(args):
    """Safe subprocess call: args is a list, no shell."""
    return subprocess.run(args, capture_output=True, text=True)

# CORRECT: Package name and version cannot inject
spec = "requests==2.31.0"  # From argv, could be malicious
_run(["pip", "install", spec])

# WRONG: Shell=True allows injection
subprocess.run(f"pip install {spec}", shell=True)  # DANGER: spec="'$(rm -rf /)'"
```

### Rule 2: Reserve `_run_shell` for Fixed, Trusted Config Strings Only

Create a separate helper **only** for fixed default/config strings that need shell operators:

```python
def _run_shell(cmd):
    """ONLY for trusted, config-sourced command strings.
    
    Never pass per-run/user data here. Examples of safe usage:
    - Makefile-like targets: "go build ./...", "pytest", "npm run build"
    - Config defaults: "ruff check . || true"
    
    DO NOT pass:
    - Package specs from argv
    - Branch names from PRs
    - PR titles or bodies
    - User input
    """
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)

# CORRECT: Fixed config string
_run_shell("go build ./...")

# CORRECT: Fixed config string with || operator (needs shell)
_run_shell("npm run lint:all || npm run lint")

# WRONG: Per-run data in shell command
pr_title = argv[0]  # From PR, could be malicious
_run_shell(f"git commit -m '{pr_title}'")  # DANGER: injection
```

### Rule 3: Guard External Tools with `shutil.which`

When an external tool is required, check if it's installed before using it:

```python
import shutil

def handle(verb, argv):
    if verb == "audit":
        # Guard: if tool not installed, return empty contract shape
        if shutil.which("pip-audit") is None:
            return []  # Empty Advisory list, no error
        
        result = _run(["pip-audit", "--format", "json"])
        return parse_audit(result.stdout)
    
    # For codeHost/tracker verbs:
    if verb == "alerts":
        if shutil.which("gh") is None:
            return []  # Empty Advisory list
        
        result = _run(["gh", "api", "repos/{owner}/{repo}/dependabot/alerts"])
        return parse_alerts(result.stdout if result.returncode == 0 else "[]")
```

**Why?** Users may not have all tools installed. Graceful degradation (returning empty shapes) is better than errors.

---

## Minimal Adapter Skeleton

Use this as a starting template:

```python
"""<Name> adapter for <axis> axis.

Supported verbs:
  - <verb1>: returns <shape>
  - <verb2>: returns <shape>
  ...
"""
import json
import shutil
import subprocess
from pathlib import Path

from .. import contracts as c


def _run(args):
    """Safe subprocess call: list form, no shell interpolation."""
    return subprocess.run(args, capture_output=True, text=True)


def _run_shell(cmd):
    """ONLY for trusted config/default strings needing shell operators.
    Never pass per-run/user data like package specs or PR titles."""
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)


def parse_<verb>(json_text: str):
    """Parse output from <external tool>.
    
    Args:
        json_text: JSON string from tool output
    
    Returns:
        List of Advisory or UpdateRecord objects
    """
    data = json.loads(json_text or "[]")
    results = []
    for item in data:
        # Transform item into contract shape
        results.append(c.Advisory(...) or c.UpdateRecord(...))
    return results


def handle(verb, argv):
    """Main entry point for <name> adapter.
    
    Args:
        verb: Operation verb
        argv: List of arguments for the verb
    
    Returns:
        Contract shape defined in contracts.md for this verb
    """
    if verb == "detect":
        return {"present": False, "ecosystem": "<name>"}
    
    if verb == "verb2":
        if shutil.which("<external_tool>") is None:
            return []  # Graceful degradation: tool not installed
        result = _run(["<external_tool>", "--arg"])
        return parse_verb2(result.stdout)
    
    if verb == "verb3":
        # Use _run_shell ONLY for fixed config strings
        result = _run_shell("make test")
        return {"output": result.stdout}
    
    raise ValueError(f"<name>: unknown verb {verb}")
```

---

## How Adapters Are Discovered

The dispatch module (`dispatch.py`) validates the axis, then either returns a fixed empty result (for `name=="none"`) or dynamically imports the adapter:

```python
AXES = {"ecosystem": "ecosystems", "codeHost": "codehosts", "issueTracker": "trackers"}

NONE_RESULTS = {
    "detect": {"present": False},
    "outdated": [],
    "audit": [],
    "alerts": [],
    "prs": c.Context(),
    "issues": c.Context(),
}

def run(axis, name, verb, argv):
    if axis not in AXES:
        raise ValueError(f"unknown axis: {axis}")
    if name == "none":
        if verb not in NONE_RESULTS:
            raise ValueError(f"'none' adapter has no verb '{verb}' on axis {axis}")
        return NONE_RESULTS[verb]
    
    # Dynamically import: bumplib.ecosystems.<name>, bumplib.codehosts.<name>, etc.
    mod = importlib.import_module(f"bumplib.{AXES[axis]}.{name}")
    return mod.handle(verb, argv)
```

So if you create `deps/scripts/bumplib/ecosystems/my_ecosystem.py` with a `handle()` function, it's automatically available as:

```bash
python bump.py ecosystem my_ecosystem detect
python bump.py ecosystem my_ecosystem outdated
# etc.
```

No registration needed beyond the file itself — and only `.bump-config.json` determines which adapter is used by default.

---

## Debugging

### Test Your Adapter in Isolation

```bash
cd /path/to/project
python ../bump.py ecosystem my_ecosystem detect
python ../bump.py ecosystem my_ecosystem outdated
```

### Check Output Format

The CLI always emits JSON via `contracts.dump()`:

```bash
python bump.py ecosystem python outdated | jq '.[0]'
# Should match UpdateRecord schema exactly
```

### Common Issues

1. **`ImportError: No module named 'bumplib.ecosystems.<name>'`** — File is in wrong directory or misspelled
2. **`ValueError: unknown verb`** — Check that verb exists in your `handle()` and matches `contracts.md`
3. **`KeyError` during parse** — JSON from tool doesn't match expected schema; add defensive `.get()` calls
4. **Mixed stdout/stderr** — Make sure warnings go to stderr, only JSON to stdout

---

## Checklist

- [ ] Adapter file created in correct axis directory (`ecosystems/`, `codehosts/`, or `trackers/`)
- [ ] `handle(verb, argv)` function defined
- [ ] All required verbs for the axis implemented
- [ ] Verbs return exact contract shapes (UpdateRecord, Advisory, Context, or dict)
- [ ] All subprocess calls use `_run(list)` with no `shell=True` for user/package data
- [ ] `_run_shell()` helper exists and is used ONLY for fixed config strings
- [ ] External tools guarded with `shutil.which()`, return empty shape if not installed
- [ ] Tests in `tests/test_bump_<axis>_<name>.py` with fixtures and parse-function tests
- [ ] `.bump-config.json` updated if needed
- [ ] Verified JSON output matches contract shapes (`contracts.md`)

