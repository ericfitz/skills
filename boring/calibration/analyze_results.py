"""Per-check separability analysis over calibration/results.csv.

For each sub-dimension code, compute:

- Distribution stats (mean, median, stdev) of metric_value, split by label
- AUC: P(boring metric > not-boring metric) for higher-is-worse checks,
  flipped for lower-is-worse checks. AUC near 0.5 = no signal; near 1.0 =
  perfectly separated. Computed via Mann-Whitney U over all ranks.
- Best Youden's J threshold: the metric value that maximizes TPR − FPR
  when boring=positive class
- Current thresholds (warn / severe) from the resolved calibration —
  read from any row, since every row echoes its run-time thresholds
- A recommendation: shift_warn / shift_severe / drop / keep

For the "checks-with-no-signal" decision: AUC < 0.55 (weaker than coin
flip + slack) flags as "drop or rethink". AUC in [0.55, 0.65] = "weak,
keep but down-weight". AUC >= 0.65 = "useful". Heuristic, not a hard
rule.

Output: a Markdown report at calibration/recommendations.md. The report
intentionally stops short of editing calibration.toml — the human
reviews and applies.

Usage (from boring/):
    uv run python calibration/analyze_results.py
"""
from __future__ import annotations

import csv
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS_CSV = _REPO_ROOT / "calibration" / "results.csv"
REPORT_MD = _REPO_ROOT / "calibration" / "recommendations.md"

# For each sub-dimension, declare whether higher metric_value = worse.
# This matches the higher_is_worse argument the checks pass into
# score_against_thresholds(). Pulled from a hand-read of each check.
HIGHER_IS_WORSE: dict[str, bool] = {
    "D1.1": True,    # position_of_first_claim_pct (later = worse)
    "D1.4": False,   # transition_marker_ratio_at_section_boundaries (lower = worse)
    "D1.6": True,    # expletive_subject_ratio (higher = worse)
    "D2.1": True,    # wordy_phrases_per_1000_words
    "D2.2": True,    # nominalizations_per_sentence
    "D2.3": True,    # passive_sentence_ratio
    "D2.4": True,    # pct_sentences_over_warn_threshold
    "D2.7": True,    # hedges_per_100_sentences
    "D2.8": True,    # throat_clearing_phrases_per_1000_words
    "D3.1": False,   # coefficient_of_variation (lower = more monotonous = worse)
    "D3.3": True,    # longest_same_first_token_run
    "D3.4": False,   # paragraph_length_coefficient_of_variation (lower = worse)
    "D3.5": False,   # mattr (lower = worse)
    "D4.1": True,    # longest_abstract_paragraph_run
    "D4.4": True,    # vague_terms_per_1000_words
}


