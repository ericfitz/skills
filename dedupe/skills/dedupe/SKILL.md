---
name: dedupe
version: 1.0.0
description: Find and analyze duplicate or overlapping functionality across a codebase. Use when the user asks to dedupe, find duplicate code, look for redundant functions, or audit for code duplication. Supports Go, Python, and TypeScript. Orchestrates per-file analysis, candidate grouping, and deep comparison through a shared SQLite database.
---

# Dedupe Command

Find and analyze duplicate or overlapping functionality across the codebase.

## Overview

This command performs a multi-phase analysis of code duplication:
1. Detects the primary language and discovers code files (excluding tests)
2. Groups files by directory/package and functional domain
3. Analyzes files in auto-tuned batches (results written to shared SQLite DB)
4. A lightweight grouper identifies candidate duplicates from DB summaries
5. Targeted deep comparison on candidates only (batched by group)
6. Generates a report organized by group and priority

All inter-agent communication flows through a shared SQLite database. Agents write results directly to the DB and return only short status strings. This keeps the orchestrator's context window small regardless of project size.

## Usage

```bash
/dedupe              # Auto-detect language, run full analysis
/dedupe go           # Analyze Go files only
/dedupe python       # Analyze Python files only
/dedupe typescript   # Analyze TypeScript files only
/dedupe clean        # Clean database and reports (force full re-analysis)
/dedupe tests        # Include test files in analysis
/dedupe go tests     # Analyze Go files including tests
```

Arguments:
- First positional arg: language name (go, python, typescript). If omitted, auto-detect.
- `clean`: Delete `.dedupe/dedupe.db` and `.dedupe/reports/` contents and exit.
- `tests`: Include test files in analysis (normally excluded).
- Language and `tests` can be combined in any order.

## Process

### Phase 0: Parse Arguments and Detect Language

1. Parse the user's request for language and option hints:
   - If the user says "clean" (or asks to reset/clear dedupe state): delete `.dedupe/dedupe.db` and `.dedupe/reports/` contents, then stop.
   - If the user mentions `go`, `python`, `typescript`, `ts`, or `py`: target that language only.
   - If the user mentions `tests` (e.g., "include tests"): set includeTests=true.
   - If invoked via the `/dedupe` command wrapper, the user's arguments are passed as the skill's args — parse them the same way.
   - If no language hint is present, proceed to auto-detection.

2. Auto-detect primary language:
   - Use Glob to count files for each language:
     - Go: `**/*.go` (exclude `vendor/**`)
     - TypeScript: `**/*.ts` (exclude `node_modules/**`, `**/*.d.ts`)
     - Python: `**/*.py` (exclude `venv/**`, `.venv/**`)
   - Select the language with the most files.
   - If multiple languages have significant presence (>20% of total each), inform the user which language was selected and mention they can specify one explicitly.

3. Display: `Language: {language} ({count} files detected)`

### Phase 1: Initialize Project and Database

1. Detect project root (find nearest `.git/` directory, or use current directory).
2. Create `.dedupe/` directory and `.dedupe/reports/` subdirectory if they don't exist.
3. Add `.dedupe/` to `.gitignore` if not already present.
4. Generate a run_id as ISO-8601 timestamp (e.g., `2026-02-15T10:30:00`).
5. Set `DB_PATH` to the absolute path of `.dedupe/dedupe.db`.
6. Initialize the database by running the following Python script via Bash:

