"""Minimal JSON Schema subset validator.

Supports type, properties, required, items, and enum — the subset the profile
and itest contracts actually use. Unknown keywords are ignored by design.
Exists because jsonschema is not installed and this repo is stdlib-only.
"""

TYPE_CHECKS = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
}


def validate(instance, schema, path="$"):
    """Return a list of error strings; empty means the instance is valid."""
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
