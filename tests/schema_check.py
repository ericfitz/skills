"""Minimal JSON Schema subset validator.

Supports type, properties, required, items, enum, and local-file $ref — the
subset the profile, itest, and dependency-model contracts actually use.
Unknown keywords are ignored by design. Exists because jsonschema is not
installed and this repo is stdlib-only.
"""

import json
from pathlib import Path


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
        for name, subschema in schema.get("properties", {}).items():
            if name in instance:
                errors.extend(
                    validate(instance[name], subschema, f"{path}.{name}"))

    if isinstance(instance, list) and "items" in schema:
        for index, item in enumerate(instance):
            errors.extend(
                validate(item, schema["items"], f"{path}[{index}]"))

    return errors
