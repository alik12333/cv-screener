"""
The human approval gate. This is APPROVE (stage 10, see docs/ARCHITECTURE.md)
- the only file in this repo allowed to move a draft out of "pending". Nothing
else may. That's the whole point: CLAUDE.md rule 2 says nothing sends without
an explicit human approve, logged with who and when, and that gate must never
have a bypass - not even "just for testing".

Two records of every decision, on purpose, not one:
- The draft's own JSON file (data/drafts/<stem>.json) is updated with status
  and the approver's name/time - convenient for "what's the current state of
  this draft" queries.
- data/audit_log.jsonl gets an appended line for every decision, and nothing
  ever removes or rewrites a line in it. If someone edited a draft file
  directly to change its status, the audit log would still show the real
  history - the draft file alone isn't a trustworthy record on its own.

A decision, once made, is not editable through this tool. Re-running approve
or reject on an already-decided draft is refused, not silently overwritten -
if a decision needs correcting, that has to be a new, separately logged
action, not a rewrite of what happened.

Usage:
    python src/approve.py --list [--role devops] [--status pending]
    python src/approve.py --show devops-00-marcus-vance
    python src/approve.py --approve devops-00-marcus-vance --by "Ali Amjad"
    python src/approve.py --reject devops-01-oliver-davies --by "Ali Amjad" --reason "..."
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DRAFTS_DIR = ROOT / "data" / "drafts"
AUDIT_LOG_PATH = ROOT / "data" / "audit_log.jsonl"


def load_draft(stem: str) -> dict:
    path = DRAFTS_DIR / f"{stem}.json"
    if not path.exists():
        raise SystemExit(f"No draft found for '{stem}'.")
    return json.loads(path.read_text())


def save_draft(stem: str, draft: dict) -> None:
    (DRAFTS_DIR / f"{stem}.json").write_text(json.dumps(draft, indent=2), encoding="utf-8")


def append_audit_log(entry: dict) -> None:
    with AUDIT_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def cmd_list(args) -> None:
    drafts = []
    for path in sorted(DRAFTS_DIR.glob("*.json")):
        d = json.loads(path.read_text())
        if args.role and d["role"] != args.role:
            continue
        if args.status and d["status"] != args.status:
            continue
        drafts.append(d)

    if not drafts:
        print("no drafts match.")
        return
    print(f"{'stem':<35} {'rank':<10} {'status':<10} subject")
    for d in drafts:
        print(f"{d['stem']:<35} {d['rank']:<10} {d['status']:<10} {d['subject']}")


def cmd_show(args) -> None:
    d = load_draft(args.stem)
    print(json.dumps(d, indent=2))


def _decide(stem: str, new_status: str, by: str, reason: str | None) -> None:
    draft = load_draft(stem)
    if draft["status"] != "pending":
        raise SystemExit(
            f"'{stem}' is already {draft['status']} (by {draft.get('approved_by') or draft.get('rejected_by')} "
            f"at {draft.get('approved_at') or draft.get('rejected_at')}). Not overwriting a past decision."
        )

    now = datetime.now(timezone.utc).isoformat()
    draft["status"] = new_status
    if new_status == "approved":
        draft["approved_by"] = by
        draft["approved_at"] = now
    else:
        draft["rejected_by"] = by
        draft["rejected_at"] = now
        draft["rejection_reason"] = reason

    save_draft(stem, draft)
    append_audit_log({
        "stem": stem, "role": draft["role"], "action": new_status,
        "by": by, "at": now, "reason": reason,
    })
    print(f"{stem}: {new_status} by {by} at {now}")


def cmd_approve(args) -> None:
    _decide(args.stem, "approved", args.by, None)
    print("(nothing is actually sent by this tool - approval only changes status and logs the decision.)")


def cmd_reject(args) -> None:
    _decide(args.stem, "rejected", args.by, args.reason)


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list")
    p_list.add_argument("--role")
    p_list.add_argument("--status")
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser("show")
    p_show.add_argument("stem")
    p_show.set_defaults(func=cmd_show)

    p_approve = sub.add_parser("approve")
    p_approve.add_argument("stem")
    p_approve.add_argument("--by", required=True)
    p_approve.set_defaults(func=cmd_approve)

    p_reject = sub.add_parser("reject")
    p_reject.add_argument("stem")
    p_reject.add_argument("--by", required=True)
    p_reject.add_argument("--reason", required=True)
    p_reject.set_defaults(func=cmd_reject)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
