# tests/test_install_sh.py
import json
import os
import stat
import subprocess
import sys
import tempfile
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


STALE = (
    'bash -c \'p=$(ls -d "$HOME"/.codex/plugins/cache/estack/github/*/scripts/refresh_gh_projects.py '
    '2>/dev/null | sort -V | tail -1); [ -n "$p" ] && exec python3 "$p"; exit 0\''
)

CODEX_STUB = """#!/usr/bin/env bash
case "$*" in
  "plugin marketplace list --json") echo '{"marketplaces": [{"name": "estack"}]}' ;;
  "plugin list --json") echo '{"installed": []}' ;;
esac
exit 0
"""


def hooks_doc(*commands):
    return {
        "hooks": {
            "SessionStart": [
                {"matcher": "startup", "hooks": [{"type": "command", "command": c, "shell": "bash"} for c in commands]}
            ]
        }
    }


class TestCodexSessionHookMerge(unittest.TestCase):
    """Runs the installer's --codex-session-hook merge against fixture hooks.json files.

    HOME is a temp dir and a stub codex on PATH answers the install queries, so
    neither the real ~/.codex nor the real codex CLI is touched.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name) / "home"
        self.codex_dir = self.home / ".codex"
        self.codex_dir.mkdir(parents=True)
        self.hooks = self.codex_dir / "hooks.json"
        self.backup = self.codex_dir / "hooks.json.bak"
        stub_dir = Path(self._tmp.name) / "bin"
        stub_dir.mkdir()
        stub = stub_dir / "codex"
        stub.write_text(CODEX_STUB)
        stub.chmod(0o755)
        self.env = {**os.environ, "HOME": str(self.home), "PATH": f"{stub_dir}{os.pathsep}{os.environ['PATH']}"}

    def tearDown(self):
        self._tmp.cleanup()

    def run_installer(self):
        result = subprocess.run(
            ["bash", str(INSTALL_SH), "codex", "--codex-session-hook"],
            capture_output=True,
            text=True,
            env=self.env,
        )
        self.assertEqual(result.returncode, 0, f"stdout: {result.stdout}\nstderr: {result.stderr}")
        return result

    def commands(self):
        data = json.loads(self.hooks.read_text())
        return [h["command"] for entry in data["hooks"]["SessionStart"] for h in entry["hooks"]]

    def current_command(self):
        """The command a fresh install writes, read back from a clean run."""
        self.run_installer()
        (command,) = self.commands()
        self.hooks.unlink()
        return command

    def test_fresh_install_adds_one_entry(self):
        self.run_installer()
        (command,) = self.commands()
        self.assertIn("cache/estack/issues/", command)
        self.assertFalse(self.backup.exists())

    def test_stale_entry_is_repointed_backed_up_and_reported(self):
        current = self.current_command()
        self.hooks.write_text(json.dumps(hooks_doc(STALE)))
        original = self.hooks.read_text()
        result = self.run_installer()
        self.assertEqual(self.commands(), [current])
        self.assertIn("repointing", result.stdout)
        self.assertIn("cache/estack/github/", result.stdout)
        self.assertEqual(self.backup.read_text(), original)

    def test_second_run_after_repoint_writes_nothing(self):
        self.hooks.write_text(json.dumps(hooks_doc(STALE)))
        self.run_installer()
        after_first = self.hooks.read_bytes()
        mtime = self.hooks.stat().st_mtime_ns
        result = self.run_installer()
        self.assertEqual(self.hooks.read_bytes(), after_first)
        self.assertEqual(self.hooks.stat().st_mtime_ns, mtime)
        self.assertIn("already runs the current", result.stdout)

    def test_current_command_is_left_alone_when_its_glob_matches_nothing(self):
        current = self.current_command()
        self.hooks.write_text(json.dumps(hooks_doc(current)))
        before = self.hooks.read_bytes()
        self.run_installer()
        self.assertEqual(self.hooks.read_bytes(), before)
        self.assertFalse(self.backup.exists())

    def test_entry_whose_path_exists_is_left_alone(self):
        script = self.home / "custom" / "refresh_gh_projects.py"
        script.parent.mkdir(parents=True)
        script.write_text("")
        command = f"python3 {script}"
        self.hooks.write_text(json.dumps(hooks_doc(command)))
        before = self.hooks.read_bytes()
        self.run_installer()
        self.assertEqual(self.hooks.read_bytes(), before)

    def test_home_variable_paths_that_exist_are_left_alone(self):
        script = self.home / "custom" / "refresh_gh_projects.py"
        script.parent.mkdir(parents=True)
        script.write_text("")
        command = 'python3 "$HOME"/custom/refresh_gh_projects.py'
        self.hooks.write_text(json.dumps(hooks_doc(command)))
        before = self.hooks.read_bytes()
        self.run_installer()
        self.assertEqual(self.hooks.read_bytes(), before)

    def test_unparseable_command_is_left_alone_with_a_warning(self):
        command = "echo refresh_gh_projects.py"
        self.hooks.write_text(json.dumps(hooks_doc(command)))
        before = self.hooks.read_bytes()
        result = self.run_installer()
        self.assertEqual(self.hooks.read_bytes(), before)
        self.assertIn("leaving as-is", result.stdout + result.stderr)

    def test_stale_entry_beside_the_current_one_is_reported_not_duplicated(self):
        current = self.current_command()
        self.hooks.write_text(json.dumps(hooks_doc(current, STALE)))
        before = self.hooks.read_bytes()
        result = self.run_installer()
        self.assertEqual(self.hooks.read_bytes(), before)
        self.assertIn("remove the stale one by hand", result.stderr)

    def test_two_stale_entries_repoint_only_the_first(self):
        current = self.current_command()
        self.hooks.write_text(json.dumps(hooks_doc(STALE, STALE + " ")))
        self.run_installer()
        self.assertEqual(self.commands(), [current, STALE + " "])


if __name__ == "__main__":
    unittest.main()
