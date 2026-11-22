# tests/test_install_sh.py
import stat
import subprocess
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO / "scripts" / "install.sh"


class TestInstallSh(unittest.TestCase):
    def test_exists(self):
        self.assertTrue(INSTALL_SH.is_file(), f"{INSTALL_SH} does not exist")

    def test_executable(self):
        mode = INSTALL_SH.stat().st_mode
        self.assertTrue(mode & stat.S_IXUSR, f"{INSTALL_SH} is not executable")

    def test_syntax(self):
        result = subprocess.run(
            ["bash", "-n", str(INSTALL_SH)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"bash -n failed:\nstdout: {result.stdout}\nstderr: {result.stderr}",
        )

    def test_no_git_add_all_footgun(self):
        text = INSTALL_SH.read_text(encoding="utf-8")
        self.assertNotIn("git add -A", text)
        self.assertNotIn("git add .", text)

    def test_codex_hook_resolves_the_issues_plugin(self):
        text = INSTALL_SH.read_text(encoding="utf-8")
        self.assertIn("cache/estack/issues/*/scripts/refresh_gh_projects.py", text)
        self.assertNotIn("cache/estack/github/", text)


if __name__ == "__main__":
    unittest.main()
