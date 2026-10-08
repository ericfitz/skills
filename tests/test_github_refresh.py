# tests/test_github_refresh.py
import json
import os
import shutil
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "github" / "scripts"))

import refresh_gh_projects as rgp

REPO = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO / "github" / "scripts" / "refresh_gh_projects.py"

FIELD_LIST_JSON = json.dumps({
    "fields": [
        {
            "id": "F1",
            "name": "Status",
            "type": "ProjectV2SingleSelectField",
            "options": [
                {"id": "O1", "name": "Todo"},
                {"id": "O2", "name": "Done"},
            ],
        },
    ],
})
MILESTONES_JSON = json.dumps([{"title": "v1", "number": 1, "node_id": "MDM1"}])
LABELS_JSON = json.dumps([{"name": "bug"}, {"name": "enhancement"}])
ISSUE_TYPES_JSON = json.dumps([{"name": "Bug"}, {"name": "Feature"}])

OLD_ENTRY = {
    "cached_at": "2020-01-01T00:00:00+00:00",
    "project": {"number": 3, "owner": "acme", "id": "PVT_1", "title": "Roadmap"},
    "fields": {"Status": {"id": "F0", "type": "single_select",
                          "options": [{"name": "Old", "id": "O0"}]}},
    "milestones": [{"title": "v0", "number": 0, "id": "MDM0"}],
    "labels": ["stale"],
    "issue_types": ["Chore"],
}


def _init_git_repo(root: Path, remote: str = "https://github.com/acme/proj.git") -> None:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=str(root), check=True)
    subprocess.run(["git", "remote", "add", "origin", remote], cwd=str(root), check=True)


def _write_cache(root: Path, entries: dict) -> Path:
    local = root / ".local"
    local.mkdir(parents=True, exist_ok=True)
    path = local / "gh-projects.json"
    path.write_text(json.dumps(entries, indent=2) + "\n")
    return path


def _with_fake_gh(bindir: Path, dispatch_script: str) -> Path:
    """Create a fake `gh` executable on a directory, for PATH injection
    (mirrors tests/test_cats_runner.py _with_fake_cats)."""
    bindir.mkdir(parents=True, exist_ok=True)
    script = bindir / "gh"
    script.write_text("#!/bin/sh\n" + dispatch_script)
    script.chmod(0o755)
    return script


_HAPPY_GH = f"""
case "$1" in
  project)
    cat <<'EOF'
{FIELD_LIST_JSON}
EOF
    ;;
  api)
    case "$2" in
      *milestones*) cat <<'EOF'
{MILESTONES_JSON}
EOF
      ;;
      *labels*) cat <<'EOF'
{LABELS_JSON}
EOF
      ;;
      *issue-types*) cat <<'EOF'
{ISSUE_TYPES_JSON}
EOF
      ;;
    esac
    ;;
esac
"""


class TestNoRepo(unittest.TestCase):
    def test_outside_git_repo_exits_zero_and_touches_nothing(self):
        with rgp.tempfile.TemporaryDirectory() as d:
            root = Path(d) / "not-a-repo"
            root.mkdir()
            rc = rgp.main(["--cwd", str(root)])
            self.assertEqual(rc, 0)
            self.assertFalse((root / ".local").exists())


class TestRepoNoCache(unittest.TestCase):
    def test_repo_without_cache_exits_zero_and_does_not_create_local(self):
        with rgp.tempfile.TemporaryDirectory() as d:
            root = Path(d) / "repo"
            _init_git_repo(root)
            rc = rgp.main(["--cwd", str(root)])
            self.assertEqual(rc, 0)
            self.assertFalse((root / ".local").exists())


