"""
Draft a candidate-facing email, and a separate internal record for the human
approver to review. This is DRAFT (stage 9, see docs/ARCHITECTURE.md).

Nothing here sends anything. Every draft lands in data/drafts/ with
status "pending" and waits for src/approve.py - see CLAUDE.md rule 2. That
file is the only thing allowed to change a draft's status, and it always
logs who and when.

Two separate texts per candidate, on purpose:
- candidate_facing_body: what the person would actually see. For a "No"
  rank this is fixed, templated, generic text with NO LLM involvement -
  itemising specific rejection reasons in writing is a real legal exposure
  risk, and not something to trust to a model's phrasing. Rejected once as
  an option (let the LLM personalise the rejection too, for a "warmer"
  tone) and it's not worth the risk for what it buys.
- internal_reasoning: the full per-criterion breakdown and evidence quotes,
  for the approver only, so they can verify the rank before clicking
  approve - never sent to the candidate.

Input is data/scores/*.json (SCORE's output) plus data/extracted/*.json for
contact details - identity gets reattached here (CLAUDE.md rule 3: blind
scoring, but the human-facing shortlist and any outreach need the real name).

Usage:
    python src/draft.py --role devops
"""

import argparse
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from aggregate import find_unanswerable_must_haves, rank_candidate
from llm import call_structured

TEMPERATURE = 0.7   # some warmth is appropriate for outreach copy, unlike extraction/scoring - but still bounded by a template and evidence, not freeform

ROOT = Path(__file__).resolve().parent.parent
SPECS_PATH = ROOT / "data" / "job_specs.json"
EXTRACTED_DIR = ROOT / "data" / "extracted"
SCORES_DIR = ROOT / "data" / "scores"
DRAFTS_DIR = ROOT / "data" / "drafts"


class OutreachParagraph(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paragraph: str


def build_outreach_prompt(role_title: str, evidence_lines: list) -> str:
    evidence_block = "\n".join(evidence_lines) if evidence_lines else "(no specific evidence available)"
    return f"""Write ONE short paragraph for a recruitment outreach email. This
paragraph goes inside a fixed template - do not write a greeting, a subject
line, or a sign-off, only the paragraph itself.

The candidate is being invited to the next stage for the {role_title} role.
Reference 1-2 SPECIFIC strengths from the evidence below, in plain
professional language a recruiter would actually write. Do not invent
anything that isn't in the evidence, and do not overstate it.

EVIDENCE (criterion: quote)
{evidence_block}

Write 2-3 sentences only.
"""


def generate_outreach_paragraph(role_title: str, evidence_lines: list) -> str:
    result = call_structured(build_outreach_prompt(role_title, evidence_lines), OutreachParagraph, temperature=TEMPERATURE)
    return result.paragraph


REJECTION_BODY = (
    "Thank you for applying for the {role_title} position and for taking the time "
    "to share your background with us.\n\n"
    "After careful review, we won't be progressing your application on this occasion. "
    "This was a competitive process and our decision reflects the specific requirements "
    "of this role rather than a judgement on your broader experience.\n\n"
    "We'll keep your details on file and would welcome an application from you for "
    "future roles that may be a closer match."
)


def display_name(full_name: str) -> str:
    """The "classic" CV layout renders names in caps (render_classic in
    generate_cvs.py), which extraction correctly preserves verbatim - right
    for extraction, wrong for greeting someone in an actual email. Only
    normalise when the whole name is uppercase, so an already-correct
    mixed-case name (e.g. "O'Connor") isn't mangled by blanket title-casing.
    """
    return full_name.title() if full_name.isupper() else full_name


def build_email(role_title: str, full_name: str, rank: str, criteria: list) -> tuple:
    display = display_name(full_name)
    first_name = display.split()[0] if display.split() else display
    greeting = f"Dear {first_name},"
    signoff = "Best regards,\nThe Recruitment Team"

    if rank == "No":
        subject = f"Your application for {role_title}"
        body = f"{greeting}\n\n{REJECTION_BODY.format(role_title=role_title)}\n\n{signoff}"
        return subject, body

    evidence_lines = [
        f"- {c['criterion']}: \"{c['evidence_quote']}\""
        for c in criteria if c["met"] and c["evidence_quote"]
    ]
    paragraph = generate_outreach_paragraph(role_title, evidence_lines)
    subject = f"Next steps for your {role_title} application"
    body = (
        f"{greeting}\n\nThank you for applying for the {role_title} role. "
        f"{paragraph}\n\nWe'd like to move forward to the next stage - a member of "
        f"our team will be in touch shortly to arrange this.\n\n{signoff}"
    )
    return subject, body


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", default="devops")
    args = parser.parse_args()

    specs = {s["id"]: s for s in json.loads(SPECS_PATH.read_text())}
    if args.role not in specs:
        raise SystemExit(f"Unknown role '{args.role}'. Choices: {sorted(specs)}")
    role_title = specs[args.role]["title"]

    score_files = sorted(SCORES_DIR.glob(f"{args.role}-*.json"))
    if not score_files:
        raise SystemExit(f"No scores for '{args.role}'. Run src/score.py first.")
    score_records = [json.loads(p.read_text()) for p in score_files]

    unanswerable = find_unanswerable_must_haves(score_records)
    if unanswerable:
        print(f"must-haves excluded from the gate (no CV evidence for any candidate): {sorted(unanswerable)}")

    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    rank_counts = {"Strong": 0, "Possible": 0, "No": 0}

    for i, record in enumerate(score_records, start=1):
        stem = record["stem"]
        print(f"[{i}/{len(score_records)}] {stem}")
        profile = json.loads((EXTRACTED_DIR / f"{stem}.json").read_text())
        result = rank_candidate(record["criteria"], unanswerable)
        rank_counts[result["rank"]] += 1

        subject, body = build_email(role_title, profile["full_name"], result["rank"], record["criteria"])

        draft = {
            "stem": stem,
            "role": args.role,
            "full_name": profile["full_name"],
            "email": profile["email"],
            "rank": result["rank"],
            "subject": subject,
            "candidate_facing_body": body,
            "internal_reasoning": {**result, "criteria_detail": record["criteria"]},
            "status": "pending",
            "approved_by": None,
            "approved_at": None,
        }
        (DRAFTS_DIR / f"{stem}.json").write_text(json.dumps(draft, indent=2), encoding="utf-8")

    print(f"\ndone. {len(score_records)} drafts written to {DRAFTS_DIR}, all status=pending.")
    print(f"rank breakdown: {rank_counts}")
    print("nothing has been sent - run src/approve.py to review the queue.")


if __name__ == "__main__":
    main()
