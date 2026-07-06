import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deps" / "scripts"))

from bumplib import contracts as c  # noqa: E402
from bumplib import categorize as cat  # noqa: E402


def rec(name, current, latest, **kw):
    bump = cat.classify_bump(current, latest)
    return c.UpdateRecord(name=name, current=current, latest=latest,
                          wanted=kw.get("wanted", latest), bump=bump,
                          kind=kw.get("kind", "direct"),
                          location=kw.get("location", "manifest"),
                          pinned=kw.get("pinned", False))


class TestSemver(unittest.TestCase):
    def test_parse_strips_leading_v(self):
        self.assertEqual(cat.parse_semver("v1.2.3"), (1, 2, 3))

    def test_parse_trims_prerelease(self):
        self.assertEqual(cat.parse_semver("2.0.0-rc.1"), (2, 0, 0))

    def test_classify(self):
        self.assertEqual(cat.classify_bump("1.2.3", "2.0.0"), "major")
        self.assertEqual(cat.classify_bump("1.2.3", "1.5.0"), "minor")
        self.assertEqual(cat.classify_bump("1.2.3", "1.2.5"), "patch")
        self.assertEqual(cat.classify_bump("1.2.3", "1.2.3"), "none")


class TestGlob(unittest.TestCase):
    def test_exact_and_prefix(self):
        self.assertTrue(cat.glob_match("zone.js", "zone.js"))
        self.assertFalse(cat.glob_match("zone.jsx", "zone.js"))
        self.assertTrue(cat.glob_match("@angular/core", "@angular/*"))
        self.assertTrue(cat.glob_match("@antv/x6-plugin", "@antv/x6*"))
        self.assertFalse(cat.glob_match("@antv/y", "@antv/x6*"))


class TestCategorize(unittest.TestCase):
    def test_safe_minor(self):
        out = cat.categorize([rec("eslint", "9.38.0", "9.39.2")], [], [], {}, set())
        self.assertEqual(len(out.safe), 1)
        self.assertEqual(out.safe[0]["reason"], "minor update")

    def test_security_patch(self):
        adv = [c.Advisory(package="qs", ecosystem="node", severity="HIGH",
                          current="6.14.1", fixed="6.14.2", ids=["CVE-1"])]
        out = cat.categorize([rec("qs", "6.14.1", "6.14.2")], adv, [], {}, set())
        self.assertEqual(len(out.securityFixes), 1)

    def test_major_needs_plan(self):
        out = cat.categorize([rec("typescript", "5.8.0", "6.0.0")], [], [], {}, set())
        self.assertEqual(len(out.needsPlan), 1)
        self.assertIn("Major", out.needsPlan[0]["reason"])

    def test_excluded_needs_plan(self):
        out = cat.categorize([rec("@angular/core", "20.2.0", "20.3.0")], [],
                             ["@angular/*"], {}, set())
        self.assertEqual(len(out.needsPlan), 1)
        self.assertIn("Excluded", out.needsPlan[0]["reason"])

    def test_pinned_needs_plan(self):
        out = cat.categorize([rec("requests", "2.28.0", "2.29.0", pinned=True)], [],
                             [], {}, set())
        self.assertEqual(out.needsPlan[0]["reason"], "pinned")

    def test_pinned_with_advisory_goes_to_plan_not_security(self):
        adv = [c.Advisory(package="qs", ecosystem="node", severity="HIGH",
                          current="6.14.1", fixed="6.14.2", ids=["CVE-1"])]
        out = cat.categorize([rec("qs", "6.14.1", "6.14.2", pinned=True)], adv, [], {}, set())
        self.assertEqual(len(out.securityFixes), 0)
        self.assertEqual(len(out.needsPlan), 1)
        self.assertEqual(out.needsPlan[0]["reason"], "pinned")

    def test_hold_needs_plan(self):
        out = cat.categorize([rec("@antv/x6", "2.19.2", "2.20.0")], [], [],
                             {"@antv/x6": "v3 breaking"}, set())
        self.assertIn("Hold", out.needsPlan[0]["reason"])

    def test_replace_target_skipped(self):
        out = cat.categorize([rec("local/mod", "1.0.0", "1.1.0")], [], [], {},
                             {"local/mod"})
        self.assertEqual(len(out.skipped), 1)

    def test_uptodate_skipped(self):
        out = cat.categorize([rec("a", "1.0.0", "1.0.0")], [], [], {}, set())
        self.assertEqual(len(out.skipped), 1)

    def test_major_security_goes_to_plan(self):
        adv = [c.Advisory(package="pgx", ecosystem="go", severity="HIGH",
                          current="4.18.3", fixed="5.0.0", ids=["CVE-9"])]
        out = cat.categorize([rec("pgx", "4.18.3", "5.8.0")], adv, [], {}, set())
        self.assertEqual(len(out.needsPlan), 1)
        self.assertIn("Major security", out.needsPlan[0]["reason"])


if __name__ == "__main__":
    unittest.main()
