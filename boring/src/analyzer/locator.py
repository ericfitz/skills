"""Locator construction helpers.

Building locators correctly is fiddly: line numbers, columns, hashes,
preview windows. This module centralizes it so checks just call
make_span_locator(doc, char_start, char_end) and get a fully-populated
Locator.
"""
from __future__ import annotations

import hashlib

from .checks.base import SCOPE_DOCUMENT, SCOPE_PARAGRAPH, SCOPE_SPAN, Locator
from .document import Document

# Number of chars of surrounding context to include in locators.
CONTEXT_WINDOW = 50
# Maximum chars of text to inline as preview.
PREVIEW_MAX = 200


def _line_col_for_offset(text: str, offset: int) -> tuple[int, int]:
    """1-indexed line and column for a char offset."""
    if offset <= 0:
        return 1, 1
    if offset > len(text):
        offset = len(text)
    # Lines before this offset
    line = text.count("\n", 0, offset) + 1
    last_nl = text.rfind("\n", 0, offset)
    col = offset - last_nl  # last_nl is -1 if not found, giving col = offset+1
    return line, col


def _hash_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _truncate_preview(text: str) -> str:
    if len(text) <= PREVIEW_MAX:
        return text
    return text[: PREVIEW_MAX - 1] + "\u2026"  # ellipsis


def make_span_locator(
    doc: Document,
    char_start: int,
    char_end: int,
    sentence_index_start: int | None = None,
    sentence_index_end: int | None = None,
) -> Locator:
    """Build a fully-populated Locator for a span of text in the document."""
    text = doc.extracted_text
    if char_start < 0:
        char_start = 0
    if char_end > len(text):
        char_end = len(text)
    span_text = text[char_start:char_end]

    line_start, col_start = _line_col_for_offset(text, char_start)
    line_end, col_end = _line_col_for_offset(text, char_end)

    # Context windows
    ctx_before_start = max(0, char_start - CONTEXT_WINDOW)
    ctx_after_end = min(len(text), char_end + CONTEXT_WINDOW)
    context_before = text[ctx_before_start:char_start]
    context_after = text[char_end:ctx_after_end]

    # Paragraph index for this span (use the start)
    paragraph_index = doc._paragraph_index_for_offset(char_start)

    # Section path at this offset
    section_path = doc.section_path_for_offset(char_start)

    return Locator(
        scope=SCOPE_SPAN,
        char_start=char_start,
        char_end=char_end,
        line_start=line_start,
        line_col_start=col_start,
        line_end=line_end,
        line_col_end=col_end,
        sentence_index_start=sentence_index_start,
        sentence_index_end=sentence_index_end,
        paragraph_index=paragraph_index,
        section_path=section_path,
        text_sha256=_hash_text(span_text),
        text_preview=_truncate_preview(span_text),
        context_before=context_before,
        context_after=context_after,
    )


def make_paragraph_locator(doc: Document, paragraph_index: int) -> Locator:
    """Locator for a whole paragraph."""
    if not (0 <= paragraph_index < len(doc.paragraphs)):
        raise IndexError(f"paragraph_index {paragraph_index} out of range")
    p = doc.paragraphs[paragraph_index]
    text = doc.extracted_text
    para_text = text[p.char_start:p.char_end]
    line_start, col_start = _line_col_for_offset(text, p.char_start)
    line_end, col_end = _line_col_for_offset(text, p.char_end)

    return Locator(
        scope=SCOPE_PARAGRAPH,
        char_start=p.char_start,
        char_end=p.char_end,
        line_start=line_start,
        line_col_start=col_start,
        line_end=line_end,
        line_col_end=col_end,
        paragraph_index=paragraph_index,
        section_path=doc.section_path_for_offset(p.char_start),
        text_sha256=_hash_text(para_text),
        text_preview=_truncate_preview(para_text),
        context_before="",
        context_after="",
    )


def make_document_locator(doc: Document) -> Locator:
    """Locator for the whole document. Used for aggregate findings."""
    text = doc.extracted_text
    return Locator(
        scope=SCOPE_DOCUMENT,
        char_start=0,
        char_end=len(text),
        line_start=1,
        line_col_start=1,
        line_end=text.count("\n") + 1,
        line_col_end=len(text) - text.rfind("\n") if "\n" in text else len(text),
        text_sha256=_hash_text(text),
        text_preview="",
        context_before="",
        context_after="",
    )
