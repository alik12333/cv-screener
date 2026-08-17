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
Two separate failures, back to back.

First: the script was written against `gemini-2.5-flash`, which Google retired for new API keys sometime after the script was handed off — every call failed with a 404 from `ClientError`. The retry loop's `except Exception as exc` only logged `type(exc).__name__`, not the message, so the real reason (a 404 naming a replacement model) was invisible until we ran the call manually outside the retry loop. Fixed by adding the exception message to the retry log line, and switching `MODEL` to `gemini-3.6-flash` (confirmed against `client.models.list()` and a live test call).

Second, on the full 62-CV run: it died partway through the first role with a 429 quota error. `MIN_SECONDS_BETWEEN_CALLS = 5.0` was written on the assumption "free tier is roughly 10-15 requests/minute" — but the actual error was `GenerateRequestsPerDayPerProjectPerModel-FreeTier, quotaValue: 20`. That's 20 requests **per day**, not per minute, and it applies per model. No amount of spacing calls out fixes a per-day cap — the only fix is using a model with more daily headroom. Switched to `gemini-3.5-flash-lite` (lite-tier models generally carry a higher free daily quota than the flagship models) and the full batch completed without a single retry. Lesson: a rate limit has more than one dimension (per-minute burst vs. per-day total), and free-tier numbers are worth confirming empirically rather than trusting a comment written on a different day against a different model — they change, and the failure mode looks identical to a burst-limit problem until you read the actual error body.

**How to explain this to a client**
We test the whole system on invented candidates before it ever touches a real CV, and because every invented CV is generated from a known-correct answer, we can measure exactly how accurate the system is rather than just eyeballing it.

**New terms**
(none beyond `docs/GLOSSARY.md`)

---

## Day 2: Extraction stage + first eval run

**What this does**
`src/extract.py` reads a CV's raw text and asks Gemini to return it as the same structured shape `generate_cvs.py` used to build it, one schema-enforced call per CV, temperature near 0 for consistency. `evals/extraction_eval.py` then compares every extracted CV against its known-correct ground truth, field by field, and produces a real accuracy number instead of an impression from reading a few examples.

**The concept behind it**
Extraction and generation use the identical technique (schema-enforced output) pointed in opposite directions — but only extraction can be graded automatically, because only extraction has a ground truth to compare against. That's the whole reason `generate_cvs.py` was built the way it was on Day 1: every synthetic CV came with its answer key for free, so this eval cost nothing to build.

**Why we built it this way**
Pulled the Pydantic models (`Employment`, `Education`, `CandidateProfile`) out of `generate_cvs.py` into a shared `src/schema.py`, imported by both generation and extraction. Considered leaving them duplicated (faster to write) and rejected it: if the two files' schemas drifted even slightly, the eval would silently be comparing against the wrong contract, and the mismatch would be invisible until the numbers looked wrong for no obvious reason. `right_to_work` is deliberately nullable in the extraction schema (`ExtractedProfile`, a subclass of `CandidateProfile`) even though generation's version is a required bool — see the finding below.

**What broke and what fixed it — the real result**
Ran the full eval against 62 CVs. Result (saved in `evals/results/2026-08-18-extraction.md`):

- **Near-perfect (96.8–100%)**: name, email, phone, location, title, notice period, skills (set-match), personal statement (text-similarity), employment history, education. These are all fields stated close to verbatim in the CV text, and extraction copies them faithfully.
- **`salary_expectation` at 98.4%**, one miss traced to a corrupted currency symbol baked into the *source CV* at generation time (a stray control byte instead of `£`) — the ground truth inherited the same corruption, and extraction's output was actually cleaner than the flawed source. Not an extraction failure.
- **`current_title` started at 96.8%**, two misses traced to a real ambiguity: one CV's personal statement described the candidate as "Senior Java Backend Developer" while their actual most recent job title (in the employment section) was "Senior Java Developer" — the two didn't agree, and extraction picked the personal statement's wording. Fixed by telling the prompt explicitly which one wins ("use the job title from the most recent employment entry"); reran, now 100%.
- **`total_years_experience` at 74.2%, the one real weak point that didn't get fixed today.** Investigated 16 mismatches directly: this number is essentially never stated as a raw figure in the CV text. It's either implied by rounded prose in the personal statement ("2.5 years", "over six years") or has to be computed by summing employment date ranges — and the model's guesses land close but not exact. This is not a prompt-wording bug like `current_title` was; it's a category mismatch. Computing a total from a list of start/end dates is arithmetic, and arithmetic is exactly what CLAUDE.md's rule 1 says should never be left to the model: "the model makes one judgement at a time, code does everything else." The right fix isn't a better extraction prompt — it's building the NORMALISE stage (pure code, no LLM) to compute this from `employment[].start`/`end` instead of asking the model to estimate it. Flagging this for whenever NORMALISE gets built rather than fixing it today, since Day 2's job was extraction and eval, not normalisation — this is exactly the kind of run-ahead CLAUDE.md's build order warns against.
- **Right_to_work**, as anticipated on Day 1, never appears in any of the three CV layouts' rendered text — confirmed across all 62 files, not just a few. Left nullable and excluded from scoring rather than let a default guess look like 100% accuracy.
- **By CV layout**: `header_heavy` scored lowest (0.949 vs 0.996 classic / 0.981 terse), matching the Day 1 guess that contact info buried in a header block would be the hardest to parse — though the gap is modest, because this is still clean generated text with no OCR noise. A real scanned CV would likely widen this gap.

