# logseq/scripts/logseqlib/scan.py
"""Read-only graph walker: link index + pure lint checks over it."""
import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import page as pg

LINK_RE = re.compile(r"\[\[([^\[\]]+)\]\]")
TAG_RE = re.compile(r"(?<!\S)#([A-Za-z0-9/_-]+)")


@dataclass
class PageInfo:
    name: str
    path: Path
    is_journal: bool
    links: set = field(default_factory=set)
    tags: set = field(default_factory=set)
    properties: dict = field(default_factory=dict)
    parse_error: str | None = None


@dataclass
class Index:
    pages: dict = field(default_factory=dict)  # lower-name -> PageInfo


def _scan_file(path: Path, is_journal: bool) -> PageInfo:
    name = pg.filename_to_page_name(path.stem)
    text = path.read_text()
    info = PageInfo(name=name, path=path, is_journal=is_journal,
                    links=set(LINK_RE.findall(text)),
                    tags=set(TAG_RE.findall(text)))
    try:
        parsed = pg.parse(text)
        info.properties = pg.page_properties(parsed)
    except pg.PageParseError as e:
        info.parse_error = str(e)
    return info


def scan_graph(graph: Path) -> Index:
    index = Index()
    for sub, is_journal in (("pages", False), ("journals", True)):
        d = graph / sub
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.md")):
            info = _scan_file(f, is_journal)
            index.pages[info.name.lower()] = info
    return index


def backlinks(index: Index, name: str) -> set:
    target = name.lower()
    return {key for key, info in index.pages.items()
            if target in {ln.lower() for ln in info.links}}


def lint_unparseable(index: Index):
    return [{"type": "unparseable", "page": info.name,
             "detail": info.parse_error}
            for info in index.pages.values() if info.parse_error]


def lint_broken_links(index: Index):
    out = []
    for info in index.pages.values():
        for link in sorted(info.links):
            if link.lower() not in index.pages:
                out.append({"type": "broken-link", "page": info.name,
                            "detail": f"[[{link}]] has no page file"})
    return out


def lint_case_conflicts(index: Index):
    spellings = {}
    for info in index.pages.values():
        for link in info.links:
            spellings.setdefault(link.lower(), set()).add(link)
    out = []
    for low, forms in sorted(spellings.items()):
        if len(forms) > 1:
            canonical = index.pages[low].name if low in index.pages else None
            out.append({"type": "case-conflict",
                        "page": canonical or sorted(forms)[0],
                        "detail": "link spellings: " + ", ".join(sorted(forms))})
    return out


def lint_orphans(index: Index):
    linked = set()
    for info in index.pages.values():
        linked |= {ln.lower() for ln in info.links}
        linked |= {t.lower() for t in info.tags}
    return [{"type": "orphan", "page": info.name,
             "detail": "no inbound links and no tags"}
            for key, info in sorted(index.pages.items())
            if not info.is_journal and key not in linked and not info.tags]


def lint_near_duplicates(index: Index):
    names = sorted(k for k, v in index.pages.items() if not v.is_journal)
    out = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if a == b:
                continue
            if difflib.SequenceMatcher(None, a, b).ratio() >= 0.85:
                out.append({"type": "near-duplicate",
                            "page": index.pages[a].name,
                            "detail": f"{index.pages[a].name} ~ "
                                      f"{index.pages[b].name}"})
    return out


def lint_all(index: Index):
    return (lint_unparseable(index) + lint_broken_links(index)
            + lint_case_conflicts(index) + lint_orphans(index)
            + lint_near_duplicates(index))
