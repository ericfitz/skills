import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "profile" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from inventorylib.docs import DOC_TYPES, detect_docs, guess_doc_type
from repobuilder import build_repo, git_commit_all, git_init


def census(files, **kwargs):
    with tempfile.TemporaryDirectory() as tmp:
        root = build_repo(tmp, files)
        return detect_docs(root, sorted(files), **kwargs)


class TestGuessDocType(unittest.TestCase):
    def test_readme_and_changelog_by_stem(self):
        self.assertEqual(guess_doc_type("README.md"), "readme")
        self.assertEqual(guess_doc_type("CHANGELOG.md"), "changelog")

    def test_type_from_path_tokens(self):
        cases = {
            "docs/prd-billing.md": "prd",
            "docs/requirements/orders.md": "requirements",
            "docs/adr/0004-use-postgres.md": "adr",
            "docs/rfcs/0001-events.md": "spec",
            "docs/architecture.md": "architecture",
            "docs/runbook-oncall.md": "runbook",
            "docs/api/orders.md": "api_reference",
            "docs/getting-started.md": "tutorial",
            "docs/user-guide.md": "user_guide",
        }
        for path, expected in cases.items():
            with self.subTest(path=path):
                self.assertEqual(guess_doc_type(path), expected)

    def test_untypable_doc_is_unknown_not_a_wrong_guess(self):
        self.assertEqual(guess_doc_type("docs/notes.md"), "unknown")

    def test_tokens_not_substrings(self):
        """'api' in 'capital' is true; token matching must not be fooled."""
        self.assertEqual(guess_doc_type("docs/capital.md"), "unknown")

    def test_filename_tokens_outrank_directory_tokens(self):
        """docs/design/setup-tutorial.md is a tutorial filed under design/."""
        self.assertEqual(guess_doc_type("docs/design/setup-tutorial.md"), "tutorial")
        self.assertEqual(guess_doc_type("docs/specs/deployment-runbook.md"), "runbook")

    def test_nearest_directory_wins_when_the_filename_says_nothing(self):
        self.assertEqual(guess_doc_type("docs/design/api/orders.md"), "api_reference")

    def test_every_guess_is_in_the_fixed_vocabulary(self):
        for path in ("README.md", "docs/x.md", "docs/adr/1-y.md", "CHANGELOG.md"):
            with self.subTest(path=path):
                self.assertIn(guess_doc_type(path), DOC_TYPES)


class TestDetectDocs(unittest.TestCase):
    def test_collects_named_docs_and_doc_directories(self):
        found = census({
            "README.md": "# x\n",
            "docs/guide.md": "# y\n",
            "specs/auth.md": "# z\n",
            "src/app.py": "x = 1\n",
        })
        self.assertEqual([d["path"] for d in found["docs"]],
                         ["README.md", "docs/guide.md", "specs/auth.md"])

    def test_markdown_beside_code_is_not_documentation(self):
        found = census({"src/notes.md": "# z\n"})
        self.assertEqual(found["docs"], [])

    def test_size_is_recorded(self):
        found = census({"docs/guide.md": "hello\n"})
        self.assertEqual(found["docs"][0]["size"], 6)

    def test_last_modified_is_null_outside_git(self):
        found = census({"docs/guide.md": "# y\n"})
        self.assertIsNone(found["docs"][0]["last_modified"])

    def test_last_modified_comes_from_git_when_committed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {"docs/guide.md": "# y\n"})
            git_init(root)
            git_commit_all(root)
            found = detect_docs(root, ["docs/guide.md"])
        stamp = found["docs"][0]["last_modified"]
        self.assertIsInstance(stamp, str)
        self.assertRegex(stamp, r"^\d{4}-\d{2}-\d{2}T")

    def test_git_lookups_are_capped(self):
        with tempfile.TemporaryDirectory() as tmp:
            files = {"docs/d%02d.md" % i: "# x\n" for i in range(3)}
            root = build_repo(tmp, files)
            git_init(root)
            git_commit_all(root)
            found = detect_docs(root, sorted(files), max_git_lookups=1)
        stamps = [d["last_modified"] for d in found["docs"]]
        self.assertIsInstance(stamps[0], str)
        self.assertEqual(stamps[1:], [None, None])

    def test_doc_sites_detected(self):
        found = census({"mkdocs.yml": "site_name: x\n",
                        "web/docusaurus.config.js": "module.exports = {}\n"})
        self.assertEqual(
            [(s["path"], s["generator"]) for s in found["docs_sites"]],
            [("mkdocs.yml", "mkdocs"), ("web/docusaurus.config.js", "docusaurus")])

    def test_sphinx_conf_counts_only_inside_a_doc_directory(self):
        found = census({"docs/conf.py": "project = 'x'\n", "src/conf.py": "X = 1\n"})
        self.assertEqual([s["path"] for s in found["docs_sites"]], ["docs/conf.py"])

    def test_no_documentation_yields_empty_lists_not_guesses(self):
        found = census({"src/app.py": "x = 1\n"})
        self.assertEqual(found["docs"], [])
        self.assertEqual(found["docs_sites"], [])

    def test_missing_file_does_not_raise(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {"docs/a.md": "# a\n"})
            found = detect_docs(root, ["docs/a.md", "docs/gone.md"])
        self.assertEqual([d["size"] for d in found["docs"]], [4, None])


if __name__ == "__main__":
    unittest.main()