def _to_float(v: str | None) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {"n": 0, "mean": 0.0, "median": 0.0, "stdev": 0.0, "min": 0.0, "max": 0.0}
    n = len(values)
    mean = sum(values) / n
    var = sum((x - mean) ** 2 for x in values) / n
    stdev = math.sqrt(var)
    sorted_v = sorted(values)
    median = sorted_v[n // 2] if n % 2 == 1 else (sorted_v[n // 2 - 1] + sorted_v[n // 2]) / 2
    return {
        "n": n, "mean": mean, "median": median, "stdev": stdev,
        "min": sorted_v[0], "max": sorted_v[-1],
    }


def _auc_higher_is_worse(boring: list[float], not_boring: list[float]) -> float:
    """AUC under the convention boring=positive class, with higher metric =
    more boring. Equivalent to Mann-Whitney U / (n_b * n_nb)."""
    if not boring or not_boring:
        pass
    if not boring or not not_boring:
        return float("nan")
    n_b = len(boring)
    n_nb = len(not_boring)
    # Combine, rank with average for ties.
    combined = [(v, "b") for v in boring] + [(v, "n") for v in not_boring]
    combined.sort(key=lambda p: p[0])
    ranks: list[float] = [0.0] * len(combined)
    i = 0
    while i < len(combined):
        j = i
        while j < len(combined) and combined[j][0] == combined[i][0]:
            j += 1
        avg = (i + j + 1) / 2  # 1-indexed average rank
        for k in range(i, j):
            ranks[k] = avg
        i = j
    rank_sum_b = sum(r for r, (_, lab) in zip(ranks, combined) if lab == "b")
    u_b = rank_sum_b - n_b * (n_b + 1) / 2
    return u_b / (n_b * n_nb)


def _youden_threshold(
    boring: list[float], not_boring: list[float], higher_is_worse: bool
) -> tuple[float, float, float, float]:
    """Find the metric value that maximizes Youden's J (TPR - FPR) with
    boring=positive class. Returns (threshold, j, tpr, fpr).

    Search strategy: try every unique metric value in the union as a
    candidate threshold. For "higher_is_worse=True", predict positive when
    metric >= threshold; otherwise predict positive when metric <= threshold.
    """
    if not boring or not not_boring:
        return float("nan"), 0.0, 0.0, 0.0
    candidates = sorted(set(boring) | set(not_boring))
    best = (candidates[0], -1.0, 0.0, 0.0)
    for t in candidates:
        if higher_is_worse:
            tpr = sum(1 for v in boring if v >= t) / len(boring)
            fpr = sum(1 for v in not_boring if v >= t) / len(not_boring)
        else:
            tpr = sum(1 for v in boring if v <= t) / len(boring)
            fpr = sum(1 for v in not_boring if v <= t) / len(not_boring)
        j = tpr - fpr
        if j > best[1]:
            best = (t, j, tpr, fpr)
    return best


def _recommendation(
    auc: float,
    current_warn: float | None,
    current_severe: float | None,
    youden_t: float,
    higher_is_worse: bool,
    boring_median: float,
    not_boring_median: float,
) -> str:
    if math.isnan(auc):
        return "INSUFFICIENT DATA — both classes need samples."
    parts: list[str] = []
    if auc < 0.55:
        parts.append(
            "**LOW SIGNAL.** AUC < 0.55. Consider dropping this check or rethinking "
            "the metric — it is not separating boring from not-boring documents in "
            "this corpus."
        )
    elif auc < 0.65:
        parts.append(
            "**WEAK SIGNAL.** AUC in [0.55, 0.65). Keep, but treat as a tiebreaker "
            "rather than a primary signal."
        )
    elif auc < 0.80:
        parts.append(
            "**USEFUL.** AUC in [0.65, 0.80). Recalibrate thresholds toward the Youden point."
        )
    else:
        parts.append("**STRONG SIGNAL.** AUC ≥ 0.80. Recalibrate confidently.")

    # Threshold direction guidance
    if not math.isnan(youden_t) and current_warn is not None:
        too_tight = (
            f"Suggested **warn** threshold: ≈ {youden_t:.3g} (current {current_warn:g}). "
            "Current threshold is too tight — flagging too many not-boring docs."
        )
        too_loose = (
            f"Suggested **warn** threshold: ≈ {youden_t:.3g} (current {current_warn:g}). "
            "Current threshold is too loose — missing boring docs."
        )
        at_point = f"Current **warn** threshold ({current_warn:g}) is at the Youden point."
        if higher_is_worse:
            if youden_t > current_warn:
                parts.append(too_tight)
            elif youden_t < current_warn:
                parts.append(too_loose)
            else:
                parts.append(at_point)
        else:  # lower is worse
            if youden_t < current_warn:
                parts.append(too_tight)
            elif youden_t > current_warn:
                parts.append(too_loose)
            else:
                parts.append(at_point)

    # Severe-threshold sanity check via class medians
    if current_severe is not None:
        if higher_is_worse and boring_median > current_severe:
            pass  # current severe is reasonable
        elif (not higher_is_worse) and boring_median < current_severe:
            pass

    return "  \n".join(parts)


def main() -> int:
    if not RESULTS_CSV.is_file():
        print(f"Missing {RESULTS_CSV}. Run calibration/run_corpus.py first.", file=sys.stderr)
        return 1

    rows: list[dict[str, str]] = []
    with RESULTS_CSV.open() as f:
        rows = list(csv.DictReader(f))

    by_code: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        code = r["code"]
        mv = _to_float(r.get("metric_value"))
        if mv is None or r.get("checked") != "True":
            continue
        by_code[code].append({
            "label": r["label"],
            "metric_value": mv,
            "score": r.get("score"),
            "filename": r.get("filename"),
            "warn": _to_float(r.get("threshold_warn")),
            "severe": _to_float(r.get("threshold_severe")),
            "name": r.get("name"),
        })

    out_lines: list[str] = []
    out_lines.append("# Calibration recommendations\n")
    out_lines.append(
        "Per-check separability analysis over the labeled corpus in "
        "`calibration/{boring,not-boring}/`. Generated by "
        "`calibration/analyze_results.py`. Review and apply selectively to "
        "`calibration.toml`.\n"
    )

    # Corpus summary
    boring_files = sorted({r["filename"] for r in rows if r["label"] == "boring"})
    nb_files = sorted({r["filename"] for r in rows if r["label"] == "not-boring"})
    out_lines.append(f"**Corpus**: {len(boring_files)} boring docs, {len(nb_files)} not-boring docs.\n")

    out_lines.append("## Quick scoreboard\n")
    out_lines.append(
        "| Code | Name | AUC | Boring median | Not-boring median | "
        "Youden T | Current warn | Verdict |"
    )
    out_lines.append("|---|---|---|---|---|---|---|---|")

    detail_blocks: list[str] = []
    for code in sorted(by_code):
        entries = by_code[code]
        higher_is_worse = HIGHER_IS_WORSE.get(code, True)
        boring_vals = [e["metric_value"] for e in entries if e["label"] == "boring"]
        nb_vals = [e["metric_value"] for e in entries if e["label"] == "not-boring"]
        if not boring_vals or not nb_vals:
            continue
        b_stats = _stats(boring_vals)
        n_stats = _stats(nb_vals)
        # AUC convention: always express as P(correct ordering with boring=positive).
        # _auc_higher_is_worse computes P(boring rank > not-boring rank).
        # If lower-is-worse, boring should rank LOWER, so flip.
        auc_raw = _auc_higher_is_worse(boring_vals, nb_vals)
        auc = auc_raw if higher_is_worse else (1 - auc_raw)
        youden_t, youden_j, tpr, fpr = _youden_threshold(boring_vals, nb_vals, higher_is_worse)

        sample_warn = entries[0]["warn"]
        sample_severe = entries[0]["severe"]

        verdict = "useful" if auc >= 0.65 else ("weak" if auc >= 0.55 else "low signal")
        if math.isnan(auc):
            verdict = "no data"

        out_lines.append(
            f"| {code} | {entries[0]['name']} | "
            f"{auc:.2f} | {b_stats['median']:.3g} | {n_stats['median']:.3g} | "
            f"{youden_t:.3g} | {sample_warn:g} | {verdict} |"
        )

        # Detail block
        rec = _recommendation(
            auc, sample_warn, sample_severe, youden_t,
            higher_is_worse, b_stats["median"], n_stats["median"],
        )
        block: list[str] = []
        block.append(f"### {code} — {entries[0]['name']}\n")
        block.append(f"- **Metric**: {entries[0].get('name')}; higher_is_worse={higher_is_worse}")
        block.append(f"- **AUC**: {auc:.3f} (boring as positive class)")
        block.append(
            f"- **Boring** (n={b_stats['n']}): mean={b_stats['mean']:.3g}, "
            f"median={b_stats['median']:.3g}, stdev={b_stats['stdev']:.3g}, "
            f"range=[{b_stats['min']:.3g}, {b_stats['max']:.3g}]"
        )
        block.append(
            f"- **Not-boring** (n={n_stats['n']}): mean={n_stats['mean']:.3g}, "
            f"median={n_stats['median']:.3g}, stdev={n_stats['stdev']:.3g}, "
            f"range=[{n_stats['min']:.3g}, {n_stats['max']:.3g}]"
        )
        block.append(
            f"- **Best Youden threshold**: {youden_t:.3g} "
            f"(J={youden_j:.2f}, TPR={tpr:.2f}, FPR={fpr:.2f})"
        )
        block.append(
            f"- **Current calibration** (sampled from corpus run): "
            f"warn={sample_warn:g}, severe={sample_severe:g}"
        )
        block.append(f"\n{rec}\n")
        # Per-doc table for inspection
        block.append("\n<details><summary>Per-document values</summary>\n")
        block.append("\n| Filename | Label | Value | Score |")
        block.append("|---|---|---|---|")
        sort_key = (
            (lambda x: (x["label"], -x["metric_value"]))
            if higher_is_worse
            else (lambda x: (x["label"], x["metric_value"]))
        )
        for e in sorted(entries, key=sort_key):
            block.append(
                f"| {e['filename']} | {e['label']} | {e['metric_value']:.4g} | {e['score']} |"
            )
        block.append("\n</details>\n")
        detail_blocks.append("\n".join(block))

    out_lines.append("")
    out_lines.append("Notes:")
    out_lines.append(
        "- AUC is `P(boring metric ranks worse than not-boring)`. "
        "0.5 = chance. ≥ 0.65 = useful, ≥ 0.80 = strong."
    )
    out_lines.append(
        "- Youden T is the single threshold that maximizes (TPR − FPR) "
        "with boring as the positive class."
    )
    out_lines.append(
        "- The recommendations are heuristic; sample size is small and "
        "the corpus is genre-specific."
    )
    out_lines.append("")
    out_lines.append("## Per-check details\n")
    out_lines.extend(detail_blocks)

    REPORT_MD.write_text("\n".join(out_lines), encoding="utf-8")
    print(f"Wrote {REPORT_MD}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
