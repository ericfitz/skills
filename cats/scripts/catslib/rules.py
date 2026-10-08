"""Declarative false-positive rules: loading, validation, and matching."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

SUPPORTED_VERSIONS = {1}

SCALAR_FIELDS = frozenset({
    "result", "response_code", "fuzzer", "path", "contract_path", "method", "url",
    "scenario", "result_reason", "result_details", "response_body",
    "response_content_type", "request_body", "any_text",
})
PREFIX_FIELDS = ("json_body.", "request_header.")
FIELDS = SCALAR_FIELDS | frozenset({"json_body", "request_headers"})

CASE_SENSITIVE_OPS = frozenset({"equals", "in", "not_equals"})
CASE_INSENSITIVE_OPS = frozenset({
    "contains", "contains_any", "contains_all", "starts_with", "starts_with_any",
    "ends_with", "matches",
})
OPERATORS = CASE_SENSITIVE_OPS | CASE_INSENSITIVE_OPS | frozenset({"exists"})

# Operators whose operand must be a list.
LIST_OPERAND_OPS = frozenset({"in", "contains_any", "contains_all", "starts_with_any"})

RULE_KEYS = frozenset({"id", "why", "when", "any_of", "enabled", "tags"})


class RuleError(Exception):
    """Raised with an actionable message when a rules file is invalid."""


@dataclass(frozen=True)
class Rule:
    id: str
    why: str
    when: dict[str, Any] | None
    any_of: list[dict[str, Any]] | None
    enabled: bool
    tags: list[str] = field(default_factory=list)
    order_index: int = 0


def _validate_field(name: str, where: str) -> None:
    if name in FIELDS:
        return
    if any(name.startswith(p) and len(name) > len(p) for p in PREFIX_FIELDS):
        return
    raise RuleError(f"{where}: unknown field {name!r}")


def _validate_condition(name: str, spec: Any, where: str) -> None:
    _validate_field(name, where)
    if isinstance(spec, dict):
        unknown = sorted(str(k) for k in set(spec) - OPERATORS)
        if unknown:
            raise RuleError(f"{where}: unknown operator(s) {', '.join(unknown)} on field {name!r}")
        if not spec:
            raise RuleError(f"{where}: empty operator mapping on field {name!r}")
        for op, operand in spec.items():
            if op in LIST_OPERAND_OPS and not isinstance(operand, list):
                raise RuleError(
                    f"{where}: operator {op!r} on field {name!r} needs a list operand, "
                    f"got {type(operand).__name__}"
                )
            if op == "matches":
                try:
                    re.compile(str(operand))
                except re.error as exc:
                    raise RuleError(f"{where}: invalid regex for {name!r}: {exc}") from exc
    elif isinstance(spec, list) and name in SCALAR_FIELDS:
        # A scalar field's actual value is never a list, so a bare list spec can
        # never match via the implicit-equals fallthrough — it silently never
        # fires. Force the author to say what they meant (usually `in`).
        raise RuleError(
            f"{where}: bare list not allowed for scalar field {name!r} "
            f"(it can never match; did you mean {{in: [...]}}?)"
        )


def _validate_condition_block(block: Any, where: str) -> dict[str, Any]:
    """Validate a condition block and return it, narrowed to a dict."""
    if not isinstance(block, dict) or not block:
        raise RuleError(f"{where}: condition blocks must be non-empty mappings")
    for name, spec in block.items():
        _validate_condition(name, spec, where)
    return block


def load_rules(path: Path) -> list[Rule]:
    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except OSError as exc:
        raise RuleError(f"cannot read rules file {path}: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise RuleError(f"{path}: not valid UTF-8: {exc}") from exc
    except yaml.YAMLError as exc:
        raise RuleError(f"{path}: invalid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise RuleError(f"{path}: top level must be a mapping with 'version' and 'rules'")

    version = raw.get("version", 1)
    if version not in SUPPORTED_VERSIONS:
        raise RuleError(f"{path}: unsupported version {version!r}")

    entries = raw.get("rules")
    if entries is None:
        raise RuleError(f"{path}: missing 'rules' list")
    if not isinstance(entries, list):
        raise RuleError(f"{path}: 'rules' must be a list, got {type(entries).__name__}")

    rules: list[Rule] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        where = f"{path}: rule #{index + 1}"
        if not isinstance(entry, dict):
            raise RuleError(f"{where}: must be a mapping, got {type(entry).__name__}")
        unknown = sorted(str(k) for k in set(entry) - RULE_KEYS)
        if unknown:
            raise RuleError(f"{where}: unknown key(s) {', '.join(unknown)}")
        rule_id = entry.get("id")
        if not isinstance(rule_id, str) or not rule_id:
            raise RuleError(f"{where}: 'id' must be a non-empty string, got {rule_id!r}")
        if rule_id in seen:
            raise RuleError(f"{path}: duplicate rule id {rule_id!r}")
        seen.add(rule_id)
        why = entry.get("why")
        if not isinstance(why, str) or not why:
            raise RuleError(f"{where} ({rule_id}): missing 'why' — every rule must justify itself")

        tags_raw = entry.get("tags")
        if tags_raw is not None and not isinstance(tags_raw, list):
            raise RuleError(
                f"{where} ({rule_id}): 'tags' must be a list, got {type(tags_raw).__name__}"
            )
        tags: list[str] = []
        for tag in tags_raw or []:
            if not isinstance(tag, str):
                raise RuleError(
                    f"{where} ({rule_id}): 'tags' entries must be strings, "
                    f"got {type(tag).__name__}"
                )
            tags.append(tag)

        if "enabled" in entry:
            enabled_raw = entry.get("enabled")
            if not isinstance(enabled_raw, bool):
                # Catches both a bare `enabled:` (parses as None) and a quoted
                # `enabled: "false"` (parses as a truthy string) — either would
                # otherwise silently mis-set the rule's enabled state.
                raise RuleError(
                    f"{where} ({rule_id}): 'enabled' must be a boolean, got {type(enabled_raw).__name__}"
                )
        else:
            enabled_raw = True

        when = entry.get("when")
        any_of = entry.get("any_of")
        if when is None and any_of is None:
            raise RuleError(f"{where} ({rule_id}): needs 'when' or 'any_of'")

        when_block = None
        if when is not None:
            when_block = _validate_condition_block(when, f"{where} ({rule_id})")
        any_of_blocks = None
        if any_of is not None:
            if not isinstance(any_of, list) or not any_of:
                raise RuleError(f"{where} ({rule_id}): 'any_of' must be a non-empty list")
            any_of_blocks = [
                _validate_condition_block(block, f"{where} ({rule_id})") for block in any_of
            ]

        rules.append(Rule(
            id=rule_id,
            why=why,
            when=when_block,
            any_of=any_of_blocks,
            enabled=enabled_raw,
            tags=tags,
            order_index=index,
        ))
    return rules


_MISSING = object()


def field_value(record: dict[str, Any], name: str) -> Any:
    """Resolve a vocabulary field (including virtual and dotted fields) from a record.

    Note: `any_text` always resolves to a string (`" "` at minimum, when both
    `result_reason` and `result_details` are empty), never to the missing sentinel —
    so `{any_text: {exists: false}}` can never match.
    """
    if name == "any_text":
        return f"{record.get('result_reason') or ''} {record.get('result_details') or ''}"
    if name.startswith("json_body."):
        cursor: Any = record.get("json_body")
        for part in name[len("json_body."):].split("."):
            if not isinstance(cursor, dict) or part not in cursor:
                return _MISSING
            cursor = cursor[part]
        return cursor
    if name.startswith("request_header."):
        # Normalize both sides so this doesn't depend on the record contract
        # pre-lowercasing header keys (it does today, but this stays correct if it stops).
        wanted = name[len("request_header."):].lower()
        headers = record.get("request_headers") or {}
        for key, value in headers.items():
            if key.lower() == wanted:
                return value
        return _MISSING
    return record.get(name, _MISSING)


def _as_text(value: Any) -> str:
    if value is _MISSING or value is None:
        return ""
    return value if isinstance(value, str) else str(value)


def _apply(op: str, actual: Any, expected: Any) -> bool:
    if op == "exists":
        # A field that is absent from the record and one whose value is JSON `null`
        # are treated identically here: both count as "does not exist". If a ported
        # rule needs to distinguish "present but null" from "absent", `exists` is
        # not the right operator for it.
        present = actual is not _MISSING and actual is not None
        return present is bool(expected)
    if op == "equals":
        return actual == expected
    if op == "not_equals":
        # A field the record doesn't have (_MISSING) is not_equals to anything,
        # including expected values that look like "empty" — there's no absent-field
        # exemption here.
        return actual != expected
    if op == "in":
        return actual in expected

    text = _as_text(actual).lower()
    if op == "contains":
        return str(expected).lower() in text
    if op == "contains_any":
        return any(str(item).lower() in text for item in expected)
    if op == "contains_all":
        return all(str(item).lower() in text for item in expected)
    if op == "starts_with":
        return text.startswith(str(expected).lower())
    if op == "starts_with_any":
        return any(text.startswith(str(item).lower()) for item in expected)
    if op == "ends_with":
        return text.endswith(str(expected).lower())
    if op == "matches":
        return re.search(str(expected), text, re.IGNORECASE) is not None
    raise RuleError(f"unhandled operator {op!r}")


def _match_block(block: dict[str, Any], record: dict[str, Any]) -> bool:
    for name, spec in block.items():
        actual = field_value(record, name)
        if isinstance(spec, dict):
            if not all(_apply(op, actual, expected) for op, expected in spec.items()):
                return False
        elif actual != spec:
            return False
    return True


def match_rule(rule: Rule, record: dict[str, Any]) -> bool:
    if rule.when is None and rule.any_of is None:
        # load_rules never produces this (it requires 'when' or 'any_of'), but this
        # function is public — a hand-built Rule with neither must not vacuously
        # match every record.
        return False
    if rule.when is not None and not _match_block(rule.when, record):
        return False
    return rule.any_of is None or any(_match_block(b, record) for b in rule.any_of)


def classify_record(
    rules: list[Rule], record: dict[str, Any], *, allow_5xx: bool
) -> tuple[bool, str | None, str | None]:
    """Return (is_false_positive, rule_id, violation_rule_id).

    Only 'error' and 'warn' results are classified. Rules are evaluated in *list*
    order — first match wins. `Rule.order_index` records each rule's position at
    load time for callers that want to report it, but it is not read here; if a
    caller reorders or concatenates rule lists, list order is what governs matching.

    A rule matching a 5xx response is refused unless allow_5xx is set; the rule id
    is returned as violation_rule_id so the caller can report it.
    """
    if record.get("result") not in ("error", "warn"):
        return (False, None, None)
    for rule in rules:
        if not rule.enabled:
            continue
        if match_rule(rule, record):
            try:
                code = int(record.get("response_code") or 0)
            except (TypeError, ValueError):
                code = 0
            if 500 <= code < 600 and not allow_5xx:
                return (False, None, rule.id)
            return (True, rule.id, None)
    return (False, None, None)
