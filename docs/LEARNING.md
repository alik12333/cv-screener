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

---

## Day 4: Cross-role duplicate detection

**What this does**
`src/dedupe.py` finds candidates who applied to more than one role under slightly different details. It cascades: exact email match and fuzzy name+phone match first (pure code, instant, checked all 1,891 possible pairs across 62 candidates with zero API calls), then embedding-based content similarity as a confirming check — but only run on the much smaller set of pairs the cheap checks already flagged (207 of them), not the whole dataset.

**The concept behind it**
An embedding turns a piece of text into a list of numbers (a vector) positioned so that similar-meaning text ends up close together in that number-space. "Close together" is measured with cosine similarity - a score from -1 to 1 (in practice, close to 1 for near-identical text) based on the angle between two vectors, not their length. That lets code compare two CVs' actual content for likeness, cheaply, without another LLM call per comparison.

**Why we built it this way**
Investigated before writing any matching code, and it's a good thing we did: checked whether names and phone numbers are actually unique in this dataset, and they're not, badly. "Oliver Vance" turned out to be 24 different, unrelated fake candidates (the generator has limited name diversity even at temperature 1.0), and a single phone number (+44 7700 900451) recurred across roughly 15 of them - almost certainly because the model leans on the real UK Ofcom-reserved fictional drama number block (07700 900xxx) for "realism". Considered skipping this check and just trusting the architecture's stated cascade (email, then fuzzy name+phone) and rejected that: running the numbers first showed it would have been unsafe, not just imprecise.

**What broke and what fixed it**
Ran fuzzy name+phone matching alone across all 62 candidates first, deliberately, to measure the actual damage before adding anything else: **207 pairs flagged, only 6 real duplicates, 201 false positives (97%)** - unrelated same-named strangers who happened to also share a phone number from the same recycled block. That's not a rare edge case, it's the dominant outcome. A resourcer shown 207 "possible duplicate" alerts for 6 real ones would ignore all of them within a day - this is the same alert-fatigue failure mode real dedupe systems hit when they trust a single identity field too much (there really are multiple "John Smith"s in any large candidate database).

Fixed by adding the embedding confirmation step. It works because of *why* our duplicates and our collisions differ: a planted duplicate is a literal deep-copy of the original candidate object with only name and email changed (see `generate_cvs.py`), so its personal statement, skills, and employment bullets are byte-for-byte identical to the original's - while two different people who happen to share a name were generated independently and have completely different content. That difference showed up starkly: every true duplicate pair scored **exactly 1.0000** similarity, and the closest false positive topped out at **0.9958** - a real, clean gap, not a fuzzy judgment call. At a threshold of 0.999, final result: **6/6 true duplicates caught, 0 false positives** (`evals/results/2026-08-18-dedupe.md`).

**How to explain this to a client**
We don't just trust that a name or phone number matches - we tested what happens when two totally different people happen to share a common name, because that happens in real applicant pools too, and a system that trusted contact details alone would wrongly flag them as the same person. Adding a check that compares what's actually written in the CV, not just the contact details, fixed that completely in testing.

**New terms**
- **Embedding**: see `docs/GLOSSARY.md` (already defined from earlier planning) - this is the day it actually got used.
- **Cosine similarity**: a score measuring how similar two embedding vectors are, based on the angle between them rather than their length - close to 1 means near-identical meaning.
- **False positive / false negative**: a false positive here is two different people wrongly flagged as duplicates; a false negative is two applications from the same person that got missed. Dedupe design is a trade-off between the two, made concrete today.

---

## Day 5: Draft stage + approval gate

**What this does**
`src/aggregate.py` turns SCORE's per-criterion verdicts into a single rank (Strong/Possible/No), in plain code - no LLM. `src/draft.py` writes a candidate-facing email and a separate internal reasoning record for every candidate, and saves both with `status: pending`. `src/approve.py` is the only thing in the repo allowed to change that status, and every decision - approve or reject - gets logged with who and exactly when, in a file nothing ever rewrites.

