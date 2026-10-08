# tests/test_depscan_files.py
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dependency-model" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from depscanlib.files import classify_files
from depscanlib.walk import walk_repo
from repobuilder import build_repo

K8S_DEPLOYMENT = "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: api\n"
COMPOSE = "services:\n  db:\n    image: postgres:16\n"
WORKFLOW = "name: ci\non: [push]\njobs:\n  test:\n    runs-on: ubuntu-latest\n"
SAM = "AWSTemplateFormatVersion: '2010-09-09'\nTransform: AWS::Serverless-2016-10-31\n"
ISSUE_FORM = "name: Bug report\ndescription: file a bug\nbody:\n  - type: input\n"


def classify(files):
    with tempfile.TemporaryDirectory() as tmp:
        root = build_repo(tmp, files)
        paths, _ = walk_repo(root)
        return classify_files(root, paths)


class TestClassifyFiles(unittest.TestCase):
    def test_returns_all_five_keys_even_when_empty(self):
        result = classify({"README.md": "# hi\n"})
        self.assertEqual(sorted(result), ["ci", "compose", "env", "iac", "k8s"])
        self.assertEqual(result["compose"], [])

    def test_detects_compose_by_name(self):
        for name in ("docker-compose.yml", "docker-compose.yaml",
                     "compose.yml", "compose.yaml"):
            with self.subTest(name=name):
                self.assertEqual(classify({name: COMPOSE})["compose"], [name])

    def test_detects_kubernetes_by_content_not_name(self):
        result = classify({"deploy/api.yaml": K8S_DEPLOYMENT,
                           "config/settings.yaml": "debug: true\n"})
        self.assertEqual(result["k8s"], ["deploy/api.yaml"])

    def test_compose_is_never_also_classified_as_kubernetes(self):
        result = classify({"docker-compose.yml": COMPOSE})
        self.assertEqual(result["compose"], ["docker-compose.yml"])
        self.assertEqual(result["k8s"], [])

    def test_detects_iac_by_extension_and_by_name(self):
        result = classify({"infra/main.tf": "resource \"aws_db_instance\" \"x\" {}\n",
                           "infra/vars.tfvars": "region = \"us-east-1\"\n",
                           "chart/Chart.yaml": "name: api\nversion: 0.1.0\n",
                           "cdk.json": "{\"app\": \"node bin/app.js\"}\n"})
        self.assertEqual(result["iac"],
                         ["cdk.json", "chart/Chart.yaml", "infra/main.tf",
                          "infra/vars.tfvars"])

    def test_template_yaml_is_iac_only_when_its_content_says_so(self):
        self.assertEqual(classify({"template.yaml": SAM})["iac"], ["template.yaml"])
        self.assertEqual(
            classify({".github/ISSUE_TEMPLATE/template.yaml": ISSUE_FORM})["iac"], [])

    def test_detects_env_files(self):
        result = classify({".env": "A=1\n", ".env.example": "A=\n",
                           "config/local.env": "B=2\n", "environment.md": "# no\n"})
        self.assertEqual(result["env"],
                         [".env", ".env.example", "config/local.env"])

    def test_detects_ci_config(self):
        result = classify({".github/workflows/ci.yml": WORKFLOW,
                           ".gitlab-ci.yml": "stages: [test]\n",
                           "Jenkinsfile": "pipeline {}\n"})
        self.assertEqual(result["ci"],
                         [".github/workflows/ci.yml", ".gitlab-ci.yml", "Jenkinsfile"])

    def test_every_list_is_sorted(self):
        result = classify({"b/compose.yml": COMPOSE, "a/compose.yml": COMPOSE})
        self.assertEqual(result["compose"], ["a/compose.yml", "b/compose.yml"])


if __name__ == "__main__":
    unittest.main()
