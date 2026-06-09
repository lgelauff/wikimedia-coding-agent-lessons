#!/usr/bin/env python3
"""Headless-Chromium probe template for the browser-verify skill.

Copy this per verification, fill the marked sections, run headless:
    python3 probe.py
Prereq: pip install playwright && playwright install chromium  (chromium only).

It auto-captures the signals that distinguish "looks fine" from "actually ran":
  - JS console errors  → a SyntaxError here means the page's <script> never executed
                          (this is how the dead-arguments-tab bug would surface)
  - uncaught page exceptions
  - failed network requests (4xx/5xx/aborted)

Each CHECK is one thing to verify (auto-derived risky path OR a user-supplied
item). Append checks; each records pass/fail + evidence. Exit 0 only if every
check passes AND there are no console/page errors.

Wait on LOCATORS or 'domcontentloaded' — never 'networkidle': some wiki-polis
pages hold a connection open and never go idle, which hangs networkidle waits.
"""
import sys
from playwright.sync_api import sync_playwright, expect

BASE_URL = "http://localhost:5000"   # ← from project config browser.base_url

console_errors, page_errors, failed = [], [], []
results = []  # (name, ok, evidence)


def check(name, fn):
    try:
        fn()
        results.append((name, True, ""))
    except Exception as e:                      # assertion or interaction failure
        results.append((name, False, str(e)[:300]))


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.on("console", lambda m: m.type == "error" and console_errors.append(m.text))
        page.on("pageerror", lambda e: page_errors.append(str(e)))
        page.on("requestfailed",
                lambda r: failed.append(f"{r.method} {r.url} :: {r.failure}"))

        # ── SETUP (login / navigate). domcontentloaded, not networkidle. ──
        page.goto(f"{BASE_URL}/", wait_until="domcontentloaded")
        # e.g. dev login: page.goto(f"{BASE_URL}/dev/login/dev-user-1", wait_until="domcontentloaded")

        # ── CHECKS: one per thing to verify (the bug claim + risky paths + user items) ──
        # check("arguments tab renders + script ran (no console error)",
        #       lambda: expect(page.get_by_role("button", name="Suggest different wording")).to_be_visible())
        # check("circle nav reachable by keyboard",
        #       lambda: (page.keyboard.press("Tab"), expect(page.locator(".arg-circle:focus")).to_be_visible()))
        # check("<user-supplied item here>", lambda: ...)

        page.screenshot(path="probe.png", full_page=True)
        browser.close()

    # console / page errors are hard failures — they mean JS didn't run as intended
    blocking = []
    if console_errors:
        blocking.append(f"{len(console_errors)} console error(s): {console_errors[:3]}")
    if page_errors:
        blocking.append(f"page exception(s): {page_errors[:3]}")
    if failed:
        print("WARN failed requests:", failed[:5], file=sys.stderr)

    print("\n=== browser-verify results ===")
    for name, ok, ev in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  — {ev}" if ev else ""))
    for b in blocking:
        print(f"  [FAIL] {b}")

    failures = [r for r in results if not r[1]] or blocking
    print("\nVERDICT:", "FAIL" if failures else "PASS", "(screenshot: probe.png)")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
