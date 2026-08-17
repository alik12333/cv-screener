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

---

## Day 1: Synthetic CV generator running end-to-end

**What this does**
`src/generate_cvs.py` asks Gemini to invent a realistic UK job applicant for each of the four fake roles in `data/job_specs.json`, at a deliberately controlled fit level (strong/medium/weak), and renders each one as a CV text file in one of three different layouts, plus a matching ground-truth JSON with the exact structured data behind it. It also plants a few "duplicate" applicants — the same invented person reapplying to a different role under a shortened name and altered email — so later stages have real duplicates to catch.

**The concept behind it**
Schema-enforced structured output: instead of asking the model to write JSON and hoping it's well-formed, the API call is given a Pydantic model (`CandidateProfile`) as the required response shape, so what comes back is guaranteed to parse correctly every time. This matters everywhere an LLM output feeds into code, not just here.

**Why we built it this way**
Synthetic data generated *from* a structured object rather than free text means the ground truth is known exactly — there's no need to hand-label CVs later to build an eval set for the extraction stage. Cost is one prompt per candidate rather than one per field, which stays well inside the free-tier rate limit.

**What broke and what fixed it**
The script was written against `gemini-2.5-flash`, which Google retired for new API keys sometime after the script was handed off — every call failed with a 404 from `ClientError`. The retry loop's `except Exception as exc` only logged `type(exc).__name__`, not the message, so the real reason (a 404 naming a replacement model) was invisible until we ran the call manually outside the retry loop. Fixed by switching `MODEL` to `gemini-3.6-flash` (confirmed against `client.models.list()` and a live test call) and adding the exception message to the retry log line, so this class of failure surfaces immediately next time instead of costing a debugging detour.

**How to explain this to a client**
We test the whole system on invented candidates before it ever touches a real CV, and because every invented CV is generated from a known-correct answer, we can measure exactly how accurate the system is rather than just eyeballing it.

**New terms**
(none beyond `docs/GLOSSARY.md`)
