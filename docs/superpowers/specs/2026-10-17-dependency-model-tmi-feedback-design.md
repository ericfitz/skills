# dependency-model: fixes from the tmi run (#92, #93, #94, #95)

Date: 2026-10-17. Issues: ericfitz/skills #92, #93, #94, #95.

## Why

A full dependency-model run on tmi (a multi-service Go repo, 996 graph nodes)
on 2026-10-17 needed four hand-written workarounds before it produced a usable
synthesis contract and report
(`~/Downloads/tmi-dependency-model-2026-10-17/work/synthesize/`):

1. `depgraph.py` reported 48 unresolved links. 45 were the same service written
   under two ids: config and network slugged topology's prose names literally
   (`nats (JetStream)` → `service:nats-(jetstream)`), the service skill
   shortened them (`service:nats`), and security guessed a third form
   (`service:openai` vs `service:openai-api`).
2. No edge left any `component:` node (0 outbound, 49 inbound), so
   `required_for[]` was filled from a hand-written caller table.
3. The 996-node graph exceeded the 60-node Mermaid cap, so the report had no
   diagram.
4. `report` writes `docs/dependencies.md`, which tmi forbids.

Success: rerunning on tmi's saved envelopes (after the skills follow the new
rules) needs no id rewrites for topology-named services, gets `required_for`
from the scripts, and the report shows a diagram, written where the caller
says.

## Goals

- One id per topology-named service and component, shared by all six
  discovery skills before they run (user decision: a shared id list, not only
  a more forgiving matcher).
- A slug rule that gives a clean, deterministic id for prose names.
- Component → service edges recorded by the service skill, turned into graph
  edges and `required_for[]` by the scripts.
- A collapsed diagram when the full graph is over the cap.
- A caller-chosen report output path.

## Non-goals

- Semantic aliases no rule can derive: `network:localhost-6379` vs
  `network:redis-6379`, a skill writing `service:openai` for a service the
  topology does not name. These stay in synthesize's existing reconcile step.
- An orchestrator skill (D8 in the discovery design still stands).
- Version bumps. Plugin and contract versions move only when the user
  declares the feature done (project CLAUDE.md).

## Anti-goals

- Inventing nodes to satisfy a link.
- Dropping or silently rewriting a link: an unmatched link is still listed
  under `unresolved`.
- A diagram that reads as the whole graph when it is not.

## Design

### 1. Slug rule (#92)

One function, `slug(name)` in `dependency-model/scripts/depgraphlib/ids.py`
(moved from `graph.py`; `graph.py` imports it), used by every script that
builds an id:

1. Lowercase.
2. Remove every parenthesized group, `(` to the matching `)`, including the
   parentheses.
3. Replace every run of characters other than `a-z`, `0-9` and `.` with one `-`.
4. Trim leading and trailing `-`.

Examples: `nats (JetStream)` → `nats`; `OAuth 2.0 / OIDC identity providers
(env-discovered; Google, GitHub, Microsoft etc.)` →
`oauth-2.0-oidc-identity-providers`; `migrate / dbtool / genconfig` →
`migrate-dbtool-genconfig`; `TMI_NATS_URL` → `tmi-nats-url`;
`metadata 169.254.169.254` → `metadata-169.254.169.254`.

Edge cases: a name that is entirely a parenthesized group, or that slugs to
the empty string, falls back to step 1, 3 and 4 without step 2; if that is
still empty the caller gets a `ValueError` naming the input. Unbalanced
parentheses: step 2 removes only balanced groups; a stray `(` or `)` is
punctuation for step 3.

This changes `component:` ids built by `depgraph.py --topology` (for example
`component:migrate---dbtool---…` becomes `component:migrate-dbtool-…`). That
is intended: the same function builds the shared id list, so they agree.

`references/categories.md` (Ids) states the new rule with these examples and
drops the `network:api-openai-com-443` example, which contradicts `.` staying.

### 2. Shared id list (#92)

New script `dependency-model/scripts/idmap.py`:

    uv run --script ${CLAUDE_PLUGIN_ROOT}/scripts/idmap.py <run_dir>/topology.json --write

