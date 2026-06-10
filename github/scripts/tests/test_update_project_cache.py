import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import update_project_cache as upc


class TestScaffold(unittest.TestCase):
    def test_constants_exist(self):
        self.assertEqual(upc.CONFIG_FILENAME, "projects.json")
        self.assertEqual(upc.CACHE_FILENAME, "project-cache.json")
        self.assertEqual(upc.LOCAL_DIR, ".local")
        self.assertEqual(upc.LEGACY_CONFIG_FILENAME, ".local-projects.json")


class TestParseGitRemote(unittest.TestCase):
    def test_https_with_git_suffix(self):
        self.assertEqual(upc.parse_git_remote("https://github.com/ericfitz/tmi.git"),
                         ("ericfitz", "tmi"))

    def test_https_no_suffix(self):
        self.assertEqual(upc.parse_git_remote("https://github.com/ericfitz/tmi"),
                         ("ericfitz", "tmi"))

    def test_ssh_form(self):
        self.assertEqual(upc.parse_git_remote("git@github.com:ericfitz/tmi.git"),
                         ("ericfitz", "tmi"))

    def test_empty(self):
        self.assertEqual(upc.parse_git_remote(""), (None, None))

    def test_garbage(self):
        self.assertEqual(upc.parse_git_remote("not-a-url"), (None, None))


if __name__ == "__main__":
    unittest.main()
