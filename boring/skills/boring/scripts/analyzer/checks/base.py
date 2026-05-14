"""Core types: Finding, Flag, Locator, and the Check protocol.

Every check produces a Finding for one sub-dimension. A Finding has a
summary score, raw measurements, and zero or more span-level Flags.

The Check protocol is intentionally minimal: a check declares its code,
name, axis, the calibration keys it reads, and a `run` method that
takes a Document and returns a Finding.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

# Severity levels emitted by checks.
SEVERITY_PASS = "pass"
SEVERITY_WARN = "warn"
SEVERITY_SEVERE = "severe"
SEVERITY_INFO = "info"  # informational, below warn threshold

# Scope of a Locator — what kind of region it points at.
SCOPE_SPAN = "span"
SCOPE_PARAGRAPH = "paragraph"
SCOPE_SECTION = "section"
SCOPE_DOCUMENT = "document"


@dataclass
class Locator:
    """Composite locator carrying multiple redundant addressing fields.

    See schema-v0.1.0.md for full semantics. For markdown/plaintext, all
    char/line fields refer to the source file. For docx, they refer to
    the extracted normalized text — paragraph_index and text_preview are
    the primary navigation aids in that case. For pdf, char/line refer to
    the extracted normalized text and page_number is populated as the
    primary navigation aid.
    """
    scope: str = SCOPE_SPAN
    char_start: int = 0
    char_end: int = 0
    line_start: int = 0
    line_col_start: int = 0
    line_end: int = 0
    line_col_end: int = 0
    sentence_index_start: int | None = None
    sentence_index_end: int | None = None
    paragraph_index: int | None = None
    page_number: int | None = None  # 1-indexed; populated for PDF source only
    page_number_end: int | None = None  # 1-indexed; differs from page_number when span crosses pages
    section_path: list[str] = field(default_factory=list)
    text_sha256: str = ""
    text_preview: str = ""
    context_before: str = ""
    context_after: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "scope": self.scope,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "line_start": self.line_start,
            "line_col_start": self.line_col_start,
            "line_end": self.line_end,
            "line_col_end": self.line_col_end,
            "section_path": self.section_path,
            "text_sha256": self.text_sha256,
            "text_preview": self.text_preview,
            "context_before": self.context_before,
            "context_after": self.context_after,
        }
        if self.sentence_index_start is not None:
            d["sentence_index_start"] = self.sentence_index_start
            d["sentence_index_end"] = self.sentence_index_end
        if self.paragraph_index is not None:
            d["paragraph_index"] = self.paragraph_index
        if self.page_number is not None:
            d["page_number"] = self.page_number
            if self.page_number_end is not None and self.page_number_end != self.page_number:
                d["page_number_end"] = self.page_number_end
        return d


@dataclass
class Flag:
    """A span-level finding within a check."""
    flag_id: str
    severity: str
    message: str
    locator: Locator
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "flag_id": self.flag_id,
            "severity": self.severity,
            "message": self.message,
            "locator": self.locator.to_dict(),
            "evidence": self.evidence,
        }


@dataclass
class Summary:
    """The check's document-level score against thresholds."""
    metric_name: str
    metric_value: float
    threshold_warn: float | None = None
    threshold_severe: float | None = None
    score: str = SEVERITY_PASS
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric_name": self.metric_name,
            "metric_value": self.metric_value,
            "threshold_warn": self.threshold_warn,
            "threshold_severe": self.threshold_severe,
            "score": self.score,
            "rationale": self.rationale,
        }


@dataclass
class Finding:
    """A check's full output for one sub-dimension."""
    code: str
    name: str
    axis: str
    checked: bool = True
    summary: Summary | None = None
    measurements: dict[str, Any] = field(default_factory=dict)
    flags: list[Flag] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "axis": self.axis,
            "checked": self.checked,
            "summary": self.summary.to_dict() if self.summary else None,
            "measurements": self.measurements,
            "flags": [f.to_dict() for f in self.flags],
            "notes": self.notes,
        }


@dataclass
class DeferredCheck:
    """A sub-dimension the script does not check (semantic judgment required).

    Carries optional 'hints' — cheap signals that may help the LLM phase.
    """
    code: str
    name: str
    axis: str
    reason: str
    hints: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "axis": self.axis,
            "reason": self.reason,
            "hints": self.hints,
        }


@runtime_checkable
class Check(Protocol):
    """Protocol every check must satisfy.

    A check is a class with class-level attributes for identity (code,
    name, axis) and an instance method `run(doc, config)` that returns
    a Finding. Checks should be stateless across calls — any caching
    happens on the Document object.
    """
    code: str        # e.g., "D2.3"
    name: str        # e.g., "Passive overhang"
    axis: str        # one of: direction, density, texture, surprise

    def run(self, doc: Any, config: Any) -> Finding: ...


def score_against_thresholds(
    value: float,
    warn: float | None,
    severe: float | None,
    higher_is_worse: bool = True,
) -> str:
    """Standard severity scoring from a value and two thresholds.

    higher_is_worse=True (default): value >= severe -> severe, value >= warn -> warn.
    higher_is_worse=False: value <= severe -> severe, value <= warn -> warn.
    Returns one of SEVERITY_PASS, SEVERITY_WARN, SEVERITY_SEVERE.
    """
    if higher_is_worse:
        if severe is not None and value >= severe:
            return SEVERITY_SEVERE
        if warn is not None and value >= warn:
            return SEVERITY_WARN
        return SEVERITY_PASS
    else:
        if severe is not None and value <= severe:
            return SEVERITY_SEVERE
        if warn is not None and value <= warn:
            return SEVERITY_WARN
        return SEVERITY_PASS
