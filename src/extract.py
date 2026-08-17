"""
Extract structured candidate data from raw CV text.

This is EXTRACT (stage 3 of the pipeline, see docs/ARCHITECTURE.md): the CV
already exists as plain text (from generate_cvs.py, standing in for the real
PARSE stage). This file's only job is text -> schema-enforced JSON, one call
per CV, using the same schema generate_cvs.py used to write the ground truth.

Usage:
    python src/extract.py
    python src/extract.py --limit 5     # smaller run while debugging
"""

import argparse
import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import Field

from schema import CandidateProfile

load_dotenv()

MODEL = "gemini-3.5-flash-lite"
MIN_SECONDS_BETWEEN_CALLS = 5.0
MAX_RETRIES = 4
TEMPERATURE = 0.0   # consistency matters here, not variety: the same CV should extract the same way every time

ROOT = Path(__file__).resolve().parent.parent
CV_DIR = ROOT / "data" / "cvs"
EXTRACTED_DIR = ROOT / "data" / "extracted"


class ExtractedProfile(CandidateProfile):
    """Same contract as generation, except right_to_work is nullable.

    No CV layout in generate_cvs.py ever states work authorisation in the
    rendered text (real CVs mostly don't either — it's an application-form
    question, not a CV field). Making this bool required here would force
    the model to guess on every single CV; null is the honest answer.
    """
    right_to_work: bool | None = Field(
        default=None,
        description=(
            "True or False ONLY if the CV text explicitly states work "
            "authorisation. Leave null if it is not mentioned — do not guess."
        ),
    )


def build_prompt(cv_text: str) -> str:
    return f"""Extract this CV into the given structured schema.

RULES
- Copy values exactly as written. Do not paraphrase, summarise, or improve wording.
- personal_statement: copy the original text verbatim if one is present.
- current_title: use the job title from the most recent employment entry, not a
  self-description used in the personal statement (they sometimes differ).
- skills: list only skills actually named in the CV. Do not infer or add related skills.
- right_to_work: leave null unless the CV explicitly states work authorisation status.
- Do not invent information that is not present in the CV text below.

CV TEXT
{cv_text}
"""


_last_call_at = 0.0


def extract_profile(client: genai.Client, cv_text: str) -> ExtractedProfile:
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
                contents=build_prompt(cv_text),
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=ExtractedProfile,
                    temperature=TEMPERATURE,
                ),
            )
            if response.parsed is not None:
                return response.parsed
            return ExtractedProfile.model_validate_json(response.text)

        except Exception as exc:                      # noqa: BLE001
            backoff = 2 ** attempt * 5
            print(f"    attempt {attempt + 1} failed ({type(exc).__name__}: {exc}), "
                  f"retrying in {backoff}s")
            time.sleep(backoff)

    raise RuntimeError(f"gave up after {MAX_RETRIES} attempts")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit("GEMINI_API_KEY is not set. Copy .env.example to .env.")

    client = genai.Client(api_key=api_key)
    EXTRACTED_DIR.mkdir(parents=True, exist_ok=True)

    cv_files = sorted(CV_DIR.glob("*.txt"))
    if args.limit:
        cv_files = cv_files[: args.limit]

    failures: list[dict] = []
    for i, cv_path in enumerate(cv_files, start=1):
        print(f"[{i}/{len(cv_files)}] {cv_path.stem}")
        cv_text = cv_path.read_text(encoding="utf-8")
        try:
            profile = extract_profile(client, cv_text)
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