class TestHappyPath(unittest.TestCase):
    def test_entry_rewritten_in_provisioning_shape(self):
        with rgp.tempfile.TemporaryDirectory() as d:
            root = Path(d) / "repo"
            _init_git_repo(root)
            cache_path = _write_cache(root, {"proj": OLD_ENTRY})
            with rgp.tempfile.TemporaryDirectory() as bindir:
                _with_fake_gh(Path(bindir), _HAPPY_GH)
                with mock.patch.dict(os.environ, {"PATH": f"{bindir}:{os.environ['PATH']}"}):
                    rc = rgp.main(["--cwd", str(root)])
            self.assertEqual(rc, 0)
            new_cache = json.loads(cache_path.read_text())
            entry = new_cache["proj"]
            # project identity is preserved verbatim
            self.assertEqual(entry["project"], OLD_ENTRY["project"])
            # fields/milestones/labels/issue_types reflect the fake gh's fresh data
            self.assertEqual(entry["fields"], {
                "Status": {"id": "F1", "type": "single_select",
                           "options": [{"name": "Todo", "id": "O1"}, {"name": "Done", "id": "O2"}]},
            })
            self.assertEqual(entry["milestones"], [{"title": "v1", "number": 1, "id": "MDM1"}])
            self.assertEqual(entry["labels"], ["bug", "enhancement"])
            self.assertEqual(entry["issue_types"], ["Bug", "Feature"])
            self.assertNotEqual(entry["cached_at"], OLD_ENTRY["cached_at"])


class TestPerEntryFailurePreservesEntry(unittest.TestCase):
    def test_failing_entry_untouched_while_others_refresh(self):
        bad_entry = dict(OLD_ENTRY, project={"number": 999, "owner": "acme",
                                             "id": "PVT_BAD", "title": "Broken"})
        script = f"""
case "$1" in
  project)
    case "$3" in
      999) echo "boom" >&2; exit 1 ;;
      *) cat <<'EOF'
{FIELD_LIST_JSON}
EOF
      ;;
    esac
    ;;
  api)
    case "$2" in
      *milestones*) cat <<'EOF'
{MILESTONES_JSON}
EOF
      ;;
      *labels*) cat <<'EOF'
{LABELS_JSON}
EOF
      ;;
      *issue-types*) cat <<'EOF'
{ISSUE_TYPES_JSON}
EOF
      ;;
    esac
    ;;
esac
"""
        with rgp.tempfile.TemporaryDirectory() as d:
            root = Path(d) / "repo"
            _init_git_repo(root)
            cache_path = _write_cache(root, {"good": OLD_ENTRY, "bad": bad_entry})
            with rgp.tempfile.TemporaryDirectory() as bindir:
                _with_fake_gh(Path(bindir), script)
                with mock.patch.dict(os.environ, {"PATH": f"{bindir}:{os.environ['PATH']}"}):
                    rc = rgp.main(["--cwd", str(root)])
            self.assertEqual(rc, 0)
            new_cache = json.loads(cache_path.read_text())
            self.assertEqual(new_cache["bad"], bad_entry)
            self.assertNotEqual(new_cache["good"]["cached_at"], OLD_ENTRY["cached_at"])
            self.assertEqual(new_cache["good"]["labels"], ["bug", "enhancement"])


class TestMissingGh(unittest.TestCase):
    def test_gh_not_found_leaves_file_untouched(self):
        with rgp.tempfile.TemporaryDirectory() as d:
            root = Path(d) / "repo"
            _init_git_repo(root)
            cache_path = _write_cache(root, {"proj": OLD_ENTRY})
            before = cache_path.read_bytes()
            before_mtime = cache_path.stat().st_mtime

            real_run = subprocess.run

            def fake_run(argv, *a, **kw):
                if argv[0] == "gh":
                    raise FileNotFoundError("gh not found")
                return real_run(argv, *a, **kw)

            with mock.patch.object(rgp.subprocess, "run", side_effect=fake_run):
                rc = rgp.main(["--cwd", str(root)])
            self.assertEqual(rc, 0)
            self.assertEqual(cache_path.read_bytes(), before)
            self.assertEqual(cache_path.stat().st_mtime, before_mtime)


