# profile/scripts/inventorylib/infra.py
"""Detect CI, container, IaC, test-config, and entrypoint artifacts."""

import json
from pathlib import Path, PurePosixPath

CI_FILES = {
    ".gitlab-ci.yml": "gitlab-ci",
    "azure-pipelines.yml": "azure-pipelines",
    "Jenkinsfile": "jenkins",
    ".travis.yml": "travis",
    "bitbucket-pipelines.yml": "bitbucket",
    ".circleci/config.yml": "circleci",
}

CONTAINER_FILES = {
    "Dockerfile": "dockerfile",
    "Containerfile": "dockerfile",
    "docker-compose.yml": "compose",
    "docker-compose.yaml": "compose",
    "compose.yml": "compose",
    "compose.yaml": "compose",
}

IAC_FILES = {
    "cdk.json": "cdk",
    "serverless.yml": "serverless",
    "Chart.yaml": "helm",
    "kustomization.yaml": "kustomize",
    "Pulumi.yaml": "pulumi",
}

# template.yaml is not in IAC_FILES: the name alone proves nothing. A GitHub
# issue form, a Backstage software template, and a SAM stack all ship as
# template.yaml. The file's own content decides — see _template_kind.
TEMPLATE_NAMES = {"template.yaml", "template.yml"}
SAM_TRANSFORM = "AWS::Serverless-2016-10-31"
CFN_MARKER = "AWSTemplateFormatVersion"

IAC_EXTS = {".tf": "terraform", ".tfvars": "terraform", ".bicep": "bicep"}

TEST_CONFIG_FILES = {
    "pytest.ini": "pytest",
    "tox.ini": "tox",
    "jest.config.js": "jest",
    "jest.config.ts": "jest",
    "vitest.config.ts": "vitest",
    "playwright.config.ts": "playwright",
    "karma.conf.js": "karma",
    "phpunit.xml": "phpunit",
    ".rspec": "rspec",
}

ENTRYPOINT_NAMES = {
    "main.py", "__main__.py", "manage.py", "app.py", "wsgi.py", "asgi.py",
    "main.go", "main.rs", "Program.cs", "main.ts", "server.js",
}

# index.* is an entrypoint only at the repo root, where it is npm's default
# main. Nested index.ts/index.js files are barrel re-exports by convention:
# on a measured Angular repo, 14 of 16 name-based entrypoint hits were
# barrels. Root-only keeps the true positive and drops the flood.
ROOT_ONLY_ENTRYPOINTS = {"index.ts", "index.js"}

# ordered: first substring found in the command wins
TEST_COMMAND_FRAMEWORKS = (
    ("vitest", "vitest"), ("jest", "jest"), ("playwright", "playwright"),
    ("mocha", "mocha"), ("ava", "ava"), ("cypress", "cypress"),
    ("pytest", "pytest"), ("go test", "go-test"),
)


def _framework_from_command(command):
    lowered = command.lower()
    for needle, framework in TEST_COMMAND_FRAMEWORKS:
        if needle in lowered:
            return framework
    return None


def _template_kind(root, path):
    """Classify a template.yaml by content, or return None to stay silent.

    SAM templates carry the serverless Transform; plain CloudFormation
    carries AWSTemplateFormatVersion. Anything else named template.yaml —
    issue forms, Backstage templates — is not IaC and must not be labeled.
    """
    try:
        text = (Path(root) / path).read_text(encoding="utf-8", errors="replace")[:4096]
    except OSError:
        return None
    if SAM_TRANSFORM in text:
        return "sam"
    if CFN_MARKER in text:
        return "cloudformation"
    return None


def _package_json_test_config(root, path):
    try:
        data = json.loads((Path(root) / path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    scripts = data.get("scripts")
    if not isinstance(scripts, dict):
        return None
    command = scripts.get("test")
    if not isinstance(command, str) or not command.strip():
        return None
    return {
        "path": path,
        "framework": _framework_from_command(command),
        "command": command,
    }


def detect_infra(root, paths):
    """Return infrastructure records grouped by kind, each list sorted by path."""
    ci, containers, iac, test_config, entrypoints = [], [], [], [], []

    for path in sorted(paths):
        parsed = PurePosixPath(path)
        name = parsed.name

        if path.startswith(".github/workflows/"):
            ci.append({"path": path, "system": "github-actions"})
        elif path in CI_FILES:
            ci.append({"path": path, "system": CI_FILES[path]})
        elif name in CI_FILES:
            ci.append({"path": path, "system": CI_FILES[name]})

        if name in CONTAINER_FILES:
            containers.append({"path": path, "kind": CONTAINER_FILES[name]})

        if name in IAC_FILES:
            iac.append({"path": path, "kind": IAC_FILES[name]})
        elif name in TEMPLATE_NAMES:
            kind = _template_kind(root, path)
            if kind:
                iac.append({"path": path, "kind": kind})
        elif parsed.suffix in IAC_EXTS:
            iac.append({"path": path, "kind": IAC_EXTS[parsed.suffix]})

        if name in TEST_CONFIG_FILES:
            test_config.append({
                "path": path,
                "framework": TEST_CONFIG_FILES[name],
                "command": None,
            })
        elif name == "package.json":
            entry = _package_json_test_config(root, path)
            if entry:
                test_config.append(entry)

        if name in ENTRYPOINT_NAMES or (
            name in ROOT_ONLY_ENTRYPOINTS and parsed.parent.as_posix() == "."
        ):
            entrypoints.append({"path": path, "language_hint": parsed.suffix})

    return {
        "ci": ci,
        "containers": containers,
        "iac": iac,
        "test_config": test_config,
        "entrypoints": entrypoints,
    }
