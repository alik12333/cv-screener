# Learning Log

## Day 0: What this is and why it exists

**What this does**
Small UK IT recruitment agencies (3 to 30 people) get flooded with applications — around 200 per role over five days. A resourcer manually opens each one, skims it for about ten seconds, and decides. That's roughly three hours of work per role, the last forty CVs get rushed, and around 160 candidates never hear back at all. This system reads every CV, scores it against the role's actual requirements with reasoning a human can check, flags people who've applied to several roles under different details, and drafts replies. It never sends anything itself — a person at the agency approves every decision first.

**Who buys it**
Small recruitment agencies who can't afford a big applicant-tracking-system subscription and don't have spare hours to manually triage every application. The sales pitch is speed (every CV actually gets read) plus responsible handling of candidate data (nothing scraped, nothing sent without a human check) plus running cost (free-tier infrastructure, a few dollars a month rather than per-seat SaaS pricing).

**Why it's built the way it is**
The one architectural decision everything else follows from: the model is only ever asked to make one small judgement at a time — parse this CV, judge this one candidate against this one criterion, write this one personalised sentence. It never computes a final score, ranks candidates, or decides who gets rejected. All of the arithmetic, ranking and routing is ordinary Python, because that's checkable, repeatable, and defensible in a way "the model said 8/10" is not. See `docs/ARCHITECTURE.md` for the full eleven-stage breakdown.

**The six concepts to learn by the end of this**
1. **Structured/schema-enforced output** — making an LLM return data in an exact shape you define, instead of parsing free text and hoping (Day 1, already used in `generate_cvs.py`).
2. **Extraction vs. generation, and evaluation harnesses** — how to measure whether an LLM extracted a CV correctly against a known-correct answer, rather than just eyeballing it (Day 2).
3. **Rubric design and evidence citation** — building scoring criteria an LLM can judge consistently, and catching when it invents a quote that isn't actually in the CV (Day 3).
4. **Fuzzy matching and embeddings** — two different techniques for recognising "this is probably the same person," used in that order because the cheap one (string matching) resolves most cases and the expensive one (vector similarity) is only needed for what's left (Day 4).
5. **Human-in-the-loop system design** — building a queue and an approval gate so automation drafts things but a person authorises them, including why this is a legal requirement here (UK GDPR Article 22), not just a nicety (Day 5).
6. **Production LLM pipeline hardening** — concurrency, rate limiting, exponential backoff, and partial failure handling, so a batch of 200 CVs doesn't die because CV #47 timed out (Day 6).

**Today's actual work**
No pipeline code yet. `docs/` was empty, and CLAUDE.md is explicit that architecture and glossary docs come first. Today: reorganised the files from the initial handoff (`generate_cvs.py`, `job_specs.json`, `requirements.txt`) into the repo layout the spec defines, added `.gitignore` and `.env.example`, and wrote `ARCHITECTURE.md` and this file. `generate_cvs.py` (the Day 1 synthetic CV generator) already existed going in — running it is the next actual step.

**New terms**
See `docs/GLOSSARY.md` — every term used above and in CLAUDE.md is defined there.