Reads the `profile:topology` contract and writes `<run_dir>/ids.json` (the
directory holding `topology.json`), printing the path. Without `--write` it
prints the document to stdout. Stdlib only, like `depgraph.py`.

    {
      "components": [{"id": "component:tmi-server", "name": "tmi-server"}],
      "services": [{"id": "service:nats", "name": "nats (JetStream)",
                    "source": "real_dependencies"}]
    }

- `components` from `components[].name`; `services` from
  `real_dependencies[].name` and `external_third_parties[].name`, `source`
  naming which. Each list sorted by `id`.
- A service named in both lists appears once, with `source:
  "real_dependencies"`.
- Collision: when two different names produce the same id within a list, both
  fall back to the slug without step 2 (parentheses kept as `-` runs). If they
  still collide, exit 2 with a JSON error naming both names; nothing is
  written.
- Exit 2, nothing written, when the topology file is unreadable, is not a JSON
  object, or a list entry lacks a string `name`.
- A `real_dependencies[]` or `external_third_parties[]` name whose id part
  equals a component's id part is the system's own listener, not a service
  (categories.md: never `service:<component>`). It is left out of `services`
  and listed in a top-level `skipped: [{"name", "reason"}]` array; not an
  error. (Builder-check answer, my call.)
- Rerun: overwrites `ids.json` with identical content for the same topology
  (deterministic, sorted). Two concurrent runs write the same bytes; the write
  is to a temp file in the run dir then `os.replace`, so a reader never sees a
  partial file.

`depgraph.py --topology` builds component ids with the same id-assignment
function as `idmap.py` (in `ids.py`, collision fallback included), so its ids
equal `ids.json`'s. It does not read
`ids.json`.

**Sequence.** `running-discovery.md` today runs `profile:topology` before
`depscan.py` and never saves its contract. Reorder it to match synthesize's
standalone invocation: `depscan.py --write` (creates the run dir), then
`profile:topology` on `scan_root` saved to `<run_dir>/topology.json`, then
`idmap.py --write`, then the six skills. Synthesize's standalone invocation
gains the `idmap.py` step in the same place. Without a topology contract there is no `ids.json`, and
the skills fall back to the slug rule.

**Skill rule** (categories.md Ids, and a short pointer line in each of the six
discovery SKILL.md files): when `<run_dir>/ids.json` exists, read it before
writing any id.

- The service skill emits each topology-named service under exactly its
  `ids.json` id and never shortens or renames it. It may emit services not in
  the list, slugged by the rule.
- Every skill writes a link to a topology-named service or component using its
  `ids.json` id, never a re-slug of a different spelling of the name.
- A skill that finds a service which is plainly a part of a listed one (Google
  OAuth inside the OIDC providers entry) links to the listed id rather than
  inventing a finer one.

### 3. More forgiving matching in `depgraph.py` (#92)

`_resolver` in `graph.py` gains two fallbacks, after the existing exact,
canonical, and `service:` → `component:` steps:

- **Re-slug match.** Apply `slug` to the part after `category:` of the written
  target and of every node id; match when exactly one node in the same
  category has that form (`service:nats-(jetstream)` → `service:nats`).
- **Name match.** Match when exactly one node in the same category has
  `slug(name)` equal to the re-slugged target
  (a written `service:google-drive-google-workspace-apis` → a node
  `service:gdrive` named `Google Drive / Google Workspace APIs`).

Ambiguity (two candidates) leaves the link unresolved, as today. Every
fallback stays within the target's category.

### 4. Component → service edges (#93)

`service.schema.json` `details` gains an optional property:

    "used_by": [{"component_id": "component:tmi-server",
                 "evidence": ["cmd/server/main.go:447"]}]

`component_id` is a `component:` id (from `ids.json` when it exists);
`evidence` is a non-empty array of `file:line` strings (`minItems: 1`;
`scripts/validate.py` does not support `minItems` today, so add it there with
a test). The schema allows
`additionalProperties: false` objects with both fields required. The service
SKILL.md asks for it: for each service, the first-party components whose code
or deployment manifests use it, with evidence; omit the field when none can
be tied to a component.

`depgraph.py` turns each `used_by` entry into a `depends_on` edge from the
component to the service, lifecycle `run`, resolved through the same resolver.
A `component_id` that matches no node goes into `unresolved` with `kind:
"used_by"`.

`health.py` (`depgraphlib/health.py`):

