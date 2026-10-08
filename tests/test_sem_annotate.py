import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sem_annotate as sa


class TestCommentPrefix(unittest.TestCase):
    def test_go_ts_js_use_slashes(self):
        for p in ("a/b/x.go", "x.ts", "x.tsx", "x.js", "x.jsx"):
            self.assertEqual(sa.comment_prefix(p), "//", p)

    def test_python_uses_hash(self):
        self.assertEqual(sa.comment_prefix("pkg/mod/x.py"), "#")

    def test_unsupported_returns_none(self):
        self.assertIsNone(sa.comment_prefix("README.md"))
        self.assertIsNone(sa.comment_prefix("x.rs"))


class TestParseMarkers(unittest.TestCase):
    SRC = (
        "package auth\n"                                  # 0
        "\n"                                              # 1
        "// SEM@b14a829: validate an oauth token (pure)\n"  # 2
        "func Validate() {}\n"                            # 3
        "    # SEM@deadbee: parse a config file\n"        # 4 (indented, hash)
        "x = 1\n"                                         # 5
    )

    def test_parse_returns_indexed_markers(self):
        got = sa.parse_markers(self.SRC)
        self.assertEqual(set(got), {2, 4})
        self.assertEqual(got[2]["sha"], "b14a829")
        self.assertEqual(got[2]["desc"], "validate an oauth token (pure)")
        self.assertEqual(got[4]["sha"], "deadbee")

    def test_find_marker_above_entity(self):
        lines = self.SRC.splitlines()
        m = sa.find_marker_above(lines, 4)   # entity 'func Validate' is on 1-based line 4
        self.assertIsNotNone(m)
        self.assertEqual(m["sha"], "b14a829")

    def test_find_marker_above_none_when_not_a_marker(self):
        lines = self.SRC.splitlines()
        # entity on 1-based line 2 ('// SEM...') -> line above is blank line 1 -> no marker
        self.assertIsNone(sa.find_marker_above(lines, 2))


class TestApplyMarker(unittest.TestCase):
    def test_build_marker_format(self):
        self.assertEqual(
            sa.build_marker("//", "  ", "abc1234", "validate a token"),
            "  // SEM@abc1234: validate a token",
        )

    def test_insert_when_absent(self):
        lines = ["package p", "", "func F() {}"]
        out = sa.apply_marker(lines, 3, "//", "abc1234", "compute a checksum")
        self.assertEqual(out[2], "// SEM@abc1234: compute a checksum")
        self.assertEqual(out[3], "func F() {}")
        self.assertEqual(len(out), 4)

    def test_replace_when_present(self):
        lines = ["package p", "// SEM@abc0000: stale desc", "func F() {}"]
        out = sa.apply_marker(lines, 3, "//", "def2222", "fresh desc")
        self.assertEqual(out, ["package p", "// SEM@def2222: fresh desc", "func F() {}"])

    def test_indentation_matches_entity(self):
        lines = ["class C:", "    def m(self): pass"]
        out = sa.apply_marker(lines, 2, "#", "abc1234", "handle a request")
        self.assertEqual(out[1], "    # SEM@abc1234: handle a request")
        self.assertEqual(out[2], "    def m(self): pass")


class TestClassify(unittest.TestCase):
    FULL = "b14a829fd98bc22eaf2939ee51854649b9620cb0"

    def test_missing_when_no_marker(self):
        self.assertEqual(sa.classify(None, self.FULL, False), "missing")

    def test_fresh_when_sha_prefix_matches_blame(self):
        self.assertEqual(sa.classify("b14a829", self.FULL, True), "fresh")

    def test_stale_when_blame_moved_and_logic_changed(self):
        self.assertEqual(sa.classify("deadbee", self.FULL, True), "stale")

    def test_fresh_when_blame_moved_but_cosmetic_only(self):
        self.assertEqual(sa.classify("deadbee", self.FULL, False), "fresh")


