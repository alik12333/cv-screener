"""
Detect candidates who applied to more than one role. This is DEDUPE (stage 7,
see docs/ARCHITECTURE.md): cascades from cheap to expensive - exact email match,
then fuzzy name + phone, then embedding similarity on CV content - each stage
only earning its cost because the one before it can be fooled.

Why the cascade doesn't stop at fuzzy name+phone here: checked before writing
any matching logic, and this dataset's synthetic names and phone numbers
collide heavily between genuinely UNRELATED candidates - "Oliver Vance" is 24
different fake people, and +44 7700 900451 alone appears across ~15 of them
(the generator has limited name diversity, and UK phone numbers cluster in the
Ofcom-reserved fictional block 07700 900xxx). That's not just a synthetic-data
quirk to shrug off - real recruitment databases really do have more than one
"John Smith". It's exactly why the architecture treats embeddings as a
required follow-up check rather than optional.

Input is data/extracted/*.json (EXTRACT's output), never ground truth. Ground
truth is read only inside resolve_true_duplicate_pairs(), purely to measure
precision/recall against the known answer - never fed to the matcher itself.

Usage:
    python src/dedupe.py
"""

import itertools
import json
import math
import os
import re
import time
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from google import genai

from blind import blind_profile, profile_to_text

load_dotenv()

EMBED_MODEL = "gemini-embedding-001"
MIN_SECONDS_BETWEEN_CALLS = 1.0   # embedding calls are lighter-weight than generation/scoring calls
MAX_RETRIES = 4

ROOT = Path(__file__).resolve().parent.parent
EXTRACTED_DIR = ROOT / "data" / "extracted"
TRUTH_DIR = ROOT / "data" / "ground_truth"
RESULTS_DIR = ROOT / "evals" / "results"

THRESHOLD_SWEEP = [0.80, 0.85, 0.90, 0.93, 0.95, 0.97, 0.99, 0.995, 0.999]
CONFIRMED_DUPLICATE_THRESHOLD = 0.999   # see docs/LEARNING.md Day 4: true duplicates score exactly
                                         # 1.0000 (byte-identical content), the closest false positive
                                         # tops out at 0.9958 - a clean, wide gap on this dataset.


# ---------------------------------------------------------------------------
# Stage 1 + 2: cheap, pure code, no LLM. Instant even at this scale.
# ---------------------------------------------------------------------------

def normalise_phone(phone: str) -> str:
    return re.sub(r"\D", "", phone)


def normalise_name(name: str) -> str:
    return " ".join(name.strip().lower().split())


def names_match(a: str, b: str) -> bool:
    """Exact match, or one is an initialised short form of the other
    (e.g. 'O. Vance' vs 'Oliver Vance') - the exact pattern generate_cvs.py
    uses to plant duplicates.
    """
    na, nb = normalise_name(a), normalise_name(b)
    if na == nb:
        return True
    a_parts, b_parts = na.split(), nb.split()
    if not a_parts or not b_parts or a_parts[-1] != b_parts[-1]:
        return False
    return a_parts[0].rstrip(".")[0] == b_parts[0].rstrip(".")[0]


def find_candidate_pairs(candidates: dict) -> dict:
    """Returns {(stem_a, stem_b): {reasons}} for every pair flagged by the
    cheap checks. No LLM calls - this is instant regardless of dataset size.
    """
    flagged = {}
    stems = sorted(candidates)
    for stem_a, stem_b in itertools.combinations(stems, 2):
        a, b = candidates[stem_a], candidates[stem_b]
        reasons = set()
        if a["email"].strip().lower() == b["email"].strip().lower():
            reasons.add("exact_email")
        if names_match(a["full_name"], b["full_name"]) and normalise_phone(a["phone"]) == normalise_phone(b["phone"]):
            reasons.add("fuzzy_name+phone")
        if reasons:
            flagged[(stem_a, stem_b)] = reasons
    return flagged


# ---------------------------------------------------------------------------
# Stage 3: embedding similarity on CV content, used to confirm or reject
# what stage 1+2 flagged (not to search the whole dataset - only the pairs
# already flagged need this extra, more expensive check).
# ---------------------------------------------------------------------------

_last_call_at = 0.0


def embed_text(client: genai.Client, text: str) -> list:
    global _last_call_at
    for attempt in range(MAX_RETRIES):
        wait = MIN_SECONDS_BETWEEN_CALLS - (time.time() - _last_call_at)
        if wait > 0:
            time.sleep(wait)
        try:
            _last_call_at = time.time()
            response = client.models.embed_content(model=EMBED_MODEL, contents=text)
            return response.embeddings[0].values
        except Exception as exc:                      # noqa: BLE001
            backoff = 2 ** attempt * 5
            print(f"    embed attempt {attempt + 1} failed ({type(exc).__name__}: {exc}), "
                  f"retrying in {backoff}s")
            time.sleep(backoff)
    raise RuntimeError(f"gave up after {MAX_RETRIES} attempts")


def cosine_similarity(u: list, v: list) -> float:
    dot = sum(x * y for x, y in zip(u, v))
    norm_u = math.sqrt(sum(x * x for x in u))
    norm_v = math.sqrt(sum(y * y for y in v))
    return dot / (norm_u * norm_v) if norm_u and norm_v else 0.0


# ---------------------------------------------------------------------------
# Evaluation only - never used by the matcher above.
# ---------------------------------------------------------------------------

