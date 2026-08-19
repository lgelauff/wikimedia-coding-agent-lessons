#!/usr/bin/env python3
"""check_version_bump.py — fail when plugin content changed without a version bump.

Why this exists: a plugin's `version` PINS consumers. Claude Code only offers an
update when the resolved version string changes, and `plugin.json` silently wins
over any `version` in the marketplace entry. So content that lands without a bump
reaches nobody — silently, with no error anywhere.

That is not hypothetical. `agent-tooling` sat at 0.9.1 while 21 commits landed on
top, including two whole new skills; sessions kept loading the 0.9.1 snapshot and
the new skills were simply absent from the roster.

Usage:
    python3 check_version_bump.py                     # compare against origin/main
    python3 check_version_bump.py --base HEAD~1
    python3 check_version_bump.py --plugin-dir agent-tooling

Exit codes: 0 = no bump needed, or bump present; 1 = content changed, version did
not; 2 = usage/git error.
"""

import argparse
import json
import subprocess
import sys


def git(*args):
    r = subprocess.run(["git", *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout


def version_at(ref, manifest):
    """Version string recorded at `ref`, or None if the file did not exist."""
    try:
        return json.loads(git("show", f"{ref}:{manifest}")).get("version")
    except RuntimeError:
        return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="origin/main",
                    help="ref to compare against (default: origin/main)")
    ap.add_argument("--plugin-dir", default="agent-tooling",
                    help="plugin directory to guard (default: agent-tooling)")
    args = ap.parse_args(argv)

    manifest = f"{args.plugin_dir}/.claude-plugin/plugin.json"
    try:
        changed = [p for p in git("diff", "--name-only", args.base, "HEAD").split()
                   if p.startswith(f"{args.plugin_dir}/")]
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    if not changed:
        return 0

    before, after = version_at(args.base, manifest), version_at("HEAD", manifest)
    if before != after:
        print(f"OK: {args.plugin_dir} {before} -> {after} ({len(changed)} files changed)")
        return 0

    print(f"BLOCKED: {len(changed)} file(s) changed under {args.plugin_dir}/ but "
          f"{manifest} is still {after!r}.", file=sys.stderr)
    print("Consumers pin to this string — without a bump these changes reach nobody.",
          file=sys.stderr)
    for p in changed[:10]:
        print(f"  {p}", file=sys.stderr)
    if len(changed) > 10:
        print(f"  … and {len(changed) - 10} more", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
