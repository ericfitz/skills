# profile:report design

Status: approved design; implementation uses subagent-driven development. This specifies a reusable renderer, not a private project report. No plugin or contract version bump is authorized.

## Original request

> couuld you please take just the artifacts from the profile output and generate me an html report that summarizes everything, lets me drill down inside the html page to see the evidence but doesn't clutter a user-facing view with too much detail by default, and gives me mermaid diagrams where relevant, and/or tables, and/or anything else that would make it easier for a human to understand? Save the page in ~/Downloads and open it in my default browser.

The reusable skill preserves six requirements:

1. Use only saved profile output artifacts, with optional saved supporting artifacts.
2. Summarize the entire profile for a human reader.
3. Let the reader drill into evidence inside the HTML page.
4. Keep the default view concise and uncluttered.
5. Use useful diagrams, tables, and other visual explanations.
6. Honor the requested output location, including Downloads, and open the result in the default browser where supported.

## Inputs and scope

`/profile:report <artifact_dir> [--out <file.html>] [--support <file>]... [--title <text>] [--no-open]`

Require `stack.json`, `docs.json`, `journeys.json`, and `topology.json` from the supplied directory. Missing or malformed required contracts are errors before output replacement. Validate against the bundled schemas; support contract version `1.0.0`, reject unsupported versions, and retain permitted unknown fields in raw details. Distinguish missing optional values (“not supplied”) from empty recorded lists (“none recorded”).

Optional explicit support files include `inventory.json`, `validation.json`, and `analysis.txt`; repeat `--support` to include them. Accept JSON as parsed data and UTF-8 text/Markdown as inert text. Do not recursively discover files, render arbitrary HTML, fetch URLs, read source paths from evidence, or invoke profile discovery. These support files are labelled supporting material, never automatically treated as runtime verification or authoritative excerpts. Invalid JSON or unsupported formats produce an actionable error before writing.

An optional support envelope is not needed for the first implementation. Support files retain their actual filename, hash and content. Contract evidence shows exact source references; if supplied support contains an actual excerpt, it is available as explicitly attributed supporting text. Do not infer excerpt-to-source matches from prose. Do not fabricate excerpts. Original source text absent from supplied artifacts is labelled “source excerpt not supplied.”

No target execution, repository scan, environment or secret inspection, network access, server, runtime CDN, or additional runtime dependency. Production renderer uses Python 3.11+ standard library and a dependency-free PEP 723 entry point. All private examples remain outside the repository; tests use public examples and synthetic data.

## Output and browser behavior

The script accepts the same arguments with `--open` instead of `--no-open`. Its default is not to open; the skill passes `--open` unless the caller requests `--no-open`. Default output is `<artifact_dir>/profile-report.html`. Explicit `--out` takes precedence, expands `~`, and resolves relative paths against the caller's working directory. The original Downloads request is represented by explicit `--out ~/Downloads/<name>.html`, not silently replaced with the default.

Require `.html` or `.htm` and an existing parent directory. Reject input/output collisions, including resolved symlink aliases. Validate and render before an atomic destination write. Preserve an existing report on validation or write failure. Open the final file URI through Python's standard browser mechanism without shell interpolation. Opening is attempted only after successful writing. Failure to open is reported separately while successful report creation remains exit 0; invalid inputs and write failures exit 2. Respect permission denials; do not relocate output or bypass blocked browser opening.

The final response states the output path, report generation status, browser-opening status, and material input/evidence gaps. It does not claim visual verification unless a browser check occurred.

## Report layout and fidelity

A compact header and overview present primary language, deployment shape, document/requirement/journey counts, distinct stack/docs confidence indicators, and a deterministic summary of supplied facts. Do not invent a system-purpose narrative. Concisely surface material gaps near the overview.

Sections cover Overview; Stack and build; Documentation and requirements; Candidate journeys; Deployment; Gaps and assumptions; Evidence and supplied artifacts. Tables and native details provide complete access to every record while long prose, inventory and raw JSON start collapsed. Include corpus authority/read depth, deferred/unavailable sources, requirement modality/criteria/preconditions/staleness, glossary/invariants, journey rank/rationale/dependencies/surface coverage, infrastructure/third parties/configuration/startup/standup notes, all unknowns and all assumptions with reasons.

Preserve high/partial/low stack/docs confidence and high/medium/low requirement confidence as different scales. Journeys remain unconfirmed candidates. Requirements describe documentary obligations, not passing tests. Topology describes declared configuration, not live runtime state. Declared external reachability is not a successful probe. Optional validation artifacts remain attributed recorded assertions with no independently verified status conferred by this renderer.

Every displayed record has an in-page evidence route to its input artifact, JSON pointer (for JSON), and SHA-256 hash. Keep artifact-record provenance distinct from original source references. Resolve `corpus_id` against the docs corpus; retain file:line references verbatim. Unresolved corpus IDs and journey dependency IDs appear as gaps. Fields lacking original-source references show artifact provenance and that attribution limitation. Unknown fields remain in raw details. Never silently drop duplicate identifiers; surface a diagnostic and generate unique internal HTML IDs independently of user strings.

## Visuals and interaction

Use tables first. Inline SVG journey diagrams may show only explicit `depends_on` edges; label edge direction and provide a complete textual edge list. For more than 24 nodes, skip the diagram and retain the complete table with an explanation. Cycles remain visible and do not break rendering. Topology has no edge schema: use grouped components, infrastructure and third parties without invented arrows. Show declared startup order as an ordered list or flow. Language bars preserve exact recorded proportions without renormalizing incomplete coverage.

Mermaid is an option in the original request, not a requirement to load a remote renderer. Inline SVG provides offline diagrams without adding a toolchain; do not include a Mermaid CDN or require JavaScript graph rendering.

Native details, semantic headings/tables, keyboard focus, responsive layout and print styles are required. Optional renderer-owned JavaScript can add filtering and automatically open evidence targets, with useful content and evidence links still working without JavaScript. No reliance on color alone. Keep the report portable when moved as a single file.

All input text and attribute content is escaped. No input HTML, script, iframe, foreign SVG, or command is executed. Raw JSON appears as escaped text, not executable JavaScript. External source locators may remain inert text. Only renderer-owned inline styles/scripts/SVG are embedded. A CSP should block external connections, objects, forms and frames while permitting the renderer's own inline assets. Do not claim automatic secret redaction: the skill accepts already-approved artifacts and never retrieves secret values.

## Validation and completion

Tests use public contract examples plus synthetic complete, empty, low-confidence, malformed, duplicate-ID, dangling-reference, cycle, hostile-markup, Unicode, and large fixtures. Assert fidelity, evidence link resolution, output preservation, portability, and opening behavior. Test behavior changes red-first and record the observed failures before implementation. Rendered HTML receives a sanitized browser smoke check for desktop/narrow layout, keyboard expansion, evidence navigation, filters, offline/no-JavaScript use and print layout; distinguish performed checks from unverified items.

Root owns independent review, whole-repository gates, final integration and handoff. Required commands: `uv run ruff check .`, `uv run pytest -q`, `uv run scripts/gen_codex_manifests.py --check`, and `bash scripts/verify-marketplace.sh`. Capture full stdout/stderr in task artifacts, preserve exit status and print concise summaries. Syntax-check changed Python and validate changed JSON. Update marketplace registration, README and architecture flows, generated manifests and requirements metadata when applicable. Preserve versions. Handoff records changed files, exact validation commands/results, review state, and next boundary.
