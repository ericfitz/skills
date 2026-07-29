# tests/test_profile_infra.py
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "profile" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from inventorylib.infra import detect_infra
from repobuilder import build_repo


def infra(files):
    with tempfile.TemporaryDirectory() as tmp:
        root = build_repo(tmp, files)
        return detect_infra(root, sorted(files))


class TestDetectInfra(unittest.TestCase):
    def test_github_workflows_are_ci(self):
        found = infra({".github/workflows/test.yml": "on: push\n"})
        self.assertEqual(found["ci"], [{"path": ".github/workflows/test.yml",
                                        "system": "github-actions"}])

    def test_gitlab_ci_detected(self):
        found = infra({".gitlab-ci.yml": "stages: [test]\n"})
        self.assertEqual(found["ci"][0]["system"], "gitlab-ci")

    def test_compose_and_dockerfile_detected(self):
        found = infra({"Dockerfile": "FROM scratch\n",
                       "docker-compose.yml": "services: {}\n"})
        kinds = {entry["kind"] for entry in found["containers"]}
        self.assertEqual(kinds, {"dockerfile", "compose"})

    def test_terraform_detected_by_extension(self):
        found = infra({"infra/main.tf": "resource {}\n"})
        self.assertEqual(found["iac"][0]["kind"], "terraform")

    def test_pytest_ini_is_test_config(self):
        found = infra({"pytest.ini": "[pytest]\n"})
        self.assertEqual(found["test_config"][0]["framework"], "pytest")

    def test_package_json_test_script_becomes_test_config(self):
        found = infra({"package.json": '{"scripts": {"test": "vitest run"}}\n'})
        entry = found["test_config"][0]
        self.assertEqual(entry["path"], "package.json")
        self.assertEqual(entry["command"], "vitest run")
        self.assertEqual(entry["framework"], "vitest")

    def test_malformed_package_json_is_skipped_silently(self):
        found = infra({"package.json": "{not json\n"})
        self.assertEqual(found["test_config"], [])

    def test_entrypoints_detected(self):
        found = infra({"cmd/server/main.go": "package main\n", "manage.py": "x = 1\n"})
        paths = {entry["path"] for entry in found["entrypoints"]}
        self.assertEqual(paths, {"cmd/server/main.go", "manage.py"})

    def test_nested_index_is_a_barrel_not_an_entrypoint(self):
        found = infra({"index.js": "run()\n",
                       "src/components/Button/index.ts": "export * from './Button'\n"})
        paths = {entry["path"] for entry in found["entrypoints"]}
        self.assertEqual(paths, {"index.js"})

    def test_sam_template_detected_by_transform(self):
        found = infra({"template.yaml":
                       "Transform: AWS::Serverless-2016-10-31\nResources: {}\n"})
        self.assertEqual(found["iac"][0]["kind"], "sam")

    def test_plain_cloudformation_is_not_called_sam(self):
        found = infra({"infra/template.yaml":
                       "AWSTemplateFormatVersion: '2010-09-09'\nResources: {}\n"})
        self.assertEqual(found["iac"][0]["kind"], "cloudformation")

    def test_issue_form_template_is_not_iac(self):
        found = infra({".github/ISSUE_TEMPLATE/template.yml":
                       "name: Bug report\nbody: []\n"})
        self.assertEqual(found["iac"], [])

    def test_documentation_is_not_this_modules_job(self):
        """Docs are censused by inventorylib.docs (Task 5b), not here."""
        found = infra({"README.md": "# x\n"})
        self.assertNotIn("docs", found)


if __name__ == "__main__":
    unittest.main()
