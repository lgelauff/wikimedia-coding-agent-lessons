#!/usr/bin/env python3
"""capture.py — headless screenshot helper (no computer takeover).

A small, parameterized building block other skills call to grab a PNG of an app
screen or a bug, headlessly via Playwright/Chromium. Extracted from the
browser-verify probe template so the shot logic lives in ONE reusable place.

It does deliberately little, so it composes:
  - it does NOT manage the stack — point it at an already-serving base_url
    (bring the app up however the project does, e.g. the local-e2e skill);
  - it does NOT assert pass/fail — it's evidence, not verification
    (browser-verify keeps the assertions and calls this for the image);
  - it does NOT post anywhere — post_pr_screenshots.py consumes the PNG.

Alongside every PNG it writes a sidecar `<out>.json` with the console errors,
final URL, viewport, and a sha256 — so a "screenshot of a bug" also carries the
JS-error evidence that is often the bug itself.

Usage:
    capture.py --url /conversation/123 --out bug.png
    capture.py --url / --login dev-user-1 --viewport 390x844 --dark
    capture.py --url /results --wait ".results-table" --clip ".arg-circle"
    capture.py --url /flow --steps steps.json     # reach a state first

Reads base_url (in order): --base-url, else --config JSON's browser.base_url,
else $CAPTURE_BASE_URL, else http://localhost:5000.

Importable: `from capture import capture` returns the saved Path.

Prereq: pip install playwright && playwright install chromium
"""
import argparse
import hashlib
import json
import pathlib
import sys
import os
import time

DEFAULT_BASE = "http://localhost:5000"
# One dedicated, predictable home for all screenshots, so a single permission
# rule covers them. Override with $CAPTURE_DIR (e.g. an in-repo .screenshots/).
CAPTURE_DIR = os.environ.get("CAPTURE_DIR", "/tmp/claude-screenshots")


def _default_out() -> str:
    return os.path.join(CAPTURE_DIR, "capture.png")


def _resolve_base(base_url: str | None, config: str | None) -> str:
    if base_url:
        return base_url.rstrip("/")
    if config:
        try:
            d = json.loads(pathlib.Path(config).read_text(encoding="utf-8"))
            b = d.get("browser", {}).get("base_url")
            if b:
                return b.rstrip("/")
        except (OSError, json.JSONDecodeError):
            pass
    return os.environ.get("CAPTURE_BASE_URL", DEFAULT_BASE).rstrip("/")


def _apply_step(page, step: dict) -> None:
    """Tiny step DSL to reach a state: {action: click|fill|press|wait|goto, ...}."""
    action = step.get("action")
    if action == "click":
        page.click(step["selector"])
    elif action == "fill":
        page.fill(step["selector"], step.get("value", ""))
    elif action == "press":
        page.keyboard.press(step["key"])
    elif action == "wait":
        page.locator(step["selector"]).first.wait_for(state=step.get("state", "visible"))
    elif action == "goto":
        page.goto(step["url"], wait_until="domcontentloaded")
    else:
        raise ValueError(f"unknown step action: {action!r}")


def capture(
    url: str,
    out: str | pathlib.Path | None = None,
    *,
    base_url: str | None = None,
    config: str | None = None,
    login: str | None = None,
    viewport: tuple[int, int] | None = None,
    clip: str | None = None,
    wait: str | None = None,
    dark: bool = False,
    steps: list[dict] | None = None,
    timeout_ms: int = 30000,
) -> pathlib.Path:
    """Render `url` headlessly and save a PNG + sidecar. Returns the PNG Path."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit("playwright not installed: pip install playwright && playwright install chromium")
    out = _default_out() if out is None else out
    base = _resolve_base(base_url, config)
    full_url = url if url.startswith("http") else f"{base}{url if url.startswith('/') else '/' + url}"
    out = pathlib.Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)

    console_errors: list[str] = []
    page_errors: list[str] = []
    failed: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx_kwargs: dict = {}
        if viewport:
            ctx_kwargs["viewport"] = {"width": viewport[0], "height": viewport[1]}
        if dark:
            ctx_kwargs["color_scheme"] = "dark"
        context = browser.new_context(**ctx_kwargs)
        page = context.new_page()
        page.set_default_timeout(timeout_ms)
        page.on("console", lambda m: m.type == "error" and console_errors.append(m.text))
        page.on("pageerror", lambda e: page_errors.append(str(e)))
        page.on("requestfailed",
                lambda r: failed.append(f"{r.method} {r.url} :: {r.failure}"))

        # domcontentloaded, never networkidle (some pages never go idle).
        if login:
            page.goto(f"{base}/dev/login/{login}", wait_until="domcontentloaded")
        page.goto(full_url, wait_until="domcontentloaded")
        for step in (steps or []):
            _apply_step(page, step)
        if wait:
            page.locator(wait).first.wait_for(state="visible")

        if clip:
            page.locator(clip).first.screenshot(path=str(out))
        else:
            page.screenshot(path=str(out), full_page=True)

        final_url = page.url
        context.close()
        browser.close()

    data = out.read_bytes()
    sidecar = out.with_suffix(out.suffix + ".json")
    sidecar.write_text(json.dumps({
        "requested_url": full_url,
        "final_url": final_url,
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "viewport": {"width": viewport[0], "height": viewport[1]} if viewport else "default",
        "dark": dark,
        "clip": clip,
        "console_errors": console_errors,
        "page_errors": page_errors,
        "failed_requests": failed,
        "png_sha256": hashlib.sha256(data).hexdigest(),
        "png_bytes": len(data),
    }, indent=2))
    return out


def _parse_viewport(s: str | None) -> tuple[int, int] | None:
    if not s:
        return None
    w, _, h = s.lower().partition("x")
    return int(w), int(h)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", required=True, help="route (joined to base_url) or full http(s) URL")
    ap.add_argument("--out", default=_default_out(),
                    help=f"output PNG path (default: {CAPTURE_DIR}/, set $CAPTURE_DIR to change)")
    ap.add_argument("--base-url", help="override base url")
    ap.add_argument("--config", help="path to pr-check.json to read browser.base_url from")
    ap.add_argument("--login", metavar="DEV_USER", help="dev-login id, e.g. dev-user-1")
    ap.add_argument("--viewport", help="WxH, e.g. 390x844")
    ap.add_argument("--clip", metavar="SELECTOR", help="screenshot just this element")
    ap.add_argument("--wait", metavar="SELECTOR", help="wait for this locator before shooting")
    ap.add_argument("--dark", action="store_true", help="emulate dark mode")
    ap.add_argument("--steps", metavar="JSON", help="path to a JSON list of step dicts")
    a = ap.parse_args()

    try:
        steps = json.loads(pathlib.Path(a.steps).read_text(encoding="utf-8")) if a.steps else None
        out = capture(
            a.url, a.out, base_url=a.base_url, config=a.config, login=a.login,
            viewport=_parse_viewport(a.viewport), clip=a.clip, wait=a.wait,
            dark=a.dark, steps=steps,
        )
    except Exception as e:  # bad --steps/--viewport, or render/navigation failure
        print(f"capture failed: {e}", file=sys.stderr)
        return 1
    print(out)                       # path on stdout, like fetch.py — callers capture this
    print(out.with_suffix(out.suffix + ".json"), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