def resolve_true_duplicate_pairs() -> set:
    """Ground truth's is_duplicate_of only stores the original's full_name,
    which (as this whole file exists to demonstrate) isn't unique. Resolve
    each planted duplicate to its exact source by matching on content that's
    byte-for-byte identical between a duplicate and its original (generate_cvs.py
    deep-copies the whole profile and only overwrites full_name and email).
    """
    all_truth = {p.stem: json.loads(p.read_text()) for p in TRUTH_DIR.glob("*.json")}
    pairs = set()
    for stem, data in all_truth.items():
        if not data["is_duplicate_of"]:
            continue
        profile = data["profile"]
        matches = [
            other for other, other_data in all_truth.items()
            if other != stem
            and other_data["profile"]["full_name"] == data["is_duplicate_of"]
            and other_data["profile"]["personal_statement"] == profile["personal_statement"]
        ]
        if len(matches) == 1:
            pairs.add(tuple(sorted((stem, matches[0]))))
        else:
            print(f"WARNING: {stem} resolved to {len(matches)} candidates, expected 1: {matches}")
    return pairs


def main() -> None:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit("GEMINI_API_KEY is not set. Copy .env.example to .env.")
    client = genai.Client(api_key=api_key)

    candidates = {p.stem: json.loads(p.read_text()) for p in sorted(EXTRACTED_DIR.glob("*.json"))}
    if not candidates:
        raise SystemExit("No extracted profiles found. Run src/extract.py first.")
    print(f"loaded {len(candidates)} candidates")

    total_pairs = len(candidates) * (len(candidates) - 1) // 2
    flagged = find_candidate_pairs(candidates)
    print(f"stage 1+2 (exact email / fuzzy name+phone) flagged {len(flagged)}/{total_pairs} possible pairs")

    true_pairs = resolve_true_duplicate_pairs()
    print(f"{len(true_pairs)} true duplicate pairs, from ground truth (eval only, not used for matching)")

    print("\nembedding all candidates (stage 3 input)...")
    embeddings = {}
    for i, stem in enumerate(sorted(candidates), start=1):
        text = profile_to_text(blind_profile(candidates[stem]))
        embeddings[stem] = embed_text(client, text)
        if i % 15 == 0 or i == len(candidates):
            print(f"  {i}/{len(candidates)}")

    scored = []
    for (a, b), reasons in flagged.items():
        sim = cosine_similarity(embeddings[a], embeddings[b])
        is_true = (a, b) in true_pairs
        scored.append({"a": a, "b": b, "reasons": sorted(reasons), "similarity": sim, "is_true_duplicate": is_true})
    scored.sort(key=lambda r: -r["similarity"])

    lines = [f"# Dedupe eval — {date.today().isoformat()}", ""]
    lines.append(f"Candidates: {len(candidates)} | Possible pairs: {total_pairs} | "
                 f"Flagged by stage 1+2: {len(flagged)} | True duplicate pairs: {len(true_pairs)}")
    lines.append("")

    lines.append("## Stage 1+2 alone (exact email OR fuzzy name+phone), no content check")
    stage12_tp = sum(1 for r in scored if r["is_true_duplicate"])
    stage12_fp = len(scored) - stage12_tp
    lines.append(f"- {len(scored)} pairs flagged: {stage12_tp} true duplicates, {stage12_fp} false positives "
                 f"(same-named strangers with colliding phone numbers).")
    lines.append("- This confirms fuzzy name+phone matching alone is NOT safe on this data: it's exactly the "
                 "false-positive flood predicted before writing the matcher.")
    lines.append("")

    lines.append("## All flagged pairs, sorted by content-similarity score (highest first)")
    lines.append("")
    lines.append("| similarity | true duplicate? | reasons | pair |")
    lines.append("|---|---|---|---|")
    for r in scored:
        tag = "YES" if r["is_true_duplicate"] else "no (collision)"
        lines.append(f"| {r['similarity']:.4f} | {tag} | {', '.join(r['reasons'])} | {r['a']} <-> {r['b']} |")
    lines.append("")

    lines.append("## Threshold sweep (stage 3 confirmation: keep a flagged pair only if similarity >= threshold)")
    lines.append("")
    lines.append("| threshold | true positives | false positives | false negatives | precision | recall |")
    lines.append("|---|---|---|---|---|---|")
    for t in THRESHOLD_SWEEP:
        kept = [r for r in scored if r["similarity"] >= t]
        tp = sum(1 for r in kept if r["is_true_duplicate"])
        fp = len(kept) - tp
        fn = len(true_pairs) - tp
        precision = tp / (tp + fp) if (tp + fp) else float("nan")
        recall = tp / (tp + fn) if (tp + fn) else float("nan")
        lines.append(f"| {t} | {tp} | {fp} | {fn} | {precision:.3f} | {recall:.3f} |")
    lines.append("")

    lines.append(f"## Final confirmed duplicates at threshold {CONFIRMED_DUPLICATE_THRESHOLD} "
                 f"(this is the actual DEDUPE stage output)")
    confirmed = [r for r in scored if r["similarity"] >= CONFIRMED_DUPLICATE_THRESHOLD]
    tp = sum(1 for r in confirmed if r["is_true_duplicate"])
    fp = len(confirmed) - tp
    fn = len(true_pairs) - tp
    lines.append(f"- {len(confirmed)} pairs confirmed: {tp} true positives, {fp} false positives, "
                 f"{fn} missed true duplicates (false negatives).")
    for r in confirmed:
        lines.append(f"  - {r['a']} <-> {r['b']} (similarity={r['similarity']:.4f})")
    lines.append("")

    report = "\n".join(lines)
    print("\n" + report)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / f"{date.today().isoformat()}-dedupe.md"
    out_path.write_text(report, encoding="utf-8")
    print(f"\nsaved to {out_path}")


if __name__ == "__main__":
    main()
