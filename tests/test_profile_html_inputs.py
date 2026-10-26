"""Saved-artifact loader behavior; all fixtures are public examples or synthetic."""

import hashlib
import json
import shutil
import sys
from html.parser import HTMLParser
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
CONTRACTS = REPO / "profile" / "references" / "contracts"
sys.path.insert(0, str(REPO / "profile" / "scripts"))

from reportlib.inputs import ReportInputError, load_profile
from reportlib.render import render_report


@pytest.fixture
def artifacts(tmp_path):
    for name in ("stack", "docs", "journeys", "topology"):
        shutil.copyfile(CONTRACTS / "examples" / f"{name}.example.json", tmp_path / f"{name}.json")
    return tmp_path


def change_contract(artifacts, name, edit):
    path = artifacts / f"{name}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    edit(data)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_loads_four_contracts_and_support(artifacts):
    """Catch skipped inputs, normalized text, incorrect hashing, or discarded JSON."""
    json_path = artifacts / "approved.json"
    json_path.write_bytes(b'{"extra": [1, true, null]}\n')
    text_path = artifacts / "approved.md"
    text_path.write_bytes("# Supplied\r\nCaf\u00e9 & <evidence>\r\n".encode())
    bundle = load_profile(artifacts, [json_path, text_path])
    assert set(bundle.contracts) == {"stack", "docs", "journeys", "topology"}
    for key, artifact in bundle.contracts.items():
        raw = (artifacts / f"{key}.json").read_bytes()
        assert artifact.name == f"{key}.json"
        assert artifact.path == (artifacts / f"{key}.json").resolve()
        assert artifact.sha256 == hashlib.sha256(raw).hexdigest()
        assert artifact.text == raw.decode("utf-8")
        assert artifact.data == json.loads(raw)
        assert artifact.media_type == "application/json"
    assert [item.name for item in bundle.support] == ["approved.json", "approved.md"]
    assert bundle.support[0].data == {"extra": [1, True, None]}
    assert bundle.support[1].data is None
    assert bundle.support[1].text == "# Supplied\r\nCaf\u00e9 & <evidence>\r\n"
    assert bundle.support[1].sha256 == hashlib.sha256(text_path.read_bytes()).hexdigest()
    assert bundle.support[1].media_type == "text/markdown"
    assert bundle.diagnostics == []


@pytest.mark.parametrize(
    ("case", "contract", "field"),
    [
        ("missing", "stack", "stack.json"),
        ("malformed", "docs", "JSON"),
        ("required", "topology", "components"),
        ("nested-required", "docs", "corpus[0].title"),
        ("nested-type", "stack", "languages[0].name"),
        ("array-item", "journeys", "candidates[0].depends_on[0]"),
        ("enum", "docs", "corpus[0].authority"),
        ("version", "journeys", "contract_version"),
        ("bool-integer", "stack", "languages[0].files"),
        ("bool-number", "stack", "languages[0].share"),
        ("wrong-boolean", "topology", "standup_notes[0].externally_reachable"),
        ("wrong-object", "stack", "inventory"),
        ("wrong-union", "docs", "corpus[0].last_modified"),
        ("wrong-root", "journeys", "$"),
        ("invalid-utf8", "topology", "UTF-8"),
    ],
)
def test_missing_invalid_or_unsupported_contract_fails(artifacts, case, contract, field):
    """Catch silently accepted schema/version failures at any nesting depth."""
    path = artifacts / f"{contract}.json"
    edits = {
        "required": lambda data: data.pop("components"),
        "nested-required": lambda data: data["corpus"][0].pop("title"),
        "nested-type": lambda data: data["languages"][0].update(name=42),
        "array-item": lambda data: data["candidates"][0].update(depends_on=[42]),
        "enum": lambda data: data["corpus"][0].update(authority="guessed"),
        "version": lambda data: data.update(contract_version="9.0.0"),
        "bool-integer": lambda data: data["languages"][0].update(files=True),
        "bool-number": lambda data: data["languages"][0].update(share=False),
        "wrong-boolean": lambda data: data["standup_notes"][0].update(externally_reachable=1),
        "wrong-object": lambda data: data.update(inventory=[]),
        "wrong-union": lambda data: data["corpus"][0].update(last_modified=False),
    }
    if case == "missing":
        path.unlink()
    elif case == "malformed":
        path.write_text("{incomplete", encoding="utf-8")
    elif case == "wrong-root":
        path.write_text("[]", encoding="utf-8")
    elif case == "invalid-utf8":
        path.write_bytes(b"\xff")
    else:
        change_contract(artifacts, contract, edits[case])
    with pytest.raises(ReportInputError) as caught:
        load_profile(artifacts)
    assert path.name in str(caught.value)
    assert field in str(caught.value)