```bash
python3 -c "
import sqlite3

conn = sqlite3.connect('DB_PATH_HERE')
conn.execute('PRAGMA journal_mode=WAL')
conn.execute('PRAGMA busy_timeout=10000')
conn.execute('PRAGMA foreign_keys=ON')

conn.executescript('''
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    language TEXT NOT NULL, project_root TEXT NOT NULL,
    include_tests INTEGER DEFAULT 0,
    total_files INTEGER, excluded_test_files INTEGER, generated_files INTEGER,
    files_from_cache INTEGER, files_analyzed INTEGER,
    started_at TEXT NOT NULL, completed_at TEXT
);

CREATE TABLE IF NOT EXISTS file_metadata (
    file_path TEXT PRIMARY KEY,
    file_size INTEGER NOT NULL, mtime TEXT NOT NULL,
    analyzed_at TEXT, group_name TEXT, domain TEXT,
    generated INTEGER DEFAULT 0, cache_valid INTEGER DEFAULT 0,
    analysis_status TEXT DEFAULT 'pending',
    error_message TEXT, retry_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS phase_state (
    phase TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'pending',
    started_at TEXT, completed_at TEXT,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS file_analyses (
    file_path TEXT PRIMARY KEY,
    language TEXT NOT NULL, file_type TEXT NOT NULL,
    file_purpose TEXT NOT NULL, generated INTEGER DEFAULT 0,
    imports TEXT, exports TEXT, analyzed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS code_units (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL,
    name TEXT NOT NULL, type TEXT NOT NULL, purpose TEXT NOT NULL,
    signature TEXT, lines_of_code INTEGER,
    complexity TEXT NOT NULL, calls_external INTEGER DEFAULT 0, is_public INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_code_units_file ON code_units(file_path);

CREATE TABLE IF NOT EXISTS groups (
    group_name TEXT PRIMARY KEY, domain TEXT NOT NULL, file_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS candidate_clusters (
    cluster_id INTEGER PRIMARY KEY AUTOINCREMENT,
    scope TEXT NOT NULL, group_name TEXT, groups_json TEXT, reason TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS candidate_units (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cluster_id INTEGER NOT NULL,
    file_path TEXT NOT NULL, unit_name TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_candidate_units_cluster ON candidate_units(cluster_id);

CREATE TABLE IF NOT EXISTS findings (
    finding_id INTEGER PRIMARY KEY AUTOINCREMENT,
    description TEXT NOT NULL, priority TEXT NOT NULL,
    scope TEXT NOT NULL, group_name TEXT, groups_json TEXT,
    similarity_analysis TEXT NOT NULL, differences TEXT NOT NULL,
    impact_complexity TEXT NOT NULL, impact_criticality TEXT NOT NULL,
    impact_risk_of_inconsistency TEXT NOT NULL,
    recommendation TEXT NOT NULL, rationale TEXT NOT NULL,
    refactoring_approach TEXT, effort TEXT NOT NULL, value TEXT NOT NULL,
    generated_file_involved INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS finding_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    finding_id INTEGER NOT NULL,
    file_path TEXT NOT NULL, unit_name TEXT NOT NULL, lines_of_code INTEGER
);
CREATE INDEX IF NOT EXISTS idx_finding_files_finding ON finding_files(finding_id);

CREATE VIEW IF NOT EXISTS compact_summaries AS
SELECT fm.group_name, g.domain, fa.file_path, fa.file_purpose, fa.generated,
    cu.name AS unit_name, cu.purpose AS unit_purpose,
    cu.type AS unit_type, cu.complexity AS unit_complexity
FROM file_analyses fa
JOIN file_metadata fm ON fa.file_path = fm.file_path
JOIN groups g ON fm.group_name = g.group_name
JOIN code_units cu ON fa.file_path = cu.file_path
WHERE fm.cache_valid = 1
ORDER BY fm.group_name, fa.file_path;
''')

conn.execute('''INSERT OR REPLACE INTO runs (run_id, language, project_root, include_tests, started_at)
    VALUES (?, ?, ?, ?, datetime('now'))''', ('RUN_ID_HERE', 'LANGUAGE_HERE', 'PROJECT_ROOT_HERE', 0))

# Initialize phase tracking
for phase in ['discovery', 'grouping', 'cache_check', 'analysis', 'grouper', 'comparison', 'report']:
    conn.execute('''INSERT OR IGNORE INTO phase_state (phase, status) VALUES (?, 'pending')''', (phase,))

conn.commit()
conn.close()
print('DB initialized')
"
```

Replace `DB_PATH_HERE`, `RUN_ID_HERE`, `LANGUAGE_HERE`, and `PROJECT_ROOT_HERE` with actual values. Set include_tests to 1 if includeTests is true.

**Important**: Also clear stale data from the previous run's grouping/comparison phases:
```bash
python3 -c "
import sqlite3
conn = sqlite3.connect('DB_PATH_HERE')
conn.execute('PRAGMA busy_timeout=10000')
conn.execute('DELETE FROM finding_files')
conn.execute('DELETE FROM findings')
conn.execute('DELETE FROM candidate_units')
conn.execute('DELETE FROM candidate_clusters')
# Reset phase state for phases that depend on fresh data
for phase in ['grouper', 'comparison', 'report']:
    conn.execute('''UPDATE phase_state SET status='pending', started_at=NULL, completed_at=NULL, error_message=NULL
        WHERE phase=?''', (phase,))
conn.commit()
conn.close()
"
```

### Phase 2: Smart File Discovery and Test Exclusion

Enumerate code files for the selected language ONLY.

#### Go Files
- Include: `**/*.go`
- Exclude always: `vendor/**`, `.dedupe/**`
- **Smart test exclusion** (unless includeTests=true):
  - Files matching `*_test.go`
  - Directories named `testdata/`
  - Files in `test/` or `tests/` directories
  - Files in directories where EVERY `.go` file ends with `_test.go` (test-only packages)
  - Files named `mock_*.go` or `*_mock.go` in test-adjacent directories

#### TypeScript Files
- Include: `**/*.ts`, `**/*.tsx`
- Exclude always: `node_modules/**`, `dist/**`, `build/**`, `**/*.d.ts`, `.dedupe/**`
- **Smart test exclusion** (unless includeTests=true):
  - Files matching `*.spec.ts`, `*.test.ts`, `*.spec.tsx`, `*.test.tsx`
  - Directories named `__tests__/`, `test/`, `tests/`
  - Files named `*.fixture.ts`, `*.mock.ts`
  - Files in directories named `fixtures/`, `__mocks__/`, `test-utils/`

#### Python Files
- Include: `**/*.py`
- Exclude always: `venv/**`, `.venv/**`, `__pycache__/**`, `.dedupe/**`
- **Smart test exclusion** (unless includeTests=true):
  - Files matching `test_*.py`, `*_test.py`
  - Directories named `tests/`, `test/`
  - Files named `conftest.py`
  - Files in directories named `fixtures/`, `testdata/`

