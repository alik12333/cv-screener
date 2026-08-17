-- Schema for the parts of the pipeline that benefit from being in a real,
-- shared database rather than local JSON files: the scored candidate pool
-- and the draft/approval queue (see docs/ARCHITECTURE.md stages 5-10).
--
-- CV generation, extraction, and dedupe stay as local files for now (data/) -
-- nothing about those benefits from a database yet, and moving everything
-- at once would be scope creep beyond what this session asked for.
--
-- Run this once against a fresh Supabase project (SQL Editor, or via a
-- direct psql/Python connection using the project's connection string).

create extension if not exists vector;  -- pgvector, per CLAUDE.md's stack table - not used by these tables yet, enabled so dedupe can move here later without a second migration

create table if not exists candidates (
    stem text primary key,
    role text not null,
    full_name text not null,
    email text not null,
    phone text,
    location text,
    current_title text,
    total_years_experience integer,
    right_to_work boolean,               -- nullable on purpose: see docs/LEARNING.md Day 2, a CV usually can't answer this
    extracted_profile jsonb not null,    -- full EXTRACT output, kept as-is rather than one column per field
    created_at timestamptz not null default now()
);

create table if not exists scores (
    stem text primary key references candidates(stem),
    role text not null,
    intended_fit text,                   -- only present for synthetic test data; null for real candidates
    criteria jsonb not null,             -- list of {criterion, type, met, confidence, evidence_quote, quote_verified, quote_match_score}
    created_at timestamptz not null default now()
);

create table if not exists drafts (
    stem text primary key references candidates(stem),
    role text not null,
    rank text not null check (rank in ('Strong', 'Possible', 'No')),
    subject text not null,
    candidate_facing_body text not null,
    internal_reasoning jsonb not null,
    status text not null default 'pending' check (status in ('pending', 'approved', 'rejected')),
    approved_by text,
    approved_at timestamptz,
    rejected_by text,
    rejected_at timestamptz,
    rejection_reason text,
    created_at timestamptz not null default now()
);

-- Append-only. Nothing in this project should ever UPDATE or DELETE a row
-- here - it's the audit trail CLAUDE.md rule 2 requires ("log who approved
-- what and when"), and a trail that can be edited after the fact isn't one.
create table if not exists audit_log (
    id bigint generated always as identity primary key,
    stem text not null,
    role text not null,
    action text not null check (action in ('approved', 'rejected')),
    by_whom text not null,
    at timestamptz not null default now(),
    reason text
);

create index if not exists idx_drafts_status on drafts(status);
create index if not exists idx_scores_role on scores(role);
