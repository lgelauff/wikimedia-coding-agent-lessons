#!/usr/bin/env python3
"""Guard: text that leaves this machine must not carry private identifiers.

This repo is public. Its rules for public text (review of 2026-10-17): no host
names or SSH aliases of private machines, no absolute home paths, no paths into
the private agent hub, no e-mail addresses, no tokens, no internal log ids, no
session ids. Until now they were checked by a hand-written grep before each push,
which is the kind of check that gets skipped.

What it checks, by default, is what a push ADDS: the added lines of the pushed
diff and the pushed commit messages. Existing text is not re-litigated on every
push; `--all` audits the whole tracked tree instead and reports that backlog.

Rules (each one has a test showing it fires):

  home-path     /Users/<name>/ or /home/<name>/ outside a URL, unless <name> is a
                placeholder (someone, you, user, x, <...>)
  agent-hub     ~/agent/... (the private notes/inbox hub)                 public-text: ok
  email         an address, unless the domain is a documentation or no-reply one
                (see ALLOWED_EMAIL_DOMAINS) or a public role address
  log-id        an internal log id such as E123 (flake8 codes inside `noqa`   public-text: ok
                comments are ignored)
  session-id    a desktop session id, local_<uuid>
  ipv4          an IPv4 address, unless loopback, unspecified or a documentation range
  token         a credential-shaped string (GitHub, Anthropic/OpenAI, AWS, Slack,
                Bearer). The match is masked in the report. detect-secrets at
                commit time stays the main secret scanner; this is a second net.
  denylist      a term from the LOCAL denylist: private host names, SSH aliases,
                project or participant names. The list lives outside the tracked
                tree (default: <git-common-dir>/info/public-text-denylist, or
                $PUBLIC_TEXT_DENYLIST), because a committed denylist would publish
                exactly the names it protects. One term per line, matched as a
                whole word, case-insensitive; `re:<regex>` for a pattern; `#` comments.

What it cannot check: threat-model details and other sensitive prose. Those still
need a reader.

A line containing `public-text: ok` is skipped (for test fixtures and documented
false positives). Use it sparingly; the reviewer sees it in the diff.

Contract: exit 0 = clean, 1 = findings, 2 = the scan could not complete (bad
range, git failure, unreadable input). 2 is "unverified", never "clean".

Usage:
  check_public_text.py --pre-push [--root DIR]   # reads git's pre-push stdin
  check_public_text.py --range BASE..HEAD        # added lines + commit messages
  check_public_text.py --all                     # audit every tracked file
  check_public_text.py FILE...                   # scan named files
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

ZERO_SHA = "0" * 40
SKIP_MARK = "public-text: ok"

PLACEHOLDER_USERS = {"someone", "you", "user", "username", "me", "x", "u", "example", "name"}

ALLOWED_EMAIL_DOMAINS = (
    "example.com", "example.org", "example.net", "example.invalid",
    "users.noreply.github.com",
)
ALLOWED_EMAILS = {
    "noreply@anthropic.com",          # commit attribution trailer
    "git@github.com",                 # SSH remote syntax, not an address
}
# Public role addresses of organisations (contact points they publish themselves).
ALLOWED_ROLE_EMAILS = {
    "security@wikimedia.org",
    "techpartnerships@wikimedia.org",
}

RULES: list[tuple[str, re.Pattern]] = [
    # Not preceded by a word char, dot or slash: keeps `…/presscorner/home/en` in a URL out.
    ("home-path", re.compile(r"(?<![\w./-])/(?:Users|home)/([A-Za-z0-9_.<>-]+)")),
    ("agent-hub", re.compile(r"~/agent(?:/|\b)")),  # public-text: ok
    ("email", re.compile(r"(?<![\w.%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")),
    ("log-id", re.compile(r"(?<![\w-])E\d{3}(?![\w-])")),
    ("session-id", re.compile(r"\blocal_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")),
    ("ipv4", re.compile(r"(?<![\d.])(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?![\d.])")),
    ("token", re.compile(
        r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|sk-ant-[A-Za-z0-9_-]{20,}"
        r"|sk-[A-Za-z0-9]{32,}|AKIA[0-9A-Z]{16}|xox[abposr]-[A-Za-z0-9-]{10,})"
        r"|Bearer\s+[A-Za-z0-9._~+/=-]{24,}")),
]

NOQA = re.compile(r"#\s*noqa\b[^#]*")
DOC_NETS = ("192.0.2.", "198.51.100.", "203.0.113.")


# ------------------------------------------------------------------ matching

def load_denylist(path: Path | None) -> list[re.Pattern]:
    if path is None or not path.is_file():
        return []
    pats = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("re:"):
            pats.append(re.compile(line[3:], re.IGNORECASE))
        else:
            pats.append(re.compile(r"(?<![\w-])" + re.escape(line) + r"(?![\w-])", re.IGNORECASE))
    return pats


def allowed(rule: str, m: re.Match) -> bool:
    text = m.group(0)
    if rule == "home-path":
        user = m.group(1)
        return user.lower() in PLACEHOLDER_USERS or user.startswith("<")
    if rule == "email":
        low = text.lower()
        if low in ALLOWED_EMAILS or low in ALLOWED_ROLE_EMAILS:
            return True
        return low.split("@", 1)[1].endswith(ALLOWED_EMAIL_DOMAINS)
    if rule == "ipv4":
        parts = [int(g) for g in m.groups()]
        if any(p > 255 for p in parts):
            return True                                  # a version string, not an address
        return text in ("127.0.0.1", "0.0.0.0") or text.startswith(DOC_NETS)
    return False


def mask(rule: str, text: str) -> str:
    return text[:6] + "…(masked)" if rule == "token" else text


def scan_line(line: str, deny: list[re.Pattern]) -> list[tuple[str, str]]:
    if SKIP_MARK in line:
        return []
    hits = []
    for rule, pat in RULES:
        target = NOQA.sub("", line) if rule == "log-id" else line
        for m in pat.finditer(target):
            if not allowed(rule, m):
                hits.append((rule, mask(rule, m.group(0))))
    for pat in deny:
        for m in pat.finditer(line):
            hits.append(("denylist", m.group(0)))
    return hits


# ------------------------------------------------------------------ inputs

def git(root: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout


HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def added_lines(root: Path, base: str, head: str):
    """Yield (path, lineno, text) for every line the diff base..head adds."""
    out = git(root, "diff", "--unified=0", "--no-color", "--no-renames", "--no-ext-diff", base, head)
    path, lineno = None, 0
    for line in out.splitlines():
        if line.startswith("+++ "):
            name = line[4:]
            path = None if name == "/dev/null" else (name[2:] if name.startswith("b/") else name)
            continue
        m = HUNK.match(line)
        if m:
            lineno = int(m.group(1))
            continue
        if path and line.startswith("+"):
            yield path, lineno, line[1:]
            lineno += 1


def commit_messages(root: Path, base: str, head: str):
    out = git(root, "log", "--format=%H%x00%B%x01", f"{base}..{head}")
    for rec in out.split("\x01"):
        rec = rec.strip("\n")
        if not rec:
            continue
        sha, _, body = rec.partition("\x00")
        for i, line in enumerate(body.splitlines(), 1):
            yield f"commit {sha[:10]} message", i, line


def push_ranges(root: Path, stdin_text: str):
    """Turn git's pre-push stdin into (base, head) ranges."""
    for line in stdin_text.splitlines():
        parts = line.split()
        if len(parts) != 4:
            continue
        _lref, lsha, _rref, rsha = parts
        if lsha == ZERO_SHA:
            continue                                     # deleting a ref publishes nothing
        if rsha == ZERO_SHA:
            # New remote ref: compare with what the remote's main already has.
            base = None
            for cand in ("origin/main", "origin/HEAD"):
                try:
                    base = git(root, "merge-base", lsha, cand).strip()
                    break
                except RuntimeError:
                    continue
            if not base:
                raise RuntimeError(f"no merge-base for new ref {lsha[:10]}; fetch origin first")
            yield base, lsha
        else:
            yield rsha, lsha


