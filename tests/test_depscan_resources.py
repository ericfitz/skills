# tests/test_depscan_resources.py
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dependency-model" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from depscanlib.files import classify_files
from depscanlib.resources import scan_resources
from depscanlib.walk import walk_repo
from repobuilder import build_repo

K8S = (
    "apiVersion: apps/v1\n"
    "kind: Deployment\n"
    "spec:\n"
    "  template:\n"
    "    spec:\n"
    "      containers:\n"
    "        - name: api\n"
    "          resources:\n"
    "            limits:\n"
    "              cpu: \"2\"\n"
    "              memory: 512Mi\n"
    "              nvidia.com/gpu: 1\n"
    "            requests:\n"
    "              cpu: 500m\n"
)

COMPOSE = (
    "services:\n"
    "  app:\n"
    "    image: api:latest\n"
    "    mem_limit: 1g\n"
    "    cpus: 1.5\n"
    "    deploy:\n"
    "      resources:\n"
    "        limits:\n"
    "          memory: 2G\n"
)

DOCKERFILE = (
    "FROM --platform=linux/amd64 python:3.11-slim\n"
    "RUN pip install -r requirements.txt\n"
)

K8S_TRAILING_COMMENT = (
    "apiVersion: apps/v1\n"
    "kind: Deployment\n"
    "spec:\n"
    "  containers:\n"
    "    - resources:\n"
    "        limits:\n"
    "          memory: 512Mi  # bump later\n"
    "          cpu: \"2\"\n"
)

COMPOSE_TRAILING_COMMENT = (
    "services:\n"
    "  app:\n"
    "    mem_limit: 1g  # raised after OOM\n"
    "    cpus: 1.5\n"
)


def scan(files):
    with tempfile.TemporaryDirectory() as tmp:
        root = build_repo(tmp, files)
        paths, _ = walk_repo(root)
        return scan_resources(root, paths, classify_files(root, paths))


def kinds(records):
    return sorted({r["kind"] for r in records})


class TestKubernetesResources(unittest.TestCase):
    def test_extracts_cpu_memory_and_gpu_limits(self):
        records = scan({"deploy/api.yaml": K8S})
        self.assertEqual(kinds(records), ["cpu", "gpu", "memory"])

    def test_records_the_declared_figure_verbatim(self):
        records = scan({"deploy/api.yaml": K8S})
        memory = [r for r in records if r["kind"] == "memory"]
        self.assertEqual(memory[0]["raw"], "512Mi")

    def test_records_source_and_one_indexed_line(self):
        records = scan({"deploy/api.yaml": K8S})
        self.assertTrue(records)
        self.assertTrue(all(r["source"] == "kubernetes" for r in records))
        self.assertTrue(all(r["line"] >= 1 for r in records))

    def test_requests_are_captured_as_well_as_limits(self):
        records = scan({"deploy/api.yaml": K8S})
        self.assertEqual(len([r for r in records if r["kind"] == "cpu"]), 2)

    def test_trailing_comment_does_not_drop_the_line(self):
        records = scan({"deploy/api.yaml": K8S_TRAILING_COMMENT})
        self.assertEqual(kinds(records), ["cpu", "memory"])
        memory = next(r for r in records if r["kind"] == "memory")
        self.assertEqual(memory["raw"], "512Mi")


class TestComposeResources(unittest.TestCase):
    def test_extracts_short_form_and_deploy_form(self):
        records = scan({"docker-compose.yml": COMPOSE})
        self.assertEqual(kinds(records), ["cpu", "memory"])
        self.assertEqual(sorted(r["raw"] for r in records if r["kind"] == "memory"),
                         ["1g", "2G"])

    def test_source_is_compose(self):
        records = scan({"docker-compose.yml": COMPOSE})
        self.assertTrue(records)
        self.assertTrue(all(r["source"] == "compose" for r in records))

    def test_trailing_comment_does_not_drop_the_line(self):
        records = scan({"docker-compose.yml": COMPOSE_TRAILING_COMMENT})
        self.assertEqual(kinds(records), ["cpu", "memory"])
        memory = next(r for r in records if r["kind"] == "memory")
        self.assertEqual(memory["raw"], "1g")


class TestDockerfileResources(unittest.TestCase):
    def test_extracts_platform_and_runtime_version(self):
        records = scan({"Dockerfile": DOCKERFILE})
        self.assertEqual(kinds(records), ["arch", "runtime-version"])
        arch = next(r for r in records if r["kind"] == "arch")
        self.assertEqual(arch["raw"], "linux/amd64")
        self.assertEqual(arch["source"], "dockerfile")

    def test_base_image_without_platform_still_yields_runtime_version(self):
        records = scan({"Dockerfile": "FROM golang:1.23-alpine AS build\n"})
        self.assertEqual(kinds(records), ["runtime-version"])
        self.assertEqual(records[0]["raw"], "golang:1.23-alpine")

    def test_dockerfile_dot_suffix_variant_is_scanned(self):
        records = scan({"Dockerfile.dev": DOCKERFILE})
        self.assertEqual(kinds(records), ["arch", "runtime-version"])

    def test_dot_dockerfile_extension_variant_is_scanned(self):
        records = scan({"backend.dockerfile": DOCKERFILE})
        self.assertEqual(kinds(records), ["arch", "runtime-version"])


class TestNoise(unittest.TestCase):
    def test_a_yaml_that_is_not_a_manifest_yields_nothing(self):
        records = scan({"config/app.yaml": "cpu: 2\nmemory: 512Mi\n"})
        self.assertEqual(records, [])

    def test_sorted_by_file_then_line(self):
        records = scan({"b/Dockerfile": DOCKERFILE, "a/Dockerfile": DOCKERFILE})
        self.assertEqual([r["file"] for r in records][:2],
                         ["a/Dockerfile", "a/Dockerfile"])


if __name__ == "__main__":
    unittest.main()
