import sys
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True
BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / "deps" / "scripts"))
FIX = BASE / "tests" / "fixtures" / "bump"

from bumplib.ecosystems import node  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
