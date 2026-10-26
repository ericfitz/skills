"""Output behavior for the offline saved-artifact report (synthetic/public data only)."""

import copy
import hashlib
import importlib
import json
import sys
from html.parser import HTMLParser
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "profile" / "scripts"
sys.path.insert(0, str(SCRIPTS))
from reportlib.inputs import Artifact, ProfileBundle, load_profile


class Element:
    def __init__(self, tag="", attrs=()):
        self.tag = tag
        self.attrs = dict(attrs)
        self.children = []

    @property
    def text(self):
        return "".join(item.text if isinstance(item, Element) else item for item in self.children)

    def all(self, tag=None):
        result = []
        for child in self.children:
            if isinstance(child, Element):
                if tag is None or child.tag == tag:
                    result.append(child)
                result.extend(child.all(tag))
        return result


class Document(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.root = Element()
        self.stack = [self.root]
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        element = Element(tag, attrs)
        self.stack[-1].children.append(element)
        if tag not in {"meta", "link", "br", "hr", "input", "img", "wbr"}:
            self.stack.append(element)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].children.append(Element(tag, attrs))

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                self.stack = self.stack[:index]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)

    def section(self, title):
        return next(section for section in self.root.all("section") if any(h.text == title for h in section.all("h2")))


def artifact(name, data=None, text=None):
    if text is None:
        text = json.dumps(data, ensure_ascii=False, indent=2)
    return Artifact(
        name,
        Path("/synthetic") / name,
        hashlib.sha256(text.encode()).hexdigest(),
        "application/json" if name.endswith(".json") else "text/plain",
        text,
        data,
    )


@pytest.fixture
def bundle():
    directory = SCRIPTS.parent / "references" / "contracts" / "examples"
    contracts = {}
    for name in ("stack", "docs", "journeys", "topology"):
        data = json.loads((directory / f"{name}.example.json").read_text())
        contracts[name] = artifact(f"{name}.json", data)
    return ProfileBundle(contracts, [], [])


def render(bundle, title=None):
    # A missing renderer is an observed assertion failure, not a collection error.
    try:
        module = importlib.import_module("reportlib.render")
    except ModuleNotFoundError:
        pytest.fail("render_report is not implemented")
    return module.render_report(bundle, title)


def replace(bundle, name, data):
    bundle.contracts[name] = artifact(f"{name}.json", data)


def load_saved_bundle(bundle, directory):
    for saved in bundle.contracts.values():
        (directory / saved.name).write_text(saved.text, encoding="utf-8")
    return load_profile(directory)


# Reverting to a generic heading or deriving identity from a PRD fails these output checks.
def test_default_title_uses_readme_identity(bundle):
    html = render(bundle)
    page = Document(html)
    assert page.root.all("h1")[0].text == "Automated Profile of orders service"
    assert page.root.all("title")[0].text == "Automated Profile of orders service"
    assert html == render(bundle)


@pytest.mark.parametrize("contract", ["stack", "docs", "journeys", "topology"])
@pytest.mark.parametrize("field", ["software_name", "project_name"])
def test_default_title_prefers_explicit_saved_identity(bundle, contract, field):
    data = copy.deepcopy(bundle.contracts[contract].data)
    data["metadata"] = {field: "  Checkout Engine  "}
    replace(bundle, contract, data)
    page = Document(render(bundle))
    assert page.root.all("h1")[0].text == "Automated Profile of Checkout Engine"
    assert page.root.all("title")[0].text == "Automated Profile of Checkout Engine"


def test_explicit_title_overrides_inferred_identity(bundle):
    page = Document(render(bundle, "Custom review title"))
    assert page.root.all("h1")[0].text == "Custom review title"
    assert page.root.all("title")[0].text == "Custom review title"


@pytest.mark.parametrize("generic_title", ["README", "Overview", "Documentation", "Getting Started", "  "])
def test_generic_readme_title_falls_back_to_recorded_repo(bundle, generic_title):
    docs = copy.deepcopy(bundle.contracts["docs"].data)
    docs["corpus"][1]["title"] = generic_title
    replace(bundle, "docs", docs)
    stack = copy.deepcopy(bundle.contracts["stack"].data)
    stack["metadata"] = {"software_name": " ", "project_name": None, "repo_name": "checkout-repo"}
    stack["inventory"]["root"] = "/saved/path/other-repo/"
    replace(bundle, "stack", stack)
    page = Document(render(bundle))
    assert page.root.all("h1")[0].text == "Automated Profile of checkout-repo"
    assert page.root.all("title")[0].text == "Automated Profile of checkout-repo"


