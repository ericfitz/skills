"""Classify repo files into the config surfaces the six categories read."""

from pathlib import PurePosixPath

from depscanlib.walk import read_text

COMPOSE_NAMES = {"docker-compose.yml", "docker-compose.yaml",
                 "compose.yml", "compose.yaml"}

IAC_NAMES = {"cdk.json", "serverless.yml", "serverless.yaml",
             "Chart.yaml", "kustomization.yaml", "kustomization.yml",
             "Pulumi.yaml"}
IAC_EXTS = {".tf", ".tfvars", ".bicep"}

# template.yaml proves nothing by its name — a GitHub issue form, a Backstage
# template, and a SAM stack all ship as one. The content decides.
TEMPLATE_NAMES = {"template.yaml", "template.yml"}
SAM_TRANSFORM = "AWS::Serverless-2016-10-31"
CFN_MARKER = "AWSTemplateFormatVersion"

CI_NAMES = {".gitlab-ci.yml", "azure-pipelines.yml", "Jenkinsfile",
            ".travis.yml", "bitbucket-pipelines.yml"}
CI_PATHS = {".circleci/config.yml", ".circleci/config.yaml"}

YAML_EXTS = {".yaml", ".yml"}
HEAD = 4096


def _is_kubernetes(root, path):
    text = read_text(root, path, HEAD)
    return "apiVersion:" in text and "kind:" in text


def _is_iac_template(root, path):
    text = read_text(root, path, HEAD)
    return SAM_TRANSFORM in text or CFN_MARKER in text


def _is_env_file(name):
    return name == ".env" or name.startswith(".env.") or name.endswith(".env")


def classify_files(root, paths):
    """Return repo-relative paths grouped by config surface, each list sorted.

    A path lands in at most one group. Order of the checks is the precedence:
    compose and CI names win over the content-based kubernetes test, so a
    compose file is never reported as a manifest.
    """
    groups = {"compose": [], "k8s": [], "iac": [], "env": [], "ci": []}

    for path in sorted(paths):
        parsed = PurePosixPath(path)
        name = parsed.name
        suffix = parsed.suffix

        if path.startswith(".github/workflows/") or name in CI_NAMES or path in CI_PATHS:
            groups["ci"].append(path)
        elif name in COMPOSE_NAMES:
            groups["compose"].append(path)
        elif _is_env_file(name):
            groups["env"].append(path)
        elif (name in IAC_NAMES or suffix in IAC_EXTS
              or (name in TEMPLATE_NAMES and _is_iac_template(root, path))):
            groups["iac"].append(path)
        elif suffix in YAML_EXTS and _is_kubernetes(root, path):
            groups["k8s"].append(path)

    return groups
