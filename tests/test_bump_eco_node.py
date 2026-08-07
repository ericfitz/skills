import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from bumplib.ecosystems import node

BASE = Path(__file__).resolve().parents[1]
FIX = BASE / "tests" / "fixtures" / "bump"


def _write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj))


class TestNode(unittest.TestCase):
    def test_parse_pnpm_outdated(self):
        recs = {r.name: r for r in node.parse_outdated((FIX / "pnpm_outdated.json").read_text(), "pnpm")}
        self.assertEqual(recs["eslint"].current, "9.38.0")
        self.assertEqual(recs["eslint"].latest, "9.39.2")
        self.assertEqual(recs["eslint"].bump, "minor")

    def test_parse_audit(self):
        advs = node.parse_audit((FIX / "npm_audit.json").read_text(), "npm")
        self.assertTrue(any(a.package == "qs" for a in advs))

    def test_parse_audit_pnpm(self):
        advs = node.parse_audit((FIX / "pnpm_audit.json").read_text(), "pnpm")
        self.assertEqual(len(advs), 1)
        adv = advs[0]
        self.assertEqual(adv.package, "qs")
        self.assertEqual(adv.severity, "HIGH")
        self.assertEqual(adv.fixed, "6.14.2")
        self.assertEqual(adv.ids, ["CVE-2022-24999"])

    def test_audit_missing_binary(self):
        """Regression test: audit verb should return [] when binary is missing."""
        with mock.patch("bumplib.ecosystems.node.shutil.which", return_value=None):
            result = node.handle("audit", [])
            self.assertEqual(result, [])

    def test_outdated_missing_binary(self):
        """Regression test: outdated verb should return [] when binary is missing."""
        with mock.patch("bumplib.ecosystems.node.shutil.which", return_value=None):
            result = node.handle("outdated", [])
            self.assertEqual(result, [])


class TestParseOutdatedShapes(unittest.TestCase):
    """`npm outdated --json` maps a name to a dict OR a list of per-dependent entries."""

    def setUp(self):
        self.text = (FIX / "npm_outdated_workspaces.json").read_text()

    def test_list_valued_entry_does_not_raise(self):
        """Regression: the list shape used to raise AttributeError: 'list' object has no
        attribute 'get'."""
        recs = {r.name: r for r in node.parse_outdated(self.text, "npm")}
        self.assertEqual(recs["js-yaml"].current, "4.3.0")
        self.assertEqual(recs["js-yaml"].latest, "5.2.3")
        self.assertEqual(recs["js-yaml"].bump, "major")

    def test_dict_and_list_shapes_both_parsed(self):
        names = {r.name for r in node.parse_outdated(self.text, "npm")}
        self.assertEqual(names, {"eslint", "js-yaml", "three", "undici"})

    def test_duplicate_dependents_collapse_to_one_record(self):
        """js-yaml is listed twice (core + server) at the same versions -> one record."""
        recs = [r for r in node.parse_outdated(self.text, "npm") if r.name == "js-yaml"]
        self.assertEqual(len(recs), 1)

    def test_non_dict_entries_skipped(self):
        recs = node.parse_outdated('{"a": [null, "junk"], "b": {"current": "1.0.0", "latest": "1.0.1"}}', "npm")
        self.assertEqual([r.name for r in recs], ["b"])

    def test_empty_input(self):
        self.assertEqual(node.parse_outdated("", "npm"), [])


