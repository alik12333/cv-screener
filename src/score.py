"""
Score one candidate against one job's rubric, one criterion at a time.

This is SCORE (stage 5, see docs/ARCHITECTURE.md). CLAUDE.md rule 1: the model
never outputs a final score - it judges one candidate against one criterion and
returns a verdict, a confidence, and an evidence quote. Turning those into a
ranked shortlist is pure code (stage 6, AGGREGATE) and isn't built yet - Day 3
is scoring only, per the build order in CLAUDE.md. Don't run ahead.

Input is data/extracted/*.json (EXTRACT's output), not data/ground_truth/. The
real pipeline never has ground truth to consult, and neither should this stage
- ground_truth is only read here for "intended_fit", to sanity-check whether
verdicts trend the way they should, never as scoring input.

Usage:
    python src/score.py                      # score all candidates for --role
    python src/score.py --role java-backend
    python src/score.py --role devops --limit 5
"""

import argparse
import json
import os
import time
import difflib
from collections import defaultdict
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from blind import blind_profile, profile_to_text

load_dotenv()

MODEL = "gemini-3.5-flash-lite"
MIN_SECONDS_BETWEEN_CALLS = 5.0
MAX_RETRIES = 4
TEMPERATURE = 0.0   # consistency matters: the same candidate/criterion pair should get the same verdict every time

ROOT = Path(__file__).resolve().parent.parent
SPECS_PATH = ROOT / "data" / "job_specs.json"
EXTRACTED_DIR = ROOT / "data" / "extracted"
TRUTH_DIR = ROOT / "data" / "ground_truth"
SCORES_DIR = ROOT / "data" / "scores"
RESULTS_DIR = ROOT / "evals" / "results"

QUOTE_MATCH_THRESHOLD = 0.9   # below this, an evidence quote is flagged as unverified


class CriterionVerdict(BaseModel):
    met: bool = Field(description="Whether the candidate text provides evidence they meet this criterion")
    confidence: float = Field(ge=0.0, le=1.0, description="0-1 confidence in this verdict")
    evidence_quote: str | None = Field(
        default=None,
        description=(
            "A short quote copied VERBATIM from the candidate text that supports "
            "the verdict. Null if the text gives no evidence either way - never "
            "invent one."
        ),
    )


def build_prompt(cv_text: str, criterion: str, criterion_type: str) -> str:
    # Without an explicit "today" anchor, a role dated "... - Present" has no
    # fixed length for the model to reason from, and it silently falls back on
    # its own notion of "now" (usually wrong). Confirmed live: the same
    # candidate/criterion pair flipped from an incorrect False (0.95 confidence)
    # to a correct True the moment this line was added.
    today = date.today().strftime("%d %B %Y")
    return f"""You are assessing ONE candidate against ONE hiring criterion only.
Ignore everything else about them that isn't relevant to this specific criterion.

Today's date: {today}

CRITERION ({criterion_type.replace('_', ' ')}): {criterion}

CANDIDATE
{cv_text}

INSTRUCTIONS
- Base your verdict only on what is written above. Do not assume anything the
  text does not state.
- If the text gives no evidence either way, set met to false, confidence low,
  and evidence_quote to null. Do not guess, and do not invent a quote to fill
  the field.
- evidence_quote must be copied character-for-character from the candidate
  text above when provided. Do not paraphrase, summarise, or strengthen it.
"""


_last_call_at = 0.0


def score_criterion(client: genai.Client, cv_text: str, criterion: str, criterion_type: str) -> CriterionVerdict:
    """One schema-enforced call, with backoff. Raises if it never succeeds."""
    global _last_call_at

    for attempt in range(MAX_RETRIES):
        wait = MIN_SECONDS_BETWEEN_CALLS - (time.time() - _last_call_at)
        if wait > 0:
            time.sleep(wait)

        try:
            _last_call_at = time.time()
            response = client.models.generate_content(
                model=MODEL,
                contents=build_prompt(cv_text, criterion, criterion_type),
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=CriterionVerdict,
                    temperature=TEMPERATURE,
                ),
            )
            if response.parsed is not None:
                return response.parsed
            return CriterionVerdict.model_validate_json(response.text)

        except Exception as exc:                      # noqa: BLE001
            backoff = 2 ** attempt * 5
            print(f"    attempt {attempt + 1} failed ({type(exc).__name__}: {exc}), "
                  f"retrying in {backoff}s")
            time.sleep(backoff)

    raise RuntimeError(f"gave up after {MAX_RETRIES} attempts")