def default_denylist(root: Path) -> Path | None:
    env = os.environ.get("PUBLIC_TEXT_DENYLIST")
    if env:
        return Path(env)
    try:
        common = git(root, "rev-parse", "--git-common-dir").strip()
    except RuntimeError:
        return None
    p = Path(common)
    if not p.is_absolute():
        p = root / p
    return p / "info" / "public-text-denylist"


# ------------------------------------------------------------------ main

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--pre-push", action="store_true", help="read git pre-push refs from stdin")
    mode.add_argument("--range", help="BASE..HEAD: added lines and commit messages")
    mode.add_argument("--all", action="store_true", help="audit every tracked text file")
    ap.add_argument("files", nargs="*", help="files to scan")
    ap.add_argument("--root", default=".", help="repository root (default: cwd)")
    ap.add_argument("--denylist", help="local denylist file (overrides the default location)")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    deny_path = Path(args.denylist) if args.denylist else default_denylist(root)
    deny = load_denylist(deny_path)
    if not deny:
        print(f"check_public_text: no local denylist at {deny_path}; private host names are NOT "
              f"checked. Create it (one term per line) to enable the denylist rule.", file=sys.stderr)

    findings: list[str] = []

    def check(where: str, lineno: int, text: str) -> None:
        for rule, hit in scan_line(text, deny):
            findings.append(f"{where}:{lineno}: [{rule}] {hit}")

    try:
        if args.pre_push or args.range:
            if args.range:
                if ".." not in args.range:
                    raise RuntimeError("--range needs BASE..HEAD")
                base, head = args.range.split("..", 1)
                ranges = [(base, head)]
            else:
                ranges = list(push_ranges(root, sys.stdin.read()))
            for base, head in ranges:
                for path, n, text in added_lines(root, base, head):
                    check(path, n, text)
                for where, n, text in commit_messages(root, base, head):
                    check(where, n, text)
            scope = f"{len(ranges)} pushed range(s)"
        else:
            if args.all:
                paths = [root / p for p in git(root, "ls-files", "-z").split("\0") if p]
            else:
                paths = [Path(p) for p in args.files]
                if not paths:
                    ap.error("give --pre-push, --range, --all, or files")
            for p in paths:
                try:
                    data = p.read_bytes()
                except OSError as e:
                    raise RuntimeError(f"cannot read {p}: {e}") from e
                if b"\0" in data[:8192]:
                    continue                             # binary
                text = data.decode("utf-8", errors="replace")
                shown = os.path.relpath(p, root) if args.all else str(p)
                for n, line in enumerate(text.splitlines(), 1):
                    check(shown, n, line)
            scope = f"{len(paths)} file(s)"
    except RuntimeError as e:
        print(f"check_public_text: could not complete: {e}", file=sys.stderr)
        return 2

    if findings:
        print("\n".join(findings))
        print(f"check_public_text: {len(findings)} finding(s) in {scope}. Remove them, or mark a "
              f"reviewed false positive with '{SKIP_MARK}' on the line.", file=sys.stderr)
        return 1
    print(f"check_public_text: clean ({scope})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
