"""Discovery, parsing and validation of .local/cats/config.yaml."""

from __future__ import annotations

import os
import string
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

CONFIG_RELPATH = Path(".local") / "cats" / "config.yaml"
SUPPORTED_VERSIONS = {1}

TOP_LEVEL_KEYS = {
    "version", "spec", "server", "health_url", "results_dir", "false_positives",
    "retain_raw_report", "allow_suppressing_5xx", "identities", "default_identity",
    "auth", "hooks", "cats", "allow_port_forward", "max_connection_error_pct",
    "keep_runs",
}
CATS_KEYS = {
    "http_methods", "max_requests_per_minute", "ref_data", "skip_field_format",
    "skip_field", "skip_fuzzers", "skip_fuzzers_for_extension", "extra_args",
}
HOOK_KEYS = {"seed", "pre_run", "post_run"}
REQUIRED = ("spec", "server", "results_dir", "false_positives", "identities")


class ConfigError(Exception):
    """Raised with an actionable message when a config is missing or invalid."""


@dataclass(frozen=True)
class Identity:
    name: str
    token_cmd: str


@dataclass(frozen=True)
class Hooks:
    seed: str | None = None
    pre_run: str | None = None
    post_run: str | None = None


@dataclass(frozen=True)
class CatsOptions:
    # No field defaults here: `load_config` is the sole constructor and always
    # passes every field explicitly, applying its own defaults (mirrored in
    # render_init_config) for absent config keys. Defaults on both sides had
    # nothing keeping them in sync — editing this dataclass had no effect.
    http_methods: list[str]
    max_requests_per_minute: int
    ref_data: Path | None
    skip_field_format: list[str]
    skip_field: list[str]
    skip_fuzzers: list[str]
    skip_fuzzers_for_extension: list[dict[str, Any]]
    extra_args: list[str]


@dataclass(frozen=True)
class Config:
    repo_root: Path
    config_path: Path
    spec: Path
    server: str
    health_url: str
    results_dir: Path
    false_positives: Path
    retain_raw_report: bool
    allow_suppressing_5xx: bool
    allow_port_forward: bool
    max_connection_error_pct: float
    keep_runs: int
    identities: dict[str, Identity]
    default_identity: str
    auth_header: str
    auth_template: str
    hooks: Hooks
    cats: CatsOptions

    def identity(self, name: str | None) -> Identity:
        key = name or self.default_identity
        if key not in self.identities:
            raise ConfigError(
                f"{self.config_path}: unknown identity {key!r}; configured: {sorted(self.identities)}"
            )
        return self.identities[key]


def find_config(start: Path) -> Path | None:
    """Walk up from *start* looking for .local/cats/config.yaml."""
    # os.path.abspath normalizes ".." lexically without touching symlinks, so a
    # symlinked checkout still resolves against its logical (not physical) ancestors.
    current = Path(os.path.abspath(start))
    for directory in [current, *current.parents]:
        candidate = directory / CONFIG_RELPATH
        if candidate.is_file():
            return candidate
    return None


def _reject_unknown(section: Any, allowed: set[str], where: str, path: Path) -> None:
    if not isinstance(section, dict):
        raise ConfigError(f"{path}: '{where}' must be a mapping")
    unknown = sorted(set(section) - allowed)
    if unknown:
        raise ConfigError(f"{path}: unknown key(s) in {where}: {', '.join(unknown)}")


def _require_str(value: Any, key: str, path: Path) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"{path}: '{key}' must be a string, got {type(value).__name__}")
    return value


def _require_list(value: Any, key: str, path: Path) -> list:
    if not isinstance(value, list):
        raise ConfigError(f"{path}: '{key}' must be a list, got {type(value).__name__}")
    return value