class TestClassifyRobust(unittest.TestCase):
    def test_uncommitted_none(self):
        self.assertEqual(sa.classify("b14a829", None, False), "uncommitted")

    def test_uncommitted_empty(self):
        self.assertEqual(sa.classify("b14a829", "", False), "uncommitted")

    def test_uncommitted_all_zeros(self):
        self.assertEqual(sa.classify("b14a829", "0000000000000000000000000000000000000000", False), "uncommitted")

    def test_missing_takes_precedence_over_uncommitted(self):
        self.assertEqual(sa.classify(None, None, False), "missing")

    def test_is_uncommitted_helper(self):
        self.assertTrue(sa._is_uncommitted(None))
        self.assertTrue(sa._is_uncommitted(""))
        self.assertTrue(sa._is_uncommitted("0000000"))
        self.assertFalse(sa._is_uncommitted("b14a829"))


class TestInvalidRevError(unittest.TestCase):
    def _patch(self, stderr):
        import subprocess as sp
        def fake_run(cmd, cwd=None, capture_output=True, text=True, check=True):
            raise sp.CalledProcessError(1, cmd, stderr=stderr)
        self._orig = sa.subprocess.run
        sa.subprocess.run = fake_run

    def tearDown(self):
        if hasattr(self, "_orig"):
            sa.subprocess.run = self._orig

    def test_revspec_not_found_raises_invalidrev(self):
        self._patch("Error: git error: revspec 'abc123' not found; class=Reference (4); code=NotFound (-3)")
        with self.assertRaises(sa.InvalidRevError):
            sa.run_sem(["diff", "abc123..HEAD", "--no-cosmetics", "--", "x.ts"])

    def test_invalidrev_is_semerror(self):
        self.assertTrue(issubclass(sa.InvalidRevError, sa.SemError))

    def test_other_failure_is_plain_semerror(self):
        self._patch("some unrelated failure")
        with self.assertRaises(sa.SemError):
            sa.run_sem(["entities", "."])
        # and NOT InvalidRevError
        with self.assertRaises(sa.SemError):
            try:
                sa.run_sem(["entities", "."])
            except sa.InvalidRevError:
                self.fail("should be plain SemError, not InvalidRevError")


class TestEntityLogicSha(unittest.TestCase):
    def setUp(self):
        self._orig_log = sa.sem_log_entity

    def tearDown(self):
        sa.sem_log_entity = self._orig_log

    def test_picks_newest_logic_ignoring_later_cosmetic(self):
        sa.sem_log_entity = lambda n, f, cwd=None: {"changes": [
            {"change_type": "added", "commit": {"sha": "aaa111"}},
            {"change_type": "modified (logic)", "commit": {"sha": "bbb222"}},
            {"change_type": "modified (cosmetic)", "commit": {"sha": "ccc333"}},
        ]}
        self.assertEqual(sa.entity_logic_sha("E", "f.py"), "bbb222")

    def test_added_only(self):
        sa.sem_log_entity = lambda n, f, cwd=None: {"changes": [
            {"change_type": "added", "commit": {"sha": "aaa111"}}]}
        self.assertEqual(sa.entity_logic_sha("E", "f.py"), "aaa111")

    def test_fallback_when_only_cosmetic(self):
        sa.sem_log_entity = lambda n, f, cwd=None: {"changes": [
            {"change_type": "modified (cosmetic)", "commit": {"sha": "ccc333"}}]}
        self.assertEqual(sa.entity_logic_sha("E", "f.py", fallback_sha="zzz999"), "zzz999")

    def test_fallback_when_empty(self):
        sa.sem_log_entity = lambda n, f, cwd=None: {"changes": []}
        self.assertEqual(sa.entity_logic_sha("E", "f.py", fallback_sha="zzz999"), "zzz999")
        self.assertEqual(sa.entity_logic_sha("E", "f.py"), "")

    def test_sem_log_entity_returns_empty_on_semerror(self):
        def boom(args, cwd=None):
            raise sa.SemError("nope")
        orig = sa.run_sem
        sa.run_sem = boom
        try:
            self.assertEqual(sa.sem_log_entity("E", "f.py"), {"changes": []})
        finally:
            sa.run_sem = orig


