---
name: report
description: Use when saved profile output artifacts need a readable HTML summary with expandable evidence and offline diagrams, including requests to save or open the report.
---

# report

Create one portable HTML report from saved profile artifacts. This skill consumes
artifacts; it does not run discovery or inspect the profiled repository.

## Usage

    /profile:report <artifact_dir> [--support <file>]... [--out <file.html>] [--title <text>] [--no-open]

Require `stack.json`, `docs.json`, `journeys.json`, and `topology.json` in the
artifact directory, conforming to the bundled version `1.0.0` contracts. Include
optional support only when explicitly supplied: JSON (`.json`), UTF-8 text
(`.txt`), or Markdown (`.md`). Support is displayed as attributed data or inert
text, not rendered HTML or verified source excerpts.

Use already-approved, secret-safe artifacts. The renderer does not redact
secrets. Do not scan for extra files, follow source references, retrieve URLs,
inspect environments or credentials, execute the target, or invoke discovery to
fill gaps. Missing or invalid contracts are an error to report.

## Generate and open

Run the bundled dependency-free Python 3.11+ script:

If `CLAUDE_PLUGIN_ROOT` is unset, resolve the plugin directory two levels above
this skill's directory (it contains `scripts/` and `skills/`) and use that
absolute script path; do not resolve it from the caller's working directory.

```bash
uv run --script "${CLAUDE_PLUGIN_ROOT}/scripts/profile_report.py" "<artifact_dir>" --out "$HOME/Downloads/profile-report.html" --open
```

The example chooses Downloads explicitly. Preserve the caller's actual output
choice: `--out` overrides the default `<artifact_dir>/profile-report.html`, `~`
expands to the home directory, and relative paths use the caller's working
directory. Require an existing parent directory and `.html` or `.htm` suffix.
Quote paths and pass titles as arguments; never interpolate artifact text into
shell commands. Repeat `--support` for each explicit file, and forward `--title`
when supplied.

The default title is `Automated Profile of <software-name>`. The renderer uses
saved contract `software_name` or `project_name` fields (top-level or `metadata`),
then an unambiguous meaningful README corpus title, then recorded `repo_name` or
the basename of `stack.inventory.root`. Generic README titles are skipped;
absent identity becomes `Unknown software`. Explicit `--title` takes precedence.
Use these saved fields without inspecting the target repository or following
source references to improve the name.

Pass script `--open` by default. If the caller requests skill `--no-open`, omit
script `--open` (the script itself defaults to no opening). `uv run --script`
isolates execution from the profiled project's dependency configuration. If
`uv` is unavailable, run the same script with `python3` and mention the fallback.

Exit 2 means validation or writing failed; the prior report is preserved. Do not
silently relocate a denied destination. Browser opening occurs only after a
successful write. A false return or exception produces a warning while generation
remains exit 0. Report a blocked or unsupported opener separately; do not bypass
it through another opener, a server, or an alternate route.

## Evidence and delivery

The report preserves artifact hashes and JSON pointers separately from original
source references. Journeys remain unconfirmed candidates, documentary
requirements remain recorded obligations, and topology remains declared
configuration. Optional validation support is an attributed assertion, not
independent runtime verification. Absent original text is labelled “source
excerpt not supplied.” Do not invent evidence or upgrade confidence.

Return the exact saved path, generation status, browser-opening status, and
material input or evidence gaps. A successful opening request does not establish
visual verification; claim that only for checks actually performed.
