# tests/test_session_scripts.py
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "session"
SCRIPTS = [PLUGIN / "scripts" / "repo-state.sh", PLUGIN / "scripts" / "handoff-hint.sh"]
PRIVATE = re.compile(r"efitz|eric|tmi|/Users|_lib|\.claude/skills", re.IGNORECASE)


def _ids(paths):
    return [p.name for p in paths]


class TestSessionScripts(unittest.TestCase):
    def test_exist(self):
        for script in SCRIPTS:
            with self.subTest(script=script.name):
                self.assertTrue(script.is_file(), f"{script} does not exist")

    def test_executable(self):
        for script in SCRIPTS:
            with self.subTest(script=script.name):
                self.assertTrue(script.stat().st_mode & stat.S_IXUSR, f"{script} is not executable")

    def test_syntax(self):
        for script in SCRIPTS:
            with self.subTest(script=script.name):
                result = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, f"bash -n failed:\n{result.stderr}")

    def test_self_test_passes_and_leaves_cwd_clean(self):
        for script in SCRIPTS:
            with self.subTest(script=script.name), tempfile.TemporaryDirectory() as tmp:
                result = subprocess.run(
                    ["bash", str(script), "--self-test"],
                    cwd=tmp,
                    capture_output=True,
                    text=True,
                    timeout=180,
                )
                self.assertEqual(
                    result.returncode, 0,
                    f"self-test failed:\nstdout: {result.stdout}\nstderr: {result.stderr}",
                )
                self.assertEqual(os.listdir(tmp), [], "self-test left files in its cwd")

    def test_hint_names_plugin_qualified_skill(self):
        text = (PLUGIN / "scripts" / "handoff-hint.sh").read_text(encoding="utf-8")
        self.assertIn("/session:continue", text)
        self.assertNotIn("/usr/bin/python3", text)

    def test_repo_state_uses_path_python(self):
        text = (PLUGIN / "scripts" / "repo-state.sh").read_text(encoding="utf-8")
        self.assertNotIn("/usr/bin/python3", text)


class TestSessionHooks(unittest.TestCase):
    def test_hooks_json_points_at_existing_script(self):
        data = json.loads((PLUGIN / "hooks" / "hooks.json").read_text(encoding="utf-8"))
        entries = data["hooks"]["SessionStart"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["matcher"], "startup|resume")
        commands = [h["command"] for h in entries[0]["hooks"]]
        self.assertEqual(len(commands), 1)
        match = re.search(r"\$\{CLAUDE_PLUGIN_ROOT\}/(\S+?)\"?$", commands[0])
        self.assertIsNotNone(match, f"no ${{CLAUDE_PLUGIN_ROOT}} script in {commands[0]!r}")
        self.assertTrue((PLUGIN / match.group(1)).is_file(), f"hook script {match.group(1)} missing")


class TestSessionSkills(unittest.TestCase):
    def test_waiting_heading_in_sync(self):
        handoff = (PLUGIN / "skills" / "handoff" / "SKILL.md").read_text(encoding="utf-8")
        cont = (PLUGIN / "skills" / "continue" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("WAITING ON USER:", handoff)
        self.assertIn("Waiting on the user", cont)
        self.assertIn("WAITING ON USER:", cont)
        self.assertIn("WAITING ON ERIC:", cont)  # legacy heading still accepted
        self.assertNotIn("WAITING ON ERIC:", handoff)

    def test_continue_hands_off_to_backlog(self):
        cont = (PLUGIN / "skills" / "continue" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("github:backlog", cont)
        self.assertIn("No queued work", cont)
        self.assertIn("unavailable: github plugin not installed", cont)
        backlog = REPO / "github" / "skills" / "backlog" / "SKILL.md"
        self.assertTrue(backlog.is_file(), f"{backlog} missing: continue invokes github:backlog")
        self.assertRegex(backlog.read_text(encoding="utf-8"), r"(?m)^name: backlog$")

    def test_scripts_resolved_via_plugin_root(self):
        for skill in ("continue", "handoff"):
            with self.subTest(skill=skill):
                text = (PLUGIN / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
                self.assertIn("${CLAUDE_PLUGIN_ROOT}/scripts/repo-state.sh", text)

    def test_no_private_names_in_plugin(self):
        legacy = "WAITING ON ERIC:"
        for path in sorted(PLUGIN.rglob("*")):
            if not path.is_file():
                continue
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if legacy in line:
                    continue
                with self.subTest(path=str(path.relative_to(REPO)), line=lineno):
                    self.assertIsNone(PRIVATE.search(line), f"{path}:{lineno}: {line}")


if __name__ == "__main__":
    unittest.main()
