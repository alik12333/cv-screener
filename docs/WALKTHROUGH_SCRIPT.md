# Walkthrough script

A script for a ~4 minute screen recording (Loom or similar) explaining this system to a recruitment agency director — someone who doesn't care how it's built, only whether it's trustworthy and whether it'll save their team time. Written to be read while recording the dashboard at `http://localhost:8000`.

Not recorded automatically — recording a screen and narrating it is a human action. This is the script to read while doing that.

---

**[Screen: the dashboard queue view, filtered to one role]**

"This is what happens after 200 people apply for one job. Right now, someone on your team opens each CV, reads it for about ten seconds, and decides. That's three hours of work, and the last forty applications get less attention than the first forty — some of them, honestly, never get read properly at all.

This system reads every single one. What you're looking at is the result: every candidate who applied for this DevOps role, ranked Strong, Possible, or No, sitting in a queue waiting for your team to decide."

**[Click into one "Strong" candidate]**

"Here's one person. Notice this isn't just a score — it's a checklist. Three years of DevOps experience: met, and here's the *exact sentence* from their CV that proves it. Terraform experience: met, same thing — the actual quote, not a summary. If you don't believe the system, you don't have to — you can read the proof yourself, right here."

**[Scroll to a "not met" criterion, e.g. "Right to work in the UK"]**

"This one's excluded from the pass/fail decision — because no CV in this batch ever states it. The system caught that automatically: if literally nobody answers a question, it stops treating that as a fail and flags it for a human to ask directly instead of silently penalising everyone for something a CV format was never going to tell it."

**[Scroll to the draft email]**

"And here's the email it's drafted — using only the evidence you just saw, nothing invented. But look: it hasn't been sent. Nothing gets sent by this system, ever. It sits right here, waiting."

**[Point at the Approve / Reject buttons]**

"This is the only thing that happens next: someone on your team reads this, and either approves it or rejects it. If they reject it, they have to say why — that's logged, permanently, with their name and the time. Nothing here can be undone or silently edited afterward. That's not a technical limitation — it's the actual point. The law around automated hiring decisions requires a human in the loop for exactly this reason, and this is built so that's never optional."

**[Switch to the Audit Log tab]**

"Every decision anyone's ever made lives here, permanently. If a candidate ever asks 'why was I rejected,' this is the honest, complete answer — not a guess."

**[Back to the queue, close on a wide view]**

"So: every application actually gets read. Every decision is something your team can check, not trust blindly. And nothing leaves this system without someone deciding it should. That's the whole thing."

---

## Notes for whoever records this

- Use a real "Strong" candidate with a genuinely full evidence trail — pick one with 5+ criteria met so the checklist visual actually lands.
- The "excluded from the gate" moment (Right to work) is the single best proof-of-thoughtfulness beat in the whole walkthrough — don't cut it for time.
- Don't over-promise: the pitch above never claims a percentage that isn't in `evals/results/`, and never says "this saves you three hours" as a fact — it says what the *manual* process costs, and lets the demo make the comparison.
