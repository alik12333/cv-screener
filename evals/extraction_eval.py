"""
Evaluate the extraction stage against the ground truth from generate_cvs.py.

Why this eval exists: "the extractor works" is not a claim we're allowed to make
from reading a handful of examples (CLAUDE.md rule 5 — every number is measured).
Every synthetic CV was generated FROM a known-correct object, so this compares
extract.py's output against that answer key field by field.

Usage:
    python evals/extraction_eval.py
"""

import difflib
import json
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRUTH_DIR = ROOT / "data" / "ground_truth"
EXTRACTED_DIR = ROOT / "data" / "extracted"
RESULTS_DIR = ROOT / "evals" / "results"

RENDERERS = ["classic", "terse", "header_heavy"]  # order must match RENDERERS in generate_cvs.py
STEM_INDEX_RE = re.compile(r"^[a-z\-]+-(\d+)-")

SIMPLE_FIELDS = [
    "full_name", "email", "phone", "location",
    "current_title", "notice_period", "salary_expectation",
]


def norm(value) -> str:
    return " ".join(str(value).strip().lower().split())


def renderer_for(stem: str) -> str:
    match = STEM_INDEX_RE.match(stem)
    if not match:
        return "unknown"
    return RENDERERS[int(match.group(1)) % 3]


def skills_f1(truth: list, extracted: list) -> float:
    t = {norm(s) for s in truth}
    e = {norm(s) for s in extracted}
    if not t and not e:
        return 1.0
    if not t or not e:
        return 0.0
    overlap = len(t & e)
    precision = overlap / len(e)
    recall = overlap / len(t)
    return 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0


def nested_match(truth_list: list, extracted_list: list, keys: list) -> tuple:
    """Order-aligned comparison: entry i in truth vs entry i in extracted."""
    correct = 0
    for i, truth_item in enumerate(truth_list):
        if i >= len(extracted_list):
            continue
        candidate = extracted_list[i]
        if all(norm(truth_item[k]) == norm(candidate.get(k, "")) for k in keys):
            correct += 1
    return correct, len(truth_list)


def main() -> None:
    truth_files = sorted(TRUTH_DIR.glob("*.json"))
    if not truth_files:
        raise SystemExit("No ground truth found. Run src/generate_cvs.py first.")

    field_correct = {f: 0 for f in SIMPLE_FIELDS}
    field_total = {f: 0 for f in SIMPLE_FIELDS}
    years_correct = years_total = 0
    skills_scores: list = []
    statement_ratios: list = []
    employment_correct = employment_total = 0
    education_correct = education_total = 0
    by_layout: dict = {r: [] for r in RENDERERS}
    failed: list = []
    compared = 0

    for truth_path in truth_files:
        stem = truth_path.stem
        truth = json.loads(truth_path.read_text())["profile"]
        extracted_path = EXTRACTED_DIR / f"{stem}.json"
        if not extracted_path.exists():
            failed.append(stem)
            continue

        extracted = json.loads(extracted_path.read_text())
        compared += 1
        per_cv_hits = 0.0
        per_cv_total = 0

        for f in SIMPLE_FIELDS:
            field_total[f] += 1
            per_cv_total += 1
            if norm(truth[f]) == norm(extracted.get(f, "")):
                field_correct[f] += 1
                per_cv_hits += 1

        years_total += 1
        per_cv_total += 1
        if truth["total_years_experience"] == extracted.get("total_years_experience"):
            years_correct += 1
            per_cv_hits += 1

        s = skills_f1(truth["skills"], extracted.get("skills", []))
        skills_scores.append(s)
        per_cv_total += 1
        per_cv_hits += s

        ratio = difflib.SequenceMatcher(
            None, norm(truth["personal_statement"]), norm(extracted.get("personal_statement", ""))
        ).ratio()
        statement_ratios.append(ratio)
        per_cv_total += 1
        per_cv_hits += ratio

        ec, et = nested_match(truth["employment"], extracted.get("employment", []), ["employer", "title"])
        employment_correct += ec
        employment_total += et
        if et:
            per_cv_total += 1
            per_cv_hits += ec / et

        dc, dt = nested_match(truth["education"], extracted.get("education", []), ["institution", "qualification"])
        education_correct += dc
        education_total += dt
        if dt:
            per_cv_total += 1
            per_cv_hits += dc / dt

        by_layout[renderer_for(stem)].append(per_cv_hits / per_cv_total)

    lines = [f"# Extraction eval — {date.today().isoformat()}", ""]
    lines.append(f"CVs compared: {compared}/{len(truth_files)} ({len(failed)} failed extraction entirely)")
    if failed:
        lines.append(f"Failed: {', '.join(failed)}")
    lines.append("")

    lines.append("## Per-field accuracy (exact match, case/whitespace-insensitive)")
    for f in SIMPLE_FIELDS:
        pct = 100 * field_correct[f] / field_total[f] if field_total[f] else 0
        lines.append(f"- {f}: {pct:.1f}% ({field_correct[f]}/{field_total[f]})")
    pct = 100 * years_correct / years_total if years_total else 0
    lines.append(f"- total_years_experience: {pct:.1f}% ({years_correct}/{years_total})")
    lines.append("")

    avg_skills = sum(skills_scores) / len(skills_scores) if skills_scores else 0
    avg_ratio = sum(statement_ratios) / len(statement_ratios) if statement_ratios else 0
    close = sum(1 for r in statement_ratios if r >= 0.85)
    lines.append("## Fuzzy fields")
    lines.append(f"- skills (set F1): {avg_skills:.3f} average")
    lines.append(f"- personal_statement (text similarity ratio): {avg_ratio:.3f} average, "
                 f"{close}/{len(statement_ratios)} CVs >= 0.85 similarity")
    lines.append("")

    lines.append("## Nested fields (per-entry, order-aligned)")
    pct = 100 * employment_correct / employment_total if employment_total else 0
    lines.append(f"- employment (employer+title match): {pct:.1f}% ({employment_correct}/{employment_total})")
    pct = 100 * education_correct / education_total if education_total else 0
    lines.append(f"- education (institution+qualification match): {pct:.1f}% ({education_correct}/{education_total})")
    lines.append("")

    lines.append("## By CV layout (average per-CV score across all fields above)")
    for layout, scores in by_layout.items():
        avg = sum(scores) / len(scores) if scores else 0
        lines.append(f"- {layout}: {avg:.3f} ({len(scores)} CVs)")
    lines.append("")

    lines.append("## Excluded from scoring")
    lines.append("- right_to_work: never appears in the rendered CV text in any layout "
                  "(confirmed across all ground truth files). Scoring it would reward a "
                  "lucky default guess rather than genuine extraction. See docs/LEARNING.md Day 2.")

    report = "\n".join(lines)
    print(report)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / f"{date.today().isoformat()}-extraction.md"
    out_path.write_text(report, encoding="utf-8")
    print(f"\nsaved to {out_path}")


if __name__ == "__main__":
    main()