**The concept behind it**
The gate only means something if there's no way around it. That's not a UI nicety, it's a structural property: DRAFT has no code path that sends anything, and APPROVE refuses to let an already-decided draft be decided again (tested this directly - a second approve call on an already-approved draft was refused, not silently accepted). The system can recommend and explain; a specific named person, at a specific recorded time, is the one who actually acts.

**Why we built it this way**
Two things went into `src/aggregate.py`, both flagged as deliberate simplifications rather than final design: the nice-to-have cutoff for "Strong" (2 or more met) is a placeholder, not a weighted rubric - CLAUDE.md's own pipeline description calls for weighted nice-to-haves in editable config, and that's not built because no agency has asked for specific weights yet. More importantly, must-have gating automatically excludes any must-have with zero evidence across every scored candidate for a role - which is how "Right to work in the UK" (Day 3's finding) gets handled correctly here without hardcoding that specific string: the run confirmed it, printing exactly `['Right to work in the UK']` as excluded before scoring a single candidate, the same criterion Day 3 found unanswerable from CV text, found here by the same general rule rather than a special case for it by name.

Also decided, and rejected an alternative: for a rejected candidate, the candidate-facing text is fixed, templated, and has zero LLM involvement - considered letting the model personalise rejections too (for a warmer, less form-letter tone) and rejected it. Itemising specific reasons in writing to a rejected candidate is a real legal exposure risk, and there's no upside worth trusting to a model's phrasing on that specific piece of text. The full reasoning still gets recorded, in the internal record, for the human approver only.

**What broke and what fixed it**
Small one, caught by reading actual output rather than trusting the code looked right: the first draft run greeted a candidate "Dear MARCUS," in shouting caps. Not an extraction bug - that candidate's CV used the "classic" layout, which renders names in caps, and extraction correctly copied it verbatim (exactly what Day 2 wanted from it). But copying verbatim is the wrong behaviour for this stage, which is writing to a real person. Fixed narrowly: only title-case a name if it's *entirely* uppercase (a clear rendering artifact), leaving already mixed-case names alone so a name like "O'Connor" doesn't get mangled by blanket title-casing.

**The result**
Ran DRAFT over all 15 already-scored DevOps candidates: 5 Strong, 0 Possible, 10 No - which lines up exactly with Day 3's fit-level breakdown (5 strong-fit candidates passed the gate and had 2+ nice-to-haves; the 5 medium-fit, 4 weak-fit, and 1 duplicate all landed in No). Demonstrated the actual gate, not just the code: listed the pending queue, approved one draft and rejected another with a named approver and a reason, then deliberately tried to approve the same draft again - refused, citing the original decision. `data/audit_log.jsonl` shows both real decisions, append-only.

**How to explain this to a client**
The AI never sends anything, full stop - it drafts, and shows its full reasoning to whoever's reviewing it, but a named person on your team has to click approve before anything goes out, and we keep a permanent record of who approved what and when. That's not just good practice - it's what UK data protection law requires for hiring-related decisions, and it's the main reason to trust this system over one that decides on its own.

**New terms**
- **Audit log**: an append-only record of actions taken (here: every approve/reject decision), kept separate from the data it describes so the history can't be quietly rewritten by editing the record itself.
- **Human-in-the-loop**: a system design where a person makes the final call on any consequential action, with the automation doing preparation and explanation but not the decision itself.

---

## Day 5, continued: n8n + Supabase, live

**What this does**
The local-only approval gate from earlier today now runs on the real infrastructure CLAUDE.md's stack table specified from day one: `src/api.py` is a FastAPI service exposing the pipeline stages (ingest, score, draft, approve/reject, audit log) over HTTP; a real Supabase Postgres project (`supabase/schema.sql`: `candidates`, `scores`, `drafts`, `audit_log` tables) replaced the local JSON files for this part of the pipeline; n8n runs in Docker as a visual workflow that calls the FastAPI service in sequence - Ingest, Score, Draft, then a node explicitly labelled "STOPS HERE" where the workflow deliberately does nothing further, because that's the human's job.

**The concept behind it**
A cloud platform like Supabase exposes two different kinds of API: a **data API** for reading/writing rows in a database you already have, and a **Management API** for controlling the account itself - creating projects, applying schema, the things you'd normally click through a dashboard for. Used the Management API directly, authenticated with a personal access token (same idea as `GEMINI_API_KEY` - a credential that proves who's allowed to act, just for infrastructure instead of AI calls) - the entire project existed, provisioned and ready, without opening the Supabase website once.