- A component's `depends_on` edge to a service already makes the service a
  neighbour, so the component's health entry gains an `upstream_health`
  condition on that service. No change needed beyond a test.
- New: every condition in a service anchor's entry gets `required_for` = the
  sorted ids of components with a `depends_on` edge to that service. Conditions
  on a component's own entry get `required_for` = `[that component]`. The
  module docstring's "required_for is always empty" changes accordingly.

synthesize step 4 changes from "fill `required_for[]` (the script leaves it
empty)" to "the script fills `required_for[]` from `used_by`; you may add ids
static evidence supports, never remove one".

### 5. Collapsed diagram (#94)

`to_mermaid(graph, cap=60)` keeps its current output when the graph fits, plus
a new `"view": "full"` field. Over the cap it builds a collapsed view:

- Keep every `component` and `service` node.
- Replace all other nodes with one node per category that has any:
  label `"<category> (<count>)"`, id `rollup:<category>`, plain `["…"]` shape.
- Edges: map each endpoint to its kept node or rollup; drop self-loops; keep
  one edge per (from, to, kind).
- Output adds `"view": "collapsed"`, `"collapsed": {"<category>": count}`,
  `"degraded": false`, `"node_count"` = the full graph's count.
- If the collapsed view still exceeds the cap, return today's degraded result
  (`mermaid: null`, `degraded: true`, `view: null`) with a reason naming both
  counts.

`report` step 3: when `view` is `collapsed`, embed the fence and state above
it that it is a collapsed view, which categories were rolled up and how many
nodes each holds, and that the full graph is in the contract.

`depgraph.py`'s `mermaid` output uses the same function, so it gains the same
fields.

### 6. Report output path (#95)

`/dependency-model:report [path] [--ref <branch>] [--out <file.md>]`.

- With `--out`, write there (relative paths resolve against the caller's
  working directory) instead of either default.
- Reject, before rendering anything, an `--out` that does not end in `.md` or
  whose parent directory does not exist; the message names the path.
- An existing file at `--out` is overwritten, as the defaults are today.
- Defaults unchanged: `docs/dependencies.md` for a working-tree run,
  `<run_dir>/dependencies.md` for a `--ref` run.

Prose in `skills/report/SKILL.md`; the skill's frontmatter description and
`docs/ARCHITECTURE.md`'s catalog row mention `--out`.

## Tests (builder's layout, these behaviors required)

- `slug`: each example above, empty and all-parenthesized names, unbalanced
  parentheses.
- `idmap.py`: tmi-shaped topology fixture → expected `ids.json`; dedupe across
  the two service lists; collision fallback; unresolvable collision exits 2
  and writes nothing; malformed topology exits 2; rerun gives identical bytes.
- Resolver: re-slug and name matches; ambiguity stays unresolved;
  cross-category never matches.
- `used_by`: schema accepts and rejects; depgraph edge; unresolved
  `component_id`; health `required_for` on service and component entries.
- `to_mermaid`: under cap unchanged plus `view: full`; over cap collapsed with
  counts and deduped edges; still over cap degraded; output parses with `mmdc`
  in one test-time check if the existing mermaid tests already do so.
- Regression: tmi's 48 unresolved links (fixture built from the
  `work/synthesize/*.orig.json` envelopes; the original security links
  survive only in `work/security/gen.py`), trimmed. The resolver alone
  resolves 26; the other 22 stay unresolved and are the reason for
  `ids.json`: the service skill named nodes differently from the topology
  (`service:google-drive-api` "Google Drive / Workspace APIs" ×9), split one
  entry in two (`arbitrary-http(s)-urls-and-webhook-receivers`), or another
  skill guessed (`service:openai` ×3, vendor OAuth ×3, `localhost` network
  ×3), plus the 3 links to things with no node. The test asserts exactly
  this split, so a resolver change that moves it is visible. (Count from
  the builder check's simulation; my call to keep the resolver as designed
  rather than add a fuzzier rule.)

## Left to the builder

- Module and test file names; fixture size.
- Whether `ids.py` re-exports `canonical_id`.
- Wording of the SKILL.md and categories.md changes, within the rules above.
- Updating `docs/ARCHITECTURE.md` (run-dir artifact list and catalog rows) and
  `README.md` if either names the files or flags changed here.
