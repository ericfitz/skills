#!/usr/bin/env python3
"""Validate a JSON file against a dependency-model contract.

Usage: validate.py <contract-name> <file.json>
  <contract-name> is a schema basename under references/contracts/, e.g.
  `discovery` (any discovery skill's envelope) or `synthesis`. Relative $refs
  between the contracts are resolved. Exit 0 valid, 1 invalid, 2 usage error.

Stdlib only. The functions are also imported by tests/schema_check.py.
"""

import json
import sys
from pathlib import Path

CONTRACTS = Path(__file__).resolve().parents[1] / "references" / "contracts"

def resolve_refs(schema, base_dir, _seen=None):
    """Return schema with local-file $ref pointers replaced by their targets.

    Only same-directory-relative file refs are supported ("core.schema.json").
    Remote refs and JSON-pointer fragments raise ValueError rather than being
    silently ignored: a $ref the validator skips is a schema that passes
    everything, which is worse than no schema at all.

    Keys sitting alongside a $ref are merged over the resolved target:
    `properties` merge key-by-key, `required` unions with the target's order
    first, everything else overrides.
    """
    if isinstance(schema, list):
        return [resolve_refs(item, base_dir, _seen) for item in schema]
    if not isinstance(schema, dict):
        return schema
    if "$ref" not in schema:
        return {key: resolve_refs(value, base_dir, _seen)
                for key, value in schema.items()}

    ref = schema["$ref"]
    if "://" in ref or ref.startswith("#"):
        raise ValueError(
            f"unsupported $ref {ref!r}: only local file refs are supported")
    seen = set(_seen or ())
    if ref in seen:
        raise ValueError(f"circular $ref: {ref!r}")

    target_path = Path(base_dir) / ref
    target = json.loads(target_path.read_text(encoding="utf-8"))
    merged = resolve_refs(target, target_path.parent, seen | {ref})
    if not isinstance(merged, dict):
        raise ValueError(f"$ref target is not an object: {ref!r}")

    for key, value in schema.items():
        if key == "$ref":
            continue
        value = resolve_refs(value, base_dir, _seen)
        current = merged.get(key)
        if key == "properties" and isinstance(current, dict) and isinstance(value, dict):
            merged[key] = {**current, **value}
        elif key == "required" and isinstance(current, list) and isinstance(value, list):
            merged[key] = current + [n for n in value if n not in current]
        else:
            merged[key] = value
    return merged


TYPE_CHECKS = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
}


def validate(instance, schema, path="$", base_dir=None):
    """Return a list of error strings; empty means the instance is valid.

    Pass base_dir to resolve local-file $ref pointers relative to it. The
    resolution happens once, at the top; recursive calls see a flat schema.
    """
    if base_dir is not None:
        schema = resolve_refs(schema, base_dir)
    errors = []

    expected = schema.get("type")
    if expected:
        types = expected if isinstance(expected, list) else [expected]
        if not any(TYPE_CHECKS[t](instance) for t in types if t in TYPE_CHECKS):
            return [f"{path}: expected type {'|'.join(types)}, "
                    f"got {type(instance).__name__}"]

    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: {instance!r} not in enum {schema['enum']!r}")

    if isinstance(instance, dict):
        for name in schema.get("required", []):
            if name not in instance:
                errors.append(f"{path}: missing required property {name!r}")
        props = schema.get("properties", {})
        for name, subschema in props.items():
            if name in instance:
                errors.extend(
                    validate(instance[name], subschema, f"{path}.{name}"))
        extra = schema.get("additionalProperties", True)
        for name in instance:
            if name in props or extra is True:
                continue
            if extra is False:
                errors.append(f"{path}: unexpected property {name!r}")
            elif isinstance(extra, dict):
                errors.extend(
                    validate(instance[name], extra, f"{path}.{name}"))

    if isinstance(instance, list) and "items" in schema:
        for index, item in enumerate(instance):
            errors.extend(
                validate(item, schema["items"], f"{path}[{index}]"))

    return errors


def main(argv):
    if len(argv) != 3:
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    schema_path = CONTRACTS / f"{argv[1]}.schema.json"
    if not schema_path.is_file():
        names = sorted(p.name.removesuffix(".schema.json") for p in CONTRACTS.glob("*.schema.json"))
        print(f"unknown contract {argv[1]!r}; choose from: {', '.join(names)}", file=sys.stderr)
        return 2
    try:
        instance = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"cannot read {argv[2]}: {exc}", file=sys.stderr)
        return 2
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = validate(instance, schema, base_dir=CONTRACTS)
    for error in errors:
        print(error)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
