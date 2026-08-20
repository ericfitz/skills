# tests/test_openapi_coupling.py
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parents[1]
INIT = REPO / "openapi" / "skills" / "init" / "SKILL.md"
ARAZZO = REPO / "openapi" / "skills" / "arazzo" / "SKILL.md"


class TestInitSkill(unittest.TestCase):
    def test_init_documents_the_pointer_file_and_idempotence(self):
        text = INIT.read_text(encoding="utf-8")
        self.assertIn(".local/openapi/config.yaml", text)
        self.assertIn("openapi_spec", text)
        self.assertIn("arazzo_spec", text)
        # exists -> print and stop
        self.assertIn("already exists", text)

    def test_init_runs_the_discovery_script_and_offers_three_choices(self):
        text = INIT.read_text(encoding="utf-8")
        self.assertIn("${CLAUDE_PLUGIN_ROOT}/scripts/find_specs.py", text)
        lower = text.lower()
        self.assertIn("accept", lower)
        self.assertIn("type a path", lower)
        self.assertIn("cancel", lower)

    def test_init_never_finishes_without_a_verified_spec(self):
        lower = INIT.read_text(encoding="utf-8").lower()
        self.assertIn("never finish without", lower)

    def test_init_handles_gitignore_and_offers_apis_yaml(self):
        text = INIT.read_text(encoding="utf-8")
        self.assertIn(".gitignore", text)
        self.assertIn("apis.yaml", text)

    def test_init_reads_cats_config_as_hint_only(self):
        text = INIT.read_text(encoding="utf-8")
        self.assertIn(".local/cats/config.yaml", text)
        self.assertNotIn("cats_tool.py", text)


if __name__ == "__main__":
    unittest.main()
