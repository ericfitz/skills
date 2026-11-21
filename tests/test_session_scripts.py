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
SCRIPTS = [
    PLUGIN / "scripts" / "repo-state.sh",
    PLUGIN / "scripts" / "handoff-hint.sh",
    PLUGIN / "scripts" / "apply-title.sh",
]
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
        self.assertIn("/session:go", text)
        self.assertNotIn("/usr/bin/python3", text)

    def test_repo_state_uses_path_python(self):
        text = (PLUGIN / "scripts" / "repo-state.sh").read_text(encoding="utf-8")
        self.assertNotIn("/usr/bin/python3", text)


class TestSessionHooks(unittest.TestCase):
    def test_hooks_json_points_at_existing_script(self):
        data = json.loads((PLUGIN / "hooks" / "hooks.json").read_text(encoding="utf-8"))
        expected = {
            "SessionStart": ("startup|resume", "scripts/handoff-hint.sh"),
            "UserPromptSubmit": (None, "scripts/apply-title.sh"),
        }
        for event, (matcher, script) in expected.items():
            entries = data["hooks"][event]
            self.assertEqual(len(entries), 1, event)
            if matcher is None:
                self.assertIn(entries[0].get("matcher", ""), ("", None), event)
            else:
                self.assertEqual(entries[0]["matcher"], matcher, event)
            hooks = entries[0]["hooks"]
            self.assertEqual(len(hooks), 1, event)
            command = hooks[0]["command"]
            match = re.search(r"\$\{CLAUDE_PLUGIN_ROOT\}/(\S+?)\"?$", command)
            self.assertIsNotNone(match, f"no ${{CLAUDE_PLUGIN_ROOT}} script in {command!r}")
            self.assertEqual(match.group(1), script, event)
            self.assertTrue((PLUGIN / match.group(1)).is_file(), f"hook script {match.group(1)} missing")
            if event == "UserPromptSubmit":
                self.assertLessEqual(hooks[0]["timeout"], 10)


class TestSessionSkills(unittest.TestCase):
    def test_waiting_heading_in_sync(self):
        handoff = (PLUGIN / "skills" / "handoff" / "SKILL.md").read_text(encoding="utf-8")
        cont = (PLUGIN / "skills" / "go" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("WAITING ON USER:", handoff)
        self.assertIn("Waiting on the user", cont)
        self.assertIn("WAITING ON USER:", cont)
        self.assertIn("WAITING ON ERIC:", cont)  # legacy heading still accepted
        self.assertNotIn("WAITING ON ERIC:", handoff)

    def test_go_hands_off_to_backlog(self):
        cont = (PLUGIN / "skills" / "go" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("github:backlog", cont)
        self.assertIn("No queued work", cont)
        self.assertIn("unavailable: github plugin not installed", cont)
        backlog = REPO / "github" / "skills" / "backlog" / "SKILL.md"
        self.assertTrue(backlog.is_file(), f"{backlog} missing: go invokes github:backlog")
        self.assertRegex(backlog.read_text(encoding="utf-8"), r"(?m)^name: backlog$")

    def test_go_names_session(self):
        cont = (PLUGIN / "skills" / "go" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("CLAUDE_CODE_SESSION_ID", cont)
        self.assertIn("${XDG_STATE_HOME:-$HOME/.local/state}/session-plugin/titles/", cont)
        self.assertIn("50 characters", cont)
        rules = re.search(r"(?ms)^## Rules\n.*", cont)
        self.assertIsNotNone(rules, "go Rules section missing")
        self.assertRegex(rules.group(0), r"title file")
        self.assertRegex(rules.group(0), r"The one write exception is the step 8\s+title file")
        self.assertIn("must not contain `'`", cont)
        step7 = re.search(r"(?ms)^7\. \*\*Stop.*?(?=^8\. )", cont)
        self.assertIsNotNone(step7, "go step 7 missing")
        self.assertIn("step 8", step7.group(0))

    def test_go_classifies_next(self):
        cont = (PLUGIN / "skills" / "go" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("NEXT done:", cont)
        self.assertIn("**done** or **open**", cont)
        self.assertIn("neither done nor open", cont)
        for text in ("--raw-field", "--output", "--ext-diff", "--textconv", "exactly one simple command"):
            self.assertIn(text, cont)
        self.assertIn("never a pick-from-backlog item", cont)
        step = re.search(r"(?ms)^6\. \*\*No queued work.*?(?=^7\. )", cont)
        self.assertIsNotNone(step, "go step 6 missing")
        self.assertIn("no open items", step.group(0))

    def test_handoff_sets_idle_before_park(self):
        handoff = (PLUGIN / "skills" / "handoff" / "SKILL.md").read_text(encoding="utf-8")
        step = re.search(r"(?ms)^6\. \*\*Go quiet.*?(?=^7\. )", handoff)
        self.assertIsNotNone(step, "handoff step 6 (Go quiet) missing")
        text = step.group(0)
        self.assertIn("status to idle", text)
        self.assertIn("lowest-attention mode", text)
        self.assertIn("Do this last", text)
        self.assertLess(text.index("status to idle"), text.index("lowest-attention mode"))
        # Services are named as examples only; the skill must not hardcode their CLI commands.
        self.assertNotRegex(handoff, r"`(agentbus2?|agentmesh) park`")
        self.assertNotIn("agentbus2", handoff)

    def test_scripts_resolved_via_plugin_root(self):
        for skill in ("go", "handoff"):
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