#### Generated Code Detection
After file discovery, detect likely generated files:
- Files containing a comment like `// Code generated`, `// DO NOT EDIT`, `# Generated`, `# Auto-generated` in first 5 lines
- For Go: files generated by tools (look for `//go:generate` or known generators like oapi-codegen, protoc, sqlc)
- Mark generated files with `generated=1` in file_metadata

#### Write Discovered Files to Database

For each discovered file, insert into `file_metadata` using a Python script. Also mark the `discovery` phase as complete:

```bash
python3 -c "
import sqlite3, os, json
from datetime import datetime

conn = sqlite3.connect('DB_PATH_HERE')
conn.execute('PRAGMA busy_timeout=10000')

conn.execute('''UPDATE phase_state SET status='running', started_at=datetime('now') WHERE phase='discovery' ''')

files = [
    # (file_path, file_size, mtime_iso, generated)
    # ... one tuple per discovered file ...
]

conn.execute('BEGIN')
for fp, size, mtime, gen in files:
    conn.execute('''INSERT OR REPLACE INTO file_metadata (file_path, file_size, mtime, generated, analysis_status, retry_count)
        VALUES (?, ?, ?, ?, 'pending', 0)''', (fp, size, mtime, gen))

conn.execute('''UPDATE phase_state SET status='completed', completed_at=datetime('now') WHERE phase='discovery' ''')
conn.commit()
conn.close()
"
```

Get file_size and mtime for each file using `os.path.getsize()` and `os.path.getmtime()` in the Python script, or use the Bash tool to gather this info first.

Display: `Found {count} code files ({excluded} test files excluded, {generated} generated files detected)`

### Phase 3: File Grouping

Build groups from the discovered files:

1. **Directory/package grouping** (primary):
   - Go: Group by Go package (directory)
   - TypeScript: Group by directory (first 2 levels of path, e.g., `src/components`)
   - Python: Group by Python package (directory with `__init__.py`, or just directory)

2. **Domain tagging**:
   For each group, infer a functional domain from directory name and file purposes:
   - `auth` - authentication, authorization, JWT, OAuth, RBAC
   - `api` - HTTP handlers, routes, endpoints, middleware
   - `websocket` - WebSocket connections, real-time features
   - `storage` - database, persistence, migrations, repositories
   - `cache` - caching, Redis, memoization
   - `model` - data models, types, schemas
   - `config` - configuration, environment
   - `util` - utilities, helpers, common functions
   - `other` - anything that doesn't fit above

3. **Write groups to database** (also mark grouping phase state):

```bash
python3 -c "
import sqlite3

conn = sqlite3.connect('DB_PATH_HERE')
conn.execute('PRAGMA busy_timeout=10000')

conn.execute('''UPDATE phase_state SET status='running', started_at=datetime('now') WHERE phase='grouping' ''')

conn.execute('BEGIN')

groups = [
    # (group_name, domain, file_count)
    # ... one tuple per group ...
]

for gn, domain, fc in groups:
    conn.execute('INSERT OR REPLACE INTO groups (group_name, domain, file_count) VALUES (?, ?, ?)',
        (gn, domain, fc))

# Update file_metadata with group assignments
file_groups = [
    # (group_name, domain, file_path)
    # ... one tuple per file ...
]
for gn, domain, fp in file_groups:
    conn.execute('UPDATE file_metadata SET group_name = ?, domain = ? WHERE file_path = ?',
        (gn, domain, fp))

conn.execute('''UPDATE phase_state SET status='completed', completed_at=datetime('now') WHERE phase='grouping' ''')
conn.commit()
conn.close()
"
```

Display:
```
Groups:
  auth/     (5 files) - auth
  api/      (12 files) - api
  internal/ (3 files) - util
  ...
```

### Phase 4: Check Metadata and Determine Cache Validity

Query the database to check which files have valid cached analyses. This also handles **recovery from interrupted runs**: files whose `analysis_status` is `'running'` (agent was dispatched but never completed) are reset to `'pending'` for retry.

