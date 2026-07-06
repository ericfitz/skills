# tests/test_bump_cli_categorize.py
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deps" / "scripts"))

from bumplib import orchestrate  # noqa: E402


def _rec(name, current, latest, bump, **kw):
    return {
        "name": name,
        "current": current,
        "latest": latest,
        "wanted": kw.get("wanted", latest),
        "bump": bump,
        "kind": kw.get("kind", "direct"),
        "location": kw.get("location", "manifest"),
        "pinned": kw.get("pinned", False),
        "ecosystem": kw.get("ecosystem", ""),
        "meta": kw.get("meta", {}),
    }


class TestCategorizePayload(unittest.TestCase):
    def test_buckets_split_correctly(self):
        payload = {
            "updates": [
                _rec("eslint", "9.38.0", "9.39.2", "minor"),
                _rec("typescript", "5.8.0", "6.0.0", "major"),
                _rec("local/mod", "1.0.0", "1.1.0", "minor"),
            ],
            "advisories": [],
            "replaceTargets": ["local/mod"],
        }
        # tempfile root: no CLAUDE.md / .bump-config.json, so disk merge is a no-op.
        with tempfile.TemporaryDirectory() as td:
            out = orchestrate.categorize_payload(payload, root=td)
        self.assertEqual(len(out.safe), 1)
        self.assertEqual(out.safe[0]["name"], "eslint")
        self.assertEqual(len(out.needsPlan), 1)
        self.assertEqual(out.needsPlan[0]["name"], "typescript")
        self.assertEqual(len(out.skipped), 1)
        self.assertEqual(out.skipped[0]["name"], "local/mod")
        self.assertEqual(len(out.securityFixes), 0)

    def test_security_advisory_bucketed(self):
        payload = {
            "updates": [_rec("qs", "6.14.1", "6.14.2", "patch")],
            "advisories": [{
                "package": "qs", "ecosystem": "node", "severity": "HIGH",
                "current": "6.14.1", "fixed": "6.14.2", "ids": ["CVE-1"],
            }],
        }
        with tempfile.TemporaryDirectory() as td:
            out = orchestrate.categorize_payload(payload, root=td)
        self.assertEqual(len(out.securityFixes), 1)
        self.assertEqual(out.securityFixes[0]["name"], "qs")

    def test_passed_exclude_and_disk_merge(self):
        payload = {
            "updates": [_rec("lodash", "4.17.20", "4.17.21", "patch")],
            "advisories": [],
            "exclude": ["lodash"],
        }
        with tempfile.TemporaryDirectory() as td:
            out = orchestrate.categorize_payload(payload, root=td)
        self.assertEqual(len(out.needsPlan), 1)
        self.assertIn("Excluded", out.needsPlan[0]["reason"])

    def test_empty_payload_yields_empty_categories(self):
        with tempfile.TemporaryDirectory() as td:
            out = orchestrate.categorize_payload({"updates": [], "advisories": []}, root=td)
        self.assertEqual(out.securityFixes, [])
        self.assertEqual(out.safe, [])
        self.assertEqual(out.needsPlan, [])
        self.assertEqual(out.skipped, [])


if __name__ == "__main__":
    unittest.main()
