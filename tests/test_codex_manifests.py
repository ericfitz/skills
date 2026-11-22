# tests/test_codex_manifests.py
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import gen_codex_manifests as gcm


def build_repo(root: Path, plugins: dict[str, dict], market_entries: list[dict] | None = None) -> Path:
    """Build a minimal fake marketplace repo under root.

    plugins: name -> manifest dict written to <name>/.claude-plugin/plugin.json.
             A manifest of None skips writing plugin.json (missing-manifest case).
             Set "_no_skills" in the manifest to skip creating skills/.
    market_entries: overrides the generated marketplace plugin list.
    """
    entries = []
    for name, manifest in plugins.items():
        plugin_dir = root / name
        (plugin_dir / "skills" / "demo").mkdir(parents=True)
        if manifest is not None:
            no_skills = manifest.pop("_no_skills", False)
            if no_skills:
                import shutil

                shutil.rmtree(plugin_dir / "skills")
            (plugin_dir / ".claude-plugin").mkdir(parents=True, exist_ok=True)
            (plugin_dir / ".claude-plugin" / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
        entries.append({"name": name, "description": "d", "source": f"./{name}", "category": "development"})
    (root / ".claude-plugin").mkdir()
    (root / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps({"name": "test-market", "plugins": market_entries if market_entries is not None else entries}),
        encoding="utf-8",
    )
    return root


def manifest(name: str, **overrides) -> dict:
    base = {"name": name, "version": "1.0.0", "description": "does things", "author": {"name": "efitz"}}
    base.update(overrides)
    return base


class TestGenerate(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_happy_path_renders_marketplace_and_plugin_manifests(self):
        build_repo(self.root, {"alpha": manifest("alpha"), "beta": manifest("beta")})
        out = gcm.generate(self.root)
        self.assertEqual(
            set(out),
            {
                self.root / ".agents" / "plugins" / "marketplace.json",
                self.root / "alpha" / ".codex-plugin" / "plugin.json",
                self.root / "beta" / ".codex-plugin" / "plugin.json",
            },
        )
        market = json.loads(out[self.root / ".agents" / "plugins" / "marketplace.json"])
        self.assertEqual(market["name"], "test-market")
        self.assertEqual(
            market["plugins"][0],
            {"name": "alpha", "category": "development", "source": {"source": "local", "path": "./alpha"}},
        )
        alpha = json.loads(out[self.root / "alpha" / ".codex-plugin" / "plugin.json"])
        self.assertEqual(
            alpha,
            {
                "name": "alpha",
                "version": "1.0.0",
                "description": "does things",
                "author": {"name": "efitz"},
                "skills": "./skills/",
            },
        )

    def test_rendered_json_is_two_space_indented_with_trailing_newline(self):
        build_repo(self.root, {"alpha": manifest("alpha")})
        for content in gcm.generate(self.root).values():
            self.assertTrue(content.endswith("}\n"))
            self.assertIn('\n  "name"', content)

    def test_missing_plugin_manifest_fails(self):
        build_repo(self.root, {"alpha": None})
        with self.assertRaisesRegex(gcm.GenerationError, "alpha.*plugin.json"):
            gcm.generate(self.root)

    def test_missing_skills_dir_fails(self):
        build_repo(self.root, {"alpha": manifest("alpha", _no_skills=True)})
        with self.assertRaisesRegex(gcm.GenerationError, "alpha.*skills"):
            gcm.generate(self.root)

    def test_duplicate_plugin_name_fails(self):
        build_repo(self.root, {"alpha": manifest("alpha")})
        entries = json.loads((self.root / ".claude-plugin" / "marketplace.json").read_text())["plugins"]
        (self.root / ".claude-plugin" / "marketplace.json").write_text(
            json.dumps({"name": "test-market", "plugins": entries + entries}), encoding="utf-8"
        )
        with self.assertRaisesRegex(gcm.GenerationError, "duplicate.*alpha"):
            gcm.generate(self.root)

    def test_name_mismatch_between_marketplace_and_plugin_json_fails(self):
        build_repo(self.root, {"alpha": manifest("omega")})
        with self.assertRaisesRegex(gcm.GenerationError, "alpha"):
            gcm.generate(self.root)

    def test_missing_marketplace_file_is_a_generation_error(self):
        with self.assertRaisesRegex(gcm.GenerationError, "marketplace.json"):
            gcm.generate(self.root)

    def test_invalid_marketplace_json_is_a_generation_error(self):
        build_repo(self.root, {"alpha": manifest("alpha")})
        (self.root / ".claude-plugin" / "marketplace.json").write_text("{not json", encoding="utf-8")
        with self.assertRaisesRegex(gcm.GenerationError, "marketplace.json"):
            gcm.generate(self.root)

    def test_entry_missing_name_is_a_generation_error(self):
        build_repo(self.root, {"alpha": manifest("alpha")}, market_entries=[{"description": "d"}])
        with self.assertRaisesRegex(gcm.GenerationError, "name"):
            gcm.generate(self.root)

    def test_entry_missing_source_is_a_generation_error(self):
        build_repo(self.root, {"alpha": manifest("alpha")}, market_entries=[{"name": "alpha"}])
        with self.assertRaisesRegex(gcm.GenerationError, "alpha"):
            gcm.generate(self.root)

    def test_invalid_plugin_json_is_a_generation_error(self):
        build_repo(self.root, {"alpha": manifest("alpha")})
        (self.root / "alpha" / ".claude-plugin" / "plugin.json").write_text("[1,", encoding="utf-8")
        with self.assertRaisesRegex(gcm.GenerationError, "alpha"):
            gcm.generate(self.root)

    def test_cli_exits_2_on_structural_error(self):
        proc = subprocess.run(
            [sys.executable, str(REPO / "scripts" / "gen_codex_manifests.py"), "--repo", str(self.root), "--check"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn("FAIL:", proc.stderr)


def write_skill(root: Path, plugin: str, skill: str, frontmatter: str) -> Path:
    skill_dir = root / plugin / "skills" / skill
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(f"---\nname: {skill}\n{frontmatter}---\n\n# {skill}\n", encoding="utf-8")
    return skill_dir


def run_cli(root: Path, *flags: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(REPO / "scripts" / "gen_codex_manifests.py"), "--repo", str(root), *flags],
        capture_output=True,
        text=True,
    )


class TestSkillPolicy(unittest.TestCase):
    """disable-model-invocation: true maps to Codex's agents/openai.yaml allow_implicit_invocation: false."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        build_repo(self.root, {"alpha": manifest("alpha")})

    def test_flagged_skill_gets_policy_file(self):
        skill = write_skill(self.root, "alpha", "shortcut", "disable-model-invocation: true\n")
        out = gcm.generate(self.root)
        content = out[skill / "agents" / "openai.yaml"]
        self.assertTrue(content.startswith(gcm.SKILL_POLICY_HEADER))
        self.assertIn("policy:\n  allow_implicit_invocation: false\n", content)

    def test_unflagged_false_and_missing_skill_md_get_none(self):
        write_skill(self.root, "alpha", "plain", "description: d\n")
        write_skill(self.root, "alpha", "off", "disable-model-invocation: false\n")
        out = gcm.generate(self.root)
        self.assertEqual([p for p in out if p.name == "openai.yaml"], [])

    def test_flag_outside_frontmatter_is_ignored(self):
        skill = write_skill(self.root, "alpha", "body", "description: d\n")
        (skill / "SKILL.md").write_text("---\nname: body\n---\n\ndisable-model-invocation: true\n", encoding="utf-8")
        self.assertNotIn(skill / "agents" / "openai.yaml", gcm.generate(self.root))

    def test_unrecognized_flag_value_fails(self):
        write_skill(self.root, "alpha", "bad", "disable-model-invocation: yes\n")
        with self.assertRaisesRegex(gcm.GenerationError, "alpha/bad.*true or false.*'yes'"):
            gcm.generate(self.root)

    def test_hand_written_openai_yaml_is_not_overwritten(self):
        skill = write_skill(self.root, "alpha", "shortcut", "disable-model-invocation: true\n")
        (skill / "agents").mkdir()
        (skill / "agents" / "openai.yaml").write_text("interface:\n  display_name: X\n", encoding="utf-8")
        with self.assertRaisesRegex(gcm.GenerationError, "hand-written"):
            gcm.generate(self.root)

    def test_check_detects_missing_policy_then_passes_after_write(self):
        write_skill(self.root, "alpha", "shortcut", "disable-model-invocation: true\n")
        self.assertEqual(run_cli(self.root).returncode, 0)
        (self.root / "alpha" / "skills" / "shortcut" / "agents" / "openai.yaml").unlink()
        proc = run_cli(self.root, "--check")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("DRIFT: alpha/skills/shortcut/agents/openai.yaml", proc.stderr)
        self.assertEqual(run_cli(self.root).returncode, 0)
        self.assertEqual(run_cli(self.root, "--check").returncode, 0)

    def test_policy_left_after_flag_removed_is_stale_then_removed(self):
        skill = write_skill(self.root, "alpha", "shortcut", "disable-model-invocation: true\n")
        self.assertEqual(run_cli(self.root).returncode, 0)
        write_skill(self.root, "alpha", "shortcut", "description: d\n")
        proc = run_cli(self.root, "--check")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("STALE: alpha/skills/shortcut/agents/openai.yaml", proc.stderr)
        self.assertEqual(run_cli(self.root).returncode, 0)
        self.assertFalse((skill / "agents").exists())
        self.assertEqual(run_cli(self.root, "--check").returncode, 0)

    def test_hand_written_openai_yaml_without_flag_is_never_stale(self):
        skill = write_skill(self.root, "alpha", "plain", "description: d\n")
        (skill / "agents").mkdir()
        (skill / "agents" / "openai.yaml").write_text("interface:\n  display_name: X\n", encoding="utf-8")
        run_cli(self.root)
        self.assertEqual(run_cli(self.root, "--check").returncode, 0)
        self.assertTrue((skill / "agents" / "openai.yaml").is_file())


CLAUDE_MARKETPLACE = REPO / ".claude-plugin" / "marketplace.json"
CODEX_MARKETPLACE = REPO / ".agents" / "plugins" / "marketplace.json"


class TestCommittedCodexManifests(unittest.TestCase):
    def test_committed_files_match_fresh_regeneration(self):
        for path, content in gcm.generate(REPO).items():
            with self.subTest(path=str(path.relative_to(REPO))):
                self.assertTrue(path.is_file(), f"{path} missing — run scripts/gen_codex_manifests.py")
                self.assertEqual(path.read_text(encoding="utf-8"), content)

    def test_marketplace_membership_matches_both_ways(self):
        claude = {p["name"] for p in json.loads(CLAUDE_MARKETPLACE.read_text(encoding="utf-8"))["plugins"]}
        codex = {p["name"] for p in json.loads(CODEX_MARKETPLACE.read_text(encoding="utf-8"))["plugins"]}
        self.assertEqual(claude, codex)

    def test_codex_plugin_skills_paths_exist(self):
        for entry in json.loads(CODEX_MARKETPLACE.read_text(encoding="utf-8"))["plugins"]:
            plugin_dir = REPO / entry["source"]["path"]
            data = json.loads((plugin_dir / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
            with self.subTest(plugin=entry["name"]):
                self.assertEqual(data["skills"], "./skills/")
                self.assertTrue((plugin_dir / "skills").is_dir())

    def test_every_flagged_skill_has_a_committed_policy(self):
        flagged = []
        for skill_md in REPO.glob("*/skills/*/SKILL.md"):
            if "\ndisable-model-invocation: true\n" in skill_md.read_text(encoding="utf-8").split("\n---", 1)[0] + "\n":
                flagged.append(skill_md.parent)
        self.assertTrue(flagged)
        for skill_dir in flagged:
            with self.subTest(skill=str(skill_dir.relative_to(REPO))):
                policy = skill_dir / "agents" / "openai.yaml"
                self.assertEqual(policy.read_text(encoding="utf-8"), gcm.SKILL_POLICY)

    def test_check_flag_passes_on_committed_tree(self):
        proc = subprocess.run(
            [sys.executable, str(REPO / "scripts" / "gen_codex_manifests.py"), "--check"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":
    unittest.main()
