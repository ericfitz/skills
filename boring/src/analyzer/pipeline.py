"""Pipeline orchestrator.

Loads the document, loads the calibration, runs every registered check,
assembles the JSON output. This is the function the CLI calls.
"""
from __future__ import annotations

import datetime as _dt
import platform
import uuid
from pathlib import Path
from typing import Any

from . import checks as _checks_pkg  # noqa: F401  # side-effect: triggers registry population
from .checks import all_checks, all_deferred
from .common.readability import compute_readability
from .config import Config, load_config
from .document import Document, load_document

SCHEMA_VERSION = "0.1.0"
SCRIPT_VERSION = "0.1.0"
SKILL_VERSION = "0.1.0"


def run_analysis(
    document_path: str | Path,
    calibration_path: str | Path,
    declared_genre: str | None = None,
    genre_source: str = "default",
) -> dict[str, Any]:
    """Run the full mechanical analysis. Returns the JSON output as a dict."""
    config = load_config(calibration_path, genre=declared_genre)
    doc = load_document(document_path, spacy_model_name=config.spacy_model_name)

    output: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "meta": _build_meta(config),
        "document": _build_document_block(doc, declared_genre, genre_source),
        "calibration": _build_calibration_block(config),
        "readability": compute_readability(doc),
        "structure": _build_structure_block(doc),
        "findings": {},
        "deferred_to_llm": [d.to_dict() for d in all_deferred()],
    }

    # Run every registered check.
    for check in all_checks():
        finding = check.run(doc, config)
        output["findings"][check.code] = finding.to_dict()

    return output


# ---------------------------------------------------------------------------


def _build_meta(config: Config) -> dict[str, Any]:
    spacy_version, model_version = _resolve_spacy_versions(config.spacy_model_name)
    return {
        "run_id": str(uuid.uuid4()),
        "run_timestamp_utc": _dt.datetime.now(_dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "skill_version": SKILL_VERSION,
        "script_version": SCRIPT_VERSION,
        "spacy_model": f"{config.spacy_model_name}-{model_version}" if model_version else config.spacy_model_name,
        "spacy_version": spacy_version,
        "proselint_version": _try_version("proselint"),
        "textstat_version": _try_version("textstat"),
        "python_version": platform.python_version(),
    }


def _build_document_block(doc: Document, declared_genre: str | None, genre_source: str) -> dict[str, Any]:
    return {
        "source_path": doc.source_path,
        "source_format": doc.source_format,
        "source_bytes": len(doc.source_bytes),
        "source_sha256": doc.source_sha256,
        "extracted_text_sha256": doc.extracted_text_sha256,
        "char_count": doc.char_count,
        "line_count": doc.line_count,
        "paragraph_count": len(doc.paragraphs),
        "sentence_count": len(doc.sentences),
        "word_count": doc.word_count,
        "declared_genre": declared_genre,
        "genre_source": genre_source,
    }


def _build_calibration_block(config: Config) -> dict[str, Any]:
    # For traceability we echo the genre profile applied and the override map.
    return {
        "calibration_file_sha256": config.calibration_file_sha256,
        "genre_profile_applied": config.genre_profile_applied,
        "active_thresholds": dict(config.active_thresholds),
    }


def _build_structure_block(doc: Document) -> dict[str, Any]:
    sentence_lengths = [_sentence_word_count(doc, s) for s in doc.sentences]
    paragraph_lengths = [_paragraph_word_count(p.text) for p in doc.paragraphs]

    return {
        "headings": [_heading_dict(doc, h) for h in doc.headings],
        "paragraph_lengths_words": paragraph_lengths,
        "sentence_lengths_words": sentence_lengths,
        "sentence_lengths_stats": _stats(sentence_lengths),
        # first_claim_position deferred to D1.1 implementation; placeholder for now
        "first_claim_position": {"found": False},
    }


def _heading_dict(doc: Document, h: Any) -> dict[str, Any]:
    return {
        "level": h.level,
        "text": h.text,
        "shape": "unknown",  # to be set by D1.3 / D1.1 once those checks exist
        "char_start": h.char_start,
        "char_end": h.char_end,
        "line_start": h.line_start,
    }


def _sentence_word_count(doc: Document, sent_ref: Any) -> int:
    span = doc.spacy_doc.char_span(sent_ref.char_start, sent_ref.char_end, alignment_mode="contract")
    if span is None:
        return 0
    return sum(1 for tok in span if tok.is_alpha)


def _paragraph_word_count(text: str) -> int:
    return len([w for w in text.split() if any(c.isalpha() for c in w)])


def _stats(values: list[int]) -> dict[str, Any]:
    if not values:
        return {"mean": 0, "median": 0, "stdev": 0, "coefficient_of_variation": 0, "p10": 0, "p90": 0}
    n = len(values)
    mean = sum(values) / n
    var = sum((x - mean) ** 2 for x in values) / n
    stdev = var ** 0.5
    cv = stdev / mean if mean else 0.0
    sorted_v = sorted(values)
    median = sorted_v[n // 2]
    p10 = sorted_v[max(0, int(0.10 * n) - 1)]
    p90 = sorted_v[min(n - 1, int(0.90 * n))]
    return {
        "mean": round(mean, 2),
        "median": median,
        "stdev": round(stdev, 2),
        "coefficient_of_variation": round(cv, 4),
        "p10": p10,
        "p90": p90,
    }


def _try_version(pkg: str) -> str | None:
    try:
        from importlib.metadata import version
        return version(pkg)
    except Exception:
        return None


def _resolve_spacy_versions(model_name: str) -> tuple[str | None, str | None]:
    spacy_v = _try_version("spacy")
    model_v = None
    try:
        from importlib.metadata import version
        model_v = version(model_name)
    except Exception:
        try:
            import spacy
            nlp = spacy.load(model_name)
            model_v = nlp.meta.get("version")
        except Exception:
            model_v = None
    return spacy_v, model_v
