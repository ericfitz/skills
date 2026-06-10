# skills

efitz's personal Claude Code marketplace (`efitz-skills`). Eight plugins, each
bundling one or more skills. Invoke a skill as `/<plugin>:<skill>`.

## loc — localization / i18n

`analyze` (missing-key manifests) · `coverage` (per-locale completeness) ·
`detect-nonloc` (should-this-be-translated) · `translate-to` (translate a
string) · `update-json` (atomic JSON locale edits) · `validate-translation`
(verify a translated string) · `backfill` (translate every missing key across
all locales).

## security

`vet-plugin` (vet a plugin/skill before installing) · `race-cond` (audit code
for race conditions and concurrency bugs).

## github

`backlog` (pick the next issue to work on) · `update-project-cache` (cache a
repo's GitHub Project metadata locally) · `create-issue` (file a detailed issue
into a repo/Project using that cache).

## ui

`vrt` (triage Playwright visual-regression / screenshot failures).

## wiki

`verify-doc` (verify a doc against source + references, then migrate it into a
project wiki).

## dev

`dedupe` (find and analyze duplicate/overlapping functionality across a
codebase).

## writing

`boring` (evaluate technical business writing for "boringness" across 20
sub-dimensions; mechanical analyzer + LLM-judged dimensions).

## deps

`bump` (update dependencies safely across Go/Python/Node — patch/minor auto,
build+test+lint validated, bisects failures, plans majors).

---

`writing-style/` is an experimental, agentic writing-style reviewer and is not
yet published as a marketplace plugin.
