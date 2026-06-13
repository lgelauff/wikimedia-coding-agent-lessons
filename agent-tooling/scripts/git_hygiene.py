#!/usr/bin/env python3
"""git_hygiene.py — flag a repo's unsaved/at-risk work.

Deterministic scan (no LLM) of a git repo for work that exists only locally and
could be lost: uncommitted changes, untracked files, stashes, unpushed commits,
and linked worktrees that are themselves dirty. Reusable as a Claude Code
SessionStart hook (warn on entering a repo) or a daily launchd job (scan many).

  git_hygiene.py                 # scan cwd's repo, print report, exit 1 if dirty
  git_hygiene.py --repo PATH
  git_hygiene.py --root ~/Documents/GitHub   # scan every child repo
  git_hygiene.py --json
"""
import argparse
import json
import os
import pathlib
import subprocess
import sys
import time


def _git(repo: str, *args: str, timeout: float = 5.0) -> str:
    # --no-optional-locks: never take index.lock (read-only safety on a busy repo).
    # timeout: this runs on the SessionStart critical path — a hung cred helper,
    # NFS worktree, or stale lock must not block the session. A hang reads as "".
    try:
        r = subprocess.run(["git", "--no-optional-locks", "-C", repo, *args],
                           capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError):
        return ""
    return r.stdout if r.returncode == 0 else ""


def _classify_porcelain(text: str) -> tuple[int, int]:
    """Return (uncommitted_tracked, untracked) from `git status --porcelain`."""
    tracked = untracked = 0
    for ln in text.splitlines():
        if not ln.strip():
            continue
        if ln.startswith("??"):
            untracked += 1
        else:
            tracked += 1
    return tracked, untracked


def _count_lines(text: str) -> int:
    return sum(1 for ln in text.splitlines() if ln.strip())


def _parse_worktrees(text: str) -> list[str]:
    """Worktree paths from `git worktree list --porcelain` (excludes main = first)."""
    paths = [ln[len("worktree "):] for ln in text.splitlines() if ln.startswith("worktree ")]
    return paths[1:] if len(paths) > 1 else []


def _unpushed(repo: str) -> tuple[int, bool]:
    """(count, no_upstream). With an upstream: commits ahead of it. Without one:
    commits not reachable from any remote — the 'forgot to push a new branch' case
    a plain @{u} check reports as 0."""
    has_upstream = bool(_git(repo, "rev-parse", "--abbrev-ref",
                             "--symbolic-full-name", "@{u}").strip())
    if has_upstream:
        return _count_lines(_git(repo, "log", "--oneline", "@{u}..HEAD")), False
    return _count_lines(_git(repo, "log", "--oneline", "HEAD", "--not", "--remotes")), True


def scan_repo(repo: str, deadline: float | None = None) -> dict:
    repo = str(pathlib.Path(repo).resolve())
    inside = _git(repo, "rev-parse", "--is-inside-work-tree").strip()
    if inside != "true":
        return {"repo": repo, "is_repo": False}
    tracked, untracked = _classify_porcelain(_git(repo, "status", "--porcelain"))
    stashes = _count_lines(_git(repo, "stash", "list"))
    unpushed, no_upstream = _unpushed(repo)
    dirty_worktrees, partial = [], False
    for wt in _parse_worktrees(_git(repo, "worktree", "list", "--porcelain")):
        if deadline is not None and time.monotonic() > deadline:
            partial = True
            break
        wt_tracked, wt_untracked = _classify_porcelain(_git(wt, "status", "--porcelain"))
        if wt_tracked or wt_untracked:
            dirty_worktrees.append({"path": wt, "uncommitted": wt_tracked, "untracked": wt_untracked})
    return {
        "repo": repo, "is_repo": True,
        "branch": _git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip(),
        "uncommitted": tracked, "untracked": untracked,
        "stashes": stashes, "unpushed": unpushed, "no_upstream": no_upstream,
        "dirty_worktrees": dirty_worktrees, "partial_scan": partial,
    }


def is_dirty(r: dict) -> bool:
    return bool(r.get("is_repo") and (
        r["uncommitted"] or r["untracked"] or r["stashes"] or r["unpushed"] or r["dirty_worktrees"]))


def summarize(r: dict) -> str:
    """One-line summary of what's at risk, or '' if clean."""
    bits = []
    if r.get("uncommitted"):
        bits.append(f"{r['uncommitted']} uncommitted")
    if r.get("untracked"):
        bits.append(f"{r['untracked']} untracked")
    if r.get("stashes"):
        bits.append(f"{r['stashes']} stash{'es' if r['stashes'] > 1 else ''}")
    if r.get("unpushed"):
        bits.append(f"{r['unpushed']} unpushed" + (" (no upstream)" if r.get("no_upstream") else ""))
    if r.get("dirty_worktrees"):
        bits.append(f"{len(r['dirty_worktrees'])} dirty worktree(s)")
    return ", ".join(bits)


def format_report(reports: list[dict]) -> str:
    dirty = [r for r in reports if is_dirty(r)]
    if not dirty:
        return ""
    lines = ["⚠️  UNSAVED / AT-RISK GIT WORK"]
    for r in dirty:
        name = pathlib.Path(r["repo"]).name
        lines.append(f"  • {name} [{r['branch']}]: {summarize(r)}")
        for wt in r["dirty_worktrees"]:
            wtn = pathlib.Path(wt["path"]).name
            lines.append(f"      ↳ worktree {wtn}: {wt['uncommitted']} uncommitted, {wt['untracked']} untracked")
        if r.get("partial_scan"):
            lines.append("      (partial — worktree scan hit the time budget)")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=os.getcwd(), help="repo to scan (default: cwd)")
    ap.add_argument("--root", help="scan every immediate child git repo under this dir")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    if a.root:
        root = pathlib.Path(a.root).expanduser()
        reports = [scan_repo(str(p)) for p in sorted(root.iterdir())
                   if p.is_dir() and not p.is_symlink() and (p / ".git").exists()]
    else:
        reports = [scan_repo(a.repo)]

    if a.json:
        print(json.dumps(reports, indent=2))
        return 1 if any(is_dirty(r) for r in reports) else 0

    report = format_report(reports)
    if report:
        print(report)
        return 1
    print("✓ git clean (nothing uncommitted/stashed/unpushed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
