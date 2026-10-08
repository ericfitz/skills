---
name: init
description: Bootstrap OpenAPI/Arazzo spec configuration for this repo — discovers and verifies the OpenAPI spec (and any Arazzo doc), then writes .local/openapi/config.yaml. Use when setting up the openapi plugin, when .local/openapi/config.yaml is missing, or when asked to locate or record the project's OpenAPI spec.
---

# init

Bootstraps `.local/openapi/config.yaml` (machine-local, gitignored):

    openapi_spec: api/openapi.yaml   # path relative to repo root, must exist
    arazzo_spec: arazzo.yaml         # where openapi:arazzo writes/reads

## Usage

    /openapi:init [path]

`path` is the repo root to configure; default is the current repo.

## Procedure

1. **Idempotence.** If `.local/openapi/config.yaml` already exists, print its
   contents and stop (exit 0). Point the user at editing the file directly if
   they want to change it.

2. **Discover.** Run the bundled discovery script:

       uv run python ${CLAUDE_PLUGIN_ROOT}/scripts/find_specs.py [path]

   It searches only `*.yaml`/`*.yml`/`*.json` files for strong spec markers,
   verifies every candidate — with `vacuum`, `redocly`, or `spectral` when one
   is installed, a structural parse otherwise — and prints JSON findings,
   best candidates first. Do not read arbitrary repo files yourself looking
   for specs; the script is the search.

   If `.local/cats/config.yaml` exists, read its spec path as an additional
   hint and verify it the same way. Never invoke the cats plugin's scripts.

3. **Choose.** Present the findings: each candidate with its path, marker
   (e.g. `openapi-3.1.0`), validity verdict, and which validator judged it.
   Recommend the best valid OpenAPI candidate, then let the user pick one of:

   - **accept** the recommendation,
   - **type a path** to a spec file discovery missed — verify it the same way
     before accepting,
   - **cancel** the skill (write nothing, stop cleanly).

   Never finish without an existing, verified OpenAPI spec file. If discovery
   found nothing and the user has no path, cancel is the outcome — do not
   write a config pointing at nothing.

4. **Arazzo path.** If discovery found a valid Arazzo document, record its
   path as `arazzo_spec`. Otherwise default to `arazzo.yaml` at the repo
   root, the Arazzo specification's recommended entry-document name.

5. **Write.** Create `.local/openapi/` and write `config.yaml` with the two
   keys. Ensure `.local/` is covered by the repo's `.gitignore`; append a
   `.local/` entry if it is missing.

6. **Offer apis.yaml.** Offer — never assume — to also generate a committed
   `apis.yaml` at the repo root in APIs.json format, so the spec locations
   are team-visible and readable by external tooling:

       name: <project name>
       type: Index
       apis:
         - name: <project name> API
           properties:
             - type: OpenAPI
               url: <openapi_spec path>
             - type: Arazzo
               url: <arazzo_spec path>

   If the user declines, the machine-local config alone is the outcome.

## Rules

- The config file is machine-local. Do not commit `.local/` contents.
- A typed path gets the same verification as a discovered one; a candidate
  that fails verification is presented as failed, not silently accepted.
- If no validator tool is installed, say the verdicts are structural only.
