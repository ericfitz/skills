# logseq/scripts/logseqlib/page.py
"""Round-trip parser/writer for classic Logseq outline pages.

Contract: write(parse(text)) == text, byte-for-byte, for any accepted text.
Unmodeled syntax (queries, embeds, logbook, code fences) rides along as raw
continuation lines and is never rewritten. Pages we cannot parse raise
PageParseError and must never be written back.
"""
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote

BULLET_RE = re.compile(r"^(?P<indent>[ \t]*)- (?P<rest>.*)$")
PROP_RE = re.compile(r"^\s*(?P<key>[A-Za-z0-9_-]+):: (?P<val>.*)$")


class PageParseError(Exception):
    pass


@dataclass
class Block:
    """A bullet and its continuation/child lines.

    Invariant: lines is never empty. parse() always seeds it with the
    bullet line, and make_block() always produces at least one line.
    """
    lines: list[str] = field(default_factory=list)
    children: list["Block"] = field(default_factory=list)

    @property
    def content(self) -> str:
        m = BULLET_RE.match(self.lines[0])
        return m.group("rest") if m else self.lines[0]


@dataclass
class Page:
    pre_lines: list[str] = field(default_factory=list)
    blocks: list[Block] = field(default_factory=list)
    indent_unit: str = "  "
    final_newline: bool = True


def _detect_indent_unit(lines: list[str]) -> str:
    for line in lines:
        m = BULLET_RE.match(line)
        if m and m.group("indent"):
            ind = m.group("indent")
            return "\t" if ind.startswith("\t") else ind
    return "  "


def _depth(indent: str, unit: str, lineno: int) -> int:
    if not indent:
        return 0
    n, rem = divmod(len(indent), len(unit))
    if rem or indent != unit * n:
        raise PageParseError(f"line {lineno}: indentation is not a whole "
                             f"number of {unit!r} units")
    return n


def parse(text: str) -> Page:
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()  # trailing newline; write() re-adds one per line
    final_newline = text == "" or text.endswith("\n")
    page = Page(indent_unit=_detect_indent_unit(lines),
                final_newline=final_newline)
    stack: list[Block] = []  # stack[i] = open block at depth i
    for i, line in enumerate(lines, start=1):
        m = BULLET_RE.match(line)
        if not m:
            if stack:
                stack[-1].lines.append(line)  # raw, full original line
            else:
                page.pre_lines.append(line)
            continue
        depth = _depth(m.group("indent"), page.indent_unit, i)
        if depth > len(stack):
            raise PageParseError(f"line {i}: bullet depth {depth} with no "
                                 f"parent at depth {depth - 1}")
        del stack[depth:]
        block = Block(lines=[f"- {m.group('rest')}"])
        if depth == 0:
            page.blocks.append(block)
        else:
            stack[-1].children.append(block)
        stack.append(block)
    return page


def _write_block(out: list[str], block: Block, unit: str, depth: int) -> None:
    prefix = unit * depth
    out.append(prefix + block.lines[0])
    out.extend(block.lines[1:])
    for child in block.children:
        _write_block(out, child, unit, depth + 1)


def write(page: Page) -> str:
    out: list[str] = list(page.pre_lines)
    for block in page.blocks:
        _write_block(out, block, page.indent_unit, 0)
    if not out:
        return ""
    text = "\n".join(out)
    return text + "\n" if page.final_newline else text


def _prop_text(block: Block, idx: int) -> str:
    # Line 0 carries the "- " bullet marker; strip it before testing for
    # a key:: value property so a bullet like "- title:: Alt Style" is
    # recognized the same way an indented continuation "  id:: x" is.
    return block.content if idx == 0 else block.lines[idx]


def block_properties(block: Block) -> dict[str, str]:
    props = {}
    for idx in range(len(block.lines)):
        m = PROP_RE.match(_prop_text(block, idx))
        if m:
            props[m.group("key")] = m.group("val")
    return props


def _is_props_only_block(block: Block) -> bool:
    if not block.lines:
        return False
    return all(PROP_RE.match(_prop_text(block, idx))
               for idx in range(len(block.lines)))


def page_properties(page: Page) -> dict[str, str]:
    props = {}
    for line in page.pre_lines:
        m = PROP_RE.match(line)
        if m:
            props[m.group("key")] = m.group("val")
    if not props and page.blocks:
        first = page.blocks[0]
        if _is_props_only_block(first):
            props = block_properties(first)
    return props


# --- mutation + naming helpers (Task 4) ---


def make_block(content: str, indent_unit: str = "  ") -> Block:
    first, *rest = content.split("\n")
    lines = [f"- {first}"] + [f"  {ln}" for ln in rest]
    return Block(lines=lines)


def append_block(page: Page, content: str) -> Page:
    page.blocks.append(make_block(content, page.indent_unit))
    return page


def journal_filename(date_iso: str) -> str:
    return date_iso.replace("-", "_") + ".md"


def page_filename(name: str) -> str:
    return name.replace("/", "%2F") + ".md"


def filename_to_page_name(stem: str) -> str:
    return unquote(stem)


def append_to_file(path: Path, content: str) -> None:
    text = path.read_text() if path.is_file() else ""
    page = parse(text)  # PageParseError propagates; file untouched
    append_block(page, content)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(write(page))
    os.replace(tmp, path)