**How to explain this to a client**
We don't just claim the system reads CVs accurately — we tested it against 62 CVs where we already knew the right answer, and it got contact details, job history, and skills right essentially every time. The one soft spot we found (an exact "years of experience" figure) is being fixed by making the computer do the maths from employment dates directly, rather than asking the AI to estimate it — which is the same principle behind why the system is trustworthy in the first place: the AI reads, the code counts.

**New terms**
- **Ground-truth drift**: when two parts of a system that are supposed to agree on a data shape (here, generation's schema and extraction's schema) evolve independently and silently stop matching, invalidating any comparison between them.

---

## Day 3: Scoring with visible reasoning

**What this does**
`src/score.py` judges one candidate against one job requirement at a time — for every must-have and nice-to-have in a role's rubric, one model call returns a yes/no verdict, a 0-1 confidence, and a quote copied from the CV backing it up. `src/blind.py` strips name, email, and university from the candidate before any of that happens (CLAUDE.md rule 3). After each verdict, the quote gets checked against the actual text the model was shown — not trusted just because it sounds plausible.

**The concept behind it**
The model is deliberately kept narrow: one candidate, one requirement, one verdict, never asked to rank or total anything. That's what makes the reasoning "visible" — a resourcer can open any verdict and see the exact sentence it's based on, and disagree with a specific judgment instead of a black-box score.

**Why we built it this way**
Considered scoring all requirements for a candidate in a single call (fewer API calls, faster) and rejected it: bundling requirements together makes it harder to isolate which judgment was wrong when one is, and makes evidence-quote verification ambiguous (which requirement was that quote for?). One call per criterion costs more requests but keeps every verdict independently checkable — the entire point of this stage.

**What broke and what fixed it**
Two real findings, both caught by reading actual output rather than trusting a clean-looking summary number.

First: scored a "medium fit" DevOps candidate whose most recent role was dated "September 2022 – Present" — as of today that's nearly 4 years, comfortably over the "3+ years" must-have. The model marked it `false` at 0.95 confidence anyway. Reproduced it in isolation and found the cause: the prompt never told the model what today's date is. An open-ended "Present" end date has no fixed length without that anchor, so the model silently fell back on its own notion of "now" — which is wrong, since it doesn't know this is a 2026 CV. Added `Today's date: {date}` to the prompt; the same candidate/criterion pair flipped to a correct `true` at full confidence in isolation. Fixed before any real batch ran.

Second, and this one wasn't a bug I could fix by editing a prompt: with the date anchor in place, that same style of candidate *still* sometimes scored `false` on the years must-have — but now because the model was trusting the extracted `total_years_experience` field (self-reported, and we already know from Day 2 that field is only ~74% accurate) over computing this specific role's tenure from its own dates. That's an upstream extraction imprecision quietly corrupting a downstream hiring verdict — a concrete, real example of exactly why the NORMALISE stage has to sit between EXTRACT and SCORE. Right now SCORE gets handed a number we already know is shaky, with no way to tell it apart from a trustworthy one. Not fixed today — the actual fix is NORMALISE recomputing tenure deterministically from raw dates, which isn't built yet.

**The full-batch result**
Ran all 15 DevOps candidates through all 7 criteria (105 judgments total, `evals/results/2026-08-18-scoring-devops.md`):
- **105/105 evidence quotes verified** — zero invented citations in this run.
- **Must-have pass rate tracked intended fit almost exactly**: strong 66.7%, medium 33.3%, weak 0%, duplicate 0%. The gradient is the right shape.
- **The strong-fit ceiling is 66.7%, not 100%, and that's a real problem, not noise.** "Right to work in the UK" is one of DevOps's 3 must-haves, and — confirmed again here, same as Day 2 — it has zero textual evidence in any CV, ever. So it fails for every candidate, including perfect ones. If AGGREGATE gets built to gate candidates on all must-haves passing without changing this, it would auto-fail 100% of applicants on a criterion the CV was never going to answer. This needs a different data source (an application-form field, merged in before the gate) — not something to solve inside SCORE, which can only work with what's in the CV. Documented here so it isn't forgotten when AGGREGATE gets built.

**How to explain this to a client**
Every "yes, they meet this requirement" comes with the exact line from the CV it's based on, and we specifically test whether the AI ever makes up a quote that isn't really there — in this run, across 105 separate checks, it didn't. Where we did find a mistake, it wasn't the AI being unreliable, it was a missing piece of context (today's date), and we caught it by testing, not by hoping.

**New terms**
- **Evidence citation**: requiring a model to point to the specific source text backing a claim, so the claim can be checked rather than taken on faith.
- **Date anchoring**: telling a model what "today" is explicitly, so it can correctly reason about open-ended time spans ("... - Present") instead of guessing.
