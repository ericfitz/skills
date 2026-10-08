# logseq/scripts/logseqlib/refactor.py
"""Changeset builders for reference renames and page merges."""
import re

from .apply import Change


def _substitute(text: str, old: str, new: str) -> str:
    link = re.compile(r"\[\[" + re.escape(old) + r"\]\]", re.IGNORECASE)
    tag = re.compile(r"(?<!\S)#" + re.escape(old) + r"(?![\w/-])",
                     re.IGNORECASE)
    text = link.sub(f"[[{new}]]", text)
    return tag.sub(f"#{new}", text)


def rename_refs(index, old: str, new: str) -> list:
    changes = []
    for info in index.pages.values():
        try:
            text = info.path.read_text()
        except (OSError, UnicodeDecodeError):
            # An undecodable file is not a valid Logseq page; it must not
            # be rewritten.
            continue
        replaced = _substitute(text, old, new)
        if replaced != text:
            changes.append(Change(info.path, replaced))
    return changes


def merge_pages(index, source: str, target: str, merged_content: str) -> list:
    if source.lower() not in index.pages:
        raise KeyError(f"unknown page: {source}")
    if target.lower() not in index.pages:
        raise KeyError(f"unknown page: {target}")
    src = index.pages[source.lower()]
    tgt = index.pages[target.lower()]
    changes = [
        Change(tgt.path, _substitute(merged_content, source, target)),
        Change(src.path, None),
    ]
    for ch in rename_refs(index, source, target):
        if ch.path not in (src.path, tgt.path):
            changes.append(ch)
    return changes