def test_optional_fields_preserve_absence_and_empty(artifacts):
    """Catch fabricated defaults and filtering of explicitly recorded empty values."""
    change_contract(artifacts, "stack", lambda data: data.pop("package_managers"))
    change_contract(artifacts, "docs", lambda data: data["corpus"][0].update(last_modified=None))
    change_contract(artifacts, "topology", lambda data: data.update(extension={"kept": True}))
    bundle = load_profile(artifacts)
    assert "package_managers" not in bundle.contracts["stack"].data
    assert bundle.contracts["stack"].data["unknowns"] == []
    assert bundle.contracts["journeys"].data["candidates"][0]["depends_on"] == []
    assert bundle.contracts["docs"].data["corpus"][0]["last_modified"] is None
    assert bundle.contracts["topology"].data["extension"] == {"kept": True}
    assert bundle.support == []


def test_cross_reference_diagnostics(artifacts):
    """Catch collapsed duplicate records and unreported dangling references."""
    def edit_docs(data):
        data["corpus"].append(dict(data["corpus"][0]))
        data["requirements"][0]["source_refs"][0]["corpus_id"] = "UNKNOWN_REQUIREMENT"
        data["journey_evidence"][0]["source_refs"][0]["corpus_id"] = "UNKNOWN_EVIDENCE"
        data["glossary"][0]["source_refs"][0]["corpus_id"] = "UNKNOWN_GLOSSARY"

    def edit_journeys(data):
        data["candidates"].append(dict(data["candidates"][0]))
        data["candidates"][1]["depends_on"] = ["J1", "MISSING_JOURNEY"]

    change_contract(artifacts, "docs", edit_docs)
    change_contract(artifacts, "journeys", edit_journeys)
    bundle = load_profile(artifacts)
    assert len(bundle.contracts["docs"].data["corpus"]) == 4
    assert len(bundle.contracts["journeys"].data["candidates"]) == 3
    diagnostics = "\n".join(bundle.diagnostics)
    assert "duplicate" in diagnostics.lower()
    for value in ("D1", "J1", "UNKNOWN_REQUIREMENT", "UNKNOWN_EVIDENCE", "UNKNOWN_GLOSSARY", "MISSING_JOURNEY"):
        assert value in diagnostics
    assert "docs.json" in diagnostics
    assert "journeys.json" in diagnostics
    assert "requirements[0].source_refs[0].corpus_id" in diagnostics
    assert "candidates[1].depends_on[1]" in diagnostics