```bash
python3 -c "
import sqlite3, os, json

conn = sqlite3.connect('DB_PATH_HERE')
conn.execute('PRAGMA busy_timeout=10000')
conn.row_factory = sqlite3.Row

conn.execute('''UPDATE phase_state SET status='running', started_at=datetime('now') WHERE phase='cache_check' ''')

# Get all current file metadata
rows = conn.execute('SELECT file_path, file_size, mtime, analysis_status, retry_count FROM file_metadata').fetchall()

need_analysis = []
from_cache = 0

for row in rows:
    fp = row['file_path']
    stored_size = row['file_size']
    stored_mtime = row['mtime']
    status = row['analysis_status']
    retries = row['retry_count'] or 0

    # Check if analysis exists and file is unchanged
    analysis = conn.execute('SELECT file_path FROM file_analyses WHERE file_path = ?', (fp,)).fetchone()

    if analysis and status == 'done':
        try:
            stat = os.stat(fp)
            current_size = stat.st_size
            current_mtime = str(stat.st_mtime)
            if str(stored_size) == str(current_size) and stored_mtime == current_mtime:
                conn.execute('''UPDATE file_metadata SET cache_valid = 1, analysis_status = 'done'
                    WHERE file_path = ?''', (fp,))
                from_cache += 1
                continue
        except OSError:
            pass

    # Reset 'running' (interrupted) back to 'pending' for retry
    # Reset 'error' files for retry if under max retries (3)
    if status == 'running':
        conn.execute('''UPDATE file_metadata SET cache_valid = 0, analysis_status = 'pending',
            retry_count = retry_count + 1 WHERE file_path = ?''', (fp,))
        need_analysis.append(fp)
    elif status == 'error' and retries < 3:
        conn.execute('''UPDATE file_metadata SET cache_valid = 0, analysis_status = 'pending',
            retry_count = retry_count + 1 WHERE file_path = ?''', (fp,))
        need_analysis.append(fp)
    elif status == 'error' and retries >= 3:
        # Permanently failed — skip but don't block the pipeline
        conn.execute('''UPDATE file_metadata SET cache_valid = 0 WHERE file_path = ?''', (fp,))
    else:
        # 'pending' or file changed — needs analysis
        conn.execute('''UPDATE file_metadata SET cache_valid = 0, analysis_status = 'pending'
            WHERE file_path = ?''', (fp,))
        need_analysis.append(fp)

# Clean up files no longer on disk
all_paths = [row['file_path'] for row in rows]
for fp in all_paths:
    if not os.path.exists(fp):
        conn.execute('DELETE FROM code_units WHERE file_path = ?', (fp,))
        conn.execute('DELETE FROM file_analyses WHERE file_path = ?', (fp,))
        conn.execute('DELETE FROM file_metadata WHERE file_path = ?', (fp,))

permanently_failed = conn.execute(
    \"SELECT COUNT(*) FROM file_metadata WHERE analysis_status='error' AND retry_count >= 3\").fetchone()[0]

conn.execute('''UPDATE phase_state SET status='completed', completed_at=datetime('now') WHERE phase='cache_check' ''')
conn.commit()
print(json.dumps({'from_cache': from_cache, 'need_analysis': need_analysis, 'permanently_failed': permanently_failed}))
conn.close()
"
```

Parse the output to get the list of files needing analysis and the cache count.

Display: `{N} files from cache, {M} files need analysis`
If permanently_failed > 0, also display: `({P} files permanently failed after 3 retries — skipping)`

### Phase 5: Batched Analysis with DB-Driven Retry

This phase is designed to be **resumable and self-healing**. Instead of building a file list once and iterating, it queries the database for pending work before each batch. If a previous run was interrupted, this phase automatically picks up where it left off.

**CRITICAL CONTEXT MANAGEMENT**: Agents are spawned with `run_in_background=true` and their output is **NEVER read back**. Instead, the orchestrator polls the database to check which files have been completed. This prevents sub-agent conversation transcripts (which can be hundreds of lines each) from accumulating in the orchestrator's context window.

**Mark analysis phase as running:**
```bash
python3 -c "
import sqlite3
conn = sqlite3.connect('DB_PATH_HERE')
conn.execute('PRAGMA busy_timeout=10000')
conn.execute('''UPDATE phase_state SET status='running', started_at=datetime('now') WHERE phase='analysis' ''')
conn.commit()
conn.close()
"
```

**The analysis loop:**

```
REPEAT:
  1. Query DB for files where analysis_status = 'pending' (up to BATCH_SIZE)
  2. If none remain → exit loop (Phase 5 complete)
  3. Mark those files as analysis_status = 'running' in the DB
  4. Spawn one Task agent per file, ALL with run_in_background=true
  5. DO NOT read agent output via TaskOutput — poll the DB instead
  6. Wait and poll DB until all files in batch are no longer 'running'
  7. Display batch progress
```

**Batch size auto-tuning:**
- 1-10 pending files: 1 batch (all parallel)
- 11-30 pending files: 2 batches of ~equal size
- 31-60 pending files: 3-4 batches of ~15 files
- 61+ pending files: batches of 15 files each

**Step 1: Query for pending files and mark as running**

Before each batch, get the next set of files to analyze and mark them:

```bash
python3 -c "
import sqlite3, json
conn = sqlite3.connect('DB_PATH_HERE')
conn.execute('PRAGMA busy_timeout=10000')

# Get pending files (limit to batch size)
rows = conn.execute('''SELECT file_path FROM file_metadata
    WHERE analysis_status = 'pending'
    ORDER BY file_path
    LIMIT BATCH_SIZE_HERE''').fetchall()
file_paths = [r[0] for r in rows]

# Mark them as running
for fp in file_paths:
    conn.execute('''UPDATE file_metadata SET analysis_status = 'running'
        WHERE file_path = ?''', (fp,))
conn.commit()

print(json.dumps(file_paths))
conn.close()
"
```

Replace `BATCH_SIZE_HERE` with the actual batch size (e.g., 15).

**Step 2: Spawn background agents for this batch**

For each file in the batch, spawn one Task agent. **All agents MUST use `run_in_background=true`**. Launch all agents in a single message with multiple Task tool calls:

- `subagent_type="general-purpose"`
- `run_in_background=true`
- `max_turns=10`
- Prompt for each agent:

