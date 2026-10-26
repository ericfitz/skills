"""Load approved saved profile artifacts without following their source references."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

_CONTRACT_NAMES = ("stack", "docs", "journeys", "topology")
_SCHEMAS = Path(__file__).resolve().parents[2] / "references" / "contracts"
_SUPPORT_MEDIA_TYPES = {".json": "application/json", ".txt": "text/plain", ".md": "text/markdown"}


class ReportInputError(ValueError):
    """An explicitly supplied artifact is unavailable or invalid."""


@dataclass
class Artifact:
    name: str
    path: Path
    sha256: str
    media_type: str
    text: str
    data: object | None


@dataclass
class ProfileBundle:
    contracts: dict[str, Artifact]
    support: list[Artifact]
    diagnostics: list[str]


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"nonstandard numeric constant {value!r}")


def _read_artifact(path: Path, media_type: str) -> Artifact:
    try:
        resolved = path.resolve()
        raw = resolved.read_bytes()
    except (OSError, RuntimeError) as exc:
        raise ReportInputError(f"{path}: cannot read input: {exc}") from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReportInputError(f"{path}: invalid UTF-8: {exc}") from exc
    data = None
    if media_type == "application/json":
        try:
            data = json.loads(text, parse_constant=_reject_json_constant)
        except (ValueError, RecursionError) as exc:
            raise ReportInputError(f"{path}: invalid JSON: {exc}") from exc
    return Artifact(path.name, resolved, hashlib.sha256(raw).hexdigest(), media_type, text, data)


def _matches_type(value: object, kind: str) -> bool:
    checks = {
        "object": lambda: isinstance(value, dict),
        "array": lambda: isinstance(value, list),
        "string": lambda: isinstance(value, str),
        "integer": lambda: isinstance(value, int) and not isinstance(value, bool),
        "number": lambda: isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": lambda: isinstance(value, bool),
        "null": lambda: value is None,
    }
    return checks[kind]()


def _validate(value: object, schema: dict, filename: str, field: str = "$") -> None:
    """Apply the schema keywords used by the four bundled profile contracts."""
    kind = schema.get("type")
    if kind is not None:
        alternatives = kind if isinstance(kind, list) else [kind]
        if not any(_matches_type(value, item) for item in alternatives):
            expected = " or ".join(alternatives)
            raise ReportInputError(f"{filename}:{field}: expected {expected}, got {type(value).__name__}")
    if "enum" in schema and value not in schema["enum"]:
        raise ReportInputError(f"{filename}:{field}: expected one of {schema['enum']!r}, got {value!r}")
    if isinstance(value, dict):
        for required in schema.get("required", []):
            if required not in value:
                raise ReportInputError(f"{filename}:{field}.{required}: required field missing")
        for key, child_schema in schema.get("properties", {}).items():
            if key in value:
                _validate(value[key], child_schema, filename, f"{field}.{key}")
    if isinstance(value, list) and "items" in schema:
        for index, child in enumerate(value):
            _validate(child, schema["items"], filename, f"{field}[{index}]")


def _identifier_diagnostics(records: list[dict], filename: str, field: str, label: str) -> tuple[set[str], list[str]]:
    seen: dict[str, int] = {}
    diagnostics = []
    for index, record in enumerate(records):
        identifier = record["id"]
        if identifier in seen:
            diagnostics.append(
                f"{filename}:$.{field}[{index}].id: duplicate {label} identifier {identifier!r} "
                f"(first at $.{field}[{seen[identifier]}].id)"
            )
        else:
            seen[identifier] = index
    return set(seen), diagnostics


def _reference_diagnostics(contracts: dict[str, Artifact]) -> list[str]:
    docs = contracts["docs"].data
    journeys = contracts["journeys"].data
    corpus_ids, diagnostics = _identifier_diagnostics(docs["corpus"], "docs.json", "corpus", "corpus")
    _, requirement_diagnostics = _identifier_diagnostics(
        docs["requirements"], "docs.json", "requirements", "requirement"
    )
    diagnostics.extend(requirement_diagnostics)
    journey_ids, journey_diagnostics = _identifier_diagnostics(
        journeys["candidates"], "journeys.json", "candidates", "journey"
    )
    diagnostics.extend(journey_diagnostics)
    for group in ("requirements", "journey_evidence", "glossary"):
        for index, record in enumerate(docs.get(group, [])):
            for ref_index, ref in enumerate(record.get("source_refs", [])):
                if ref["corpus_id"] not in corpus_ids:
                    diagnostics.append(
                        f"docs.json:$.{group}[{index}].source_refs[{ref_index}].corpus_id: "
                        f"unresolved corpus identifier {ref['corpus_id']!r}"
                    )
    for index, candidate in enumerate(journeys["candidates"]):
        for ref_index, dependency in enumerate(candidate.get("depends_on", [])):
            if dependency not in journey_ids:
                diagnostics.append(
                    f"journeys.json:$.candidates[{index}].depends_on[{ref_index}]: "
                    f"unresolved journey identifier {dependency!r}"
                )
    return diagnostics


def load_profile(artifact_dir: Path, support_paths: list[Path] | None = None) -> ProfileBundle:
    """Read four saved contracts and only the explicitly supplied support files."""
    contracts = {}
    for name in _CONTRACT_NAMES:
        artifact = _read_artifact(artifact_dir / f"{name}.json", "application/json")
        schema = _read_artifact(_SCHEMAS / f"{name}.schema.json", "application/json").data
        _validate(artifact.data, schema, artifact.name)
        if artifact.data["contract_version"] != "1.0.0":
            raise ReportInputError(
                f"{artifact.name}:$.contract_version: unsupported version {artifact.data['contract_version']!r}; "
                "expected '1.0.0'"
            )
        contracts[name] = artifact
    support = []
    for path in support_paths or []:
        media_type = _SUPPORT_MEDIA_TYPES.get(path.suffix.lower())
        if media_type is None:
            raise ReportInputError(f"{path}: unsupported support format; expected .json, .txt or .md")
        support.append(_read_artifact(path, media_type))
    return ProfileBundle(contracts, support, _reference_diagnostics(contracts))