class TestScan(unittest.TestCase):
    def setUp(self):
        self.files = {}  # path -> source text

        def fake_read(path):
            return self.files[path]

        self._orig_read = sa._read_text
        self._orig_entities = sa.sem_entities
        self._orig_blame = sa.sem_blame
        self._orig_logic = sa.logic_changed_entities
        self._orig_logic_sha = sa.entity_logic_sha
        sa._read_text = fake_read

    def tearDown(self):
        sa._read_text = self._orig_read
        sa.sem_entities = self._orig_entities
        sa.sem_blame = self._orig_blame
        sa.logic_changed_entities = self._orig_logic
        sa.entity_logic_sha = self._orig_logic_sha

    def test_scan_flags_missing_and_stale_only(self):
        path = "auth/x.go"
        self.files[path] = (
            "package auth\n"
            "// SEM@aaaaaaa: validate a token\n"   # fresh: sha matches blame below
            "func Fresh() {}\n"
            "func Missing() {}\n"                   # no marker -> missing
        )
        entities = [
            {"name": "Fresh", "type": "function", "start_line": 3, "end_line": 3},
            {"name": "Missing", "type": "function", "start_line": 4, "end_line": 4},
        ]
        blame = [
            {"name": "Fresh", "lines": [3, 3], "commit": "aaaaaaa000111222333"},
            {"name": "Missing", "lines": [4, 4], "commit": "bbbbbbb000111222333"},
        ]
        sa.sem_entities = lambda paths, cwd=None: entities
        sa.sem_blame = lambda f, cwd=None: blame
        sa.logic_changed_entities = lambda base, f, cwd=None: set()
        sa.entity_logic_sha = lambda name, f, cwd=None, fallback_sha="": \
            {"Fresh": "aaaaaaa000111222333", "Missing": "bbbbbbb000111222333"}.get(name, "")

        work = sa.scan([path])
        names = {w["name"]: w["status"] for w in work}
        self.assertEqual(names, {"Missing": "missing"})
        self.assertEqual(work[0]["anchor_sha"], "bbbbbbb000111222333")


class TestScanInvalidSha(unittest.TestCase):
    def setUp(self):
        self.files = {"src/a.ts": "// SEM@deadbee: old\nfunction A() {}\n"}
        self._orig = (sa._read_text, sa.sem_entities, sa.sem_blame,
                      sa.entity_logic_sha, sa.logic_changed_entities)
        sa._read_text = lambda p: self.files[p]
        sa.sem_entities = lambda paths, cwd=None: [
            {"name": "A", "type": "function", "file": "src/a.ts", "start_line": 2, "end_line": 2}]
        sa.sem_blame = lambda f, cwd=None: [{"name": "A", "commit": "ffff999"}]
        sa.entity_logic_sha = lambda name, f, cwd=None, fallback_sha="": "ffff999"
        def boom(base, f, cwd=None):
            raise sa.InvalidRevError("revspec not found")
        sa.logic_changed_entities = boom

    def tearDown(self):
        (sa._read_text, sa.sem_entities, sa.sem_blame,
         sa.entity_logic_sha, sa.logic_changed_entities) = self._orig

    def test_bad_hash_reported_not_crashed(self):
        work = sa.scan(["src/a.ts"])
        self.assertEqual(len(work), 1)
        self.assertEqual(work[0]["status"], "invalid-sha")
        self.assertEqual(work[0]["bad_sha"], "deadbee")
        self.assertEqual(work[0]["name"], "A")