```
Read and follow the instructions in ${CLAUDE_PLUGIN_ROOT}/agents/dedupe-analyzer.md.
The file to analyze is: {FILE_PATH}
The database path is: {DB_PATH}
IMPORTANT: Use the EXACT file path shown above in ALL database writes. Do not modify, shorten, or make the path relative.
Analyze the file, write results to the database, and return ONLY a status line.
```

Replace `{FILE_PATH}` and `{DB_PATH}` with actual values. `{FILE_PATH}` MUST be an absolute path.

**IMPORTANT**: Do NOT call TaskOutput on any of these agents. Do NOT read the output_file returned by the Task tool. The agents write their results directly to the database. Reading their output would pull their entire conversation transcript (including full file contents and Python scripts) into the orchestrator's context, defeating the purpose of the SQLite architecture.

**Step 3: Poll the database for completion**

After spawning all agents in a batch, poll the database to wait for them to finish. Use `sleep` between polls to avoid busy-waiting:

```bash
python3 -c "
import sqlite3, json, time

db_path = 'DB_PATH_HERE'
batch_files = BATCH_FILES_JSON_HERE  # list of file paths in this batch

max_wait = 300  # 5 minutes max
poll_interval = 10  # check every 10 seconds
elapsed = 0

while elapsed < max_wait:
    time.sleep(poll_interval)
    elapsed += poll_interval

    conn = sqlite3.connect(db_path)
    conn.execute('PRAGMA busy_timeout=10000')

    still_running = conn.execute(
        '''SELECT COUNT(*) FROM file_metadata
        WHERE analysis_status = 'running' AND file_path IN ({})'''
        .format(','.join('?' * len(batch_files))),
        batch_files
    ).fetchone()[0]

    conn.close()

    if still_running == 0:
        break

# Final status
conn = sqlite3.connect(db_path)
done = conn.execute(\"SELECT COUNT(*) FROM file_metadata WHERE analysis_status='done'\").fetchone()[0]
pending = conn.execute(\"SELECT COUNT(*) FROM file_metadata WHERE analysis_status='pending'\").fetchone()[0]
running = conn.execute(\"SELECT COUNT(*) FROM file_metadata WHERE analysis_status='running'\").fetchone()[0]
errors = conn.execute(\"SELECT COUNT(*) FROM file_metadata WHERE analysis_status='error'\").fetchone()[0]
total = conn.execute('SELECT COUNT(*) FROM file_metadata').fetchone()[0]
print(json.dumps({'done': done, 'pending': pending, 'running': running, 'errors': errors, 'total': total, 'elapsed': elapsed}))
conn.close()
"
```

Replace `BATCH_FILES_JSON_HERE` with the actual Python list of file paths for this batch (e.g., `['/Users/foo/src/a.ts', '/Users/foo/src/b.ts']`).

**Step 4: Handle stragglers and report progress**

After polling completes, check if any files from this batch are still 'running' (timed out). Mark them as errors:

```bash
python3 -c "
import sqlite3, json

db_path = 'DB_PATH_HERE'
batch_files = BATCH_FILES_JSON_HERE

conn = sqlite3.connect(db_path)
conn.execute('PRAGMA busy_timeout=10000')

# Mark timed-out files as errors
timed_out = conn.execute(
    '''UPDATE file_metadata SET analysis_status = 'error',
    error_message = 'agent timed out after 5 minutes'
    WHERE analysis_status = 'running' AND file_path IN ({})'''
    .format(','.join('?' * len(batch_files))),
    batch_files
).rowcount

# Also fix any relative path issues: if an agent wrote to file_analyses with a relative path,
# match it to file_metadata and fix it
for fp in batch_files:
    import os
    basename = os.path.basename(fp)
    # Check if agent wrote with a relative path
    rel_rows = conn.execute(
        '''SELECT file_path FROM file_analyses
        WHERE file_path != ? AND file_path LIKE ?''',
        (fp, '%' + basename)
    ).fetchall()
    for rel_row in rel_rows:
        rel_path = rel_row[0]
        # Verify this relative path is a suffix of the absolute path
        if fp.endswith(rel_path) or fp.endswith(rel_path.lstrip('./')):
            conn.execute('UPDATE file_analyses SET file_path = ? WHERE file_path = ?', (fp, rel_path))
            conn.execute('UPDATE code_units SET file_path = ? WHERE file_path = ?', (fp, rel_path))
            # Now that file_analyses has the correct path, mark file_metadata as done
            conn.execute('''UPDATE file_metadata SET analysis_status = 'done', cache_valid = 1
                WHERE file_path = ? AND analysis_status = 'running' ''', (fp,))

conn.commit()

done = conn.execute(\"SELECT COUNT(*) FROM file_metadata WHERE analysis_status='done'\").fetchone()[0]
total = conn.execute('SELECT COUNT(*) FROM file_metadata').fetchone()[0]
errors = conn.execute(\"SELECT COUNT(*) FROM file_metadata WHERE analysis_status='error'\").fetchone()[0]
pending = conn.execute(\"SELECT COUNT(*) FROM file_metadata WHERE analysis_status='pending'\").fetchone()[0]
print(json.dumps({'done': done, 'total': total, 'errors': errors, 'pending': pending, 'timed_out': timed_out}))
conn.close()
"
```

