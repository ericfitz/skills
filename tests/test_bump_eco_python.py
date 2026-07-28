import unittest
from pathlib import Path
from unittest import mock

from bumplib.ecosystems import python as py

BASE = Path(__file__).resolve().parents[1]
FIX = BASE / "tests" / "fixtures" / "bump"


class TestPython(unittest.TestCase):
    def test_parse_outdated(self):
        recs = {r.name: r for r in py.parse_outdated((FIX / "pip_outdated.json").read_text())}
        self.assertEqual(recs["requests"].current, "2.28.0")
        self.assertEqual(recs["requests"].latest, "2.31.0")

    def test_parse_audit(self):
        advs = py.parse_audit((FIX / "pip_audit.json").read_text())
        self.assertTrue(any("PYSEC" in (a.ids[0] if a.ids else "") for a in advs))

    def test_audit_missing_binary_uv(self):
        """Regression test: audit verb should return [] when uv binary is missing (uv manager)."""
        # Mock detect to return uv manager
        with mock.patch("bumplib.ecosystems.python.shutil.which", return_value=None), \
                mock.patch("bumplib.ecosystems.python.detect") as mock_detect:
            mock_detect.return_value = {"packageManager": "uv"}
            result = py.handle("audit", [])
            self.assertEqual(result, [])

    def test_audit_missing_binary_pip(self):
        """Regression test: audit verb should return [] when pip-audit binary is missing (pip manager)."""
        # Mock detect to return pip manager
        with mock.patch("bumplib.ecosystems.python.shutil.which", return_value=None), \
                mock.patch("bumplib.ecosystems.python.detect") as mock_detect:
            mock_detect.return_value = {"packageManager": "pip"}
            result = py.handle("audit", [])
            self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