class TestDepIndex(unittest.TestCase):
    """Direct-vs-transitive classification reads the real workspace manifests."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        _write(self.root / "package.json",
               {"name": "monorepo", "workspaces": ["packages/*"],
                "devDependencies": {"eslint": "^10.3.0"}})
        _write(self.root / "packages" / "viewer" / "package.json",
               {"name": "@mono/viewer", "dependencies": {"three": "^0.184.0"},
                "devDependencies": {"jsdom": "^29.0.0"}})
        # must be ignored: vendored copies are not declarations
        _write(self.root / "node_modules" / "undici" / "package.json",
               {"name": "undici", "dependencies": {"never-declared": "^1.0.0"}})

    def test_indexes_root_and_workspace_manifests(self):
        idx = node.dep_index(self.root)
        self.assertEqual(idx["eslint"]["location"], "package.json")
        self.assertEqual(idx["eslint"]["type"], "dev")
        self.assertEqual(idx["three"]["location"], "packages/viewer/package.json")
        self.assertEqual(idx["three"]["range"], "^0.184.0")
        self.assertEqual(idx["three"]["workspaceDir"], "packages/viewer")
        self.assertEqual(idx["three"]["workspaceName"], "@mono/viewer")

    def test_node_modules_not_walked(self):
        self.assertNotIn("never-declared", node.dep_index(self.root))

    def test_unreadable_manifest_is_skipped(self):
        (self.root / "packages" / "broken").mkdir(parents=True)
        (self.root / "packages" / "broken" / "package.json").write_text("{not json")
        self.assertIn("eslint", node.dep_index(self.root))

    def test_kind_and_location_from_index(self):
        recs = {r.name: r for r in node.parse_outdated(
            (FIX / "npm_outdated_workspaces.json").read_text(), "npm", node.dep_index(self.root))}
        self.assertEqual(recs["three"].kind, "direct")
        self.assertEqual(recs["three"].location, "packages/viewer/package.json")
        self.assertEqual(recs["three"].meta["declaredRange"], "^0.184.0")
        # undici is only ever a transitive dep here
        self.assertEqual(recs["undici"].kind, "transitive")
        self.assertEqual(recs["undici"].location, "package.json")

    def test_no_index_keeps_legacy_direct_assumption(self):
        recs = {r.name: r for r in node.parse_outdated(
            (FIX / "npm_outdated_workspaces.json").read_text(), "npm")}
        self.assertEqual(recs["undici"].kind, "direct")


class TestSemverRange(unittest.TestCase):
    def test_caret(self):
        self.assertTrue(node.satisfies("1.9.0", "^1.2.3"))
        self.assertFalse(node.satisfies("2.0.0", "^1.2.3"))
        self.assertFalse(node.satisfies("1.2.2", "^1.2.3"))

    def test_caret_zero_major_pins_minor(self):
        """^0.184.0 admits 0.184.x but not 0.185.0 -- the case `npm update` cannot cross."""
        self.assertTrue(node.satisfies("0.184.9", "^0.184.0"))
        self.assertFalse(node.satisfies("0.185.1", "^0.184.0"))

    def test_caret_zero_minor_pins_patch(self):
        self.assertTrue(node.satisfies("0.0.3", "^0.0.3"))
        self.assertFalse(node.satisfies("0.0.4", "^0.0.3"))

    def test_tilde(self):
        self.assertTrue(node.satisfies("1.2.9", "~1.2.3"))
        self.assertFalse(node.satisfies("1.3.0", "~1.2.3"))

    def test_exact_pin(self):
        self.assertTrue(node.satisfies("1.2.3", "1.2.3"))
        self.assertFalse(node.satisfies("1.2.4", "1.2.3"))

    def test_unknown_forms_are_none_not_false(self):
        """None means 'cannot prove' -- callers must stay conservative, never guess."""
        for rng in ("*", "1.x", "latest", ">=1.2.3", "^1 || ^2", "workspace:*",
                    "file:../local", "github:o/r", "", "1.2.3-beta.1"):
            self.assertIsNone(node.satisfies("2.0.0", rng), rng)
        self.assertIsNone(node.satisfies("not-a-version", "^1.0.0"))

    def test_widen_preserves_operator(self):
        self.assertEqual(node._widen("^0.184.0", "0.185.1"), "^0.185.1")
        self.assertEqual(node._widen("~1.2.3", "1.3.0"), "~1.3.0")
        self.assertEqual(node._widen("1.2.3", "1.2.4"), "1.2.4")


class TestSplitSpec(unittest.TestCase):
    def test_plain_scoped_and_bare(self):
        self.assertEqual(node.split_spec("eslint@9.1.0"), ("eslint", "9.1.0"))
        self.assertEqual(node.split_spec("@angular/core@20.0.0"), ("@angular/core", "20.0.0"))
        self.assertEqual(node.split_spec("eslint"), ("eslint", ""))
        self.assertEqual(node.split_spec("@angular/core"), ("@angular/core", ""))

    def test_pkg_name_wrapper_unchanged(self):
        self.assertEqual(node._pkg_name("@angular/core@20"), "@angular/core")


class TestApply(unittest.TestCase):
    """apply() must honor the version in a `name@X.Y.Z` spec, which it previously discarded."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        _write(self.root / "package.json",
               {"name": "monorepo", "devDependencies": {"eslint": "^10.3.0"}})
        _write(self.root / "packages" / "viewer" / "package.json",
               {"name": "@mono/viewer", "dependencies": {"three": "^0.184.0"},
                "devDependencies": {"@types/three": "^0.184.0"}})
        (self.root / "package-lock.json").write_text("{}")
        self.calls = []
        self.enterContext(mock.patch("bumplib.ecosystems.node.Path", side_effect=self._path))
        self.enterContext(mock.patch("bumplib.ecosystems.node._run", side_effect=self._record))

    def _path(self, p):
        return self.root if str(p) == "." else Path(p)

    def _record(self, args):
        self.calls.append(list(args))
        return mock.Mock(returncode=0, stdout="", stderr="")

    def test_in_range_target_uses_update_only(self):
        node.handle("apply", ["eslint@10.8.0"])
        self.assertIn(["npm", "update", "eslint"], self.calls)
        self.assertFalse(any("install" in cmd and len(cmd) > 2 for cmd in self.calls))

    def test_out_of_range_target_installs_into_its_workspace(self):
        """three@0.185.1 is outside ^0.184.0, so the manifest range must be rewritten."""
        node.handle("apply", ["three@0.185.1"])
        self.assertIn(["npm", "install", "-w", "packages/viewer", "three@^0.185.1"], self.calls)
        self.assertNotIn(["npm", "update", "three"], self.calls)

    def test_dev_dependency_keeps_its_save_flag(self):
        node.handle("apply", ["@types/three@0.185.4"])
        self.assertIn(["npm", "install", "-w", "packages/viewer", "-D", "@types/three@^0.185.4"],
                      self.calls)

    def test_transitive_and_bare_specs_stay_on_update(self):
        node.handle("apply", ["undici@7.29.0", "eslint"])
        self.assertIn(["npm", "update", "undici", "eslint"], self.calls)

    def test_files_modified_reports_real_manifests(self):
        res = node.handle("apply", ["three@0.185.1", "eslint@10.8.0"])
        self.assertEqual(res["filesModified"],
                         ["package-lock.json", "package.json", "packages/viewer/package.json"])
        self.assertEqual(res["applied"], ["three@0.185.1", "eslint@10.8.0"])

    def test_mixed_batch_splits_between_install_and_update(self):
        node.handle("apply", ["three@0.185.1", "eslint@10.8.0", "undici@7.29.0"])
        self.assertIn(["npm", "install", "-w", "packages/viewer", "three@^0.185.1"], self.calls)
        self.assertIn(["npm", "update", "eslint", "undici"], self.calls)

    def test_pnpm_targets_workspace_by_name(self):
        """pnpm's -w means 'the workspace root', so a workspace is selected with --filter."""
        (self.root / "pnpm-lock.yaml").write_text("")
        res = node.handle("apply", ["three@0.185.1"])
        self.assertIn(["pnpm", "add", "--filter", "@mono/viewer", "three@^0.185.1"], self.calls)
        self.assertIn("pnpm-lock.yaml", res["filesModified"])


if __name__ == "__main__":
    unittest.main()