Display: `Batch complete: {done}/{total} files analyzed ({errors} errors, {pending} pending)`

**Step 5: Retry loop for errors**

After all normal batches complete, if there are files with `analysis_status='error'` and `retry_count < 3`, retry them:

```bash
python3 -c "
import sqlite3, json
conn = sqlite3.connect('DB_PATH_HERE')
conn.execute('PRAGMA busy_timeout=10000')
# Reset retriable errors to pending
updated = conn.execute('''UPDATE file_metadata SET analysis_status = 'pending', retry_count = retry_count + 1
    WHERE analysis_status = 'error' AND retry_count < 3''').rowcount
conn.commit()
print(json.dumps({'retriable': updated}))
conn.close()
"
```

If `retriable > 0`, loop back to Step 1 to process them. Use a smaller batch size for retries (5 files max).

**Maximum 2 retry rounds** to avoid infinite loops. After retries, any remaining errors are permanently failed.

**Step 6: Finalize**

After all batches and retries are done:

```bash
python3 -c "
import sqlite3, json
conn = sqlite3.connect('DB_PATH_HERE')
conn.execute('PRAGMA busy_timeout=10000')

done = conn.execute(\"SELECT COUNT(*) FROM file_metadata WHERE analysis_status='done'\").fetchone()[0]
errors = conn.execute(\"SELECT COUNT(*) FROM file_metadata WHERE analysis_status='error'\").fetchone()[0]
total = conn.execute('SELECT COUNT(*) FROM file_metadata').fetchone()[0]
from_cache = conn.execute(\"SELECT COUNT(*) FROM file_metadata WHERE cache_valid=1 AND analysis_status='done'\").fetchone()[0]

# Any files still 'running' at this point were orphaned — mark as error
conn.execute('''UPDATE file_metadata SET analysis_status = 'error', error_message = 'agent never completed'
    WHERE analysis_status = 'running' ''')

conn.execute('''UPDATE phase_state SET status='completed', completed_at=datetime('now') WHERE phase='analysis' ''')
conn.execute('''UPDATE runs SET files_from_cache = ?, files_analyzed = ?, total_files = ?
    WHERE run_id = ?''', (from_cache, done, total, 'RUN_ID_HERE'))
conn.commit()

print(json.dumps({'done': done, 'errors': errors, 'total': total}))
conn.close()
"
```

Display final summary:
- `Analysis complete: {done}/{total} files analyzed successfully`
- If errors > 0: `({errors} files failed after retries — these will be excluded from duplicate detection)`

### Phase 6: Run Grouper

**CRITICAL CONTEXT MANAGEMENT**: The grouper agent is spawned with `run_in_background=true`. Do NOT read its output. Poll the database for results instead.

1. Mark the grouper phase as running:
```bash
python3 -c "
import sqlite3
conn = sqlite3.connect('DB_PATH_HERE')
conn.execute('PRAGMA busy_timeout=10000')
conn.execute('''UPDATE phase_state SET status='running', started_at=datetime('now') WHERE phase='grouper' ''')
conn.commit()
conn.close()
"
```

2. Spawn a single Task agent with `subagent_type="general-purpose"` and `run_in_background=true`.
   - Prompt: `Read and follow the instructions in ${CLAUDE_PLUGIN_ROOT}/agents/dedupe-grouper.md. The database path is: {DB_PATH}. Query the compact_summaries view, identify candidate duplicates, write them to the database, and return ONLY a status line.`
   - Replace `{DB_PATH}` with the actual database path.

3. **Do NOT read the agent's output.** Instead, poll the database to check for results:

```bash
python3 -c "
import sqlite3, json, time

db_path = 'DB_PATH_HERE'
max_wait = 300  # 5 minutes
poll_interval = 10
elapsed = 0

while elapsed < max_wait:
    time.sleep(poll_interval)
    elapsed += poll_interval

    conn = sqlite3.connect(db_path)
    conn.execute('PRAGMA busy_timeout=10000')

    # Check if grouper wrote any candidates
    intra = conn.execute(\"SELECT COUNT(*) FROM candidate_clusters WHERE scope='intra-group'\").fetchone()[0]
    cross = conn.execute(\"SELECT COUNT(*) FROM candidate_clusters WHERE scope='cross-group'\").fetchone()[0]
    total = intra + cross

    conn.close()

    # The grouper clears old candidates first, then writes new ones.
    # If we see any candidates, the grouper has finished (or is finishing).
    # Also check if enough time has passed for a minimum run.
    if total > 0 or elapsed >= 60:
        break

# Give a final grace period and re-check
if total == 0:
    time.sleep(15)
    conn = sqlite3.connect(db_path)
    intra = conn.execute(\"SELECT COUNT(*) FROM candidate_clusters WHERE scope='intra-group'\").fetchone()[0]
    cross = conn.execute(\"SELECT COUNT(*) FROM candidate_clusters WHERE scope='cross-group'\").fetchone()[0]
    total = intra + cross
    conn.close()

print(json.dumps({'intra': intra, 'cross': cross, 'total': total, 'elapsed': elapsed}))
"
```

