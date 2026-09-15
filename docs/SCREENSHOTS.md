# Screenshot and recording checklist

Nothing in this repo captures a screen or records video automatically — that's a manual step. This is the exact shot list, in the order that tells the strongest story to someone skimming quickly, plus the exact markdown to paste into `README.md` once each file exists. Save every image into `docs/screenshots/` using the filenames below and the snippets just work.

Don't add these to the README until the files actually exist — a broken image link looks worse to a reader than no image at all.

## The five screenshots, in order

1. **`docs/screenshots/01-queue.png`** — the dashboard's queue view (`http://localhost:8000`), filtered to one role, several candidates visible with their rank badges (Strong/Possible/No) and status badges. This is the "here's the triage, at a glance" shot.

2. **`docs/screenshots/02-evidence.png`** — a single Strong candidate's detail panel, scrolled to show at least 3–4 criteria with their evidence quotes visible in the highlighted exhibit blocks, and the confidence percentages readable. This is the single most important shot — it's the whole pitch (every claim traces to a quote) in one image.

3. **`docs/screenshots/03-gate.png`** — the same candidate, scrolled to the "must-have gate" section showing a criterion excluded from the gate (e.g. "Right to work in the UK") with the explanation text visible. Proves the system handles an edge case thoughtfully, not just the happy path.

4. **`docs/screenshots/04-approve.png`** — the draft email preview plus the Approve/Reject buttons, ideally with the reviewer name field filled in. Shows the actual human decision point.

5. **`docs/screenshots/05-audit-log.png`** — the Audit Log tab, with a handful of real decisions visible (approved and rejected both, if you have both by then). Proves the accountability trail is real, not just claimed.

Optional sixth: a screenshot of the n8n workflow canvas mid-execution (all nodes green) — useful if you want to show the visual orchestration layer specifically, but the five above tell the core story without it.

## Markdown to add to README.md once the files exist

Paste this block right after the "## What's actually in here" section:

```markdown
## Screenshots

**The queue** — every candidate, ranked, waiting for a decision:
![Queue view](docs/screenshots/01-queue.png)

**The evidence** — every claim traces to an exact quoted sentence from the real CV:
![Evidence trail](docs/screenshots/02-evidence.png)

**Handling the edge case** — a must-have with no evidence anywhere gets excluded from the gate, not silently failed:
![Must-have gate](docs/screenshots/03-gate.png)

**The decision point** — nothing sends until a person clicks:
![Approve or reject](docs/screenshots/04-approve.png)

**The permanent record** — every decision, who made it, when:
![Audit log](docs/screenshots/05-audit-log.png)
```

## If you record a walkthrough video

Once you've recorded the Loom from `docs/WALKTHROUGH_SCRIPT.md`, add this near the top of `README.md`, right after the opening paragraph:

```markdown
[**Watch the 4-minute walkthrough →**](YOUR_LOOM_LINK_HERE)
```
