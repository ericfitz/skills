"""Calibration loading and per-genre resolution.

Reads calibration.toml, applies the genre profile overrides, exposes a
flat dotted-path lookup interface for checks. Echoes the resolved
threshold values back into the JSON output for traceability.
"""
from __future__ import annotations

import hashlib
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Config:
    """Resolved configuration for a single analysis run."""
    raw_data: dict[str, Any]
    genre: str
    genre_profile_applied: str  # which profile was actually used (may differ from genre)
    calibration_file_sha256: str
    active_thresholds: dict[str, Any] = field(default_factory=dict)
    spacy_model_name: str = "en_core_web_sm"
    spacy_model_version_min: str = "3.7.0"
    checks_disabled: set[str] = field(default_factory=set)
    checks_required: dict[str, bool] = field(default_factory=dict)

    def get(self, dotted_path: str, default: Any = None) -> Any:
        """Look up a threshold by dotted path (e.g. 'density.passive.warn_ratio').

        Resolves against the resolved (post-override) values.
        """
        # Walk the default tree, applying overrides.
        keys = dotted_path.split(".")
        cur: Any = self.raw_data["default"]
        try:
            for k in keys:
                cur = cur[k]
        except (KeyError, TypeError):
            return default
        # If an override exists, prefer that
        if dotted_path in self.active_thresholds:
            return self.active_thresholds[dotted_path]
        return cur

    def is_check_disabled(self, check_code: str | None = None, check_path: str | None = None) -> bool:
        """A check is disabled if its check_path is in the genre's checks_disabled set."""
        return bool(check_path and check_path in self.checks_disabled)

    def is_required(self, requirement_name: str, default: bool = False) -> bool:
        return self.checks_required.get(requirement_name, default)


def load_config(
    calibration_path: str | Path,
    genre: str | None = None,
) -> Config:
    """Load calibration.toml and resolve overrides for the chosen genre.

    Parameters
    ----------
    calibration_path : path to calibration.toml
    genre : declared genre. If None or unknown, falls back to "default" — i.e.,
            no profile-specific overrides are applied.
    """
    path = Path(calibration_path)
    raw = path.read_bytes()
    file_sha = "sha256:" + hashlib.sha256(raw).hexdigest()
    data = tomllib.loads(raw.decode("utf-8"))

    spacy_model_name = data.get("meta", {}).get("spacy_model_required", "en_core_web_sm")
    spacy_min = data.get("meta", {}).get("spacy_model_version_min", "3.7.0")

    # Resolve genre profile
    genre_profile_applied = "default"
    overrides: dict[str, Any] = {}
    checks_disabled: set[str] = set()
    checks_required: dict[str, bool] = {}

    if genre and genre in data.get("genre", {}):
        genre_profile_applied = genre
        profile = data["genre"][genre]
        overrides = profile.get("overrides", {}) or {}
        disabled_block = profile.get("checks_disabled", {}) or {}
        if "items" in disabled_block:
            checks_disabled = set(disabled_block["items"])
        required_block = profile.get("checks_required", {}) or {}
        # checks_required is a flat boolean map at this level
        checks_required = {k: bool(v) for k, v in required_block.items()}

    # Build active_thresholds: for traceability, every threshold a check
    # might read should be resolvable. Echo only the ones overridden,
    # plus we'll let `get()` fall through to defaults for the rest.
    active_thresholds = dict(overrides)

    return Config(
        raw_data=data,
        genre=genre or "",
        genre_profile_applied=genre_profile_applied,
        calibration_file_sha256=file_sha,
        active_thresholds=active_thresholds,
        spacy_model_name=spacy_model_name,
        spacy_model_version_min=spacy_min,
        checks_disabled=checks_disabled,
        checks_required=checks_required,
    )


def resolve_threshold_snapshot(config: Config, paths: list[str]) -> dict[str, Any]:
    """Build a snapshot of active threshold values for the given paths.

    Used to populate the `active_thresholds` block in the JSON output.
    Includes both default-derived values and any genre-applied overrides,
    so the report can show the exact number used in scoring.
    """
    snapshot: dict[str, Any] = {}
    for p in paths:
        snapshot[p] = config.get(p)
    return snapshot