class TestTimeout(unittest.TestCase):
    def test_sleeping_gh_times_out_and_still_exits_zero(self):
        # The fake gh sleeps 8s; GH_TIMEOUT is 5s. If subprocess.run were
        # called without a timeout= (or with a longer one), this test would
        # take ~8s+ instead of ~5s -- the wall-clock bound below is what
        # actually pins the 5s-per-call contract, not just the outcome.
        script = "sleep 8\n"
        with rgp.tempfile.TemporaryDirectory() as d:
            root = Path(d) / "repo"
            _init_git_repo(root)
            cache_path = _write_cache(root, {"proj": OLD_ENTRY})
            with rgp.tempfile.TemporaryDirectory() as bindir:
                _with_fake_gh(Path(bindir), script)
                with mock.patch.dict(os.environ, {"PATH": f"{bindir}:{os.environ['PATH']}"}):
                    started = time.monotonic()
                    rc = rgp.main(["--cwd", str(root)])
                    elapsed = time.monotonic() - started
            self.assertEqual(rc, 0)
            self.assertLess(elapsed, 7.0,
                            "took longer than the 5s per-call timeout should allow; "
                            "the sleeping fake gh likely ran to completion (8s)")
            new_cache = json.loads(cache_path.read_text())
            # the entry could not be refreshed inside the per-call timeout, so
            # it must be preserved exactly as it was
            self.assertEqual(new_cache["proj"], OLD_ENTRY)


class TestSoftBudget(unittest.TestCase):
    def test_budget_exceeded_preserves_remaining_entries_untouched(self):
        # Pin the over_budget branch deterministically: rather than racing
        # real wall-clock time against a near-zero SOFT_BUDGET_SECONDS
        # (flaky -- entry "a"'s own gh calls take a variable few ms), drive
        # time.monotonic() with a fixed sequence. The loop calls it once for
        # `start`, then once per entry's budget check (short-circuited only
        # once over_budget is already True) -- three calls for two entries:
        # elapsed=0.0 for entry "a" (under budget, gets refreshed for real),
        # elapsed=999.0 for entry "b" (over budget, preserved untouched).
        entry_a = dict(OLD_ENTRY, project={"number": 1, "owner": "acme",
                                           "id": "PVT_A", "title": "A"})
        entry_b = dict(OLD_ENTRY, project={"number": 2, "owner": "acme",
                                           "id": "PVT_B", "title": "B"})
        with rgp.tempfile.TemporaryDirectory() as d:
            root = Path(d) / "repo"
            _init_git_repo(root)
            cache_path = _write_cache(root, {"a": entry_a, "b": entry_b})
            with rgp.tempfile.TemporaryDirectory() as bindir:
                _with_fake_gh(Path(bindir), _HAPPY_GH)
                with mock.patch.dict(os.environ, {"PATH": f"{bindir}:{os.environ['PATH']}"}), \
                        mock.patch.object(rgp, "SOFT_BUDGET_SECONDS", 0.0), \
                        mock.patch.object(rgp.time, "monotonic",
                                          side_effect=[0.0, 0.0, 999.0]):
                    rc = rgp.main(["--cwd", str(root)])
            self.assertEqual(rc, 0)
            new_cache = json.loads(cache_path.read_text())
            self.assertNotEqual(new_cache["a"], entry_a)  # refreshed
            self.assertEqual(new_cache["b"], entry_b)      # preserved verbatim


class TestReposJsonUntouched(unittest.TestCase):
    def test_repos_json_never_read_or_written(self):
        with rgp.tempfile.TemporaryDirectory() as d:
            root = Path(d) / "repo"
            _init_git_repo(root)
            _write_cache(root, {"proj": OLD_ENTRY})
            repos_path = root / ".local" / "repos.json"
            repos_content = json.dumps({"proj": {"path": str(root),
                                                  "github": {"owner": "acme", "repo": "proj"}}})
            repos_path.write_text(repos_content)
            with rgp.tempfile.TemporaryDirectory() as bindir:
                _with_fake_gh(Path(bindir), _HAPPY_GH)
                with mock.patch.dict(os.environ, {"PATH": f"{bindir}:{os.environ['PATH']}"}):
                    rc = rgp.main(["--cwd", str(root)])
            self.assertEqual(rc, 0)
            self.assertEqual(repos_path.read_text(), repos_content)