@pytest.mark.parametrize(
    ("root", "expected"),
    [
        ("/saved/unavailable/checkout-repo/", "checkout-repo"),
        ("C:\\saved\\unavailable\\checkout-repo\\", "checkout-repo"),
        ("/", "Unknown software"),
        ("C:\\", "Unknown software"),
        (None, "Unknown software"),
        ("  ", "Unknown software"),
    ],
)
def test_default_title_uses_only_recorded_repo_path(bundle, root, expected):
    docs = copy.deepcopy(bundle.contracts["docs"].data)
    docs["corpus"] = []
    replace(bundle, "docs", docs)
    stack = copy.deepcopy(bundle.contracts["stack"].data)
    stack["inventory"]["root"] = root
    replace(bundle, "stack", stack)
    page = Document(render(bundle))
    assert page.root.all("h1")[0].text == f"Automated Profile of {expected}"
    assert page.root.all("title")[0].text == f"Automated Profile of {expected}"


def test_ambiguous_readme_titles_use_repo_fallback(bundle):
    docs = copy.deepcopy(bundle.contracts["docs"].data)
    docs["corpus"].append(dict(docs["corpus"][1], id="other", locator="subpackage/README.md", title="Other service"))
    replace(bundle, "docs", docs)
    stack = copy.deepcopy(bundle.contracts["stack"].data)
    stack["repo_name"] = "checkout-repo"
    replace(bundle, "stack", stack)
    page = Document(render(bundle))
    assert page.root.all("h1")[0].text == "Automated Profile of checkout-repo"


def test_inferred_name_remains_escaped_text(bundle):
    hostile = '</title><img src="https://evil.example" onerror="alert(1)">'
    docs = copy.deepcopy(bundle.contracts["docs"].data)
    docs["corpus"][1]["title"] = hostile
    replace(bundle, "docs", docs)
    page = Document(render(bundle))
    assert page.root.all("h1")[0].text == f"Automated Profile of {hostile}"
    assert page.root.all("title")[0].text == f"Automated Profile of {hostile}"
    assert not page.root.all("img")


# Dropping a contract section, record provenance, exact source or valid anchor fails this test.
def test_full_profile_summary_and_evidence(bundle):
    page = Document(render(bundle, "Synthetic profile"))
    headings = [h.text for h in page.root.all("h2")]
    assert headings == [
        "Overview",
        "Stack and build",
        "Documentation and requirements",
        "Candidate journeys",
        "Deployment",
        "Gaps and assumptions",
        "Evidence and supplied artifacts",
    ]
    assert page.root.all("h1")[0].text == "Synthetic profile"
    for section, values in {
        "Stack and build": ["go1.22", "go build ./...", "87.5%", "42"],
        "Documentation and requirements": [
            "Order cancellation",
            "must",
            "medium",
            "historical",
            "skimmed",
            "settled order",
        ],
        "Candidate journeys": ["Create an order", "Cancel an order", "2 of 7 public HTTP routes"],
        "Deployment": ["postgres", "stripe", "DATABASE_URL", "migrations", "moderate"],
    }.items():
        text = page.section(section).text
        assert all(value in text for value in values)
    ids = [e.attrs["id"] for e in page.root.all() if "id" in e.attrs]
    assert len(ids) == len(set(ids))
    links = [e.attrs["href"][1:] for e in page.root.all("a") if e.attrs.get("href", "").startswith("#")]
    assert links and set(links) <= set(ids)
    records = [e for e in page.root.all() if e.attrs.get("data-record")]
    assert len(records) >= 20
    for record in records:
        assert any(a.attrs.get("class") == "evidence-link" for a in record.all("a"))
    evidence = page.section("Evidence and supplied artifacts").text
    for value in [
        "docs.json",
        bundle.contracts["docs"].sha256,
        "/requirements/0",
        "docs/prd-cancellations.md",
        "## Cancellation window",
        "internal/http/routes.go:52",
    ]:
        assert value in evidence
    assert all("open" not in e.attrs for e in page.root.all("details"))


