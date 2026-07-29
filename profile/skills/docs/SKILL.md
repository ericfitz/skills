---
name: docs
version: 1.0.0
description: Read a project's documentary record — PRDs, requirements documents, specifications, design docs, ADRs, wiki pages — and extract the requirements, user-workflow evidence, domain vocabulary, and invariants it states. Use when profiling an unfamiliar project, gathering requirements, or establishing what a system was supposed to do. Emits the profile:docs contract.
---

# docs

Read what this project wrote down about itself, and extract what it says the system is
supposed to do.

This is the second gate phase: `journeys`, `topology`, and other consumers all read from
the record this phase produces, so they read it once and agree about it.

Reference: `${CLAUDE_PLUGIN_ROOT}/references/doc-sources.md`
Contract: `${CLAUDE_PLUGIN_ROOT}/references/contracts/docs.schema.json`
Example: `${CLAUDE_PLUGIN_ROOT}/references/contracts/examples/docs.example.json`

## Usage

    /profile:docs [path]

## Input

You are normally handed a `profile:stack` contract; use `inventory.docs` and
`inventory.docs_sites` as your in-repo census. You may also be handed external
document pointers — URLs, wiki locations, local paths.

**Standalone invocation:** if you were not handed a `stack` contract, invoke
`profile:stack` first and use its output. If you were not given external pointers and
you are running in a conversation with the user, ask once whether any requirements
documents, PRDs, or specifications live outside the repository, and accept "none".

## Procedure

1. **Resolve sources.** For each in-repo document, the capability is Read. For each
   external pointer, match it to a capability that is already available in this
   session per the source-tier table. Record every resolved source in
   `sources_available[]` with the capability you used.

2. **Record what you cannot reach.** A pointer with no matching capability goes in
   `unavailable_sources[]` with a reason and a `suggested_remedy` drawn from the remedy
   table. Then continue — an unreachable source is a reported gap, never a stop.

3. **Census.** For every candidate, record locator, title, headings, and
   `last_modified`. Correct the inventory's `doc_type_guess`, which is a path-based
   guess made without reading anything.

4. **Rank** by the signals in the reference, in the order given.

5. **Deep-read** down the ranking to the 25-document budget. Each document read becomes
   a `corpus[]` entry with `read: full` or `read: skimmed` and an `authority` value.
   Everything below the line becomes a `deferred[]` entry.

6. **Extract requirements.** A requirement is a statement about what the system must,
   should, or may do. Give each one an id, its `modality`, the actors it names, any
   acceptance criteria stated alongside it, any preconditions the document states, and
   `source_refs` pointing at the document and a heading anchor. A statement with no
   `source_refs` does not ship.

7. **Record `staleness`** per requirement: the document's `last_modified`, any version
   or release identifiers the text names, and any status the document states about
   itself ("draft", "approved", "superseded by X").

8. **Extract `journey_evidence`** — narratives describing what someone does with the
   system, with an actor and an entry-point hint where the text gives one. These are
   evidence for a later phase, not conclusions.

9. **Extract `glossary` and `domain_invariants`** — the project's own terms, and the
   statements that must always hold ("an order never leaves the cancelled state").
   These are the highest-leverage output for anyone writing precise assertions later.

10. **Record `open_questions`** — things the documentation raises but never settles.

11. Set `coverage_confidence`: `high` when you read the normative documents and nothing
    important was unreachable; `partial` when the budget or an unavailable source left a
    real gap; `low` when there is essentially no documentation.

12. Emit the contract, then a short prose summary that states how many documents you
    read out of how many you found, and names anything you could not reach.

## Rules

- **Never build a retrieval mechanism.** Use a capability that already exists in this
  session, or record the source as unavailable with a remedy. Do not scrape, do not
  construct URLs you were not given, and do not install anything.
- **Never read source code to verify a requirement.** You extract what the documents
  say. Whether the code agrees is your caller's finding to make, not yours.
- **Emit `journey_evidence`, never candidates.** Forming and ranking user-workflow
  candidates belongs to `profile:journeys`. Handing it evidence is the job; handing it
  conclusions takes its job away.
- Every requirement, evidence item, and glossary entry carries `source_refs`.
- Do not describe strategy, coverage, boundaries, or fixtures of any kind. This phase
  reports what the documents state; consumers decide what to do with it.
- A repository with no documentation is a legitimate finding: empty arrays and
  `coverage_confidence: low`, said plainly. Do not pad it with inferences from code.