class TestScanInvalidShaPlainSemError(unittest.TestCase):
    """#12 regression: logic_changed_entities raises plain SemError (not InvalidRevError)
    for a bad marker SHA — scan must treat it as invalid-sha, not re-raise."""

    def setUp(self):
        self.files = {"src/a.ts": "// SEM@deadbee: old\nfunction A() {}\n"}
        self._orig = (sa._read_text, sa.sem_entities, sa.sem_blame,
                      sa.entity_logic_sha, sa.logic_changed_entities)
        sa._read_text = lambda p: self.files[p]
        sa.sem_entities = lambda paths, cwd=None: [
            {"name": "A", "type": "function", "file": "src/a.ts", "start_line": 2, "end_line": 2}]
        sa.sem_blame = lambda f, cwd=None: [{"name": "A", "commit": "ffff999"}]
        sa.entity_logic_sha = lambda name, f, cwd=None, fallback_sha="": "ffff999"
        def boom(base, f, cwd=None):
            raise sa.SemError(
                "sem diff failed: the git_object of id 'deadbee...' "
                "can not be successfully peeled into a commit"
            )
        sa.logic_changed_entities = boom

    def tearDown(self):
        (sa._read_text, sa.sem_entities, sa.sem_blame,
         sa.entity_logic_sha, sa.logic_changed_entities) = self._orig

    def test_plain_semerror_on_bad_sha_reported_not_crashed(self):
        work = sa.scan(["src/a.ts"])
        self.assertEqual(len(work), 1)
        self.assertEqual(work[0]["status"], "invalid-sha")
        self.assertEqual(work[0]["bad_sha"], "deadbee")
        self.assertEqual(work[0]["name"], "A")


class TestScanFreshAfterWrite(unittest.TestCase):
    """#13 regression: marker anchored to the entity's last logic change is fresh."""
    def setUp(self):
        # decl-line blame is commit A, but body last changed in commit B; marker carries B.
        self.files = {"src/g.ts": "// SEM@bbbbbbb: guard\nclass G {}\n"}
        self._orig = (sa._read_text, sa.sem_entities, sa.sem_blame,
                      sa.entity_logic_sha, sa.logic_changed_entities)
        sa._read_text = lambda p: self.files[p]
        sa.sem_entities = lambda paths, cwd=None: [
            {"name": "G", "type": "class", "file": "src/g.ts", "start_line": 2, "end_line": 2}]
        sa.sem_blame = lambda f, cwd=None: [{"name": "G", "commit": "aaaaaaa_declline"}]
        sa.entity_logic_sha = lambda name, f, cwd=None, fallback_sha="": "bbbbbbb000111"  # commit B
        # Must NOT be consulted: anchor already prefix-matches the marker, so classify
        # returns fresh without a logic diff. Make it explode to prove that.
        def must_not_call(base, f, cwd=None):
            raise AssertionError("logic_changed_entities should not be called when anchor matches marker")
        sa.logic_changed_entities = must_not_call

    def tearDown(self):
        (sa._read_text, sa.sem_entities, sa.sem_blame,
         sa.entity_logic_sha, sa.logic_changed_entities) = self._orig

    def test_marker_matching_anchor_is_fresh(self):
        # anchor 'bbbbbbb000111' startswith marker 'bbbbbbb' -> fresh, logic check skipped
        work = sa.scan(["src/g.ts"])
        names = {w["name"]: w["status"] for w in work}
        self.assertNotIn("G", names)  # fresh -> not surfaced


