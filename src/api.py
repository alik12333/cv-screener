"""
HTTP service wrapping the pipeline stages n8n orchestrates: SCORE onward.

CV generation, extraction, and dedupe stay as the local batch scripts built
on Days 1-4 (data/*.json) - nothing about those benefits from being a live
HTTP service. This is the part CLAUDE.md's stack table means by "FastAPI,
called by n8n": the visible, per-candidate queue a human approver actually
interacts with, backed by real Postgres (Supabase) instead of local files.

Run from inside src/ (matches every other script's same-directory imports):
    cd src && uvicorn api:app --reload --port 8000
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from aggregate import find_unanswerable_must_haves, rank_candidate
from blind import blind_profile, profile_to_text
from db import get_connection
from draft import build_email
from score import score_criterion, verify_quote

ROOT = Path(__file__).resolve().parent.parent
SPECS_PATH = ROOT / "data" / "job_specs.json"
EXTRACTED_DIR = ROOT / "data" / "extracted"
DASHBOARD_HTML_PATH = Path(__file__).parent / "static" / "dashboard.html"

app = FastAPI(title="cv-screener")


@app.get("/", response_class=HTMLResponse)
def dashboard():
    """The approval queue UI (stage 10) - a static page with no build step,
    served straight from disk and re-read on every request so edits show up
    on refresh. It only calls the JSON endpoints already defined below; no
    separate frontend stack, per CLAUDE.md's "no new frameworks" rule.
    """
    return DASHBOARD_HTML_PATH.read_text(encoding="utf-8")

# EXTRACT's right_to_work is a required 3-way string ("stated_true" /
# "stated_false" / "not_stated" - see extract.py for why), but the Supabase
# column is a nullable boolean. Convert at the one place this crosses that
# boundary rather than changing the column type to match the LLM schema.
_RIGHT_TO_WORK_TO_BOOL = {"stated_true": True, "stated_false": False, "not_stated": None}


def _load_specs() -> dict:
    return {s["id"]: s for s in json.loads(SPECS_PATH.read_text())}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/candidates/{stem}/ingest")
def ingest_candidate(stem: str, role: str):
    """Loads EXTRACT's local output for one candidate into `candidates` -
    the handoff point between the local batch scripts and the live service.
    """
    path = EXTRACTED_DIR / f"{stem}.json"
    if not path.exists():
        raise HTTPException(404, f"No extracted profile for '{stem}'. Run src/extract.py first.")
    profile = json.loads(path.read_text())

    with get_connection() as conn:
        conn.execute(
            """
            insert into candidates (stem, role, full_name, email, phone, location,
                current_title, total_years_experience, right_to_work, extracted_profile)
            values (%(stem)s, %(role)s, %(full_name)s, %(email)s, %(phone)s, %(location)s,
                %(current_title)s, %(total_years_experience)s, %(right_to_work)s, %(profile)s)
            on conflict (stem) do update set
                extracted_profile = excluded.extracted_profile,
                role = excluded.role
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
        conn.commit()
    return {"stem": stem, "status": "ingested"}


@app.post("/candidates/{stem}/score")
def score_candidate(stem: str, role: str):
    """Runs SCORE (stage 5) for one candidate against a role's rubric and
    writes the result to `scores`. The one endpoint that calls an LLM -
    kept single-candidate on purpose, matching "the model judges one
    candidate against one criterion" (CLAUDE.md rule 1).
    """
    specs = _load_specs()
    if role not in specs:
        raise HTTPException(404, f"Unknown role '{role}'")
    spec = specs[role]
    criteria_defs = [(m, "must_have") for m in spec["must_haves"]] + \
                     [(n, "nice_to_have") for n in spec["nice_to_haves"]]

    path = EXTRACTED_DIR / f"{stem}.json"
    if not path.exists():
        raise HTTPException(404, f"No extracted profile for '{stem}'.")
    profile = json.loads(path.read_text())
    cv_text = profile_to_text(blind_profile(profile))

    results = []
    for criterion, ctype in criteria_defs:
        verdict = score_criterion(cv_text, criterion, ctype)
        verified, match_score = verify_quote(verdict.evidence_quote, cv_text)
        results.append({
            "criterion": criterion, "type": ctype, "met": verdict.met,
            "confidence": verdict.confidence, "evidence_quote": verdict.evidence_quote,
            "quote_verified": verified, "quote_match_score": round(match_score, 3),
        })

    with get_connection() as conn:
        conn.execute(
            """
            insert into scores (stem, role, criteria)
            values (%s, %s, %s)
            on conflict (stem) do update set criteria = excluded.criteria, role = excluded.role
            """,
            (stem, role, json.dumps(results)),
        )
        conn.commit()
    return {"stem": stem, "role": role, "criteria": results}


