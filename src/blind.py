"""
Blind a candidate profile before it reaches the scoring stage.

Why: CLAUDE.md rule 3 - strip identity-correlated fields before scoring, and
reattach them only for the final human-facing shortlist. Cheap to do, reduces
adverse-impact risk, and is a feature the product sells out loud.

What's stripped, and why each one:
- full_name: the obvious one.
- email: usually derived from the name (e.g. "oliver.vance88@..."), so leaving
  it in would just leak the name back in through the side door.
- education.institution ("university" in CLAUDE.md's list): qualification and
  year are kept - what someone studied and when is relevant to scoring; which
  specific institution carries a prestige/name-recognition bias risk and isn't.

Not stripped: location, phone, salary, notice period, employer names, skills,
dates. CLAUDE.md's list is specific (name, gender markers, age, photo,
university) - this schema has no age or photo fields and no explicit gender
field, so there's nothing further to redact against that list.
"""

import copy

PLACEHOLDER_NAME = "The Candidate"
PLACEHOLDER_EMAIL = "[redacted]@example.com"
PLACEHOLDER_INSTITUTION = "[institution redacted]"


def blind_profile(profile: dict) -> dict:
    """Returns a deep-copied profile with identity fields stripped for scoring."""
    blinded = copy.deepcopy(profile)
    blinded["full_name"] = PLACEHOLDER_NAME
    blinded["email"] = PLACEHOLDER_EMAIL
    for edu in blinded.get("education", []):
        edu["institution"] = PLACEHOLDER_INSTITUTION
    return blinded


def profile_to_text(profile: dict) -> str:
    """Render a (blinded) profile back to plain text for the scoring prompt.

    Deliberately not reusing generate_cvs.py's renderers - those exist to
    produce realistic-looking CV layouts for the extraction eval. Scoring
    doesn't need layout variety, it needs a flat, unambiguous field dump the
    model can scan quickly for one specific criterion at a time.
    """
    lines = [
        f"Name: {profile['full_name']}",
        f"Current title: {profile['current_title']}",
        f"Location: {profile['location']}",
        f"Total years experience (self-reported): {profile['total_years_experience']}",
        f"Personal statement: {profile['personal_statement']}",
        f"Skills: {', '.join(profile['skills'])}",
        "",
        "Employment history:",
    ]
    for job in profile["employment"]:
        lines.append(f"- {job['title']} at {job['employer']} ({job['start']} - {job['end']})")
        for bullet in job["bullets"]:
            lines.append(f"    {bullet}")
    lines += ["", "Education:"]
    lines += [f"- {e['qualification']}, {e['institution']} ({e['year']})" for e in profile["education"]]
    lines += ["", f"Notice period: {profile['notice_period']}",
              f"Salary expectation: {profile['salary_expectation']}"]
    return "\n".join(lines)
