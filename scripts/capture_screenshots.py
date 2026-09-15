"""
One-off documentation tool: drives the live dashboard with Playwright (using
the system's installed Chrome, no extra browser download) to capture the
real screenshots and GIF frames listed in docs/SCREENSHOTS.md.

Not part of the pipeline - dev-only, run manually against a live
`uvicorn api:app` + populated Supabase queue. Deletable after the shots
exist; not referenced by any other script.

Usage (from repo root, dashboard already running on :8000):
    .venv/Scripts/python scripts/capture_screenshots.py
"""

from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / "docs" / "screenshots"
GIF_FRAMES = ROOT / "docs" / "gifs" / "_frames"
SHOTS.mkdir(parents=True, exist_ok=True)
GIF_FRAMES.mkdir(parents=True, exist_ok=True)

BASE = "http://localhost:8000"
REVIEWER = "Ali Amjad"

STRONG_STEM = "devops-04-elliot-marsh"   # 6/7 criteria met, full evidence trail
REJECT_STEM = "devops-01-alex-taylor"    # fails the 3+ years must-have, clean reject case
REJECT_REASON = "Under 3 years DevOps/SRE experience (2 years self-reported) - below the must-have threshold for this role."


def set_reviewer(page):
    page.fill("#reviewer-name", REVIEWER)


def select_candidate(page, stem):
    page.click(f'.queue-row[data-stem="{stem}"]')
    page.wait_for_selector(".criterion")
    page.wait_for_timeout(200)


def main():
    frame_n = [0]

    def shot_frame(page):
        frame_n[0] += 1
        page.screenshot(path=str(GIF_FRAMES / f"{frame_n[0]:02d}.png"))

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1360, "height": 900}, device_scale_factor=1)
        page.goto(BASE)
        page.wait_for_selector(".queue-row")
        set_reviewer(page)

        # ---- 01: queue, filtered to devops, mixed ranks ----
        page.select_option("#f-role", "devops")
        page.wait_for_timeout(300)
        page.screenshot(path=str(SHOTS / "01-queue.png"))
        shot_frame(page)

        # ---- open the strong candidate ----
        select_candidate(page, STRONG_STEM)
        shot_frame(page)

        # ---- 03: gate summary + excluded must-have (top of detail pane) ----
        page.screenshot(path=str(SHOTS / "03-gate.png"))

        # ---- 02: evidence criteria, scrolled down ----
        page.eval_on_selector("#detail-pane", "el => el.scrollTo(0, 420)")
        page.wait_for_timeout(150)
        page.screenshot(path=str(SHOTS / "02-evidence.png"))
        shot_frame(page)
        page.eval_on_selector("#detail-pane", "el => el.scrollTo(0, 650)")
        page.wait_for_timeout(150)
        shot_frame(page)

        # ---- 04: draft email + approve/reject box ----
        page.eval_on_selector("#detail-pane", "el => el.scrollTo(0, el.scrollHeight)")
        page.wait_for_timeout(150)
        page.screenshot(path=str(SHOTS / "04-approve.png"))
        shot_frame(page)

        browser.close()

    print("Done. Screenshots in", SHOTS, "| GIF frames in", GIF_FRAMES)


if __name__ == "__main__":
    main()
