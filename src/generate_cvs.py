"""
Generate synthetic CVs for the screening pipeline.

Why synthetic: the whole product is "we handle candidate data responsibly".
Demoing on scraped real CVs would contradict that in the first thirty seconds.

Why this file matters beyond test data: every CV is generated FROM a structured
object, so data/ground_truth/*.json is the correct answer for every CV in
data/cvs/. When you write the extractor tomorrow, you already have the answer
key. That is your first eval set and it cost you nothing.

Usage:
    python src/generate_cvs.py
    python src/generate_cvs.py --per-role 5        # smaller run while debugging
"""

import argparse
import json
import os
import random
import time
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from google import genai
from google.genai import types

from schema import CandidateProfile

load_dotenv()

MODEL = "gemini-3.5-flash-lite"     # gemini-3.6-flash's free tier is capped at 20 requests/DAY (not/minute); lite models carry a higher free daily quota
MIN_SECONDS_BETWEEN_CALLS = 5.0     # free tier is roughly 10-15 requests/minute
MAX_RETRIES = 4

ROOT = Path(__file__).resolve().parent.parent
SPECS_PATH = ROOT / "data" / "job_specs.json"
CV_DIR = ROOT / "data" / "cvs"
TRUTH_DIR = ROOT / "data" / "ground_truth"


FIT_INSTRUCTIONS = {
    "strong": (
        "This candidate clearly meets every must-have and several nice-to-haves. "
        "Do not make them perfect: leave one nice-to-have unmet."
    ),
    "medium": (
        "This candidate meets most must-haves but falls short on one, for example "
        "slightly fewer years than asked, or a related-but-different framework."
    ),
    "weak": (
        "This candidate is a poor fit. They may come from an adjacent field, be far "
        "too junior, or miss several must-haves. Their CV should still look real and "
        "professional. Some weak candidates should have an unexplained employment gap."
    ),
}


def build_prompt(spec: dict, fit: Literal["strong", "medium", "weak"]) -> str:
    return f"""Invent one realistic UK job applicant for this vacancy.

VACANCY
Title: {spec['title']}
Location: {spec['location']}
Must-haves: {'; '.join(spec['must_haves'])}
Nice-to-haves: {'; '.join(spec['nice_to_haves'])}

FIT LEVEL: {fit}
{FIT_INSTRUCTIONS[fit]}

RULES
- Invent the person entirely. Do not use any real or well-known name.
- Use UK conventions: UK cities, UK phone format, GBP salary, notice in weeks or months.
- Vary the writing. Real CVs are inconsistent: some verbose, some terse.
- Employment dates must be chronologically sensible and consistent with
  total_years_experience.
"""


# ---------------------------------------------------------------------------
# Calling the model
# ---------------------------------------------------------------------------

_last_call_at = 0.0


def generate_candidate(client: genai.Client, spec: dict, fit: str) -> CandidateProfile:
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
                contents=build_prompt(spec, fit),
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=CandidateProfile,
                    temperature=1.0,   # high on purpose: we want variety
                ),
            )
            if response.parsed is not None:
                return response.parsed
            return CandidateProfile.model_validate_json(response.text)

        except Exception as exc:                      # noqa: BLE001
            backoff = 2 ** attempt * 5
            print(f"    attempt {attempt + 1} failed ({type(exc).__name__}: {exc}), "
                  f"retrying in {backoff}s")
            time.sleep(backoff)

    raise RuntimeError(f"gave up after {MAX_RETRIES} attempts")


# ---------------------------------------------------------------------------
# Rendering. Three layouts so your parser is not tested on one uniform shape.
# ---------------------------------------------------------------------------

def render_classic(c: CandidateProfile) -> str:
    out = [c.full_name.upper(), f"{c.location} | {c.phone} | {c.email}", ""]
    out += ["PERSONAL STATEMENT", c.personal_statement, ""]
    out += ["KEY SKILLS", ", ".join(c.skills), ""]
    out.append("EMPLOYMENT HISTORY")
    for job in c.employment:
        out.append(f"{job.title}, {job.employer}   {job.start} - {job.end}")
        out += [f"  - {b}" for b in job.bullets]
        out.append("")
    out.append("EDUCATION")
    out += [f"{e.qualification}, {e.institution} ({e.year})" for e in c.education]
    out += ["", f"Notice period: {c.notice_period}",
            f"Salary expectation: {c.salary_expectation}"]
    return "\n".join(out)


