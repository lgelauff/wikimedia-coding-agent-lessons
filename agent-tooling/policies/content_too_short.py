#!/usr/bin/env python3
"""Policy: is fetched content suspiciously short (likely not the real resource)?

Agent-agnostic decision executable. The fact it judges is a block of fetched
content (read from stdin). A very short response usually means a redirect,
login wall, or error page rather than the expected resource.

  cat page.html | content_too_short.py            -> exit 0/1
  cat page.html | content_too_short.py --min 500   -> stricter threshold

Contract: exit 0 = looks fine, exit 1 = suspiciously short; on flag, a neutral
reason is printed to stdout. This is advisory — an adapter typically surfaces it
as a warning, not a hard block.
"""
import argparse
import os
import sys

DEFAULT_MIN = int(os.environ.get("CONTENT_MIN_CHARS", "300"))


def too_short(content: str, min_chars: int = DEFAULT_MIN) -> str | None:
    """Return a reason if content is below min_chars, else None."""
    n = len(content or "")
    if n < min_chars:
        return (
            f"Fetched content is very short ({n} chars, threshold {min_chars}) — "
            "likely a redirect, login wall, or error page rather than the expected "
            "resource. Treat as UNVERIFIED; verify another way (git remote, DNS, "
            "curl, ask the user) before relying on it."
        )
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--min", type=int, default=DEFAULT_MIN, help="minimum char count")
    a = ap.parse_args()
    reason = too_short(sys.stdin.read(), a.min)
    if reason:
        print(reason)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