4. Parse the counts from the JSON output.
   - If 0 total candidates after polling: either the grouper found nothing or it failed. Check if an error occurred, then skip Phase 7 and proceed to Phase 8 with "No duplicates found."
   - If the grouper appears to have failed, mark phase as error and retry once. If the retry also fails, skip to Phase 8 with partial results.

5. On success, mark phase complete:
```bash
python3 -c "
import sqlite3
conn = sqlite3.connect('DB_PATH_HERE')
conn.execute('PRAGMA busy_timeout=10000')
conn.execute('''UPDATE phase_state SET status='completed', completed_at=datetime('now') WHERE phase='grouper' ''')
conn.commit()
conn.close()
"
```

Display: `Grouper found {N} intra-group and {M} cross-group candidate clusters`

### Phase 7: Deep Comparison (Batched by Group)

**CRITICAL CONTEXT MANAGEMENT**: All deduplicator agents are spawned with `run_in_background=true`. Do NOT read their output. Poll the database for findings instead.

0. **Mark comparison phase as running:**
```bash
python3 -c "
import sqlite3
conn = sqlite3.connect('DB_PATH_HERE')
conn.execute('PRAGMA busy_timeout=10000')
conn.execute('''UPDATE phase_state SET status='running', started_at=datetime('now') WHERE phase='comparison' ''')
conn.commit()
conn.close()
"
```

1. **Query candidate clusters from the database** to determine how to partition work among deduplicator agents:

```bash
python3 -c "
import sqlite3, json

conn = sqlite3.connect('DB_PATH_HERE')
conn.row_factory = sqlite3.Row

# Get intra-group clusters grouped by group_name
intra = {}
for row in conn.execute(\"SELECT cluster_id, group_name FROM candidate_clusters WHERE scope='intra-group'\"):
    gn = row['group_name']
    if gn not in intra:
        intra[gn] = []
    intra[gn].append(row['cluster_id'])

# Get cross-group clusters
cross_ids = [row['cluster_id'] for row in conn.execute(
    \"SELECT cluster_id FROM candidate_clusters WHERE scope='cross-group'\")]

total_agents = len(intra) + (1 if cross_ids else 0)
print(json.dumps({'intra': intra, 'cross': cross_ids, 'total_agents': total_agents}))
conn.close()
"
```

2. **Build agent assignments**: Each intra-group set of clusters goes to one agent. Cross-group clusters can be batched together (up to ~10 per agent) or split across multiple agents.

3. **Spawn Deduplicator Agents** — all with `run_in_background=true`:
   - One agent per group with intra-group candidates
   - One or more agents for cross-group candidates
   - All agents run in parallel (single message with multiple Task calls)
   - `subagent_type="general-purpose"`, `run_in_background=true`
   - Prompt for each: `Read and follow the instructions in ${CLAUDE_PLUGIN_ROOT}/agents/dedupe-deduplicator.md. The database path is: {DB_PATH}. Your assigned cluster IDs are: {CLUSTER_IDS}. Query the database for your clusters, read source code, perform deep comparison, write findings to the database, and return ONLY a status line.`
   - Replace `{DB_PATH}` and `{CLUSTER_IDS}` with actual values.

4. **Do NOT read agent output.** Poll the database for findings instead:

```bash
python3 -c "
import sqlite3, json, time

db_path = 'DB_PATH_HERE'
total_agents = TOTAL_AGENTS_HERE  # number of agents spawned
total_clusters = TOTAL_CLUSTERS_HERE  # total number of candidate clusters

max_wait = 600  # 10 minutes max (deduplicators read source code, can be slow)
poll_interval = 15
elapsed = 0

# Track findings count to detect when agents finish writing
prev_findings = 0
stable_count = 0

while elapsed < max_wait:
    time.sleep(poll_interval)
    elapsed += poll_interval

    conn = sqlite3.connect(db_path)
    conn.execute('PRAGMA busy_timeout=10000')
    findings = conn.execute('SELECT COUNT(*) FROM findings').fetchone()[0]
    finding_files = conn.execute('SELECT COUNT(*) FROM finding_files').fetchone()[0]
    conn.close()

    if findings == prev_findings and elapsed >= 60:
        stable_count += 1
    else:
        stable_count = 0
        prev_findings = findings

    # If findings count has been stable for 3 consecutive polls (45s), agents are likely done
    if stable_count >= 3:
        break

print(json.dumps({'findings': findings, 'finding_files': finding_files, 'elapsed': elapsed}))
"
```

Replace `TOTAL_AGENTS_HERE` and `TOTAL_CLUSTERS_HERE` with actual values.

5. **Mark comparison phase as complete:**
```bash
python3 -c "
import sqlite3, json
conn = sqlite3.connect('DB_PATH_HERE')
conn.execute('PRAGMA busy_timeout=10000')
findings = conn.execute('SELECT COUNT(*) FROM findings').fetchone()[0]
conn.execute('''UPDATE phase_state SET status='completed', completed_at=datetime('now') WHERE phase='comparison' ''')
conn.commit()
print(json.dumps({'total_findings': findings}))
conn.close()
"
```

Display: `Deep comparison complete: {findings} findings written to database`

### Phase 8: Report Assembly and Presentation

