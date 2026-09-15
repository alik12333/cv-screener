"""
Second half of scripts/capture_screenshots.py, split out deliberately:
this part makes REAL, permanent approve/reject decisions against the live
Supabase queue (the app refuses to ever re-decide a draft, by design - see
CLAUDE.md rule 2), so it only runs after an explicit human go-ahead, never
automatically alongside the read-only screenshot capture.

Usage (from repo root, dashboard already running on :8000):
    .venv/Scripts/python scripts/capture_decisions.py
"""

from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / "docs" / "screenshots"
GIF_FRAMES = ROOT / "docs" / "gifs" / "_frames"

BASE = "http://localhost:8000"
REVIEWER = "Ali Amjad"
STRONG_STEM = "devops-04-elliot-marsh"
REJECT_STEM = "devops-01-alex-taylor"
REJECT_REASON = "Under 3 years DevOps/SRE experience (2 years self-reported) - below the must-have threshold for this role."


def select_candidate(page, stem):
    page.click(f'.queue-row[data-stem="{stem}"]')
    page.wait_for_selector(".criterion")
    page.wait_for_timeout(200)


def main():
    frame_n = [len(list(GIF_FRAMES.glob("*.png")))]

    def shot_frame(page):
        frame_n[0] += 1
        page.screenshot(path=str(GIF_FRAMES / f"{frame_n[0]:02d}.png"))

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1360, "height": 900})
        page.goto(BASE)
        page.wait_for_selector(".queue-row")
        page.fill("#reviewer-name", REVIEWER)
        page.select_option("#f-role", "devops")
        page.wait_for_timeout(300)

        select_candidate(page, STRONG_STEM)
        page.eval_on_selector("#detail-pane", "el => el.scrollTo(0, el.scrollHeight)")
        page.wait_for_timeout(150)
        page.click("button.btn-approve")
        page.wait_for_selector(".decision-notice.approved")
        page.wait_for_timeout(200)
        shot_frame(page)
        print(f"Approved {STRONG_STEM}")

        select_candidate(page, REJECT_STEM)
        page.eval_on_selector("#detail-pane", "el => el.scrollTo(0, el.scrollHeight)")
        page.fill(".decide-box textarea", REJECT_REASON)
        page.click("button.btn-reject")
        page.wait_for_selector(".decision-notice.rejected")
        page.wait_for_timeout(200)
        print(f"Rejected {REJECT_STEM}")

        page.click("#tab-audit")
        page.wait_for_selector("table.audit td")
        page.wait_for_timeout(200)
        page.screenshot(path=str(SHOTS / "05-audit-log.png"))
        shot_frame(page)

        browser.close()

    print("Done.")


if __name__ == "__main__":
    main()
