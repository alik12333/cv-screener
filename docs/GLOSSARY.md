# Glossary

Every technical term used in this repo, one line each, A-Z. Add to this as new terms appear — this file is a running reference, not a one-time write.

**Adverse impact** — when a selection process disadvantages a protected group even without intending to; blind scoring (below) is one mitigation.

**Aggregate (pipeline stage)** — pure-code stage that turns per-criterion LLM verdicts into a weighted total and applies binary must-have gates. No LLM involved.

**Audit log** — an append-only record of actions taken (here: every human approve/reject decision on a draft), kept separate from the data it describes so the history can't be quietly rewritten by editing the record itself.

**Backoff (exponential backoff)** — after a failed API call, waiting progressively longer before retrying (e.g. 5s, 10s, 20s) instead of retrying instantly, so you don't hammer a rate-limited or struggling service.

**Binary gate** — a must-have requirement that's pass/fail with no partial credit; failing one caps a candidate regardless of how strong the rest of their CV is.

**Blind scoring** — stripping name, gender markers, age, photo and university from a CV before it's scored, then reattaching identity only for the final shortlist display, to reduce bias in the judgement itself.

**Confidence (in a scoring verdict)** — a value the model reports alongside its judgement indicating how sure it is, so low-confidence verdicts can be flagged for human review instead of trusted blindly.

**Connection pooler (pgbouncer)** — a proxy that sits in front of a database and reuses a small number of real connections across many client requests. Used here (Supabase's pooler, in "transaction mode") instead of a direct database connection because it supports IPv4 networks, which Supabase's direct connections don't by default.

**Cosine similarity** — a score (roughly 0-1 for real text) measuring how alike two embedding vectors are, based on the angle between them rather than their length; close to 1 means near-identical meaning. Used in dedupe to compare CV content directly instead of trusting contact details alone.

**Dedupe / deduplication** — detecting that two applications are actually the same person, e.g. re-applying under a shortened name and a different email.

**Docker networking / `host.docker.internal`** — a container has its own network namespace, so "localhost" inside a container refers to the container itself, not the machine running Docker. `host.docker.internal` is Docker Desktop's special DNS name for reaching the host machine from inside a container - needed here so n8n (in Docker) can call the FastAPI service (running directly on the host).

**Embedding** — a numeric vector representation of text such that semantically similar text produces similar vectors. Used in dedupe to compare CV content (not contact details) as a confirming check on top of cheap name/email/phone matching.

**Evaluation harness (eval)** — code that runs a pipeline stage against known-correct answers (ground truth) and measures accuracy, so "it works" is a number, not an impression.

**FastAPI** — a Python web framework used here as the service layer that n8n calls into to run pipeline stages.

**False positive / false negative** — a false positive is a wrong "yes" (e.g. two different people flagged as the same candidate); a false negative is a wrong "no" (e.g. two applications from the same person that got missed). Every detection system trades one against the other.

**Fuzzy matching** — comparing strings allowing for small differences (typos, abbreviations, formatting) rather than requiring an exact match; used for name/phone matching in dedupe, confirmed (not replaced) by an embedding-based content check afterward.

**Ground truth** — the known-correct structured data for a test CV, generated alongside it in `data/ground_truth/` by `generate_cvs.py`, used to grade the extraction stage.

**Human-in-the-loop** — a system design where a person makes the final call on any consequential action; the automation prepares, drafts, and explains, but the decision itself is never made by code or a model alone.

**Idempotency** — a property where processing the same input twice has the same effect as processing it once; achieved here by hashing incoming attachments so a re-sent or re-delivered CV isn't processed twice.

**LangGraph** — a framework for building multi-step LLM agent workflows with explicit state and control flow; scheduled to join the stack in week 4, and deliberately the only new framework allowed in (see CLAUDE.md anti-goals).

**Management API** — an API for controlling a cloud account itself (creating projects, changing settings), as opposed to a data API for reading/writing the data inside a project you already have. Used to create this project's Supabase project and apply its schema, entirely from the command line.

**MCP (Model Context Protocol)** — a standard for connecting LLM applications to external tools and data sources. A Supabase MCP server is registered in this project's local Claude Code config, though the Supabase setup actually done so far used the Management API directly (a newly-registered MCP server only connects at session start, and waiting for a restart wasn't worth it mid-task).

**n8n** — a self-hosted workflow automation tool, running in Docker, used as the orchestration layer that calls the FastAPI service (`src/api.py`) to sequence pipeline stages; the human approval queue itself now lives in Supabase, not in n8n.

**Normalise (pipeline stage)** — pure-code stage that cleans extracted data: resolving skill synonyms, standardising job titles, parsing dates, computing employment gaps. No LLM.

**Partial failure** — when some items in a batch (e.g. some CVs in a run of 200) fail while others succeed; handled by isolating failures to a review queue rather than letting one bad CV crash the whole batch.

**pgvector** — a Postgres extension that stores and searches embedding vectors directly in the database, used here for dedupe similarity search without a separate vector database.

**Pydantic model** — a Python class that defines the exact shape (fields and types) data must take; used as the contract for every LLM call in this repo so output is schema-enforced rather than free text.

**RAG (Retrieval-Augmented Generation)** — a pattern where an LLM's prompt is supplemented with relevant retrieved text (e.g. from a database) rather than relying only on what the model already knows; on the "actively learning" list.

**Rate limiter** — code that ensures API calls don't exceed a service's allowed frequency (e.g. spacing Gemini free-tier calls at least 5 seconds apart).

**Requests per day (RPD)** — a quota measured in total calls allowed per 24 hours, separate from (and not fixed by) spacing calls further apart per minute; free-tier LLM APIs often cap both dimensions independently, and per model.

**Rubric** — the set of scoring criteria (must-haves and nice-to-haves) for a role, kept in editable config so weights can change without a code change.

**Schema-enforced output / structured output** — asking an LLM API to return data conforming to a predefined schema (here, a Pydantic model), instead of parsing free-text output and hoping it matches the expected shape.

**Temperature** — a setting controlling how random/varied an LLM's output is; kept near 0 for extraction and scoring (consistency matters) and higher for CV generation (variety is the point).

**Vector search / vector similarity** — finding items whose embeddings are numerically close to a query embedding; in this repo, measured with cosine similarity as the confirming step in dedupe.