# Conflating absence/empty, confidence scales or assertions with runtime proof fails here.
def test_missing_empty_and_confidence_fidelity(bundle):
    docs = copy.deepcopy(bundle.contracts["docs"].data)
    docs["requirements"][0].pop("actors")
    docs["requirements"][0]["acceptance_criteria"] = []
    docs["requirements"][0]["confidence"] = "low"
    docs["coverage_confidence"] = "partial"
    replace(bundle, "docs", docs)
    stack = copy.deepcopy(bundle.contracts["stack"].data)
    stack["confidence"] = "low"
    replace(bundle, "stack", stack)
    page = Document(render(bundle))
    text = page.root.text
    assert "not supplied" in text and "none recorded" in text
    assert "Stack confidence: low" in text and "Docs coverage confidence: partial" in text
    assert "Requirement confidence: low" in text
    assert "high / partial / low" in text and "high / medium / low" in text
    assert "unconfirmed candidates" in page.section("Candidate journeys").text
    assert "documentary obligations" in page.section("Documentation and requirements").text
    assert "Declared configuration" in page.section("Deployment").text
    assert "successful probe" in page.section("Deployment").text


# Treating schema-optional fields as required must fail for each independently valid omission.
@pytest.mark.parametrize(
    ("contract", "key", "section_title", "heading"),
    [
        ("stack", "unknowns", "Gaps and assumptions", "Stack unknowns"),
        ("docs", "deferred", "Gaps and assumptions", "Deferred documents"),
        ("docs", "open_questions", "Gaps and assumptions", "Open questions"),
        ("topology", "real_dependencies", "Deployment", "Infrastructure details"),
        ("topology", "external_third_parties", "Deployment", "Third-party details"),
    ],
)
def test_valid_optional_field_omissions_render(bundle, tmp_path, contract, key, section_title, heading):
    data = copy.deepcopy(bundle.contracts[contract].data)
    data.pop(key)
    replace(bundle, contract, data)
    loaded = load_saved_bundle(bundle, tmp_path)
    assert key not in loaded.contracts[contract].data

    section = Document(render(loaded)).section(section_title)
    index = next(
        index
        for index, child in enumerate(section.children)
        if isinstance(child, Element) and child.tag == "h3" and child.text == heading
    )
    field = section.children[index + 1]
    assert "not supplied" in field.text
    assert "none recorded" not in field.text
    assert any(link.attrs.get("class") == "evidence-link" for link in field.all("a"))


# Defaulting missing deployment lists to [] would misstate their recorded evidence.
@pytest.mark.parametrize(
    ("key", "heading"),
    [("real_dependencies", "Infrastructure dependencies"), ("external_third_parties", "Third parties")],
)
@pytest.mark.parametrize(
    ("supplied", "expected", "incorrect"),
    [(False, "not supplied", "none recorded"), (True, "none recorded", "not supplied")],
)
def test_optional_deployment_groups_preserve_missing_and_empty(
    bundle, tmp_path, key, heading, supplied, expected, incorrect
):
    data = copy.deepcopy(bundle.contracts["topology"].data)
    if supplied:
        data[key] = []
    else:
        data.pop(key)
    replace(bundle, "topology", data)
    deployment = Document(render(load_saved_bundle(bundle, tmp_path))).section("Deployment")
    group = next(
        element
        for element in deployment.all("div")
        if element.attrs.get("class") == "deployment-group" and any(h.text == heading for h in element.all("h3"))
    )
    assert expected in group.text
    assert incorrect not in group.text