**Why we built it this way**
Tried registering an official Supabase MCP server first (`claude mcp add`), since it would have let me create the project through a purpose-built tool interface. Rejected continuing down that path once it became clear a newly-registered MCP server only connects when a Claude Code session starts - it wouldn't have been live until a restart, which would have stalled the whole task. Called Supabase's Management API directly over HTTP instead: the exact same account-level actions (list organisations, create a project, fetch connection details), no restart required. The MCP server stays registered in the project's local Claude Code config for next time.

Also had to choose between Supabase's two database connection styles: a **direct connection** (`db.<ref>.supabase.co:5432`) and a **connection pooler** (`aws-0-eu-west-2.pooler.supabase.com:6543`, running pgbouncer in transaction mode). Went with the pooler - Supabase's direct connections are IPv6-only by default, which fails outright on networks without IPv6 (a real, common failure mode, not a hypothetical one), while the pooler supports IPv4 and works everywhere.

**What broke and what fixed it**
n8n runs inside its own Docker container, with its own network namespace - the first version of the workflow pointed its HTTP Request nodes at `http://localhost:8000`, which would have failed, because "localhost" from inside a container means the container itself, not the Windows machine running FastAPI. Caught this before wiring any nodes, not after: ran `docker exec cvarc-n8n-1 wget http://host.docker.internal:8000/health` first to confirm Docker Desktop's special DNS name for the host machine actually resolves, then built every node's URL against `host.docker.internal` from the start.

**The result**
Proved the full chain twice: once end-to-end via curl (ingest, then score - 7 real Gemini calls, one per rubric criterion - then draft), and once by actually clicking "Test workflow" in n8n's canvas and watching the nodes execute. A real row landed in Supabase's `drafts` table (`status = pending`), visible in Supabase's own Table Editor - not a local file, not a mock, an actual cloud database anyone on the team could open and inspect.

**How to explain this to a client**
The whole pipeline runs as a visual workflow you can watch execute step by step, backed by a real cloud database you can open and check at any time - this isn't something that only exists in a developer's terminal, it's infrastructure your team could look at directly.

**New terms**
- **Management API**: an API for controlling a cloud account itself (creating projects, changing settings) as opposed to a data API for reading/writing the data inside a project you already have.
- **Connection pooler (pgbouncer)**: a proxy that sits in front of a database and reuses a small number of real connections across many client requests; used here in "transaction mode," and chosen over a direct database connection because it supports IPv4 networks, which the direct connection doesn't.
- **Docker networking / `host.docker.internal`**: a container has its own network namespace, so "localhost" inside a container refers to the container, not the machine running Docker. `host.docker.internal` is Docker Desktop's special DNS name for reaching the host machine from inside a container.

---

## Day 5, continued again: switching from Gemini to Groq

