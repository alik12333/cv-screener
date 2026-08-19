"""
Push already-computed local pipeline output into the live Supabase-backed
queue, without spending a single additional LLM call.

Why this exists: local batch runs (generate_cvs.py, extract.py, score.py,
draft.py) and the live system (src/api.py + Supabase, what the dashboard and
n8n actually read from) are two separate stores. A full 62-candidate batch
run computed locally is invisible to the approval queue until it's synced
over - discovered live when the dashboard built today showed only 4
candidates instead of 62, because those were the only ones ever pushed
through the API. Re-running everything through the API to populate it would
re-call the LLM for all ~550 judgements for no reason; the results already
exist as local JSON.

Never overwrites a draft that's already live (CLAUDE.md rule 2: a decision,
once made, is never silently replaced) - a stem already in `drafts` is left
alone, whichever system decided it first.

Usage:
    python src/sync_to_live.py                 # sync everything in data/
    python src/sync_to_live.py --role devops    # just one role
"""

import argparse
import json
from pathlib import Path

from db import get_connection

ROOT = Path(__file__).resolve().parent.parent
SPECS_PATH = ROOT / "data" / "job_specs.json"
EXTRACTED_DIR = ROOT / "data" / "extracted"
SCORES_DIR = ROOT / "data" / "scores"
DRAFTS_DIR = ROOT / "data" / "drafts"
AUDIT_LOG_PATH = ROOT / "data" / "audit_log.jsonl"

_RIGHT_TO_WORK_TO_BOOL = {"stated_true": True, "stated_false": False, "not_stated": None}


def role_for_stem(stem: str, role_ids: list[str]) -> str | None:
    # extracted profiles don't carry their own role (extract.py never sees
    # one) - the stem's own naming convention ("{role}-{index}-{name}", set
    # by generate_cvs.py) is the only place it's recorded before scoring.
    for role_id in role_ids:
        if stem.startswith(role_id + "-"):
            return role_id
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--role")
    args = parser.parse_args()

    role_ids = [s["id"] for s in json.loads(SPECS_PATH.read_text())]

    with get_connection() as conn:
        existing_candidates = {r[0] for r in conn.execute("select stem from candidates").fetchall()}
        existing_scores = {r[0] for r in conn.execute("select stem from scores").fetchall()}
        existing_drafts = {r[0] for r in conn.execute("select stem from drafts").fetchall()}

        candidates_synced = 0
        for path in sorted(EXTRACTED_DIR.glob("*.json")):
            if path.name.startswith("_"):
                continue
            stem = path.stem
            role = role_for_stem(stem, role_ids)
            if role is None or (args.role and role != args.role):
                continue
            if stem in existing_candidates:
                continue
            profile = json.loads(path.read_text())
            conn.execute(
                """
                insert into candidates (stem, role, full_name, email, phone, location,
                    current_title, total_years_experience, right_to_work, extracted_profile)
                values (%(stem)s, %(role)s, %(full_name)s, %(email)s, %(phone)s, %(location)s,
                    %(current_title)s, %(total_years_experience)s, %(right_to_work)s, %(profile)s)
                on conflict (stem) do nothing
                """,
                {
                    "stem": stem, "role": role, "full_name": profile["full_name"],
                    "email": profile["email"], "phone": profile.get("phone"),
                    "location": profile.get("location"), "current_title": profile.get("current_title"),
                    "total_years_experience": profile.get("total_years_experience"),
                    "right_to_work": _RIGHT_TO_WORK_TO_BOOL.get(profile.get("right_to_work")),
                    "profile": json.dumps(profile),
                },
            )
            candidates_synced += 1
        conn.commit()

        scores_synced = 0
        for path in sorted(SCORES_DIR.glob("*.json")):
            record = json.loads(path.read_text())
            stem = record["stem"]
            if args.role and record["role"] != args.role:
                continue
            if stem in existing_scores:
                continue
            conn.execute(
                """
                insert into scores (stem, role, intended_fit, criteria)
                values (%(stem)s, %(role)s, %(intended_fit)s, %(criteria)s)
                on conflict (stem) do nothing
                """,
                {
                    "stem": stem, "role": record["role"],
                    "intended_fit": record.get("intended_fit"),
                    "criteria": json.dumps(record["criteria"]),
                },
            )
            scores_synced += 1
        conn.commit()

        drafts_synced = 0
        drafts_skipped = 0
        for path in sorted(DRAFTS_DIR.glob("*.json")):
            if path.name.startswith("_"):
                continue
            record = json.loads(path.read_text())
            stem = record["stem"]
            if args.role and record["role"] != args.role:
                continue
            if stem in existing_drafts:
                drafts_skipped += 1
                continue
            conn.execute(
                """
                insert into drafts (stem, role, rank, subject, candidate_facing_body,
                    internal_reasoning, status, approved_by, approved_at,
                    rejected_by, rejected_at, rejection_reason)
                values (%(stem)s, %(role)s, %(rank)s, %(subject)s, %(body)s,
                    %(reasoning)s, %(status)s, %(approved_by)s, %(approved_at)s,
                    %(rejected_by)s, %(rejected_at)s, %(rejection_reason)s)
                on conflict (stem) do nothing
                """,
                {
                    "stem": stem, "role": record["role"], "rank": record["rank"],
                    "subject": record["subject"], "body": record["candidate_facing_body"],
                    "reasoning": json.dumps(record["internal_reasoning"]),
                    "status": record["status"],
                    "approved_by": record.get("approved_by"), "approved_at": record.get("approved_at"),
                    "rejected_by": record.get("rejected_by"), "rejected_at": record.get("rejected_at"),
                    "rejection_reason": record.get("rejection_reason"),
                },
            )
            drafts_synced += 1
        conn.commit()

        # local decisions made via approve.py's CLI (data/audit_log.jsonl)
        # for stems that just arrived above - the API's own audit_log rows
        # for stems decided through the live system already exist and are
        # untouched.
        audit_synced = 0
        if AUDIT_LOG_PATH.exists():
            existing_audit_stems = {
                r[0] for r in conn.execute("select distinct stem from audit_log").fetchall()
            }
            for line in AUDIT_LOG_PATH.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                entry = json.loads(line)
                if entry["stem"] in existing_audit_stems:
                    continue
                if args.role and entry["role"] != args.role:
                    continue
                conn.execute(
                    "insert into audit_log (stem, role, action, by_whom, at, reason) "
                    "values (%(stem)s, %(role)s, %(action)s, %(by)s, %(at)s, %(reason)s)",
                    entry,
                )
                existing_audit_stems.add(entry["stem"])
                audit_synced += 1
        conn.commit()

    print(f"candidates: {candidates_synced} synced ({len(existing_candidates)} already live)")
    print(f"scores: {scores_synced} synced ({len(existing_scores)} already live)")
    print(f"drafts: {drafts_synced} synced, {drafts_skipped} left alone (already decided or drafted live)")
    print(f"audit log: {audit_synced} local decisions synced")


if __name__ == "__main__":
    main()
