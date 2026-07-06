"""Common JSON contract for bump adapters: normalized dataclasses + (de)serialization.

Every adapter verb emits one of these shapes; the categorizer and orchestrator
consume them without knowing which provider produced the data.
"""
import json
from dataclasses import dataclass, field, is_dataclass, asdict

BUMP_MAJOR = "major"
BUMP_MINOR = "minor"
BUMP_PATCH = "patch"
BUMP_NONE = "none"


@dataclass
class UpdateRecord:
    name: str
    current: str
    latest: str
    wanted: str
    bump: str
    kind: str
    location: str
    pinned: bool = False
    ecosystem: str = ""
    meta: dict = field(default_factory=dict)


@dataclass
class Advisory:
    package: str
    ecosystem: str
    severity: str
    current: str
    fixed: str
    ids: list = field(default_factory=list)
    summary: str = ""
    source: str = ""


@dataclass
class Context:
    issues: list = field(default_factory=list)
    pullRequests: list = field(default_factory=list)


@dataclass
class Categories:
    securityFixes: list = field(default_factory=list)
    safe: list = field(default_factory=list)
    needsPlan: list = field(default_factory=list)
    skipped: list = field(default_factory=list)


def _plain(obj):
    if is_dataclass(obj):
        return asdict(obj)
    if isinstance(obj, list):
        return [_plain(x) for x in obj]
    return obj


def dump(obj) -> str:
    return json.dumps(_plain(obj), sort_keys=True, indent=2)


def load_records(s) -> list:
    data = json.loads(s) if isinstance(s, str) else s
    return [UpdateRecord(**d) for d in data]


def load_advisories(s) -> list:
    data = json.loads(s) if isinstance(s, str) else s
    return [Advisory(**d) for d in data]