0. **Mark report phase as running:**
```bash
python3 -c "
import sqlite3
conn = sqlite3.connect('DB_PATH_HERE')
conn.execute('PRAGMA busy_timeout=10000')
conn.execute('''UPDATE phase_state SET status='running', started_at=datetime('now') WHERE phase='report' ''')
conn.commit()
conn.close()
"
```

1. **Generate the report** using the dedicated Python script:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/dedupe-report.py 'DB_PATH_HERE' '.dedupe/reports/dedupe-TIMESTAMP.md'
```

The script queries the database and generates the full markdown report. It prints a JSON stats summary to stdout.

2. **Parse the stats JSON** from stdout. It includes: total_findings, high/medium/low counts, top_recommendations, report_path.

3. **Generate executive summary**: Using ONLY the stats JSON (which is small), write a 2-3 paragraph executive summary. Then insert it into the report file, replacing the `{{EXECUTIVE_SUMMARY}}` placeholder:

```bash
python3 -c "
import sys
report_path = 'REPORT_PATH_HERE'
summary = '''EXECUTIVE_SUMMARY_TEXT_HERE'''

with open(report_path, 'r') as f:
    content = f.read()
content = content.replace('{{EXECUTIVE_SUMMARY}}', summary)
with open(report_path, 'w') as f:
    f.write(content)
print('Report updated')
"
```

4. **Update run record and mark report phase complete:**
```bash
python3 -c "
import sqlite3
conn = sqlite3.connect('DB_PATH_HERE')
conn.execute('PRAGMA busy_timeout=10000')
conn.execute('''UPDATE runs SET total_findings = ?, report_path = ?, completed_at = datetime('now')
    WHERE run_id = ?''', (TOTAL_FINDINGS, 'REPORT_PATH_HERE', 'RUN_ID_HERE'))
conn.execute('''UPDATE phase_state SET status='completed', completed_at=datetime('now') WHERE phase='report' ''')
conn.commit()
conn.close()
"
```

5. **Display summary** to user:
   - Path to full report
   - Statistics (total findings, high/medium/low breakdown)
   - Top 5 recommendations (from the stats JSON)

## Error Handling

**General principles:**
- Every phase records its state in `phase_state`. If a run is interrupted, re-running `/dedupe` resumes from where it left off.
- File-level failures are tracked per-file in `file_metadata.analysis_status` with retry counting.
- Phase-level failures are tracked in `phase_state.status` with error messages.
- The pipeline is designed to **degrade gracefully**: if some files fail analysis, the rest still get grouped and compared. If the grouper fails, partial results are still reported.

**Specific error handling:**
- If project root detection fails: warn and use current directory
- If language auto-detection finds no code files: report error and stop
- If analyzer agent fails: status is recorded as `'error'` in `file_metadata`; agent is retried up to 3 times across runs; permanently failed files are excluded from grouping
- If analyzer agent is interrupted (status left as `'running'`): Phase 4 resets it to `'pending'` on the next run for automatic retry
- If grouper agent fails: mark `phase_state` as error, retry once immediately; if retry fails, skip to Phase 8 with "grouper failed" note
- If a deduplicator agent fails: count as failure, continue with other agents, include partial results
- If database is corrupted or cannot be opened: delete `.dedupe/dedupe.db` and recreate from scratch
- If the report script fails: fall back to displaying a simple summary from a DB stats query

## Implementation Notes

- **All agent results flow through SQLite, not through context.** This is the critical design principle.
- **All agents MUST be spawned with `run_in_background=true`.** The orchestrator must NEVER read agent output via TaskOutput or by reading the output_file. The Task tool returns the agent's entire conversation transcript (including full file contents read by the agent and full Python scripts it generated), which would consume massive context. Instead, the orchestrator polls the database for results.
- Agents receive the database path as a parameter and write results directly to it.
- Agents return ONLY a short status string (e.g., "OK: 7 units") — never JSON data. But this return value is only for the agent's own records; the orchestrator never sees it.
- The orchestrator (this command) never parses large JSON from agent outputs.
- The report is generated by a deterministic Python script, not by the orchestrator LLM.
- The database uses WAL mode and busy_timeout=10000ms for safe concurrent access from parallel agents.
- The database persists at `.dedupe/dedupe.db` and supports incremental re-analysis on subsequent runs.
- The `clean` command deletes the database file and reports directory.
- Generated files are analyzed but flagged, so the deduplicator won't recommend refactoring them.

### State Tracking and Resumability

- The `phase_state` table tracks each phase's status: `pending` → `running` → `completed` (or `error`).
- The `file_metadata.analysis_status` column tracks each file: `pending` → `running` → `done` (or `error`).
- The `file_metadata.retry_count` column tracks how many times a file has been retried (max 3).
- The `file_metadata.error_message` column stores the last error for failed files.
- **Phase 5 is fully DB-driven**: instead of iterating a list, it queries for `analysis_status='pending'` before each batch. This means interrupted runs automatically resume.
- Files left in `'running'` state (agent dispatched but never completed) are reset to `'pending'` by Phase 4 on the next run.
- Files that fail 3 times are permanently marked as `'error'` and excluded from grouping/comparison, but do not block the pipeline.

---

Now execute this process.
