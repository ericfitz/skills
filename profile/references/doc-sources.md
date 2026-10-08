# Doc sources

Reference for `profile:docs`: which sources exist, how each is read, how to rank what
you find, and what to say when a source cannot be reached.

## Source tiers

| tier | what | how it is read |
|---|---|---|
| in-repo | everything in `inventory.docs`, plus navigation from `inventory.docs_sites` | Read, Glob, Grep |
| user-named external | URLs, wiki pages, tracker documents, local paths outside the repo, all named by the caller | WebFetch for a URL; an MCP server present in this session for the system it belongs to; Read for a local path |
| unreachable | a named source with no matching capability | not read — recorded in `unavailable_sources[]` |

**Never build a retrieval mechanism. Use a capability that already exists in this
session, or record the source as unavailable with a remedy. Do not scrape, do not
construct URLs you were not given, and do not install anything.**

## Remedy table

Use this exact wording for `suggested_remedy` in `unavailable_sources[]`:

| case | `suggested_remedy` |
|---|---|
| no MCP for the named system | "Enable the *X* MCP server and run again" |
| a URL that fetches but returns a login page | "Export the page to markdown and place it under `docs/` or give a local path" |
| a source named too vaguely to locate | "Give a full URL or file path" |
| a binary format | "Convert to text and place it in the repo" |

## `doc_type` table

All thirteen values from `inventorylib/docs.py` `DOC_TYPES`. The inventory's
`doc_type_guess` is a **path-based guess** — nearest path segment wins, filename
outranking directory, computed without reading any content. This phase corrects
every guess once the document has actually been read.

| `doc_type` | what it looks like | what it is worth |
|---|---|---|
| `prd` | a product requirements document naming what a feature must do | highest — often the most direct source of `requirements` |
| `requirements` | a requirements or acceptance-criteria document, not framed as a product pitch | highest — same standing as `prd` |
| `spec` | an RFC or technical specification defining a protocol, format, or contract | high — normative, precise, usually testable as written |
| `design` | a design document describing an approach or proposal | high — often normative if approved, but check `stated_status` |
| `architecture` | a document describing system structure, components, or boundaries | high — mostly descriptive; occasionally states hard constraints |
| `adr` | an architecture decision record | medium — usually `historical`, but the decision itself can still bind future work |
| `runbook` | operational instructions for running or recovering the system | medium — descriptive; occasionally states invariants operators must preserve |
| `user_guide` | how-to material aimed at end users or operators | medium — descriptive; good source of `journey_evidence` |
| `readme` | the top-level or directory README | medium — usually descriptive, but often the only requirements a small project ever wrote down |
| `api_reference` | generated or hand-written reference for an API surface | lower — precise but rarely normative prose; good for vocabulary, weak for requirements |
| `tutorial` | a walkthrough of getting started or a quickstart | lower — strong source of `journey_evidence`, weak source of requirements |
| `changelog` | a log of past releases or changes | lower — useful only for `staleness` and version references |
| `unknown` | anything the census could not classify by path, or that defies these categories once read | lowest — read only if the ranking signals put it near the top of the budget |

## `authority` table

| `authority` | how to tell |
|---|---|
| `normative` | the document states obligations the team agreed to: a spec, an approved PRD, a requirements document |
| `descriptive` | explains how things work without binding anyone: most READMEs, overviews, tutorials |
| `historical` | superseded, dated, or explicitly marked as such: most ADRs describing past decisions |
| `unknown` | the document gives no signal either way |

## Ranking signals

Rank candidates by these signals, in this priority order:

1. **`doc_type` tier** — `prd`, `requirements`, `spec` outrank `design`, `architecture`,
   which outrank `adr`, `user_guide`, `readme`, which outrank `api_reference`,
   `changelog`.
2. **Normative density** — count matches per document with:

       rg -c -i -e '\bMUST\b' -e '\bSHALL\b' -e '\bSHOULD\b' -e 'acceptance criteria' <path>

3. **Recency** — `last_modified` from the census; a document untouched for years
   describing a system under active development is likely `historical`.
4. **Position in a docs-site navigation** — a page linked from the top level of
   `mkdocs.yml` or a Docusaurus sidebar outranks an orphan.

## Working from a truncated census

`inventory.docs` is truncated at 200 entries; `inventory.docs_total` preserves the
real count. Always compare the two. When `docs_total` exceeds the length of
`inventory.docs`, the list you were handed is incomplete — say so, and do not treat
it as the full document set when ranking or when computing how many documents were
found.

## Budget

**Deep-read at most 25 documents. Everything below the line goes in `deferred[]` with
its rank and why. Always state in your summary how many documents you read out of how
many you found. A cap that is not reported reads as complete coverage.**

## Closing rule

**You are extracting what the documents say, not judging whether it is true. Never
read source code to check a requirement. A requirement that contradicts the code is a
finding your caller makes, not one you make.**