def _require_bool(value: Any, key: str, path: Path, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ConfigError(f"{path}: '{key}' must be a boolean, got {type(value).__name__}")
    return value


def _require_pct(value: Any, key: str, path: Path, default: float) -> float:
    if value is None:
        return default
    try:
        pct = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{path}: '{key}' must be a number, got {value!r}") from exc
    if not 0.0 <= pct <= 100.0:
        raise ConfigError(f"{path}: '{key}' must be between 0 and 100, got {pct!r}")
    return pct


def _require_nonneg_int(value: Any, key: str, path: Path, default: int) -> int:
    if value is None:
        return default
    # bool is an int subclass in Python (isinstance(True, int) is True), so a
    # naive isinstance(value, int) check would silently accept `keep_runs: true`
    # as 1 — reject bools explicitly before the int check.
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{path}: '{key}' must be a non-negative integer, got {value!r}")
    if value < 0:
        raise ConfigError(f"{path}: '{key}' must be a non-negative integer, got {value!r}")
    return value


def _validate_auth_template(template: str, path: Path) -> None:
    """Reject any replacement field other than 'token' before it ever reaches
    `.format(token=token)` at call time — an unknown field name raises an
    uncaught KeyError there, and a bare `{}` raises IndexError."""
    for _literal, field_name, _spec, _conversion in string.Formatter().parse(template):
        if field_name is not None and field_name != "token":
            raise ConfigError(
                f"{path}: 'auth.template' has unsupported placeholder {{{field_name}}}; "
                "only {token} is allowed"
            )


def load_config(path: Path) -> Config:
    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except OSError as exc:
        raise ConfigError(f"{path}: cannot read config: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise ConfigError(f"{path}: not valid UTF-8: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: invalid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: top level must be a mapping")

    version = raw.get("version", 1)
    if version not in SUPPORTED_VERSIONS:
        raise ConfigError(
            f"{path}: unsupported version {version!r}; supported: {sorted(SUPPORTED_VERSIONS)}"
        )
    _reject_unknown(raw, TOP_LEVEL_KEYS, "top level", path)
    for key in REQUIRED:
        if not raw.get(key):
            raise ConfigError(f"{path}: missing required key {key!r}")

    # repo_root is the directory containing .local/
    repo_root = path.parents[2]

    spec_raw = _require_str(raw["spec"], "spec", path)
    server_raw = _require_str(raw["server"], "server", path)
    results_dir_raw = _require_str(raw["results_dir"], "results_dir", path)
    false_positives_raw = _require_str(raw["false_positives"], "false_positives", path)

    health_url_value = raw.get("health_url")
    if health_url_value is not None:
        health_url_raw = _require_str(health_url_value, "health_url", path)
        if not health_url_raw:
            raise ConfigError(f"{path}: 'health_url' must not be empty; omit it to default to 'server'")
    else:
        health_url_raw = server_raw

    identities_raw = raw["identities"]
    if not isinstance(identities_raw, dict) or not identities_raw:
        raise ConfigError(f"{path}: 'identities' must be a non-empty mapping")
    identities: dict[str, Identity] = {}
    for name, spec in identities_raw.items():
        if not isinstance(spec, dict) or not spec.get("token_cmd"):
            raise ConfigError(f"{path}: identity {name!r} needs a 'token_cmd'")
        token_cmd = _require_str(spec["token_cmd"], f"identities.{name}.token_cmd", path)
        identities[name] = Identity(name=name, token_cmd=token_cmd)

    default_identity = raw.get("default_identity") or next(iter(identities))
    if default_identity not in identities:
        raise ConfigError(
            f"{path}: default_identity {default_identity!r} is not defined in 'identities'"
        )

    auth = raw.get("auth") or {}
    _reject_unknown(auth, {"header", "template"}, "auth", path)
    auth_template = auth.get("template") or "Bearer {token}"
    _validate_auth_template(auth_template, path)

    hooks_raw = raw.get("hooks") or {}
    _reject_unknown(hooks_raw, HOOK_KEYS, "hooks", path)
    hooks = Hooks(
        seed=hooks_raw.get("seed") or None,
        pre_run=hooks_raw.get("pre_run") or None,
        post_run=hooks_raw.get("post_run") or None,
    )

    cats_raw = raw.get("cats") or {}
    _reject_unknown(cats_raw, CATS_KEYS, "cats", path)

    http_methods_value = cats_raw.get("http_methods")
    http_methods = (
        _require_list(http_methods_value, "cats.http_methods", path)
        if http_methods_value is not None
        else ["POST", "PUT", "GET", "DELETE", "PATCH"]
    )

    mrpm_raw = cats_raw.get("max_requests_per_minute", 3000)
    try:
        max_requests_per_minute = int(mrpm_raw)
    except (TypeError, ValueError) as exc:
        raise ConfigError(
            f"{path}: 'cats.max_requests_per_minute' must be an integer, got {mrpm_raw!r}"
        ) from exc

    ref_data_value = cats_raw.get("ref_data")
    if ref_data_value is not None:
        ref_data_str = _require_str(ref_data_value, "cats.ref_data", path)
        if not ref_data_str:
            raise ConfigError(f"{path}: 'cats.ref_data' must not be empty; omit it to leave unset")
        ref_data = repo_root / ref_data_str
    else:
        ref_data = None

    skip_field_format = _require_list(
        cats_raw.get("skip_field_format", []), "cats.skip_field_format", path
    )
    skip_field = _require_list(cats_raw.get("skip_field", []), "cats.skip_field", path)
    skip_fuzzers = _require_list(cats_raw.get("skip_fuzzers", []), "cats.skip_fuzzers", path)
    skip_fuzzers_for_extension = _require_list(
        cats_raw.get("skip_fuzzers_for_extension", []), "cats.skip_fuzzers_for_extension", path
    )
    extra_args = _require_list(cats_raw.get("extra_args", []), "cats.extra_args", path)

    for entry in skip_fuzzers_for_extension:
        if not isinstance(entry, dict) or not {"extension", "fuzzers"} <= set(entry):
            raise ConfigError(
                f"{path}: each skip_fuzzers_for_extension entry needs 'extension' and 'fuzzers'"
            )

    cats_opts = CatsOptions(
        http_methods=http_methods,
        max_requests_per_minute=max_requests_per_minute,
        ref_data=ref_data,
        skip_field_format=skip_field_format,
        skip_field=skip_field,
        skip_fuzzers=skip_fuzzers,
        skip_fuzzers_for_extension=skip_fuzzers_for_extension,
        extra_args=extra_args,
    )

    return Config(
        repo_root=repo_root,
        config_path=path,
        spec=repo_root / spec_raw,
        server=server_raw.rstrip("/"),
        health_url=health_url_raw.rstrip("/"),
        results_dir=repo_root / results_dir_raw,
        false_positives=repo_root / false_positives_raw,
        retain_raw_report=_require_bool(
            raw.get("retain_raw_report"), "retain_raw_report", path, False
        ),
        allow_suppressing_5xx=_require_bool(
            raw.get("allow_suppressing_5xx"), "allow_suppressing_5xx", path, False
        ),
        allow_port_forward=_require_bool(
            raw.get("allow_port_forward"), "allow_port_forward", path, False
        ),
        max_connection_error_pct=_require_pct(
            raw.get("max_connection_error_pct"), "max_connection_error_pct", path, 1.0
        ),
        keep_runs=_require_nonneg_int(raw.get("keep_runs"), "keep_runs", path, 5),
        identities=identities,
        default_identity=default_identity,
        auth_header=auth.get("header") or "Authorization",
        auth_template=auth_template,
        hooks=hooks,
        cats=cats_opts,
    )


INITIAL_RULES_YAML = """# CATS false-positive rules.
#
# Rules are evaluated in file order; the FIRST match wins and its id is recorded
# on the test row. Only 'error' and 'warn' results are classified.
#
# Fields: result, response_code, fuzzer, path, contract_path, method, url, scenario,
#         result_reason, result_details, any_text (reason + details), response_body,
#         response_content_type, request_body, json_body.<dotted.path>,
#         request_header.<name>
# Operators: equals (bare scalar), in, not_equals, contains, contains_any,
#            contains_all, starts_with, starts_with_any, ends_with, matches, exists
# equals/in/not_equals are case-sensitive; the rest are case-insensitive.
version: 1
rules:
  - id: RATE_LIMIT_429
    why: Rate limiting is infrastructure protection, not API behavior under test.
    when: {response_code: 429}

  - id: CONNECTION_ERROR_999
    why: CATS reports 999 for transport/connection failures, not API defects.
    when: {response_code: 999}
"""


def render_init_config(*, spec: str, server: str, health_url: str,
                       results_dir: str, rules: str) -> str:
    return f"""# CATS tooling configuration (machine-local; not committed).
version: 1

spec: {spec}
server: {server}
health_url: {health_url}
results_dir: {results_dir}
false_positives: {rules}

# Delete the raw CATS report after a successful parse (it is large and redundant
# once results are in SQLite). Set to true to keep it.
retain_raw_report: false
# Refuse any rule that would suppress a 5xx response.
allow_suppressing_5xx: false
# Refuse to fuzz through a kubectl port-forward bound to `server`'s port — a
# userspace forward silently drops requests under load, producing a run that
# looks clean but never reached most of the API. Set to true only if you
# understand and accept that risk (or use `run --allow-port-forward`).
allow_port_forward: false
# Maximum percentage of tests that may fail with a connection error (CATS
# codes 953/999) before a completed run is considered invalid and latest.db
# is not updated to point at it.
max_connection_error_pct: 1.0
# How many of the most recent per-run databases (cats-results-<run_id>.db) to
# keep; older ones are deleted after a successful run. Each run's database is
# roughly 1.4 GB, so the default keeps the results directory near 7 GB while
# still allowing run-over-run comparison across a normal fix-verify cycle.
# Set to 0 to disable pruning entirely. `latest.db`'s target is always kept
# regardless of this setting. Only a successful, uncontaminated run prunes —
# see `run --no-prune` to skip pruning for a single invocation.
keep_runs: 5

identities:
  default:
    # Command printing a bearer token on stdout. Nothing else may go to stdout.
    token_cmd: "echo REPLACE_ME"
default_identity: default
auth:
  header: Authorization
  template: "Bearer {{token}}"

# Shell commands run at pipeline stages. Any language or toolchain.
# Each receives CATS_SERVER, CATS_SPEC, CATS_RESULTS_DIR, CATS_REPORT_DIR,
# CATS_RUN_ID and CATS_IDENTITY; post_run also gets CATS_DB and CATS_EXIT_CODE.
hooks:
  seed: ""
  pre_run: ""
  post_run: ""

cats:
  http_methods: [POST, PUT, GET, DELETE, PATCH]
  max_requests_per_minute: 3000
  # ref_data: test/results/cats/cats-test-data.yml
  skip_field_format: []
  skip_field: []
  skip_fuzzers: []
  skip_fuzzers_for_extension: []
  extra_args: ["--printExecutionStatistics"]
"""