**What this does**
Every LLM call in the pipeline (generation, extraction, scoring, drafting) now goes through Groq instead of Gemini, via one shared helper (`src/llm.py`) that all four stages call instead of each duplicating its own client setup and retry logic. Embeddings (dedupe's job) stay on Gemini - Groq doesn't offer an embeddings endpoint at all.

**The concept behind it**
Not every "free" claim about an API means the same thing. OpenRouter (suggested first) really does offer $0-per-token models, but the *request* quota behind that is only 50/day unless you've deposited $10 at some point in your account's history (after which it's 1,000/day, permanently) - a detail that matters enormously for a pipeline that can burn 100+ requests in a single scoring run, and easily missed if you stop reading at "it's free."

**Why we built it this way**
Looked this up properly rather than trust the premise - checked OpenRouter's actual rate-limit docs, Groq's actual rate-limit docs, and tested structured-output support against both live rather than assumed from either provider's marketing. Groq won on every axis that mattered here: 14,400 requests/day against OpenRouter's 50 (or 1,000 with a paid deposit), no credit card needed, and it was already the second provider CLAUDE.md's own stack table named for exactly this situation - a documented fallback plan, not an improvised one.

Consolidating four near-identical retry/backoff functions (one each in `generate_cvs.py`, `extract.py`, `score.py`, `draft.py`) into `src/llm.py` was a judgment call made *because* all four needed the same provider swap at the same time - duplicated code that all changes together at once is exactly the moment consolidating stops being premature. It also means every stage now shares one real rate limiter instead of four independent ones, which is more correct once multiple stages can run concurrently inside the FastAPI service (a scenario that didn't exist when the duplication was first written).

**What broke and what fixed it**
Two real incompatibilities with Groq's *strict* structured-output mode, found by testing live rather than reading between the lines of documentation:

1. Groq requires `additionalProperties: false` set explicitly on every object in the schema, including nested ones (`Employment`, `Education` inside `CandidateProfile`). Gemini never needed this. Fixed by setting `model_config = ConfigDict(extra="forbid")` on every Pydantic model that reaches an LLM call - Pydantic only emits that flag when extra fields are forbidden, and it propagates correctly into nested `$defs` when every nested model sets it too (confirmed with a live test before touching the real schemas).
2. Groq requires every schema property to be listed in `required` - a field with a default (Pydantic's way of representing "optional") gets excluded from `required` automatically, and Groq's strict mode rejects that outright. This broke two fields that were deliberately nullable: `ExtractedProfile.right_to_work` (Day 2's decision not to force a guess when a CV doesn't state work authorisation) and `CriterionVerdict.evidence_quote` (Day 3's decision not to invent a quote when there's no evidence). Fixed each with a required sentinel instead of an optional value: `right_to_work` became a 3-way string (`"stated_true"` / `"stated_false"` / `"not_stated"`) rather than a nullable bool, and `evidence_quote` became a required string using `""` for "no evidence" rather than `None`. Both keep the exact original meaning - "don't force the model to guess" - just expressed in a shape the strict schema accepts. The one place this crosses back into a real nullable database column (`candidates.right_to_work` in Supabase) now has a small, explicit three-line conversion in `src/api.py`, rather than lettting the mismatch travel further than it has to.

**How to explain this to a client**
We test every claim about "free" before relying on it, not just for the AI provider but for exactly how much you can actually use before it stops being free - the difference between two providers that both say "free" was the difference between 50 requests a day and 14,400. Switching providers took under an hour because every part of the system that talks to an AI model goes through one shared, well-tested piece of code, not four separate copies that would each need fixing on their own.

**New terms**
- **Structured-output strict mode**: a stricter variant of schema-enforced output where the API guarantees the response will always match the schema exactly (no retries or validation needed on your end), in exchange for schema restrictions the non-strict mode doesn't have - here, every field must be required and every object must forbid extra properties.
- **Sentinel value**: a specific, ordinary-looking value (like `""` or `"not_stated"`) used to stand in for "no real value here," chosen when the natural representation (like `null`/`None`) isn't available or allowed in a given context.

---

## Day 5, continued a third time: Groq's real limit, and making the provider a switch instead of a migration

**What this does**
`src/llm.py` now supports both Groq and Gemini behind one `call_structured()` function, picked at call time by an `LLM_PROVIDER` env var (`.env`, default `gemini`). Nothing else in the codebase branches on provider - `extract.py`, `score.py`, `draft.py`, `generate_cvs.py` are unchanged from yesterday. Switching providers going forward is a one-line `.env` edit, or `LLM_PROVIDER=groq python src/whatever.py` for a single run.

**The concept behind it**
"Free tier" quotas aren't all measured the same way, and the currency matters as much as the number. Groq's headline 14,400 requests/day sounded generous against Gemini's request caps - but Groq also caps *total tokens* per day (200,000, on this model), and this pipeline's calls are token-heavy (full CV text plus the whole JSON schema, every call). A 62-candidate generation run followed by a partial extraction run exhausted that in under 100 calls - nowhere near the request cap, nothing to do with pacing, just raw token volume. Gemini's flash-lite tier, by contrast, is bounded by request count, not tokens, which fits this pipeline's shape - fewer, heavier calls - much better.

**Why we built it this way**
Yesterday's decision to move fully to Groq wasn't wrong given what was known then: it correctly solved the problem in front of it (one Gemini model capped at 20 requests/day). Today's problem is different - it's Groq's *token* budget, which request-based pacing can't fix at all, on any day, because the constraint isn't spacing, it's volume. Rather than migrate fully back (undoing yesterday's real fixes) or pick a side permanently, the honest move was to keep both: the Pydantic schema changes made for Groq's strict mode (`extra="forbid"`, required sentinels instead of nullable fields) turn out to be perfectly valid for Gemini too - a schema with no optional fields is just a stricter-than-necessary one, not an invalid one. So the same schemas serve both providers unchanged; only the calling code needed two implementations behind one interface.

**What broke and what fixed it**
Two more real incompatibilities, both confirmed live before being taken as fact:

1. Gemini's schema format has no `additionalProperties` field at all. Passing a Pydantic class with `extra="forbid"` straight to `response_schema` (as the original pre-Groq code did) now 400s, because the SDK's own auto-conversion emits `additionalProperties` from that config, and Gemini's backend rejects the field name outright (`Unknown name "additional_properties"`). Fixed by building the schema as a plain dict (`schema.model_json_schema()`) and stripping that one key before sending, instead of passing the class itself - `$defs`/`$ref` for nested models (`Employment`, `Education`) still resolve correctly with it stripped, confirmed with a live nested-model test before touching the real schemas.
2. First attempt at that fix also stripped `title` "for tidiness," on the assumption it was only ever JSON Schema's own metadata keyword. It isn't only that here - `Employment.title` is a real field (the job title), and stripping every `title` key recursively deleted that field's schema entry while `required` still listed it, which Gemini correctly rejected as inconsistent (`required[1]: property is not defined`). Caught immediately by testing against the actual `CandidateProfile` schema rather than only a toy example - a flat test schema with no field named `title` would never have surfaced this. Fixed by leaving `title` alone entirely; it cost nothing to keep and the collision risk wasn't worth chasing.

**How to explain this to a client**
Even between two AI providers that both offer a genuinely free tier, "free" can mean different things - one limits how many times you can ask, the other limits how much you can ask for in total, and a system that's heavy on the second kind of question needs the first kind of provider. Building the switch as a one-line setting rather than a rewrite means a real client running low on one provider's free quota can move to the other in minutes, not days.

**New terms**
- **Tokens per day (TPD)**: a quota measured in total tokens (input plus output, summed across every call) allowed per 24 hours - distinct from requests-per-day, and binds first for pipelines that make few, token-heavy calls rather than many small ones.

---

## Day 5, continued a fourth time: full run at scale, and the switch actually got used

**What this does**
Ran the complete pipeline - generate, extract, score, draft - across all 62 synthetic candidates and all 4 roles in one sitting. Result: 62/62 extracted, 450/450 scored (99.6% evidence-quote verification), 62/62 drafted, zero candidates lost to an unrecovered failure. 27 Strong, 1 Possible, 34 No across the four roles.

**The concept behind it**
This ended up being an unplanned live test of exactly the thing built two sections ago: a provider that's a config switch, not a migration. Gemini's real free-tier number turned out to be **500 requests/day** for `gemini-3.5-flash-lite` - stated plainly in the API's own error message, more reliable than any third-party estimate (one blog said ~1,000, the actual answer was half that). Extraction (37 calls) plus scoring (450 calls) used almost exactly that budget, so drafting hit the wall within the first role. Rather than wait for a reset, `LLM_PROVIDER=groq` for one command finished the remaining three roles' drafts in a few minutes - Groq's *token* budget (the thing that broke it yesterday) had room again for these small, cheap outreach-paragraph calls, even though its *request* budget was never the issue either day.

**Why we built it this way**
This is the actual argument for building the switch as an env var instead of picking a permanent winner: neither provider's free tier is generous enough on its own for a full run at this scale, but the two together, used for what each is actually good at, are. That's a real operating pattern for a free-tier system, not a one-off workaround.

**What broke and what fixed it**
`draft.py` crashed the entire role - losing every candidate after the failure point, not just the one that failed - the first time it hit Gemini's request cap, because it had no per-candidate error isolation (unlike `extract.py`, which already had this from Day 2). Fixed by giving it the same pattern: a try/except around the one LLM call per candidate, a `_failures.json` log, and a `--resume` flag that skips candidates that already have a draft file. This is Day 6's "partial failure handling" concept, just arriving two days early because a real failure demanded it rather than because the build order scheduled it - CLAUDE.md's own principle of measuring rather than assuming applies to the build order too, not just the numbers.

One subtlety worth recording: `find_unanswerable_must_haves` (which decides which must-have criteria get excluded from the pass/fail gate because no candidate's CV ever addresses them) has to run over every candidate's scores for the role even during a `--resume` run, or a partial subset could reach a different, wrong conclusion than the full set would. Only the per-candidate drafting loop skips already-done stems - the gate decision itself never does.

**How to explain this to a client**
We ran your entire candidate pool - all four roles, every application - through the full system in one sitting, and when one free AI provider hit its daily limit partway through, the system kept going on a second one without losing any work or needing anyone to intervene by hand.

**New terms**
- **Requests per day (RPD), confirmed number**: Gemini's `gemini-3.5-flash-lite` free tier is 500 requests/day per project, per model - read directly from a live 429 error's `quotaValue` field, not estimated from documentation.
- **Partial failure isolation**: catching a single item's failure in a batch, logging it, and continuing the rest of the batch - as opposed to letting one failure abort everything after it. `extract.py` had this from Day 2; `draft.py` needed the same fix today.

---

## Day 7: the dashboard, honest numbers, and explaining this to someone who isn't going to read the code

**What this does**
Built the approval-queue dashboard (a two-pane UI served straight from `src/api.py` - queue on the left, full evidence trail on the right, an audit log tab), wrote `src/sync_to_live.py` to get already-computed local batch results into the live database without spending any more LLM calls, refreshed two eval reports that had gone stale against a dataset that no longer exists, and wrote the actual README, walkthrough script, and everything needed to hand this project to someone who's never seen the code.

**The concept behind it**
The last piece of CLAUDE.md's six concepts to learn: explaining a system to a non-technical buyer. A recruitment agency director doesn't care about Pydantic schemas or rate limiters - they care whether they can trust it, and trust here comes from one thing: every claim on screen traces back to an exact quoted sentence from a real CV. The dashboard's entire design is built around making that traceability visible, not just true. Same instinct drove the README: every number in it links to a committed eval report, and the "honest limitations" section says what's actually missing rather than staying quiet about it.

**Why we built it this way**
Two scope decisions worth naming. First, the dashboard stays inside the existing FastAPI service as one static HTML file with vanilla JS - zero new frameworks, zero build step - directly because CLAUDE.md rules out new frameworks and scopes the UI to what the approval gate needs; the design brief was "show the complete evidence trail for one decision," not "build a general dashboard." Second, rather than re-run the whole pipeline through the live API to populate the dashboard (which would re-spend real LLM calls for zero new information), `sync_to_live.py` moves already-computed results directly - the expensive part already happened locally, moving JSON into Postgres costs nothing.

**What broke and what fixed it**
Two real gaps, both caught by checking rather than assuming:

1. The dashboard initially showed 4 candidates instead of 62. Local batch scripts and the live Supabase-backed system turned out to be two entirely separate stores - a full local run is invisible to anything reading from the live database until it's explicitly synced over. This was never a bug exactly, more an architectural seam nobody had needed to cross before today.
2. Two committed eval reports (`extraction`, `dedupe`, from Day 2 and Day 4) were about to get cited in the README with numbers that no longer meant anything - both were measured against the original dataset, wiped and regenerated during the Groq migration. Reran both against current data before writing a single number into the README. Real deltas came out of it, not just confirmation: `total_years_experience` extraction accuracy dropped 74.2% → 53.2%, and dedupe recall dropped from 6/6 to 5/6 true duplicates caught. Both went into the README as-is, not smoothed over - CLAUDE.md rule 5 is "every number is measured," not "every number looks good."

**How to explain this to a client**
Every number in this project's README came from an actual run on this exact codebase, today - if a number got worse between two versions of the system, the README says so, because a client checking our claims later should never find a surprise we already knew about and didn't mention.

**New terms**
- **Stale eval report**: a committed, dated measurement that described real system behaviour when it was written, but no longer reflects current behaviour because the underlying data or code has since changed - worth checking for, not assuming away, before citing any number as current.

---

## Day 7, continued: real screenshots, a bug the screenshots caught, and going public

**What this does**
Captured the five real dashboard screenshots `docs/SCREENSHOTS.md` had been specifying since Day 7 but never had (`scripts/capture_screenshots.py`, Playwright driving the system's installed Chrome), stitched the same frames into a silent looping GIF for the top of the README, made two real approve/reject decisions against the live queue to get a genuine audit-log screenshot rather than a staged one (`scripts/capture_decisions.py`, deliberately split into its own script - see below), and published all of it to the already-public GitHub repo.

**The concept behind it**
A screenshot is a claim, same as a README number - "here's the evidence trail" only means something if the image is a real run, not a mockup. That's why every shot here traces to an actual candidate (`devops-04-elliot-marsh`, Strong, 6/7 criteria - `devops-01-alex-taylor`, No, under the 3-years must-have) rather than fabricated example data, same principle as CLAUDE.md rule 5 applied to pictures instead of numbers.

**Why we built it this way**
Two decisions worth naming. First, capturing screenshots and *making real queue decisions* got split into two separate scripts on purpose, not merged into one convenient run - `capture_decisions.py` writes permanent state to a live system (this app refuses to ever let a decision be re-made, by design), so it only runs after an explicit go-ahead, never bundled automatically with the read-only screenshot pass. Second, screenshots got captured with Playwright driving the *system's already-installed Chrome* (`channel="chrome"`) rather than downloading Playwright's own bundled browser - same outcome, no ~150MB download, and it's a one-off dev tool anyway (installed into `.venv`, which is gitignored - never touched `requirements.txt`).

**What broke and what fixed it**
The very first evidence-panel screenshot showed "**undefined** · devops-04-elliot-marsh" instead of the candidate's name and email. Real bug, not a screenshot artefact: `GET /drafts/{stem}` (`src/api.py`) had never joined the `candidates` table, so `full_name`/`email` were simply missing from the response and the dashboard's JS rendered `undefined`. This had been live on every real use of the dashboard since Day 7 - nobody had looked closely enough at that specific corner of the screen to notice, which is exactly the kind of thing a "take a real screenshot, don't just eyeball it" pass is for. Fixed with a two-line join; caught before anything went into the public README, not after.

Second, smaller one: the first attempt at the audit-log screenshot fired before the table's async load finished, because `page.wait_for_selector("table.audit td")` matched the *"Loading…"* placeholder cell itself, not real data - a selector that matches its own loading state doesn't prove loading is done. Fixed by waiting for a `td.mono` (only present in real rows, never the placeholder) instead.

**How to explain this to a client**
Every screenshot in this README is a real run against real (synthetic) data, not a mockup - including one that accidentally caught and got us to fix a display bug before a client ever saw it.

**New terms**
- **Headless browser automation**: driving a real browser (here, the machine's own installed Chrome) from a script with no visible window, to reach and screenshot exact UI states a static page-load can't - clicking, filtering, scrolling - the same way a person would, just repeatable.
