# logseq/scripts/logseqlib/convert.py
"""Obsidian markdown -> Logseq outline conversion (pure text, no I/O)."""
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

ADMONITIONS = {"note": "NOTE", "warning": "WARNING", "tip": "TIP",
               "important": "IMPORTANT", "caution": "CAUTION"}
ASSET_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".pdf", ".webp"}

EMBED_RE = re.compile(r"!\[\[([^\[\]]+)\]\]")
MD_IMG_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
CALLOUT_RE = re.compile(r"^> \[!(\w+)\]\s*(.*)$")
LIST_RE = re.compile(r"^(?P<ind>[ \t]*)(?P<mark>[-*]|\d+\.) (?P<rest>.*)$")


@dataclass
class ConvertResult:
    content: str
    warnings: list = field(default_factory=list)
    assets: list = field(default_factory=list)


def _frontmatter(lines, warnings):
    """Return (prop_lines, rest_lines)."""
    if not lines or lines[0].strip() != "---":
        return [], lines
    try:
        end = next(i for i in range(1, len(lines))
                   if lines[i].strip() == "---")
    except StopIteration:
        return [], lines
    props, i = [], 1
    while i < end:
        line = lines[i]
        m = re.match(r"^(\w[\w-]*):\s*(.*)$", line)
        if not m:
            i += 1
            continue
        key, val = m.group(1), m.group(2).strip()
        items = []
        j = i + 1
        while j < end and re.match(r"^\s+- ", lines[j]):
            items.append(lines[j].strip()[2:])
            j += 1
        if items and not val:
            val, i = ", ".join(items), j
        elif not val or (j < end and lines[j].startswith((" ", "\t"))
                         and lines[j].strip()):
            warnings.append(f"frontmatter key '{key}' skipped (nested value)")
            while j < end and lines[j].startswith((" ", "\t")):
                j += 1
            i = j
            continue
        else:
            i += 1
        if val.startswith("[") and val.endswith("]"):
            val = ", ".join(p.strip() for p in val[1:-1].split(","))
        props.append(f"{key}:: {val}")
    return props, lines[end + 1:]


def _inline(line, assets):
    def embed(m):
        target = m.group(1)
        if PurePosixPath(target).suffix.lower() in ASSET_EXTS:
            assets.append(target)
            name = PurePosixPath(target).name
            return f"![{name}](../assets/{name})"
        return f"{{{{embed [[{target}]]}}}}"

    def image(m):
        alt, src = m.group(1), m.group(2)
        if src.startswith(("http://", "https://")):
            return m.group(0)
        assets.append(src)
        return f"![{alt}](../assets/{PurePosixPath(src).name})"

    return EMBED_RE.sub(embed, MD_IMG_RE.sub(image, line))


def convert_note(text: str, title: str) -> ConvertResult:
    warnings, assets, out = [], [], []
    props, lines = _frontmatter(text.split("\n"), warnings)
    numbered_warned = False
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if line.startswith("```"):
            block = [f"- {line}"]
            i += 1
            while i < len(lines):
                block.append(f"  {lines[i]}")
                if lines[i].startswith("```"):
                    i += 1
                    break
                i += 1
            out.extend(block)
            continue
        if line.startswith("> "):
            quote = []
            while i < len(lines) and lines[i].startswith("> "):
                quote.append(lines[i])
                i += 1
            m = CALLOUT_RE.match(quote[0])
            if m and m.group(1).lower() in ADMONITIONS:
                kind = ADMONITIONS[m.group(1).lower()]
                body = ([m.group(2)] if m.group(2) else []) + \
                       [q[2:] for q in quote[1:]]
                out.append(f"- #+BEGIN_{kind}")
                out.extend(f"  {_inline(b, assets)}" for b in body)
                out.append(f"  #+END_{kind}")
            else:
                if m:
                    warnings.append(f"unknown callout type '{m.group(1)}'")
                out.append(f"- {_inline(quote[0], assets)}")
                out.extend(f"  {_inline(q, assets)}" for q in quote[1:])
            continue
        lm = LIST_RE.match(line)
        if lm:
            while i < len(lines) and LIST_RE.match(lines[i]):
                m2 = LIST_RE.match(lines[i])
                ind = m2.group("ind").replace("\t", "  ")
                depth = len(ind) // 2
                if m2.group("mark") not in ("-", "*") and not numbered_warned:
                    warnings.append("numbered list flattened")
                    numbered_warned = True
                out.append("  " * depth + f"- {_inline(m2.group('rest'), assets)}")
                i += 1
            continue
        if line.startswith("#") and line.lstrip("#").startswith(" "):
            out.append(f"- {_inline(line, assets)}")
            i += 1
            continue
        para = []
        while (i < len(lines) and lines[i].strip()
               and not lines[i].startswith(("```", "> "))
               and not LIST_RE.match(lines[i])
               and not (lines[i].startswith("#")
                        and lines[i].lstrip("#").startswith(" "))):
            para.append(_inline(lines[i], assets))
            i += 1
        out.append(f"- {para[0]}")
        out.extend(f"  {p}" for p in para[1:])
    head = "\n".join(props) + "\n\n" if props else ""
    body = "\n".join(out) + "\n" if out else ""
    return ConvertResult(content=head + body, warnings=warnings,
                         assets=assets)
