"""
Turn SCORE's per-criterion verdicts into a single rank, in pure code.

This is AGGREGATE (stage 6) and RANK (stage 8) combined into one small module
- see docs/ARCHITECTURE.md. CLAUDE.md rule 1: the model never outputs a final
score, this arithmetic does.

Kept intentionally small: binary gates for must-haves, a plain count for
nice-to-haves, no per-criterion weighting yet (job_specs.json doesn't define
weights, and nobody's asked for configurable ones - CLAUDE.md's anti-goal on
premature abstraction). Build that only when it's actually needed.
"""


def find_unanswerable_must_haves(role_score_records: list) -> set:
    """A must-have that has ZERO evidence across every scored candidate for a
    role can't be judged from a CV at all - Day 3 found exactly this for
    "Right to work in the UK" (docs/LEARNING.md). Gating on it as written
    would auto-fail every candidate, including perfect ones, so it's excluded
    from the pass/fail gate here and flagged separately as "needs
    confirmation" - the real fix (sourcing it from the application form, not
    the CV) is still someone else's job, not this function's.
    """
    has_evidence = {}
    for record in role_score_records:
        for c in record["criteria"]:
            if c["type"] != "must_have":
                continue
            has_evidence.setdefault(c["criterion"], False)
            if c["evidence_quote"]:
                has_evidence[c["criterion"]] = True
    return {criterion for criterion, seen in has_evidence.items() if not seen}


def rank_candidate(criteria: list, unanswerable_must_haves: set) -> dict:
    """Pure code, no LLM. Binary gate on must-haves (excluding unanswerable
    ones), then Strong/Possible/No by how many nice-to-haves are met.

    The nice-to-have cutoff (>=2 met -> Strong) is a placeholder, not a
    weighted rubric - flagged here as a guess: a real agency would likely
    want this threshold configurable per role. Not building that today
    because nobody's asked for it yet.
    """
    must_haves = [c for c in criteria if c["type"] == "must_have"]
    nice_to_haves = [c for c in criteria if c["type"] == "nice_to_have"]

    gating = [c for c in must_haves if c["criterion"] not in unanswerable_must_haves]
    needs_confirmation = [c["criterion"] for c in must_haves if c["criterion"] in unanswerable_must_haves]

    passed_gates = all(c["met"] for c in gating)
    nice_met = sum(1 for c in nice_to_haves if c["met"])

    if not passed_gates:
        rank = "No"
    elif nice_met >= 2:
        rank = "Strong"
    else:
        rank = "Possible"

    return {
        "rank": rank,
        "must_haves_passed": sum(1 for c in gating if c["met"]),
        "must_haves_total": len(gating),
        "must_haves_needing_confirmation": needs_confirmation,
        "nice_to_haves_met": nice_met,
        "nice_to_haves_total": len(nice_to_haves),
    }