def render_terse(c: CandidateProfile) -> str:
    out = [f"{c.full_name}  //  {c.current_title}",
           f"{c.email}  {c.phone}  {c.location}", "", c.personal_statement, ""]
    for job in c.employment:
        out.append(f"{job.start}-{job.end}  {job.title} @ {job.employer}")
        out.append("   " + " ".join(job.bullets))
    out += ["", "Skills: " + " / ".join(c.skills)]
    out += [f"Education: {e.qualification}, {e.institution}, {e.year}"
            for e in c.education]
    out.append(f"Available: {c.notice_period}. Seeking {c.salary_expectation}.")
    return "\n".join(out)


def render_header_heavy(c: CandidateProfile) -> str:
    """Contact details buried in a header block, the way a Word template does it."""
    bar = "=" * 60
    out = [bar, c.full_name, c.current_title, c.location,
           f"t: {c.phone}   e: {c.email}", bar, ""]
    out += ["Profile", c.personal_statement, "", "Experience"]
    for job in c.employment:
        out.append(f"  {job.employer} | {job.title}")
        out.append(f"  {job.start} to {job.end}")
        out += [f"    * {b}" for b in job.bullets]
        out.append("")
    out += ["Technical Skills", "  " + ", ".join(c.skills), "", "Education"]
    out += [f"  {e.year}  {e.qualification}, {e.institution}" for e in c.education]
    out += ["", f"Notice: {c.notice_period}", f"Expected salary: {c.salary_expectation}"]
    return "\n".join(out)


RENDERERS = [render_classic, render_terse, render_header_heavy]


# ---------------------------------------------------------------------------

def slug(name: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in name).strip("-")


def save(candidate: CandidateProfile, spec_id: str, index: int, meta: dict) -> None:
    stem = f"{spec_id}-{index:02d}-{slug(candidate.full_name)}"
    renderer = RENDERERS[index % len(RENDERERS)]
    (CV_DIR / f"{stem}.txt").write_text(renderer(candidate), encoding="utf-8")
    (TRUTH_DIR / f"{stem}.json").write_text(
        json.dumps({**meta, "profile": candidate.model_dump()}, indent=2),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-role", type=int, default=14)
    parser.add_argument("--duplicates", type=int, default=6)
    args = parser.parse_args()

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit("GEMINI_API_KEY is not set. Copy .env.example to .env.")

    client = genai.Client(api_key=api_key)
    specs = json.loads(SPECS_PATH.read_text())
    CV_DIR.mkdir(parents=True, exist_ok=True)
    TRUTH_DIR.mkdir(parents=True, exist_ok=True)

    # Roughly a third strong, a third medium, a third weak.
    fits = ["strong", "medium", "weak"]
    everyone: list[tuple[CandidateProfile, str]] = []

    for spec in specs:
        print(f"\n{spec['title']}")
        for i in range(args.per_role):
            fit = fits[i % 3]
            print(f"  [{i + 1}/{args.per_role}] {fit}")
            candidate = generate_candidate(client, spec, fit)
            save(candidate, spec["id"], i, {
                "applied_to": spec["id"],
                "intended_fit": fit,
                "is_duplicate_of": None,
            })
            everyone.append((candidate, spec["id"]))

    # Plant known duplicates: the same person applying to a second role under a
    # shortened name and a different email. Day 4 has to catch these.
    print("\nplanting duplicates")
    for n in range(args.duplicates):
        original, original_spec = random.choice(everyone)
        other = random.choice([s for s in specs if s["id"] != original_spec])

        first, *rest = original.full_name.split()
        variant = original.model_copy(deep=True)
        variant.full_name = f"{first[0]}. {' '.join(rest)}" if rest else first
        variant.email = original.email.replace("@", f"{random.randint(1, 99)}@")

        save(variant, other["id"], 90 + n, {
            "applied_to": other["id"],
            "intended_fit": "duplicate",
            "is_duplicate_of": original.full_name,
        })
        print(f"  {original.full_name} -> {variant.full_name} ({other['id']})")

    total = len(list(CV_DIR.glob("*.txt")))
    print(f"\ndone. {total} CVs in {CV_DIR}")
    print(f"answer key in {TRUTH_DIR}")


if __name__ == "__main__":
    main()