@app.post("/candidates/{stem}/draft")
def draft_candidate(stem: str):
    """Runs AGGREGATE+RANK then DRAFT (stages 6, 8, 9) for one candidate,
    using every scored candidate for the same role to decide which
    must-haves have zero CV evidence (src/aggregate.py). Writes a pending
    draft to `drafts` - nothing here sends anything.
    """
    with get_connection() as conn:
        row = conn.execute("select role, criteria from scores where stem = %s", (stem,)).fetchone()
        if row is None:
            raise HTTPException(404, f"No score for '{stem}'. Call /candidates/{stem}/score first.")
        role, criteria = row
        role_rows = conn.execute("select criteria from scores where role = %s", (role,)).fetchall()
        role_records = [{"criteria": r[0]} for r in role_rows]

        candidate_row = conn.execute("select full_name from candidates where stem = %s", (stem,)).fetchone()
        if candidate_row is None:
            raise HTTPException(404, f"No candidate record for '{stem}'. Call /candidates/{stem}/ingest first.")
        full_name = candidate_row[0]

    specs = _load_specs()
    role_title = specs[role]["title"]

    unanswerable = find_unanswerable_must_haves(role_records)
    result = rank_candidate(criteria, unanswerable)

    subject, body = build_email(role_title, full_name, result["rank"], criteria)

    with get_connection() as conn:
        conn.execute(
            """
            insert into drafts (stem, role, rank, subject, candidate_facing_body, internal_reasoning, status)
            values (%(stem)s, %(role)s, %(rank)s, %(subject)s, %(candidate_facing_body)s, %(internal_reasoning)s, 'pending')
            on conflict (stem) do update set
                rank = excluded.rank, subject = excluded.subject,
                candidate_facing_body = excluded.candidate_facing_body,
                internal_reasoning = excluded.internal_reasoning,
                status = 'pending', approved_by = null, approved_at = null,
                rejected_by = null, rejected_at = null, rejection_reason = null
            """,
            {
                "stem": stem, "role": role, "rank": result["rank"], "subject": subject,
                "candidate_facing_body": body,
                "internal_reasoning": json.dumps({**result, "criteria_detail": criteria}),
            },
        )
        conn.commit()
    return {"stem": stem, "rank": result["rank"], "subject": subject, "status": "pending"}


class DraftQueueItem(BaseModel):
    stem: str
    role: str
    rank: str
    subject: str
    status: str


@app.get("/drafts", response_model=list[DraftQueueItem])
def list_drafts(role: str | None = None, status: str | None = None):
    query = "select stem, role, rank, subject, status from drafts where 1=1"
    params: list = []
    if role:
        query += " and role = %s"
        params.append(role)
    if status:
        query += " and status = %s"
        params.append(status)
    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
    return [DraftQueueItem(stem=r[0], role=r[1], rank=r[2], subject=r[3], status=r[4]) for r in rows]


@app.get("/drafts/{stem}")
def get_draft(stem: str):
    with get_connection() as conn:
        row = conn.execute(
            """select stem, role, rank, subject, candidate_facing_body, internal_reasoning,
                      status, approved_by, approved_at, rejected_by, rejected_at, rejection_reason
               from drafts where stem = %s""",
            (stem,),
        ).fetchone()
    if row is None:
        raise HTTPException(404, f"No draft for '{stem}'")
    cols = ["stem", "role", "rank", "subject", "candidate_facing_body", "internal_reasoning",
            "status", "approved_by", "approved_at", "rejected_by", "rejected_at", "rejection_reason"]
    return dict(zip(cols, row))


class ApproveRequest(BaseModel):
    by: str


class RejectRequest(BaseModel):
    by: str
    reason: str


@app.post("/drafts/{stem}/approve")
def approve_draft(stem: str, req: ApproveRequest):
    return _decide(stem, "approved", req.by, None)


@app.post("/drafts/{stem}/reject")
def reject_draft(stem: str, req: RejectRequest):
    return _decide(stem, "rejected", req.by, req.reason)


def _decide(stem: str, new_status: str, by: str, reason: str | None) -> dict:
    """The gate. The only function in this service allowed to move a draft
    out of 'pending' - and it refuses to touch a draft that's already been
    decided, same as src/approve.py's local CLI version (rule 2: no bypass).
    """
    now = datetime.now(timezone.utc)
    with get_connection() as conn:
        row = conn.execute("select status, role from drafts where stem = %s", (stem,)).fetchone()
        if row is None:
            raise HTTPException(404, f"No draft for '{stem}'")
        current_status, role = row
        if current_status != "pending":
            raise HTTPException(409, f"'{stem}' is already {current_status}. Not overwriting a past decision.")

        if new_status == "approved":
            conn.execute(
                "update drafts set status = 'approved', approved_by = %s, approved_at = %s where stem = %s",
                (by, now, stem),
            )
        else:
            conn.execute(
                "update drafts set status = 'rejected', rejected_by = %s, rejected_at = %s, rejection_reason = %s "
                "where stem = %s",
                (by, now, reason, stem),
            )
        conn.execute(
            "insert into audit_log (stem, role, action, by_whom, at, reason) values (%s, %s, %s, %s, %s, %s)",
            (stem, role, new_status, by, now, reason),
        )
        conn.commit()
    return {"stem": stem, "status": new_status, "by": by, "at": now.isoformat()}


@app.get("/audit-log")
def audit_log_endpoint(stem: str | None = None):
    query = "select stem, role, action, by_whom, at, reason from audit_log"
    params: list = []
    if stem:
        query += " where stem = %s"
        params.append(stem)
    query += " order by at desc"
    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
    cols = ["stem", "role", "action", "by", "at", "reason"]
    return [dict(zip(cols, r)) for r in rows]