# A renderer must accept contracts with only schema-required fields and no records.
def test_schema_minimal_valid_bundle_renders(tmp_path):
    contracts = {
        "stack": {
            "contract_version": "1.0.0",
            "primary_language": None,
            "languages": [],
            "confidence": "low",
            "inventory": {},
        },
        "docs": {
            "contract_version": "1.0.0",
            "sources_available": [],
            "unavailable_sources": [],
            "corpus": [],
            "requirements": [],
            "coverage_confidence": "low",
        },
        "journeys": {"contract_version": "1.0.0", "candidates": [], "sources_read": []},
        "topology": {"contract_version": "1.0.0", "shape": "unknown", "components": [], "assumptions": []},
    }
    for name, data in contracts.items():
        (tmp_path / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")
    loaded = load_profile(tmp_path)
    assert {name: saved.data for name, saved in loaded.contracts.items()} == contracts
    page = Document(render(loaded))
    assert page.root.all("h1")[0].text == "Automated Profile of Unknown software"
    assert page.root.all("title")[0].text == "Automated Profile of Unknown software"
    assert len(page.root.all("h2")) == 7
    assert "0 / 0" in page.section("Overview").text
    assert "null (recorded)" in page.section("Stack and build").text
    journeys = page.section("Candidate journeys")
    assert "none recorded" in journeys.text
    assert not journeys.all("svg")
    deployment = page.section("Deployment")
    groups = {
        group.all("h3")[0].text: group.text
        for group in deployment.all("div")
        if group.attrs.get("class") == "deployment-group"
    }
    assert "none recorded" in groups["Components"]
    assert "not supplied" in groups["Infrastructure dependencies"]
    assert "not supplied" in groups["Third parties"]
    assert not deployment.all("path") and not deployment.all("line")
    for saved in loaded.contracts.values():
        assert saved.text in [pre.text for pre in page.section("Evidence and supplied artifacts").all("pre")]


# Losing a gap, assumption reason or promoting support into proof fails this test.
def test_gaps_and_unsupported_proof(bundle):
    stack = copy.deepcopy(bundle.contracts["stack"].data)
    stack["unknowns"] = ["UNKNOWN-SENTINEL"]
    replace(bundle, "stack", stack)
    bundle.diagnostics.append("Unresolved sentinel reference")
    bundle.support.append(artifact("validation.json", {"status": "PASS-SENTINEL"}))
    page = Document(render(bundle))
    gaps = page.section("Gaps and assumptions").text
    for value in [
        "UNKNOWN-SENTINEL",
        "Unresolved sentinel reference",
        "Confluence space ORDERS",
        "below the 25-document read budget",
        "exactly 24 hours",
        "discovery is read-only; nothing was executed",
    ]:
        assert value in gaps
    assert "UNKNOWN-SENTINEL" in page.section("Overview").text
    evidence = page.section("Evidence and supplied artifacts").text
    assert "PASS-SENTINEL" in evidence
    assert "recorded assertions" in evidence and "independently verified" in evidence
    assert "source excerpt not supplied" in evidence


# Any input escaping failure, executable attribute or external asset would fail here.
def test_hostile_strings_are_inert(bundle):
    hostile = '</script><img src="https://evil.example/x" onerror="alert(1)"><script>alert(2)</script>'
    docs = copy.deepcopy(bundle.contracts["docs"].data)
    docs["corpus"][0]["locator"] = 'javascript:alert("unsafe")'
    docs["requirements"][0]["statement"] = hostile
    docs["unknown_html"] = '<iframe src="https://evil.example"></iframe>'
    replace(bundle, "docs", docs)
    journeys = copy.deepcopy(bundle.contracts["journeys"].data)
    journeys["candidates"][0]["evidence"] = [hostile]
    replace(bundle, "journeys", journeys)
    bundle.support.append(artifact("hostile.txt", text=hostile))
    page = Document(render(bundle, hostile))
    assert page.root.all("h1")[0].text == hostile
    assert not any(page.root.all(tag) for tag in ("img", "iframe", "object", "embed", "form", "link"))
    for element in page.root.all():
        assert not any(key.startswith("on") for key in element.attrs)
        assert "src" not in element.attrs
        if "href" in element.attrs:
            assert element.attrs["href"].startswith("#")
    assert all("alert(1)" not in script.text for script in page.root.all("script"))
    assert any(
        meta.attrs.get("http-equiv") == "Content-Security-Policy"
        and "default-src 'none'" in meta.attrs.get("content", "")
        for meta in page.root.all("meta")
    )
    assert hostile in page.section("Evidence and supplied artifacts").text


# Invented, dropped, reversed or truncated declared dependency edges fail here.
def test_journey_edges_and_topology_groups(bundle):
    journeys = copy.deepcopy(bundle.contracts["journeys"].data)
    journeys["candidates"][0]["depends_on"] = ["J2", "missing"]
    replace(bundle, "journeys", journeys)
    page = Document(render(bundle))
    section = page.section("Candidate journeys")
    edge_rows = [row for row in section.all("tr") if row.attrs.get("data-edge")]
    assert [tuple(td.text for td in row.all("td")[:2]) for row in edge_rows] == [
        ("J1", "J2"),
        ("J1", "missing"),
        ("J2", "J1"),
    ]
    assert "unresolved" in edge_rows[1].text.lower()
    assert "depends on" in section.text
    graphs = section.all("svg")
    assert len(graphs) == 1
    assert len([p for p in graphs[0].all("path") if "data-dependency" in p.attrs]) == 2
    deployment = page.section("Deployment")
    assert not deployment.all("path") and not deployment.all("line")
    for group in ["Components", "Infrastructure dependencies", "Third parties"]:
        assert group in deployment.text
    journeys["candidates"] = [
        dict(journeys["candidates"][0], id=f"J{i}", name=f"Journey {i}", depends_on=["missing"]) for i in range(25)
    ]
    replace(bundle, "journeys", journeys)
    large = Document(render(bundle)).section("Candidate journeys")
    assert not large.all("svg") and "24" in large.text
    assert len([r for r in large.all("tr") if r.attrs.get("data-edge")]) == 25


# Altering support bytes, dropping unknown data, introducing nondeterminism or invented excerpts fails.
def test_optional_artifacts_and_determinism(bundle):
    support = "  exact supplied text\n<script>inert</script>\nUnicode: 雪 & café\n"
    bundle.support.append(artifact("analysis.txt", text=support))
    docs = copy.deepcopy(bundle.contracts["docs"].data)
    docs["future_field"] = {"sentinel": "UNKNOWN-FIELD-SENTINEL"}
    replace(bundle, "docs", docs)
    html = render(bundle)
    assert html == render(bundle)
    page = Document(html)
    assert support in [pre.text for pre in page.root.all("pre")]
    assert bundle.contracts["docs"].text in [pre.text for pre in page.root.all("pre")]
    assert "UNKNOWN-FIELD-SENTINEL" in page.root.text
    assert "source excerpt not supplied" in page.root.text
    assert "analysis.txt" in page.root.text and bundle.support[0].sha256 in page.root.text
    assert "excerpt" not in support


# Normalizing incomplete language proportions, or losing duplicate corpus resolutions, fails.
def test_exact_language_shares_and_duplicate_identifiers(bundle):
    stack = copy.deepcopy(bundle.contracts["stack"].data)
    stack["languages"] = [{"name": "Python", "files": 3, "share": 0.3}, {"name": "Go", "files": 2, "share": 0.2}]
    replace(bundle, "stack", stack)
    docs = copy.deepcopy(bundle.contracts["docs"].data)
    docs["corpus"].append(dict(docs["corpus"][0], locator="SECOND-CORPUS.md"))
    replace(bundle, "docs", docs)
    bundle.diagnostics.append("duplicate corpus identifier D1")
    page = Document(render(bundle))
    bars = page.section("Stack and build").all("meter")
    assert [(bar.attrs["value"], bar.attrs["max"]) for bar in bars] == [("0.3", "1"), ("0.2", "1")]
    evidence = page.section("Evidence and supplied artifacts").text
    assert "SECOND-CORPUS.md" in evidence
    assert "duplicate" in page.section("Gaps and assumptions").text
    ids = [element.attrs["id"] for element in page.root.all() if "id" in element.attrs]
    assert len(ids) == len(set(ids))


# A future, non-schema field must remain inspectable without being interpreted as attribution.
def test_unknown_reference_shaped_fields_are_inert(bundle):
    stack = copy.deepcopy(bundle.contracts["stack"].data)
    stack["languages"][0]["source_refs"] = "FUTURE-REF-SENTINEL"
    stack["languages"][0]["evidence"] = False
    replace(bundle, "stack", stack)
    page = Document(render(bundle))
    assert "FUTURE-REF-SENTINEL" in page.section("Evidence and supplied artifacts").text
    panels = [
        detail
        for detail in page.root.all("details")
        if detail.attrs.get("id", "").startswith("evidence-") and "/languages/0" in detail.text
    ]
    assert panels and all("Original-source attribution not supplied" in detail.text for detail in panels)
