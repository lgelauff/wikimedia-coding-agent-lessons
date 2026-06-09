#!/usr/bin/env python3
"""Scope a PR/branch diff into review flags, driven by a per-project config.

Agent-agnostic: takes a project config (glob/pattern rules) + a diff, and emits
the changed files plus boolean scope flags as JSON. A PR-quality-gate adapter
(e.g. a Claude skill) calls this once instead of running a dozen ad-hoc
git/gh/grep pipelines — deterministic, testable, one allowlist entry.

Config (JSON), all keys optional except `scope`:
  {
    "base_ref": "origin/main",
    "scope": { "FLAG": ["glob", ...], ... },   # path globs per flag
    "sensitive_patterns": ["oauth", "csrf", ...] # substrings matched in ADDED diff lines
  }

A flag is set if any changed file matches any of its globs. DOCS_ONLY is derived
(every changed file ends in .md). SENSITIVE is set if any added (`+`) diff line
contains a sensitive pattern (case-insensitive). Globs use fnmatch — `*` may cross
`/`, so matching is intentionally permissive (over-scoping is safer than missing).

Usage:
  scope.py --config .claude/pr-check.json --pr 174
  scope.py --config .claude/pr-check.json --base origin/main
"""
import argparse
import fnmatch
import json
import subprocess
import sys


def classify(files, added_lines, config):
    """Pure core: (files, added_lines, config) -> {files, flags}. Used by tests."""
    scope = config.get("scope", {})
    flags = {}
    for flag, globs in scope.items():
        flags[flag] = any(
            fnmatch.fnmatch(f, g) for f in files for g in globs
        )
    flags["DOCS_ONLY"] = bool(files) and all(f.endswith(".md") for f in files)
    pats = [p.lower() for p in config.get("sensitive_patterns", [])]
    blob = "\n".join(added_lines).lower()
    flags["SENSITIVE"] = any(p in blob for p in pats)
    return {"files": files, "flags": flags}


def _run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout


def _gather(args):
    if args.pr:
        files = _run(["gh", "pr", "diff", str(args.pr), "--name-only"])
        diff = _run(["gh", "pr", "diff", str(args.pr)])
    else:
        base = args.base
        merge_base = _run(["git", "merge-base", base, "HEAD"]).strip()
        rng = f"{merge_base}...HEAD"
        files = _run(["git", "diff", "--name-only", rng])
        diff = _run(["git", "diff", rng])
    file_list = [f for f in files.splitlines() if f.strip()]
    added = [ln[1:] for ln in diff.splitlines()
             if ln.startswith("+") and not ln.startswith("+++")]
    return file_list, added


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--pr", type=int)
    g.add_argument("--base")
    args = ap.parse_args()

    with open(args.config) as fh:
        config = json.load(fh)
    if args.base is None and not args.pr:
        args.base = config.get("base_ref", "origin/main")

    try:
        files, added = _gather(args)
    except subprocess.CalledProcessError as e:
        print(f"scope: git/gh failed: {e.stderr.strip()}", file=sys.stderr)
        sys.exit(1)

    print(json.dumps(classify(files, added, config), indent=2))


if __name__ == "__main__":
    main()
