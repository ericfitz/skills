"""Tests for catslib.runner.prune_run_dbs (issue #587: per-run DB retention).

SAFETY: every test here operates against a fresh tempfile.TemporaryDirectory —
never against a repo's real results_dir. Do not change that.
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cats" / "scripts"))

from catslib import runner as run


def _mk_db(root: Path, run_id: str) -> Path:
    p = root / f"cats-results-{run_id}.db"
    p.write_text("x")
    return p


# Five run_ids, oldest to newest; the filename format sorts lexicographically
# in the same order as chronologically, matching run_id_for's own output.
RUN_IDS = [
    "20260101T000000Z",
    "20260102T000000Z",
    "20260103T000000Z",
    "20260104T000000Z",
    "20260105T000000Z",
]


class TestPruneRunDbs(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def _seed(self, ids=RUN_IDS):
        return [_mk_db(self.root, i) for i in ids]

    def test_keeps_n_newest_by_run_id(self):
        self._seed()
        deleted = run.prune_run_dbs(self.root, keep=2)

        remaining = {p.name for p in self.root.glob("cats-results-*.db")}
        self.assertEqual(
            remaining,
            {f"cats-results-{i}.db" for i in RUN_IDS[-2:]},
        )
        self.assertEqual(
            {p.name for p in deleted},
            {f"cats-results-{i}.db" for i in RUN_IDS[:3]},
        )

    def test_latest_db_target_protected_even_when_older_than_cutoff(self):
        self._seed()
        oldest = f"cats-results-{RUN_IDS[0]}.db"
        (self.root / "latest.db").symlink_to(oldest)

        deleted = run.prune_run_dbs(self.root, keep=2)

        self.assertNotIn(oldest, {p.name for p in deleted})
        self.assertTrue((self.root / oldest).exists())
        # the two naturally-newest are still kept alongside the protected one
        remaining = {p.name for p in self.root.glob("cats-results-*.db")}
        self.assertEqual(
            remaining,
            {oldest, f"cats-results-{RUN_IDS[-1]}.db", f"cats-results-{RUN_IDS[-2]}.db"},
        )

    def test_dangling_latest_db_protects_the_name_and_does_not_raise(self):
        self._seed()
        target = f"cats-results-{RUN_IDS[0]}.db"
        (self.root / "latest.db").symlink_to(target)
        (self.root / target).unlink()  # latest.db now dangles

        try:
            deleted = run.prune_run_dbs(self.root, keep=2)
        except OSError:
            self.fail("prune_run_dbs raised on a dangling latest.db symlink")

        # the dangling target never existed as a candidate, so pruning of the
        # remaining four proceeds normally (keep 2, delete 2) with no crash
        remaining = {p.name for p in self.root.glob("cats-results-*.db")}
        self.assertEqual(len(remaining), 2)
        self.assertEqual(len(deleted), 2)

    def test_non_matching_filenames_are_never_candidates(self):
        # The report file here belongs to RUN_IDS[2], the run that survives
        # `keep=1` below. Since #600, a report whose run_id IS pruned is
        # deleted with it — see TestPruneReportCompanions — so this case has
        # to name a surviving run to still be testing what it says it tests.
        untouched = [
            "cats-test-data.yml",
            "report-20260103T000000Z.html",
            "cats-results-junk.db",
        ]
        for name in untouched:
            (self.root / name).write_text("x")
        (self.root / "latest.db").write_text("not actually a symlink")
        self._seed(RUN_IDS[:3])

        run.prune_run_dbs(self.root, keep=1)

        remaining = {p.name for p in self.root.iterdir()}
        for name in [*untouched, "latest.db"]:
            self.assertIn(name, remaining)

    def test_keep_zero_disables_pruning(self):
        self._seed()
        deleted = run.prune_run_dbs(self.root, keep=0)
        self.assertEqual(deleted, [])
        self.assertEqual(len(list(self.root.glob("cats-results-*.db"))), len(RUN_IDS))

    def test_dry_run_deletes_nothing(self):
        self._seed()
        would_delete = run.prune_run_dbs(self.root, keep=2, dry_run=True)

        self.assertEqual(len(would_delete), 3)
        for p in would_delete:
            self.assertTrue(p.exists())
        self.assertEqual(len(list(self.root.glob("cats-results-*.db"))), len(RUN_IDS))

    def test_unlink_oserror_is_logged_and_pruning_continues(self):
        self._seed(RUN_IDS[:4])  # keep=1 -> 3 candidates for deletion
        flaky_name = f"cats-results-{RUN_IDS[0]}.db"
        real_unlink = Path.unlink

        def flaky_unlink(self, missing_ok=False):
            if self.name == flaky_name:
                raise OSError("simulated unlink failure")
            return real_unlink(self, missing_ok=missing_ok)

        with mock.patch.object(Path, "unlink", flaky_unlink), \
                self.assertLogs(run.__name__, level="WARNING") as ctx:
            deleted = run.prune_run_dbs(self.root, keep=1)

        self.assertNotIn(flaky_name, {p.name for p in deleted})
        self.assertTrue((self.root / flaky_name).exists())  # failed delete leaves it in place
        # the other two candidates still get removed despite one failure
        self.assertEqual(len(deleted), 2)
        self.assertTrue(any(flaky_name in m for m in ctx.output))

    def test_protect_names_survive_outside_the_keep_window(self):
        self._seed()
        protected = f"cats-results-{RUN_IDS[0]}.db"  # oldest; would normally be pruned

        deleted = run.prune_run_dbs(self.root, keep=1, protect=frozenset({protected}))

        self.assertNotIn(protected, {p.name for p in deleted})
        self.assertTrue((self.root / protected).exists())

    def test_sidecar_wal_shm_files_removed_alongside_db(self):
        [oldest, *_rest] = self._seed(RUN_IDS[:2])
        wal = oldest.with_name(oldest.name + "-wal")
        shm = oldest.with_name(oldest.name + "-shm")
        wal.write_text("w")
        shm.write_text("s")

        run.prune_run_dbs(self.root, keep=1)

        self.assertFalse(oldest.exists())
        self.assertFalse(wal.exists())
        self.assertFalse(shm.exists())


if __name__ == "__main__":
    unittest.main()


class TestPruneReportCompanions(unittest.TestCase):
    """Issue #600: a pruned run must take its raw report artifacts with it,
    and a surviving run must keep its own."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def _mk_report(self, run_id: str):
        d = self.root / f"report-{run_id}"
        d.mkdir()
        (d / "Test1.json").write_text("{}")
        (self.root / f"report-{run_id}.html").write_text("<html>")
        return d

    def test_companions_of_pruned_runs_are_removed(self):
        for i in RUN_IDS:
            _mk_db(self.root, i)
            self._mk_report(i)

        run.prune_run_dbs(self.root, keep=2)

        for i in RUN_IDS[:3]:
            self.assertFalse((self.root / f"report-{i}").exists(), i)
            self.assertFalse((self.root / f"report-{i}.html").exists(), i)
        for i in RUN_IDS[-2:]:
            self.assertTrue((self.root / f"report-{i}").is_dir(), i)
            self.assertTrue((self.root / f"report-{i}.html").is_file(), i)

    def test_dry_run_leaves_companions_alone(self):
        for i in RUN_IDS:
            _mk_db(self.root, i)
            self._mk_report(i)

        run.prune_run_dbs(self.root, keep=2, dry_run=True)

        for i in RUN_IDS:
            self.assertTrue((self.root / f"report-{i}").is_dir(), i)

    def test_suffixed_sibling_directory_is_not_swept_up(self):
        # A `report-<run_id>*` glob would delete a deliberately-kept annotated
        # copy; only the exact name and `report-<run_id>.<ext>` files may go.
        _mk_db(self.root, RUN_IDS[0])
        _mk_db(self.root, RUN_IDS[-1])
        self._mk_report(RUN_IDS[0])
        keep_me = self.root / f"report-{RUN_IDS[0]}-annotated"
        keep_me.mkdir()

        run.prune_run_dbs(self.root, keep=1)

        self.assertFalse((self.root / f"report-{RUN_IDS[0]}").exists())
        self.assertTrue(keep_me.is_dir())

    def test_missing_companions_are_not_an_error(self):
        self._seeded = [_mk_db(self.root, i) for i in RUN_IDS]
        deleted = run.prune_run_dbs(self.root, keep=2)
        self.assertEqual(len(deleted), 3)

    def test_failed_db_unlink_leaves_its_companions_alone(self):
        # The companion is the evidence for a run; it must not be destroyed
        # when the database it belongs to survived the prune by accident.
        for i in RUN_IDS:
            _mk_db(self.root, i)
            self._mk_report(i)

        real_unlink = Path.unlink
        doomed = f"cats-results-{RUN_IDS[0]}.db"

        def flaky(self, *a, **kw):
            if self.name == doomed:
                raise OSError("EPERM")
            return real_unlink(self, *a, **kw)

        with mock.patch.object(Path, "unlink", flaky):
            run.prune_run_dbs(self.root, keep=2)

        self.assertTrue((self.root / f"report-{RUN_IDS[0]}").is_dir())
        self.assertFalse((self.root / f"report-{RUN_IDS[1]}").exists())
