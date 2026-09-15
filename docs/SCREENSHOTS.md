# Screenshots and the walkthrough GIF

The five screenshots below are real, captured from a live run against this repo's actual synthetic dataset — not mockups. `scripts/capture_screenshots.py` drives the dashboard with Playwright (against the system's installed Chrome, so it needs no extra browser download) to reach each view; `scripts/capture_decisions.py` is split out separately because it makes two *real, permanent* approve/reject decisions against the live Supabase queue, so it only ever runs with an explicit go-ahead, never bundled into the read-only capture. Both are one-off dev tools, not part of the pipeline.

The candidate used throughout is `devops-04-elliot-marsh` (Strong, 6/7 criteria met) for the evidence/gate/approve shots, and `devops-01-alex-taylor` (No — under the 3-years must-have) for the reject case in the audit log. `docs/gifs/walkthrough.gif` is the same sequence of real frames, stitched together — a silent, looping substitute for narrated video (see the note at the bottom of this file on why it isn't the real thing).

To regenerate after a UI change: run the dashboard locally, then `.venv/Scripts/python scripts/capture_screenshots.py`, review the output, and only then run `capture_decisions.py` if you're OK making two more permanent queue decisions.

## The five screenshots, in order

1. **`docs/screenshots/01-queue.png`** — the dashboard's queue view (`http://localhost:8000`), filtered to one role, several candidates visible with their rank badges (Strong/Possible/No) and status badges. This is the "here's the triage, at a glance" shot.

2. **`docs/screenshots/02-evidence.png`** — a single Strong candidate's detail panel, scrolled to show at least 3–4 criteria with their evidence quotes visible in the highlighted exhibit blocks, and the confidence percentages readable. This is the single most important shot — it's the whole pitch (every claim traces to a quote) in one image.

3. **`docs/screenshots/03-gate.png`** — the same candidate, scrolled to the "must-have gate" section showing a criterion excluded from the gate (e.g. "Right to work in the UK") with the explanation text visible. Proves the system handles an edge case thoughtfully, not just the happy path.

4. **`docs/screenshots/04-approve.png`** — the draft email preview plus the Approve/Reject buttons, ideally with the reviewer name field filled in. Shows the actual human decision point.

5. **`docs/screenshots/05-audit-log.png`** — the Audit Log tab, with a handful of real decisions visible (approved and rejected both, if you have both by then). Proves the accountability trail is real, not just claimed.

Optional sixth: a screenshot of the n8n workflow canvas mid-execution (all nodes green) — useful if you want to show the visual orchestration layer specifically, but the five above tell the core story without it. Not captured yet — Docker/n8n weren't running when the rest of these were taken.

All five are already embedded in `README.md`, right after the "What's actually in here" section.

## Why the GIF isn't the real walkthrough video

`docs/gifs/walkthrough.gif` is real frames from a real run, but it's silent and unnarrated — a sequence of screenshots, not a recording of a person explaining the system. It exists because a script can drive a browser and take screenshots, but it can't record a voice explaining *why* the "Right to work in the UK" exclusion matters to a director who's never seen this before. That's a genuinely different thing, and `docs/WALKTHROUGH_SCRIPT.md` is written for exactly that gap — a ~4 minute script to read while recording a real Loom.

Once that's recorded, add this near the top of `README.md`, right after the opening paragraph:

```markdown
[**Watch the 4-minute walkthrough →**](YOUR_LOOM_LINK_HERE)
```
