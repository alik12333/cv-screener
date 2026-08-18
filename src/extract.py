"""
Extract structured candidate data from raw CV text.

This is EXTRACT (stage 3 of the pipeline, see docs/ARCHITECTURE.md): the CV
already exists as plain text (from generate_cvs.py, standing in for the real
PARSE stage). This file's only job is text -> schema-enforced JSON, one call
per CV, using the same schema generate_cvs.py used to write the ground truth.

Usage:
    python src/extract.py
    python src/extract.py --limit 5     # smaller run while debugging
    python src/extract.py --resume      # skip CVs that already have output
                                         # (for resuming after a rate-limit/
                                         # power-cut interruption, not for
                                         # normal runs - a fresh run is the
                                         # default so eval numbers reflect
                                         # the current code on every CV)
"""

import argparse
import json
from pathlib import Path
from typing import Literal

from llm import call_structured
from schema import CandidateProfile

TEMPERATURE = 0.0   # consistency matters here, not variety: the same CV should extract the same way every time

ROOT = Path(__file__).resolve().parent.parent
CV_DIR = ROOT / "data" / "cvs"
EXTRACTED_DIR = ROOT / "data" / "extracted"


class ExtractedProfile(CandidateProfile):
    """Same contract as generation, except right_to_work is a required 3-way
    enum instead of a nullable bool.

    No CV layout in generate_cvs.py ever states work authorisation in the
    rendered text (real CVs mostly don't either — it's an application-form
    question, not a CV field), so the model needs an honest way to say "not
    stated" instead of guessing. A nullable bool used to carry that meaning,
    but Groq's strict structured-output mode requires every field to be
    listed in `required`, which excludes anything with a default (how
    Pydantic represents "optional") - confirmed directly, not assumed.
    A required 3-way string carries the identical meaning without violating
    that constraint.
    """
    right_to_work: Literal["stated_true", "stated_false", "not_stated"]


def build_prompt(cv_text: str) -> str:
    return f"""Extract this CV into the given structured schema.

RULES
- Copy values exactly as written. Do not paraphrase, summarise, or improve wording.
- personal_statement: copy the original text verbatim if one is present.
- current_title: use the job title from the most recent employment entry, not a
  self-description used in the personal statement (they sometimes differ).
- skills: list only skills actually named in the CV. Do not infer or add related skills.
- right_to_work: use "stated_true" or "stated_false" ONLY if the CV text
  explicitly states work authorisation status. Use "not_stated" if it is not
  mentioned - do not guess.
- Do not invent information that is not present in the CV text below.

CV TEXT
{cv_text}
"""


def extract_profile(cv_text: str) -> ExtractedProfile:
    return call_structured(build_prompt(cv_text), ExtractedProfile, temperature=TEMPERATURE)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    EXTRACTED_DIR.mkdir(parents=True, exist_ok=True)

    cv_files = sorted(CV_DIR.glob("*.txt"))
    if args.resume:
        cv_files = [p for p in cv_files if not (EXTRACTED_DIR / f"{p.stem}.json").exists()]
    if args.limit:
        cv_files = cv_files[: args.limit]

    failures: list[dict] = []
    for i, cv_path in enumerate(cv_files, start=1):
        print(f"[{i}/{len(cv_files)}] {cv_path.stem}")
        cv_text = cv_path.read_text(encoding="utf-8")
        try:
            profile = extract_profile(cv_text)
        except RuntimeError as exc:
            # Fail loudly, per CLAUDE.md rule 6: a CV that can't be extracted
            # goes to review with a reason. It never gets silently skipped or
            # scored as zero.
            print(f"    EXTRACTION FAILED: {exc}")
            failures.append({"stem": cv_path.stem, "reason": str(exc)})
            continue

        out_path = EXTRACTED_DIR / f"{cv_path.stem}.json"
        out_path.write_text(json.dumps(profile.model_dump(), indent=2), encoding="utf-8")

    if failures:
        (EXTRACTED_DIR / "_failures.json").write_text(
            json.dumps(failures, indent=2), encoding="utf-8"
        )

    print(f"\ndone. {len(cv_files) - len(failures)}/{len(cv_files)} extracted successfully.")
    if failures:
        print(f"{len(failures)} failed — see {EXTRACTED_DIR / '_failures.json'}")


if __name__ == "__main__":
    main()
