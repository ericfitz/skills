# tests/test_codex_manifests.py
import json
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
            (plugin_dir / ".claude-plugin" / "plugin.json").write_text(
                json.dumps(manifest), encoding="utf-8")
        entries.append({"name": name, "description": "d", "source": f"./{name}", "category": "development"})
    (root / ".claude-plugin").mkdir()
    (root / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps({"name": "test-market", "plugins": market_entries if market_entries is not None else entries}),
        encoding="utf-8")
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
            {self.root / ".agents" / "plugins" / "marketplace.json",
             self.root / "alpha" / ".codex-plugin" / "plugin.json",
             self.root / "beta" / ".codex-plugin" / "plugin.json"})
        market = json.loads(out[self.root / ".agents" / "plugins" / "marketplace.json"])
        self.assertEqual(market["name"], "test-market")
        self.assertEqual(
            market["plugins"][0],
            {"name": "alpha", "category": "development",
             "source": {"source": "local", "path": "./alpha"}})
        alpha = json.loads(out[self.root / "alpha" / ".codex-plugin" / "plugin.json"])
        self.assertEqual(alpha, {"name": "alpha", "version": "1.0.0", "description": "does things",
                                 "author": {"name": "efitz"}, "skills": "./skills/"})

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
            json.dumps({"name": "test-market", "plugins": entries + entries}), encoding="utf-8")
        with self.assertRaisesRegex(gcm.GenerationError, "duplicate.*alpha"):
            gcm.generate(self.root)

    def test_name_mismatch_between_marketplace_and_plugin_json_fails(self):
        build_repo(self.root, {"alpha": manifest("omega")})
        with self.assertRaisesRegex(gcm.GenerationError, "alpha"):
            gcm.generate(self.root)


if __name__ == "__main__":
    unittest.main()