def verify_quote(quote: str | None, source_text: str) -> tuple[bool, float]:
    """Checks a claimed evidence quote actually appears in what the model was shown.

    This is the "catching invented quotes" check. Exact match (after collapsing
    whitespace/case) scores 1.0. Otherwise we compare the quote against the best
    matching window of the source text - catches minor reformatting without
    letting a fabricated quote slip through as "close enough".
    """
    if quote is None or not quote.strip():
        return True, 1.0   # nothing claimed, nothing to verify

    norm_quote = " ".join(quote.strip().lower().split())
    norm_source = " ".join(source_text.lower().split())
    if norm_quote in norm_source:
        return True, 1.0

    matcher = difflib.SequenceMatcher(None, norm_source, norm_quote)
    match = matcher.find_longest_match(0, len(norm_source), 0, len(norm_quote))
    window_start = max(0, match.a - 10)
    window = norm_source[window_start: match.a + len(norm_quote) + 10]
    ratio = difflib.SequenceMatcher(None, window, norm_quote).ratio()
    return ratio >= QUOTE_MATCH_THRESHOLD, ratio


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", default="devops")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit("GEMINI_API_KEY is not set. Copy .env.example to .env.")

    specs = {s["id"]: s for s in json.loads(SPECS_PATH.read_text())}
    if args.role not in specs:
        raise SystemExit(f"Unknown role '{args.role}'. Choices: {sorted(specs)}")
    spec = specs[args.role]
    criteria = [(m, "must_have") for m in spec["must_haves"]] + \
               [(n, "nice_to_have") for n in spec["nice_to_haves"]]

    client = genai.Client(api_key=api_key)
    SCORES_DIR.mkdir(parents=True, exist_ok=True)

    extracted_files = sorted(EXTRACTED_DIR.glob(f"{args.role}-*.json"))
    if not extracted_files:
        raise SystemExit(f"No extracted profiles for '{args.role}'. Run src/extract.py first.")
    if args.limit:
        extracted_files = extracted_files[: args.limit]

    quote_checks: list[bool] = []
    fit_summary: dict[str, tuple] = {}

    for i, extracted_path in enumerate(extracted_files, start=1):
        stem = extracted_path.stem
        print(f"[{i}/{len(extracted_files)}] {stem}")
        profile = json.loads(extracted_path.read_text())
        cv_text = profile_to_text(blind_profile(profile))

        truth_path = TRUTH_DIR / f"{stem}.json"
        intended_fit = json.loads(truth_path.read_text())["intended_fit"] if truth_path.exists() else None

        results = []
        for criterion, ctype in criteria:
            verdict = score_criterion(client, cv_text, criterion, ctype)
            verified, match_score = verify_quote(verdict.evidence_quote, cv_text)
            quote_checks.append(verified)
            if not verified:
                print(f"    UNVERIFIED QUOTE [{ctype}] '{criterion[:50]}': "
                      f"{verdict.evidence_quote!r} (match={match_score:.2f})")
            results.append({
                "criterion": criterion,
                "type": ctype,
                "met": verdict.met,
                "confidence": verdict.confidence,
                "evidence_quote": verdict.evidence_quote,
                "quote_verified": verified,
                "quote_match_score": round(match_score, 3),
            })

        (SCORES_DIR / f"{stem}.json").write_text(
            json.dumps({"stem": stem, "role": args.role, "intended_fit": intended_fit, "criteria": results}, indent=2),
            encoding="utf-8",
        )

        must_haves = [r for r in results if r["type"] == "must_have"]
        fit_summary[stem] = (intended_fit, sum(1 for r in must_haves if r["met"]), len(must_haves))

    # ---------------------------------------------------------------------
    # Summary
    # ---------------------------------------------------------------------
    total = len(quote_checks)
    verified = sum(quote_checks)
    lines = [f"# Scoring eval — {args.role} — {date.today().isoformat()}", ""]
    lines.append(f"Candidates: {len(extracted_files)} | Criteria per candidate: {len(criteria)} "
                 f"| Judgements: {total}")
    lines.append("")
    lines.append("## Evidence quote verification")
    lines.append(f"- Verified (found in the text the model was shown): {verified}/{total} "
                 f"({100 * verified / total:.1f}%)")
    if verified < total:
        lines.append(f"- Unverified/possibly invented: {total - verified}/{total} — see console output "
                     f"above for which criterion/candidate pairs.")
    lines.append("")

    lines.append("## Must-have pass rate by intended fit (sanity check, not used for scoring)")
    by_fit = defaultdict(list)
    for _, (fit, passed, out_of) in fit_summary.items():
        if fit and out_of:
            by_fit[fit].append(passed / out_of)
    for fit in ["strong", "medium", "weak", "duplicate"]:
        rates = by_fit.get(fit)
        if not rates:
            continue
        avg = 100 * sum(rates) / len(rates)
        lines.append(f"- {fit}: {avg:.1f}% average must-have pass rate ({len(rates)} candidates)")
    lines.append("")
    lines.append(f"Per-candidate criterion breakdowns saved in data/scores/ (gitignored, regenerable).")

    report = "\n".join(lines)
    print("\n" + report)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / f"{date.today().isoformat()}-scoring-{args.role}.md"
    out_path.write_text(report, encoding="utf-8")
    print(f"\nsaved to {out_path}")


if __name__ == "__main__":
    main()
