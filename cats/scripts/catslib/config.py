"""Discovery, parsing and validation of .local/cats/config.yaml."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

CONFIG_RELPATH = Path(".local") / "cats" / "config.yaml"
SUPPORTED_VERSIONS = {1}

TOP_LEVEL_KEYS = {
    "version", "spec", "server", "health_url", "results_dir", "false_positives",
    "retain_raw_report", "allow_suppressing_5xx", "identities", "default_identity",
    "auth", "hooks", "cats",
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
    http_methods: list[str] = field(default_factory=lambda: ["POST", "PUT", "GET", "DELETE", "PATCH"])
    max_requests_per_minute: int = 3000
    ref_data: Path | None = None
    skip_field_format: list[str] = field(default_factory=list)
    skip_field: list[str] = field(default_factory=list)
    skip_fuzzers: list[str] = field(default_factory=list)
    skip_fuzzers_for_extension: list[dict[str, Any]] = field(default_factory=list)
    extra_args: list[str] = field(default_factory=list)


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
                f"unknown identity {key!r}; configured: {sorted(self.identities)}"
            )
        return self.identities[key]


def find_config(start: Path) -> Path | None:
    """Walk up from *start* looking for .local/cats/config.yaml."""
    current = start.absolute()
    for directory in [current, *current.parents]:
        candidate = directory / CONFIG_RELPATH
        if candidate.is_file():
            return candidate
    return None


def _reject_unknown(keys, allowed, where: str) -> None:
    unknown = sorted(set(keys) - allowed)
    if unknown:
        raise ConfigError(f"unknown key(s) in {where}: {', '.join(unknown)}")


def load_config(path: Path) -> Config:
    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: invalid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: top level must be a mapping")

    version = raw.get("version", 1)
    if version not in SUPPORTED_VERSIONS:
        raise ConfigError(
            f"{path}: unsupported version {version!r}; supported: {sorted(SUPPORTED_VERSIONS)}"
        )
    _reject_unknown(raw, TOP_LEVEL_KEYS, str(path))
    for key in REQUIRED:
        if not raw.get(key):
            raise ConfigError(f"{path}: missing required key {key!r}")

    # repo_root is the directory containing .local/
    repo_root = path.parents[2]

    identities_raw = raw["identities"]
    if not isinstance(identities_raw, dict) or not identities_raw:
        raise ConfigError(f"{path}: 'identities' must be a non-empty mapping")
    identities: dict[str, Identity] = {}
    for name, spec in identities_raw.items():
        if not isinstance(spec, dict) or not spec.get("token_cmd"):
            raise ConfigError(f"{path}: identity {name!r} needs a 'token_cmd'")
        identities[name] = Identity(name=name, token_cmd=spec["token_cmd"])

    default_identity = raw.get("default_identity") or next(iter(identities))
    if default_identity not in identities:
        raise ConfigError(
            f"{path}: default_identity {default_identity!r} is not defined in 'identities'"
        )

    auth = raw.get("auth") or {}
    _reject_unknown(auth, {"header", "template"}, "auth")

    hooks_raw = raw.get("hooks") or {}
    _reject_unknown(hooks_raw, HOOK_KEYS, "hooks")
    hooks = Hooks(
        seed=hooks_raw.get("seed") or None,
        pre_run=hooks_raw.get("pre_run") or None,
        post_run=hooks_raw.get("post_run") or None,
    )

    cats_raw = raw.get("cats") or {}
    _reject_unknown(cats_raw, CATS_KEYS, "cats")
    for entry in cats_raw.get("skip_fuzzers_for_extension", []):
        if not isinstance(entry, dict) or not {"extension", "fuzzers"} <= set(entry):
            raise ConfigError(
                f"{path}: each skip_fuzzers_for_extension entry needs 'extension' and 'fuzzers'"
            )
    ref_data = cats_raw.get("ref_data")
    cats_opts = CatsOptions(
        http_methods=cats_raw.get("http_methods") or ["POST", "PUT", "GET", "DELETE", "PATCH"],
        max_requests_per_minute=int(cats_raw.get("max_requests_per_minute", 3000)),
        ref_data=(repo_root / ref_data) if ref_data else None,
        skip_field_format=cats_raw.get("skip_field_format") or [],
        skip_field=cats_raw.get("skip_field") or [],
        skip_fuzzers=cats_raw.get("skip_fuzzers") or [],
        skip_fuzzers_for_extension=cats_raw.get("skip_fuzzers_for_extension") or [],
        extra_args=cats_raw.get("extra_args") or [],
    )

    return Config(
        repo_root=repo_root,
        config_path=path,
        spec=repo_root / raw["spec"],
        server=raw["server"].rstrip("/"),
        health_url=(raw.get("health_url") or raw["server"]).rstrip("/"),
        results_dir=repo_root / raw["results_dir"],
        false_positives=repo_root / raw["false_positives"],
        retain_raw_report=bool(raw.get("retain_raw_report", False)),
        allow_suppressing_5xx=bool(raw.get("allow_suppressing_5xx", False)),
        identities=identities,
        default_identity=default_identity,
        auth_header=auth.get("header") or "Authorization",
        auth_template=auth.get("template") or "Bearer {token}",
        hooks=hooks,
        cats=cats_opts,
    )
