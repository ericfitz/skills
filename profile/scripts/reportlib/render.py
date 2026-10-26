"""Pure, self-contained HTML presentation of approved saved profile artifacts."""

import base64
import hashlib
import json
import math
from html import escape

from .assets import SCRIPT, STYLE
from .inputs import Artifact, ProfileBundle

_MISSING = object()
_SECTIONS = (
    ("overview", "Overview"),
    ("stack", "Stack and build"),
    ("docs", "Documentation and requirements"),
    ("journeys", "Candidate journeys"),
    ("deployment", "Deployment"),
    ("gaps", "Gaps and assumptions"),
    ("evidence", "Evidence and supplied artifacts"),
)


def _e(value: object) -> str:
    return escape(str(value), quote=True).replace("\r", "&#13;")


def _name(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _recorded_name(bundle: ProfileBundle, key: str) -> str | None:
    names = set()
    for contract in ("stack", "docs", "journeys", "topology"):
        data = bundle.contracts[contract].data
        metadata = data.get("metadata")
        containers = (data, metadata) if isinstance(metadata, dict) else (data,)
        for container in containers:
            if name := _name(container.get(key)):
                names.add(name)
    return next(iter(names)) if len(names) == 1 else None


def _software_name(bundle: ProfileBundle) -> str:
    """Infer identity only from saved fields, without following paths or source references."""
    for key in ("software_name", "project_name"):
        if name := _recorded_name(bundle, key):
            return name
    generic_titles = {"readme", "read me", "overview", "documentation", "getting started"}
    readme_names = {
        name
        for item in bundle.contracts["docs"].data["corpus"]
        if item["doc_type"] == "readme"
        and (name := _name(item["title"]))
        and name.casefold() not in generic_titles
    }
    if len(readme_names) == 1:
        return next(iter(readme_names))
    if name := _recorded_name(bundle, "repo_name"):
        return name
    inventory = bundle.contracts["stack"].data["inventory"]
    if root := _name(inventory.get("root")):
        # Normalize saved path syntax as text, independent of the rendering host OS.
        basename = root.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
        if basename and basename not in {".", ".."} and not (len(basename) == 2 and basename[1] == ":"):
            return basename
    return "Unknown software"


def _label(key: str) -> str:
    return key.replace("_", " ").capitalize()


def _pointer(*parts: object) -> str:
    return "".join("/" + str(part).replace("~", "~0").replace("/", "~1") for part in parts)


def _plain(value: object, limit: int = 170) -> str:
    if value is _MISSING:
        return "not supplied"
    if value is None:
        return "null (recorded)"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        text = ", ".join(_plain(item) for item in value) if value else "none recorded"
    elif isinstance(value, dict):
        text = json.dumps(value, ensure_ascii=False)
    else:
        text = str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _value(value: object) -> str:
    if value is _MISSING:
        return '<span class="muted">not supplied</span>'
    if value is None:
        return '<span class="muted">null (recorded)</span>'
    if isinstance(value, dict):
        if not value:
            return '<span class="muted">empty object (recorded)</span>'
        return "<dl>" + "".join(f"<dt>{_e(_label(k))}</dt><dd>{_value(v)}</dd>" for k, v in value.items()) + "</dl>"
    if isinstance(value, list):
        if not value:
            return '<span class="muted">none recorded</span>'
        return "<ul>" + "".join(f"<li>{_value(item)}</li>" for item in value) + "</ul>"
    if isinstance(value, bool):
        return "true" if value else "false"
    return _e(value)


def _details(summary: str, body: str, identifier: str | None = None) -> str:
    attribute = f' id="{identifier}"' if identifier else ""
    return f'<details{attribute}><summary>{summary}</summary><div class="detail-body">{body}</div></details>'


class _Report:
    def __init__(self, bundle: ProfileBundle):
        self.bundle = bundle
        self.panels: list[str] = []
        self.serial = 0
        self.artifact_ids = {key: f"artifact-{i}" for i, key in enumerate(bundle.contracts)}
        self.corpus = bundle.contracts["docs"].data["corpus"]

    def provenance(self, contract: str, pointer: str, value: object) -> str:
        """Provide unique evidence independently of user-controlled record identifiers."""
        self.serial += 1
        identifier = f"evidence-{self.serial}"
        artifact = self.bundle.contracts[contract]
        artifact_id = self.artifact_ids[contract]
        body = (
            f'<p>Input artifact: <a href="#{artifact_id}">{_e(artifact.name)}</a></p>'
            f"<p>JSON pointer: <code>{_e(pointer or '(root)')}</code></p>"
            f'<p>SHA-256: <code class="hash">{_e(artifact.sha256)}</code></p>'
            + self.source_refs(value, contract, pointer)
            + _details("Exact recorded value", f"<pre>{_e(json.dumps(value, ensure_ascii=False, indent=2))}</pre>")
        )
        self.panels.append(_details(f"{_e(artifact.name)} · {_e(pointer or '(root)')}", body, identifier))
        return f'<a class="evidence-link" href="#{identifier}">Evidence</a>'

    def source_refs(self, value: object, contract: str, pointer: str) -> str:
        # Only schema-declared reference fields carry attribution semantics. Unknown fields stay raw data.
        group = pointer.split("/")[1] if pointer else ""
        refs = []
        corpus_refs = contract == "docs" and group in {"requirements", "journey_evidence", "glossary"}
        file_refs = (contract == "journeys" and group == "candidates") or (
            contract == "topology" and group in {"components", "real_dependencies", "standup_notes"}
        )
        locator_refs = contract == "docs" and group in {
            "corpus",
            "sources_available",
            "unavailable_sources",
            "deferred",
        }
        if isinstance(value, dict):
            for ref in value.get("source_refs", []) if corpus_refs else []:
                matches = [item for item in self.corpus if item["id"] == ref["corpus_id"]]
                exact = _value(ref)
                if matches:
                    resolutions = "".join(
                        "<li>"
                        + _e(item["locator"])
                        + " · "
                        + _e(item["title"])
                        + " · authority: "
                        + _e(item["authority"])
                        + " · read: "
                        + _e(item["read"])
                        + "</li>"
                        for item in matches
                    )
                    exact += "<p>Corpus resolution" + (" (ambiguous duplicate identifier)" if len(matches) > 1 else "")
                    exact += f":</p><ul>{resolutions}</ul>"
                else:
                    exact += "<p>Unresolved corpus identifier.</p>"
                refs.append(exact)
            for ref in value.get("evidence", []) if file_refs else []:
                refs.append(_e(ref))
            if locator_refs and "locator" in value:
                refs.append(_e(value["locator"]))
        if contract == "journeys" and group == "sources_read" and isinstance(value, str):
            refs.append(_e(value))
        source = (
            "<ul>" + "".join(f"<li>{ref}</li>" for ref in refs) + "</ul>"
            if refs
            else ("<p>Original-source attribution not supplied for this record.</p>")
        )
        return "<h3>Original source references</h3>" + source + '<p class="muted">source excerpt not supplied</p>'

    def fact(self, contract: str, key: str, label: str | None = None) -> str:
        data = self.bundle.contracts[contract].data
        value = data.get(key, _MISSING)
        provenance = (
            self.provenance(contract, _pointer(key), value)
            if value is not _MISSING
            else (self.provenance(contract, "", data))
        )
        return f"<dt>{_e(label or _label(key))}</dt><dd>{_value(value)} {provenance}</dd>"

    def records(
        self,
        contract: str,
        key: str,
        heading: str,
        columns: tuple[str, ...],
        fields: tuple[str, ...] = (),
        collapsed: bool = False,
    ) -> str:
        data = self.bundle.contracts[contract].data
        values = data.get(key, _MISSING)
        if values is _MISSING or not values:
            return (
                f"<h3>{_e(heading)}</h3><p>{_value(values)} "
                + (
                    self.provenance(contract, _pointer(key), values)
                    if values is not _MISSING
                    else self.provenance(contract, "", data)
                )
                + "</p>"
            )
        rows = []
        for index, item in enumerate(values):
            pointer = _pointer(key, index)
            evidence = self.provenance(contract, pointer, item)
            if isinstance(item, dict):
                cells = "".join(f"<td>{_e(_plain(item.get(column, _MISSING)))}</td>" for column in columns)
                keys = list(dict.fromkeys((*fields, *item)))
                detail = (
                    "<dl>"
                    + "".join(
                        f"<dt>{_e(_label(field))}</dt><dd>{_value(item.get(field, _MISSING))}</dd>" for field in keys
                    )
                    + "</dl>"
                )
                if contract == "docs" and key == "requirements":
                    detail += f"<p>Requirement confidence: {_e(item['confidence'])}</p>"
                cells += f"<td>{_details('Record details', detail)}{evidence}</td>"
            else:
                cells = f"<td>{_value(item)}</td><td>{evidence}</td>"
            rows.append(f'<tr data-record="{_e(contract + pointer)}">{cells}</tr>')
        headers = "".join(f'<th scope="col">{_e(_label(column))}</th>' for column in columns)
        if not isinstance(values[0], dict):
            headers = '<th scope="col">Recorded value</th>'
        headers += '<th scope="col">Details &amp; evidence</th>'

        def table(contents):
            return (
                f'<div class="table-wrap"><table><caption>{_e(heading)}</caption>'
                f"<thead><tr>{headers}</tr></thead><tbody>{''.join(contents)}</tbody></table></div>"
            )

        if collapsed:
            return _details(f"{_e(heading)} ({len(values)})", table(rows))
        visible = table(rows[:6])
        if len(rows) > 6:
            visible += _details(f"All remaining {len(rows) - 6} records", table(rows[6:]))
        return visible

    def overview(self) -> str:
        stack = self.bundle.contracts["stack"].data
        docs = self.bundle.contracts["docs"].data
        journeys = self.bundle.contracts["journeys"].data
        topology = self.bundle.contracts["topology"].data
        metrics = [
            (
                "Primary language",
                _plain(stack["primary_language"]),
                "stack",
                "/primary_language",
                stack["primary_language"],
            ),
            ("Declared deployment", topology["shape"], "topology", "/shape", topology["shape"]),
            ("Documents / requirements", f"{len(docs['corpus'])} / {len(docs['requirements'])}", "docs", "", docs),
            ("Candidate journeys", str(len(journeys["candidates"])), "journeys", "/candidates", journeys["candidates"]),
        ]
        cards = "".join(
            f'<div class="metric"><span class="label">{_e(label)}</span><strong>{_e(value)}</strong>'
            f"{self.provenance(contract, pointer, raw)}</div>"
            for label, value, contract, pointer, raw in metrics
        )
        confidence = (
            f'<div class="confidence"><span class="badge">Stack confidence: {_e(stack["confidence"])}</span>'
            f'<span class="badge">Docs coverage confidence: {_e(docs["coverage_confidence"])}</span></div>'
            '<p class="muted">Stack/docs scale: high / partial / low. '
            "Requirement scale: high / medium / low. These scales are distinct.</p>"
        )
        notices = []
        unknowns = stack.get("unknowns", _MISSING)
        if unknowns is _MISSING:
            notices.append("Stack unknowns: not supplied " + self.provenance("stack", "", stack))
        else:
            for index, unknown in enumerate(unknowns):
                notices.append(_e(unknown) + " " + self.provenance("stack", _pointer("unknowns", index), unknown))
        for key, label in [
            ("unavailable_sources", "unavailable sources"),
            ("deferred", "deferred documents"),
            ("open_questions", "open questions"),
        ]:
            values = docs.get(key, _MISSING)
            if values is _MISSING:
                notices.append(f"{_e(label.capitalize())}: not supplied " + self.provenance("docs", "", docs))
            elif values:
                notices.append(f"{len(values)} {_e(label)} " + self.provenance("docs", _pointer(key), values))
        if topology["assumptions"]:
            notices.append(
                f"{len(topology['assumptions'])} unconfirmed deployment assumptions "
                + self.provenance("topology", "/assumptions", topology["assumptions"])
            )
        notices += [_e(item) for item in self.bundle.diagnostics]
        if notices:
            first = "".join(f"<li>{item}</li>" for item in notices[:5])
            remainder = f"<p>{len(notices) - 5} more recorded gaps below.</p>" if len(notices) > 5 else ""
            gaps = '<div class="notice"><h3>Evidence gaps</h3><ul>' + first + "</ul>" + remainder
            gaps += '<a href="#gaps">Inspect all gaps and assumptions</a></div>'
        else:
            gaps = (
                '<p class="muted">No gaps recorded in the supplied gap fields; '
                "this is not a completeness guarantee.</p>"
            )
        return '<div class="metrics">' + cards + "</div>" + confidence + gaps

    def stack(self) -> str:
        data = self.bundle.contracts["stack"].data
        rows = []
        for index, language in enumerate(data["languages"]):
            share = language["share"]
            # Visual length is bounded by the meter; the unmodified recorded value stays explicit.
            bounded = max(0.0, min(1.0, share)) if math.isfinite(share) else 0
            percent = format(share * 100, ".12g")
            rows.append(
                f'<tr data-record="stack/languages/{index}"><td class="language-name">{_e(language["name"])}</td>'
                f"<td>{_e(language['files'])}</td><td>{_e(percent)}% (share {_e(share)})"
                f'<meter min="0" max="1" value="{_e(bounded)}" aria-label="{_e(language["name"])} share">'
                f"{_e(percent)}%</meter></td><td>"
                f"{self.provenance('stack', _pointer('languages', index), language)}</td></tr>"
            )
        languages = (
            '<div class="table-wrap"><table><caption>Recorded language mix</caption><thead><tr>'
            '<th scope="col">Language</th><th scope="col">Files</th><th scope="col">Share</th>'
            '<th scope="col">Evidence</th></tr></thead><tbody>' + "".join(rows) + "</tbody></table></div>"
            if rows
            else "<p>Languages: none recorded " + self.provenance("stack", "/languages", []) + "</p>"
        )
        return (
            '<p class="section-intro">Recorded build tooling and language inventory. Proportions are not renormalized; '
            "the meter uses a 0-100% scale and clips values outside that scale.</p>"
            + languages
            + "<dl>"
            + "".join(
                self.fact("stack", key)
                for key in ("primary_language", "package_managers", "runtimes", "build_commands", "monorepo")
            )
            + "</dl>"
            + _details(
                "Full inventory",
                _value(data.get("inventory", _MISSING))
                + " "
                + self.provenance("stack", "/inventory", data["inventory"])
                if "inventory" in data
                else "<p>not supplied</p>" + self.provenance("stack", "", data),
            )
        )

    def docs(self) -> str:
        return (
            '<p class="section-intro">Requirements are documentary obligations, not passing tests. '
            "Authority and read depth describe the supplied corpus, not independent validation.</p>"
            + self.records(
                "docs",
                "requirements",
                "Documentary requirements",
                ("id", "statement", "modality", "confidence"),
                (
                    "id",
                    "statement",
                    "modality",
                    "actors",
                    "acceptance_criteria",
                    "preconditions_stated",
                    "source_refs",
                    "staleness",
                    "confidence",
                ),
            )
            + self.records(
                "docs",
                "corpus",
                "Document corpus",
                ("id", "title", "authority", "read"),
                ("last_modified",),
                collapsed=True,
            )
            + self.records(
                "docs",
                "journey_evidence",
                "Documentary journey evidence",
                ("narrative", "actor"),
                ("narrative", "actor", "entry_point_hint", "source_refs"),
                collapsed=True,
            )
            + self.records(
                "docs", "glossary", "Domain glossary", ("term", "definition"), ("source_refs",), collapsed=True
            )
            + self.records("docs", "domain_invariants", "Domain invariants", (), collapsed=True)
            + self.records(
                "docs", "sources_available", "Available source channels", ("kind", "locator"), collapsed=True
            )
        )

    def journeys(self) -> str:
        data = self.bundle.contracts["journeys"].data
        nodes = data["candidates"]
        intro = '<p class="section-intro">These are unconfirmed candidates. Rank and business criticality are recorded '
        intro += "judgments. Arrows run from a candidate to the candidate it depends on.</p>"
        graph = self.journey_graph(nodes)
        rows = []
        identifiers = {node["id"] for node in nodes}
        for index, node in enumerate(nodes):
            for edge_index, dependency in enumerate(node.get("depends_on", [])):
                resolved = "declared" if dependency in identifiers else "unresolved dependency identifier"
                evidence = self.provenance(
                    "journeys", _pointer("candidates", index, "depends_on", edge_index), dependency
                )
                rows.append(
                    f'<tr data-edge="declared"><td>{_e(node["id"])}</td><td>{_e(dependency)}</td>'
                    f"<td>{resolved}</td><td>{evidence}</td></tr>"
                )
        edges = (
            '<div class="table-wrap"><table><caption>Complete declared dependency edges · candidate depends on target'
            '</caption><thead><tr><th scope="col">Candidate</th><th scope="col">Depends on</th>'
            '<th scope="col">Reference status</th><th scope="col">Evidence</th></tr></thead><tbody>'
            + "".join(rows)
            + "</tbody></table></div>"
            if rows
            else "<p>No dependency edges recorded.</p>"
        )
        return (
            intro
            + "<dl>"
            + self.fact("journeys", "surface_coverage")
            + "</dl>"
            + graph
            + self.records(
                "journeys",
                "candidates",
                "Candidate journeys",
                ("rank", "name", "business_criticality", "entry_point"),
                (
                    "id",
                    "name",
                    "actor",
                    "narrative",
                    "entry_point",
                    "evidence",
                    "business_criticality",
                    "rank",
                    "rationale",
                    "depends_on",
                ),
            )
            + _details("All declared dependency edges", edges)
            + self.records("journeys", "sources_read", "Sources read", (), collapsed=True)
        )

    def journey_graph(self, nodes: list[dict]) -> str:
        if not nodes:
            return "<p>No candidate nodes recorded.</p>"
        if len(nodes) > 24:
            return '<p class="muted">Diagram omitted above 24 nodes; complete candidate and edge tables are below.</p>'
        if len({node["id"] for node in nodes}) != len(nodes):
            return (
                '<p class="muted">Diagram omitted for duplicate identifiers; '
                "complete records and edges remain below.</p>"
            )
        columns = min(4, len(nodes))
        width = columns * 210
        height = math.ceil(len(nodes) / columns) * 116 + 30
        positions = {node["id"]: (25 + (i % columns) * 210, 30 + (i // columns) * 116) for i, node in enumerate(nodes)}
        paths = []
        for node in nodes:
            x, y = positions[node["id"]]
            for dependency in node.get("depends_on", []):
                if dependency not in positions:
                    continue
                tx, ty = positions[dependency]
                # Curves above boxes keep direction visible, including cycles and self-dependencies.
                start_x, end_x = x + 86, tx + 86
                bend = min(y, ty) - 27
                path = f"M {start_x} {y} C {start_x} {bend}, {end_x} {bend}, {end_x} {ty}"
                paths.append(
                    f'<path class="edge" data-dependency="declared" d="{path}" marker-end="url(#journey-arrow)"/>'
                )
        boxes = []
        for index, node in enumerate(nodes):
            x, y = positions[node["id"]]
            label = _plain(node["name"], 24)
            boxes.append(
                f"<g><title>{_e(node['id'])}: {_e(node['name'])}</title>"
                f'<rect class="node" x="{x}" y="{y}" width="172" height="64" rx="7"/>'
                f'<text x="{x + 10}" y="{y + 23}">#{index + 1} · {_e(_plain(node["id"], 18))}</text>'
                f'<text x="{x + 10}" y="{y + 44}">{_e(label)}</text></g>'
            )
        return (
            '<figure class="graph"><svg xmlns="http://www.w3.org/2000/svg" role="img" '
            f'aria-labelledby="journey-graph-title journey-graph-desc" viewBox="0 0 {width} {height}">'
            '<title id="journey-graph-title">Declared journey dependencies</title>'
            '<desc id="journey-graph-desc">Each arrow means candidate depends on target. '
            "All edges, including unresolved references, are in the complete table below.</desc>"
            '<defs><marker id="journey-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" '
            'markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#6b808a"/>'
            "</marker></defs>" + "".join(paths) + "".join(boxes) + "</svg>"
            "<figcaption>Only explicit depends_on edges are drawn. Cycles are retained. "
            "Unresolved targets remain in the complete edge table.</figcaption></figure>"
        )

    def deployment(self) -> str:
        data = self.bundle.contracts["topology"].data
        groups = []
        for key, heading, descriptor in [
            ("components", "Components", "role"),
            ("real_dependencies", "Infrastructure dependencies", "kind"),
            ("external_third_parties", "Third parties", "used_for"),
        ]:
            values = data.get(key, _MISSING)
            items = (
                "".join(
                    "<li>"
                    + _e(item["name"])
                    + " · "
                    + _e(item[descriptor])
                    + " "
                    + self.provenance("topology", _pointer(key, index), item)
                    + "</li>"
                    for index, item in enumerate(values)
                )
                or "<li>none recorded</li>"
                if values is not _MISSING
                else "<li>not supplied</li>"
            )
            groups.append(f'<div class="deployment-group"><h3>{heading}</h3><ul>{items}</ul></div>')
        sequence = data.get("startup_sequence", _MISSING)
        if isinstance(sequence, list) and sequence:
            startup = (
                '<ol class="startup">'
                + "".join(
                    '<li data-record="startup">'
                    + _e(item)
                    + " "
                    + self.provenance("topology", _pointer("startup_sequence", index), item)
                    + "</li>"
                    for index, item in enumerate(sequence)
                )
                + "</ol>"
            )
        else:
            startup = "<dl>" + self.fact("topology", "startup_sequence") + "</dl>"
        return (
            '<p class="section-intro">Declared configuration, not live runtime state. Groups indicate membership; '
            "the artifact declares no topology edges. Declared external reachability is not a successful probe.</p>"
            '<div class="deployment-groups">' + "".join(groups) + "</div>"
            "<dl>"
            + "".join(self.fact("topology", key) for key in ("shape", "config_mechanism", "ports_and_endpoints"))
            + "</dl><h3>Declared startup order</h3>"
            + startup
            + self.records("topology", "components", "Component details", ("name", "role"), collapsed=True)
            + self.records(
                "topology",
                "real_dependencies",
                "Infrastructure details",
                ("name", "kind", "how_started"),
                ("config_source",),
                collapsed=True,
            )
            + self.records(
                "topology", "external_third_parties", "Third-party details", ("name", "used_for"), collapsed=True
            )
            + self.records(
                "topology",
                "standup_notes",
                "Standup notes",
                ("component", "standup_difficulty", "externally_reachable"),
                ("component", "standup_difficulty", "config_needed", "externally_reachable", "evidence"),
            )
        )

    def gaps(self) -> str:
        diagnostics = "".join(f"<li>{_e(item)}</li>" for item in self.bundle.diagnostics)
        return (
            '<p class="section-intro">Recorded limits and unresolved references remain open. '
            "Absence of a recorded gap does not establish completeness or runtime correctness.</p>"
            "<h3>Reference diagnostics</h3>"
            + (f"<ul>{diagnostics}</ul>" if diagnostics else "<p>none recorded</p>")
            + self.records("stack", "unknowns", "Stack unknowns", ())
            + self.records(
                "docs", "unavailable_sources", "Unavailable sources", ("locator", "reason", "suggested_remedy")
            )
            + self.records("docs", "deferred", "Deferred documents", ("locator", "rank", "why_deferred"))
            + self.records("docs", "open_questions", "Open questions", ())
            + self.records("topology", "assumptions", "Unconfirmed assumptions", ("claim", "why_unconfirmed"))
        )

    @staticmethod
    def artifact(artifact: Artifact, identifier: str, supporting: bool = False) -> str:
        label = "Supporting material" if supporting else "Saved contract"
        body = f"<p>{label} · {_e(artifact.media_type)}</p>"
        body += f'<p>SHA-256: <code class="hash">{_e(artifact.sha256)}</code></p>'
        body += '<p class="muted">Exact supplied UTF-8 text, including unknown fields. '
        body += "Source locators are inert text; no sources were retrieved.</p>"
        body += f"<pre><code>{_e(artifact.text)}</code></pre>"
        return _details(_e(artifact.name), body, identifier)

    def evidence(self) -> str:
        return (
            '<p class="section-intro">Artifact provenance identifies where an assertion was recorded. '
            "Original source references are preserved separately. Original text is absent unless explicitly supplied "
            "as supporting material; source excerpt not supplied. Support contains recorded assertions and is not "
            "independently verified by this renderer. No runtime-proof status is conferred.</p>"
            "<h3>Saved input artifacts</h3>"
            + "".join(
                self.artifact(artifact, self.artifact_ids[key]) for key, artifact in self.bundle.contracts.items()
            )
            + "<h3>Optional supporting material</h3>"
            + (
                "".join(
                    self.artifact(artifact, f"support-{index}", True)
                    for index, artifact in enumerate(self.bundle.support)
                )
                or "<p>not supplied</p>"
            )
            + '<h3>Record evidence</h3><p class="muted">Follow an Evidence link to its artifact, SHA-256, JSON pointer '
            "and original source references. Expand the matching panel manually if JavaScript is disabled.</p>"
            + "".join(self.panels)
        )


def render_report(bundle: ProfileBundle, title: str | None = None) -> str:
    """Render a validated bundle deterministically, without I/O or interpreting its content."""
    report = _Report(bundle)
    bodies = [report.overview(), report.stack(), report.docs(), report.journeys(), report.deployment(), report.gaps()]
    bodies.append(report.evidence())
    sections = "".join(
        f'<section id="{key}" aria-labelledby="heading-{key}"><h2 id="heading-{key}">{heading}</h2>{body}</section>'
        for (key, heading), body in zip(_SECTIONS, bodies, strict=True)
    )
    navigation = "".join(f'<a href="#{key}">{heading}</a>' for key, heading in _SECTIONS)
    heading = title if title is not None else f"Automated Profile of {_software_name(bundle)}"
    style_hash = base64.b64encode(hashlib.sha256(STYLE.encode()).digest()).decode()
    script_hash = base64.b64encode(hashlib.sha256(SCRIPT.encode()).digest()).decode()
    csp = (
        f"default-src 'none'; style-src 'sha256-{style_hash}'; script-src 'sha256-{script_hash}'; "
        "connect-src 'none'; img-src 'none'; object-src 'none'; frame-src 'none'; "
        "base-uri 'none'; form-action 'none'"
    )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<meta http-equiv="Content-Security-Policy" content="{_e(csp)}">'
        f"<title>{_e(heading)}</title><style>{STYLE}</style></head><body>"
        '<a class="skip" href="#main">Skip to report</a>'
        f'<header><div class="eyebrow">Saved artifact profile</div><h1>{_e(heading)}</h1>'
        "<p>A readable map of the recorded stack, documentary obligations, "
        "candidate journeys and declared deployment.</p>"
        "<p>Evidence stays in this file. Discovery and runtime verification were not performed by this renderer.</p>"
        f'<nav aria-label="Report sections">{navigation}</nav></header>'
        f'<main id="main">{sections}</main>'
        "<footer>Offline, self-contained report · Supplied evidence only · Expand details for complete recorded values "
        "and source attribution.</footer>"
        f"<script>{SCRIPT}</script></body></html>"
    )