class TestWrite(unittest.TestCase):
    def test_write_stamps_worklist_sha_and_desc(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.go")
            with open(p, "w") as f:
                f.write("package p\nfunc A() {}\nfunc B() {}\n")
            worklist = [
                {"file": p, "name": "A", "start_line": 2, "anchor_sha": "aaa1111"},
                {"file": p, "name": "B", "start_line": 3, "anchor_sha": "bbb2222"},
            ]
            descriptions = [
                {"file": p, "name": "A", "start_line": 2, "desc": "build A"},
                {"file": p, "name": "B", "start_line": 3, "desc": "build B"},
            ]
            res = sa.write(descriptions, worklist)
            self.assertEqual(res["files_written"], 1)
            self.assertEqual(res["markers"], 2)
            self.assertEqual(res["skipped"], 0)
            out = Path(p).read_text().splitlines()
            self.assertEqual(out[1], "// SEM@aaa1111: build A")
            self.assertEqual(out[3], "// SEM@bbb2222: build B")

    def test_write_skips_unmatched_description(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.go")
            with open(p, "w") as f:
                f.write("package p\nfunc A() {}\n")
            res = sa.write(
                [{"file": p, "name": "A", "start_line": 2, "desc": "x"},
                 {"file": p, "name": "Ghost", "start_line": 99, "desc": "y"}],
                [{"file": p, "name": "A", "start_line": 2, "anchor_sha": "aaa1111"}])
            self.assertEqual(res["skipped"], 1)
            self.assertEqual(res["markers"], 1)

    def test_write_unsupported_file_type_counts_in_skipped(self):
        """FIX 3: a description for README.md (comment_prefix None) that matches the
        worklist key must be counted in skipped, not silently dropped."""
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            # README.md is an unsupported type (comment_prefix returns None)
            readme = os.path.join(d, "README.md")
            with open(readme, "w") as f:
                f.write("# Title\nSome section\n")
            worklist = [{"file": readme, "name": "Some section", "start_line": 2,
                         "anchor_sha": "aaa1111"}]
            descriptions = [{"file": readme, "name": "Some section", "start_line": 2,
                             "desc": "overview of the project"}]
            res = sa.write(descriptions, worklist)
            self.assertEqual(res["skipped"], 1, "unsupported file type must count in skipped")
            self.assertEqual(res["markers"], 0)
            self.assertEqual(res["files_written"], 0)
            # no file should be written/modified for README.md
            self.assertEqual(Path(readme).read_text(), "# Title\nSome section\n")

    def test_write_blank_anchor_falls_back_to_head(self):
        orig = sa.head_sha
        sa.head_sha = lambda cwd=None: "headfff"
        try:
            with tempfile.TemporaryDirectory() as d:
                p = os.path.join(d, "x.go")
                with open(p, "w") as f:
                    f.write("package p\nfunc A() {}\n")
                sa.write([{"file": p, "name": "A", "start_line": 2, "desc": "x"}],
                         [{"file": p, "name": "A", "start_line": 2, "anchor_sha": ""}])
                self.assertEqual(Path(p).read_text().splitlines()[1], "// SEM@headfff: x")
        finally:
            sa.head_sha = orig


REAL_DIFF_PAYLOAD = {
    "summary": {"added": 0, "deleted": 0, "modified": 1},
    "changes": [
        {
            "entityName": "classify",
            "changeType": "modified",
            "entityType": "function",
            "startLine": 10,
            "endLine": 20,
            "filePath": "dev/scripts/sem_annotate.py",
        },
        {
            "entityName": "some_added",
            "changeType": "added",
            "entityType": "function",
            "startLine": 30,
            "endLine": 40,
            "filePath": "dev/scripts/sem_annotate.py",
        },
    ],
    "binaryChanges": [],
}


class TestParseChangedEntities(unittest.TestCase):
    def test_returns_modified_and_added_entities(self):
        result = sa._parse_changed_entities(REAL_DIFF_PAYLOAD)
        self.assertEqual(result, {"classify", "some_added"})

    def test_added_entities_count_as_changed(self):
        """#39: an entity that is `added` since its anchor means the anchor predates the
        entity (marker hand-written at HEAD before the introducing commit existed). The
        anchor cannot vouch for the body, so this is a logic change, never fresh."""
        result = sa._parse_changed_entities(
            {"changes": [{"changeType": "added", "entityName": "foo"}]}
        )
        self.assertEqual(result, {"foo"})

    def test_other_change_types_are_excluded(self):
        result = sa._parse_changed_entities(
            {"changes": [{"changeType": "deleted", "entityName": "gone"},
                         {"changeType": "reordered", "entityName": "shuffled"},
                         {"changeType": "moved", "entityName": "relocated"}]}
        )
        self.assertEqual(result, set())

    def test_empty_payload_returns_empty_set(self):
        self.assertEqual(sa._parse_changed_entities({}), set())


class TestArgs(unittest.TestCase):
    def test_scan_subcommand(self):
        ns = sa.parse_args(["scan", "auth/", "-C", "/repo"])
        self.assertEqual(ns.cmd, "scan")
        self.assertEqual(ns.paths, ["auth/"])
        self.assertEqual(ns.cwd, "/repo")
        self.assertFalse(ns.rebuild)

    def test_update_is_scan_over_files(self):
        ns = sa.parse_args(["--update", "a.go", "b.go"])
        self.assertEqual(ns.cmd, "scan")
        self.assertEqual(ns.paths, ["a.go", "b.go"])

    def test_update_with_cwd(self):
        ns = sa.parse_args(["--update", "a.go", "-C", "/repo"])
        self.assertEqual(ns.cmd, "scan")
        self.assertEqual(ns.paths, ["a.go"])
        self.assertEqual(ns.cwd, "/repo")

    def test_update_with_rebuild(self):
        ns = sa.parse_args(["--update", "a.go", "--rebuild"])
        self.assertEqual(ns.cmd, "scan")
        self.assertEqual(ns.paths, ["a.go"])
        self.assertTrue(ns.rebuild)

    def test_write_subcommand_with_worklist(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.go")
            with open(p, "w") as f:
                f.write("package p\nfunc A() {}\n")
            wl = os.path.join(d, "wl.json")
            with open(wl, "w") as f:
                json.dump([{"file": "x.go", "name": "A", "start_line": 2, "anchor_sha": "aaa1111"}], f)
            stdin = io.StringIO(json.dumps([{"file": "x.go", "name": "A", "start_line": 2, "desc": "build A"}]))
            _orig = sys.stdin
            sys.stdin = stdin
            try:
                rc = sa.main(["write", "--worklist", wl, "-C", d])
            finally:
                sys.stdin = _orig
            self.assertEqual(rc, 0)
            self.assertEqual(Path(p).read_text().splitlines()[1], "// SEM@aaa1111: build A")


class TestScanScope(unittest.TestCase):
    def setUp(self):
        # No markers => both entities classify as "missing" (surfaced by scan).
        self.files = {"src/a.ts": "function A() {}\n",
                      "scripts/b.ts": "function B() {}\n"}
        self._orig = (sa._read_text, sa.sem_entities, sa.sem_blame,
                      sa.logic_changed_entities, sa.entity_logic_sha, sa.sem_scope.load_scope)
        sa._read_text = lambda p: self.files[p]
        sa.sem_entities = lambda paths, cwd=None: [
            {"name": "A", "type": "function", "file": "src/a.ts", "start_line": 1, "end_line": 1},
            {"name": "B", "type": "function", "file": "scripts/b.ts", "start_line": 1, "end_line": 1},
        ]
        sa.sem_blame = lambda f, cwd=None: [{"name": "A", "commit": "ccc"}, {"name": "B", "commit": "ddd"}]
        sa.logic_changed_entities = lambda base, f, cwd=None: set()
        sa.entity_logic_sha = lambda name, f, cwd=None, fallback_sha="": "ccc" if f.startswith("src/") else "ddd"

    def tearDown(self):
        (sa._read_text, sa.sem_entities, sa.sem_blame,
         sa.logic_changed_entities, sa.entity_logic_sha, sa.sem_scope.load_scope) = self._orig

    def test_scope_exclude_drops_entities(self):
        sa.sem_scope.load_scope = lambda cwd=None: {"include": ["src/", "scripts/"],
                                                    "exclude": ["scripts/"]}
        work = sa.scan(None)
        names = {w["name"] for w in work}
        self.assertIn("A", names)            # src/ kept (missing marker -> surfaced)
        self.assertNotIn("B", names)         # scripts/ excluded by scope

    def test_explicit_paths_ignore_scope(self):
        called = {"n": 0}
        def boom(cwd=None):
            called["n"] += 1
            return {"exclude": ["**/*"]}
        sa.sem_scope.load_scope = boom
        sa.scan(["src/a.ts"])
        self.assertEqual(called["n"], 0)     # explicit args => scope file never consulted


class TestDbSubcommand(unittest.TestCase):
    def test_db_status_dispatches(self):
        import sem_db
        orig = sem_db.status
        sem_db.status = lambda cwd=None: {"verdict": "up-to-date", "stored_sha": "x",
                                          "stored_count": "1", "current_sha": "x",
                                          "current_count": "1"}
        out = io.StringIO()
        _stdout = sys.stdout
        sys.stdout = out
        try:
            rc = sa.main(["db", "status", "-C", "/tmp"])
        finally:
            sys.stdout = _stdout
            sem_db.status = orig
        self.assertEqual(rc, 0)
        self.assertIn("up-to-date", out.getvalue())

    def test_db_update_no_files_is_auto(self):
        import sem_db
        called = {"auto": 0}
        orig = sem_db.auto_update
        sem_db.auto_update = lambda cwd=None: called.__setitem__("auto", 1) or {"mode": "auto", "files": 0, "entities": 0}
        try:
            rc = sa.main(["db", "update", "-C", "/tmp"])
        finally:
            sem_db.auto_update = orig
        self.assertEqual(rc, 0)
        self.assertEqual(called["auto"], 1)


class TestScanAnchorPredatesEntity(unittest.TestCase):
    """#39: the tmi DeduplicateGroups incident (#30). The marker was hand-written in the
    same commit that created the file, anchored at then-HEAD -- the parent of the
    introducing commit. `sem diff <anchor>..HEAD -- file` therefore reports the entity as
    `added` (correctly: relative to that base it is new) and, with only `modified`
    counted, every later body change was classified fresh. Reachability is irrelevant:
    this reproduces in linear history with a fully reachable anchor."""

    ADDED_PAYLOAD = json.dumps({
        "summary": {"fileCount": 1, "added": 1, "modified": 0},
        "changes": [{"entityId": "a.go::function::F", "changeType": "added",
                     "entityType": "function", "entityName": "F", "filePath": "a.go"}],
        "binaryChanges": []})

    def setUp(self):
        ent = {"name": "F", "type": "function", "file": "a.go",
               "start_line": 2, "end_line": 4}
        self.enterContext(mock.patch.object(sa, "sem_entities", return_value=[ent]))
        self.enterContext(mock.patch.object(sa, "sem_blame", return_value=[]))
        self.enterContext(mock.patch.object(sa, "entity_logic_sha", return_value="a1b2c3d4e5"))
        self.enterContext(mock.patch.object(
            sa, "_read_text", return_value="// SEM@deadbee: does a thing\nfunc F() {}\n"))

    def test_added_since_anchor_is_stale(self):
        with mock.patch.object(sa, "run_sem", return_value=self.ADDED_PAYLOAD) as run:
            work = sa.scan(["a.go"])
        self.assertEqual([w["status"] for w in work], ["stale"])
        self.assertEqual(work[0]["anchor_sha"], "a1b2c3d4e5")
        # the comparison is a plain sem diff against the anchor -- no reachability gate
        self.assertEqual(run.call_args[0][0][:2], ["diff", "deadbee..HEAD"])

    def test_no_change_since_anchor_is_fresh(self):
        empty = json.dumps({"summary": {}, "changes": [], "binaryChanges": []})
        with mock.patch.object(sa, "run_sem", return_value=empty):
            work = sa.scan(["a.go"])
        self.assertEqual(work, [])

    def test_no_reachability_check(self):
        """sem diff handles orphaned-but-present bases correctly (Ataraxy-Labs/sem#479,
        cannot-reproduce), so the v2.4.3 `orphaned` status is gone: in a squash-merge
        repo it re-described every branch-written marker after every release."""
        self.assertFalse(hasattr(sa, "sha_reachable"))


if __name__ == "__main__":
    unittest.main()
