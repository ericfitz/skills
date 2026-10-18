# deps:bump advisory gaps — design

Date: 2026-10-18. Scope: three defects found running `/deps:bump` on this repo (PR #96).

## Findings

1. **Python audit skips optional extras.** `_audit_uv` exported `uv.lock` without
   `--all-extras`/`--all-groups`, so packages reached only through an extra (nltk and
   urllib3 via `boring`) were never audited. Measured on 9186e25: default export audited
   8 packages, 0 advisories; `--all-extras --all-groups` found 38 advisories on nltk
   and urllib3.
2. **Advisories with no update record are dropped.** `categorize` looked up an advisory
   only from an UpdateRecord of the same name; an advisory on a package that is not
   directly outdated (every transitive one) vanished from the output.
3. **Dependabot alerts lose identity.** `parse_alerts` passed GitHub's ecosystem name
   through (`pip`, `npm`, ...) where the contract uses `python`/`node`/`go`, and left
   `ids` empty although the alert carries GHSA and CVE identifiers.
4. **SKILL.md Phase 9 Step 6 repeats work.** `merge-pr` runs
   `gh pr merge --squash --delete-branch`, which already checks out the base, pulls, and
   deletes the local branch; the skill's `git branch -D` then fails.

## Decisions (human, 2026-10-18)

- **Transitive advisories: auto-fix patch/minor.** An advisory with no matching
  UpdateRecord becomes a synthesized `kind: "transitive"` record (current from the
  advisory, latest = the highest fixed version). Patch/minor, not excluded/held/pinned:
  Security Fixes, applied like any other spec. Major: Needs Plan. No known current
  version or no fixed version: Needs Plan. Nothing is dropped.
- **Nested projects: report only.** Advisories carry an optional `location` (Dependabot's
  `manifest_path`). An orphan advisory whose location is in a subdirectory (a separate
  project the adapter does not cover, e.g. `writing/skills/boring/uv.lock`) goes to
  Needs Plan naming that location; full per-lockfile support is a separate issue.

## Contract changes (additive)

- `Advisory.location` (string, optional, default `""`): manifest or lockfile the
  advisory was found in. Python/uv audit sets `uv.lock`; Dependabot sets `manifest_path`.
- `UpdateRecord.bump` may be `"unknown"` on a synthesized record whose current version
  is not known.
- Dependabot `ecosystem` is normalized: `pip`→`python`, `npm`→`node`, `go`→`go`; other
  values pass through lowercased. `ids` = GHSA id then CVE id(s) from `identifiers`.