class TestUnchangedContentPreservesMtime(unittest.TestCase):
    def test_no_rewrite_when_content_matches(self):
        # Construct an old entry whose fields/milestones/labels/issue_types
        # already equal what the fake gh will return, so a refresh produces
        # identical content (modulo cached_at) and must not rewrite the file.
        matching_entry = {
            "cached_at": "2020-01-01T00:00:00+00:00",
            "project": {"number": 3, "owner": "acme", "id": "PVT_1", "title": "Roadmap"},
            "fields": {
                "Status": {"id": "F1", "type": "single_select",
                           "options": [{"name": "Todo", "id": "O1"}, {"name": "Done", "id": "O2"}]},
            },
            "milestones": [{"title": "v1", "number": 1, "id": "MDM1"}],
            "labels": ["bug", "enhancement"],
            "issue_types": ["Bug", "Feature"],
        }
        with rgp.tempfile.TemporaryDirectory() as d:
            root = Path(d) / "repo"
            _init_git_repo(root)
            cache_path = _write_cache(root, {"proj": matching_entry})
            before_mtime = cache_path.stat().st_mtime
            before_bytes = cache_path.read_bytes()
            with rgp.tempfile.TemporaryDirectory() as bindir:
                _with_fake_gh(Path(bindir), _HAPPY_GH)
                with mock.patch.dict(os.environ, {"PATH": f"{bindir}:{os.environ['PATH']}"}):
                    rc = rgp.main(["--cwd", str(root)])
            self.assertEqual(rc, 0)
            self.assertEqual(cache_path.stat().st_mtime, before_mtime)
            self.assertEqual(cache_path.read_bytes(), before_bytes)


class TestUnparseableCacheLeftAlone(unittest.TestCase):
    def test_unparseable_json_is_not_touched(self):
        with rgp.tempfile.TemporaryDirectory() as d:
            root = Path(d) / "repo"
            _init_git_repo(root)
            local = root / ".local"
            local.mkdir()
            cache_path = local / "gh-projects.json"
            cache_path.write_text("{not valid json")
            rc = rgp.main(["--cwd", str(root)])
            self.assertEqual(rc, 0)
            self.assertEqual(cache_path.read_text(), "{not valid json")


class TestVerbose(unittest.TestCase):
    def test_verbose_does_not_change_exit_code(self):
        with rgp.tempfile.TemporaryDirectory() as d:
            root = Path(d) / "not-a-repo"
            root.mkdir()
            rc = rgp.main(["--verbose", "--cwd", str(root)])
            self.assertEqual(rc, 0)


class TestProcessLevelSmoke(unittest.TestCase):
    """The rest of this suite calls rgp.main() in-process, which never
    exercises the module's own import line -- a >=3.10-only construct in a
    module-level import (e.g. `from datetime import UTC`) still passes every
    in-process test but crashes with exit 1 at interpreter startup under an
    older `python3`. These run the actual script as a subprocess under real
    interpreters to pin "stdlib-only, works under bare python3"."""

    def _assert_clean_exit(self, python_exe: str) -> None:
        with rgp.tempfile.TemporaryDirectory() as d:
            root = Path(d) / "not-a-repo"
            root.mkdir()
            result = subprocess.run(
                [python_exe, str(SCRIPT_PATH), "--cwd", str(root)],
                capture_output=True, text=True, timeout=30,
            )
        self.assertEqual(result.returncode, 0,
                         f"{python_exe}: stderr={result.stderr!r}")

    def test_plain_python3_exits_zero(self):
        python3 = shutil.which("python3")
        if not python3:
            self.skipTest("no python3 on PATH")
        self._assert_clean_exit(python3)

    def test_system_usr_bin_python3_exits_zero_if_present(self):
        # The real, non-hypothetical case a SessionStart hook runs under on
        # macOS: /usr/bin/python3 is whatever Apple shipped (3.9.6 as of
        # this writing), independent of any project venv or uv-managed
        # interpreter the rest of this suite runs under.
        system_python3 = "/usr/bin/python3"
        if not Path(system_python3).exists():
            self.skipTest("/usr/bin/python3 not present on this machine")
        self._assert_clean_exit(system_python3)


if __name__ == "__main__":
    unittest.main()