def test_duplicate_requirement_ids_retain_obligations_and_warn_in_report_gaps(artifacts):
    """Catch silently ambiguous requirement IDs without losing distinct obligations."""
    statement = "Distinct obligation sharing the same requirement ID"
    change_contract(
        artifacts,
        "docs",
        lambda data: data["requirements"].append(dict(data["requirements"][0], statement=statement)),
    )

    bundle = load_profile(artifacts)
    requirements = bundle.contracts["docs"].data["requirements"]
    assert [item["id"] for item in requirements] == ["R1", "R2", "R1"]
    assert requirements[0]["statement"] == "A customer must be able to cancel an order at any time before it ships."
    assert requirements[2]["statement"] == statement
    duplicate_warnings = [item for item in bundle.diagnostics if "duplicate requirement identifier" in item]
    assert len(duplicate_warnings) == 1
    warning = duplicate_warnings[0]
    for value in ("docs.json", "R1", "$.requirements[0].id", "$.requirements[2].id"):
        assert value in warning

    class GapText(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.in_gaps = False
            self.parts = []

        def handle_starttag(self, tag, attrs):
            if tag == "section":
                self.in_gaps = dict(attrs).get("id") == "gaps"

        def handle_endtag(self, tag):
            if tag == "section":
                self.in_gaps = False

        def handle_data(self, data):
            if self.in_gaps:
                self.parts.append(data)

    rendered = render_report(bundle)
    gaps = GapText()
    gaps.feed(rendered)
    assert warning in "".join(gaps.parts)
    assert requirements[0]["statement"] in rendered
    assert statement in rendered


def test_cycles_are_valid_declared_relationships(artifacts):
    """Catch rejected cycles even though saved contracts permit them."""
    change_contract(artifacts, "journeys", lambda data: data["candidates"][0].update(depends_on=["J2"]))
    bundle = load_profile(artifacts)
    assert bundle.contracts["journeys"].data["candidates"][0]["depends_on"] == ["J2"]
    assert bundle.diagnostics == []


def test_explicit_support_only(artifacts, monkeypatch):
    """Catch adjacent-file discovery or dereferencing of evidence source paths."""
    evidence = artifacts / "referenced-source.txt"
    evidence.write_text("never read this source", encoding="utf-8")
    (artifacts / "adjacent.json").write_text("{invalid adjacent JSON", encoding="utf-8")
    support = artifacts / "approved.txt"
    support.write_text("explicit support\n", encoding="utf-8")
    change_contract(artifacts, "topology", lambda data: data["components"][0].update(evidence=[str(evidence)]))
    allowed = {artifacts / f"{name}.json" for name in ("stack", "docs", "journeys", "topology")}
    allowed.update(CONTRACTS.glob("*.schema.json"))
    allowed.add(support)
    allowed = {item.resolve() for item in allowed}
    original_open = Path.open

    def guarded_open(path, *args, **kwargs):
        assert path.resolve() in allowed, f"unexpected read: {path}"
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    bundle = load_profile(artifacts, [support])
    assert len(bundle.support) == 1
    assert bundle.support[0].text == "explicit support\n"
    assert bundle.support[0].media_type == "text/plain"
    assert bundle.contracts["topology"].data["components"][0]["evidence"] == [str(evidence)]


@pytest.mark.parametrize(
    ("filename", "content", "context"),
    [("support.html", b"<b>unsupported</b>", "support"), ("support.json", b"{broken", "JSON"), ("support.md", b"\xff", "UTF-8")],
)
def test_invalid_support_fails(artifacts, filename, content, context):
    """Catch acceptance of unsupported formats or unusable support contents."""
    path = artifacts / filename
    path.write_bytes(content)
    with pytest.raises(ReportInputError) as caught:
        load_profile(artifacts, [path])
    assert filename in str(caught.value)
    assert context in str(caught.value)


def test_missing_support_fails(artifacts):
    path = artifacts / "missing.md"
    with pytest.raises(ReportInputError, match=r"missing\.md"):
        load_profile(artifacts, [path])


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_nonstandard_json_numbers_fail(artifacts, constant):
    """Catch Python's permissive JSON constants bypassing JSON input validity."""
    path = artifacts / "support.json"
    path.write_text('{"measurement": ' + constant + "}", encoding="utf-8")
    with pytest.raises(ReportInputError) as caught:
        load_profile(artifacts, [path])
    assert "support.json" in str(caught.value)
    assert "JSON" in str(caught.value)
