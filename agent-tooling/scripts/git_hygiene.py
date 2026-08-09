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


# Directories whose ignored contents are effectively always regenerable. Kept short on purpose:
# a false alarm costs a glance, a false all-clear costs the work.
_IGNORE_NOISE = ("__pycache__", ".pytest_cache", ".ruff_cache", "node_modules", ".mypy_cache",
                 ".ipynb_checkpoints", ".DS_Store", ".venv", "venv/", ".tox", ".gradle")


def _is_noise(rel: str) -> bool:
    return any(tok in rel for tok in _IGNORE_NOISE)


def _ignored_present(path: str, deadline: float | None = None) -> list[dict]:
    """Gitignored paths that EXIST on disk, largest first.

    THE blind spot: `git status` is structurally silent about ignored files, so a worktree can
    report perfectly clean while holding the only copy of something. Real incidents this exists
    for: 1,120 MB of derived analysis fields deleted with a "clean" worktree; a bug-detector and
    its scan output living only in a worktree's ignored scratch dir.

    Opt-in only (--ignored): walking ignored trees can mean tens of GB, which must never sit on
    the SessionStart critical path.
    """
    raw = _git(path, "ls-files", "--others", "--ignored", "--exclude-standard", "--directory",
               timeout=30.0)
    rows = []
    for rel in filter(None, (ln.strip() for ln in raw.splitlines())):
        if _is_noise(rel):
            continue
        if deadline is not None and time.monotonic() > deadline:
            break
        full = pathlib.Path(path) / rel
        try:
            if full.is_dir():
                total = nfiles = 0
                for dirpath, dirnames, filenames in os.walk(full):
                    dirnames[:] = [d for d in dirnames if not _is_noise(d + "/")]
                    for fn in filenames:
                        try:
                            total += (pathlib.Path(dirpath) / fn).stat().st_size
                            nfiles += 1
                        except OSError:
                            pass
                if nfiles:
                    rows.append({"path": rel, "bytes": total, "files": nfiles, "dir": True})
            elif full.exists():
                rows.append({"path": rel, "bytes": full.stat().st_size, "files": 1, "dir": False})
        except OSError:
            continue
    return sorted(rows, key=lambda r: -r["bytes"])


def _human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024.0
    return f"{n:.1f}TB"


def scan_repo(repo: str, deadline: float | None = None, with_ignored: bool = False) -> dict:
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
        wt_ignored = _ignored_present(wt, deadline) if with_ignored else []
        if wt_tracked or wt_untracked or wt_ignored:
            dirty_worktrees.append({"path": wt, "uncommitted": wt_tracked,
                                    "untracked": wt_untracked, "ignored": wt_ignored})
    return {
        "repo": repo, "is_repo": True,
        "branch": _git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip(),
        "uncommitted": tracked, "untracked": untracked,
        "stashes": stashes, "unpushed": unpushed, "no_upstream": no_upstream,
        "dirty_worktrees": dirty_worktrees, "partial_scan": partial,
        # Main-checkout ignored content is reported but NEVER counts as at-risk: it is the normal
        # build/data store and a session ending cannot hurt it. Only a WORKTREE's ignored content
        # is at-risk, because collapsing a worktree is routine cleanup that takes it along.
        "ignored_main": _ignored_present(repo, deadline) if with_ignored else [],
    }


def is_dirty(r: dict) -> bool:
    return bool(r.get("is_repo") and (
        r["uncommitted"] or r["untracked"] or r["stashes"] or r["unpushed"] or r["dirty_worktrees"]))


def at_risk_ignored(r: dict) -> list[dict]:
    """Worktree ignored content — the losable kind. Excludes the main checkout deliberately."""
    return [{"worktree": wt["path"], **row}
            for wt in r.get("dirty_worktrees", []) for row in wt.get("ignored", [])]


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
            bits = f"{wt['uncommitted']} uncommitted, {wt['untracked']} untracked"
            ign = wt.get("ignored") or []
            if ign:
                tot = sum(x["bytes"] for x in ign)
                bits += f", {len(ign)} GITIGNORED path(s) {_human(tot)}"
            lines.append(f"      ↳ worktree {wtn}: {bits}")
            # Ignored content is the losable kind: git status never shows it, and collapsing the
            # worktree deletes it silently. Name the biggest so the decision is concrete.
            for row in ign[:4]:
                kind = "dir " if row["dir"] else "file"
                lines.append(f"          {_human(row['bytes']):>9}  {kind}  {row['path']}"
                             f"{'  <-- invisible to git status' if row is ign[0] else ''}")
            if len(ign) > 4:
                lines.append(f"          ... and {len(ign) - 4} more (--json for all)")
        if r.get("ignored_main"):
            tot = sum(x["bytes"] for x in r["ignored_main"])
            lines.append(f"      (main checkout also holds {len(r['ignored_main'])} ignored path(s), "
                         f"{_human(tot)} — reported for awareness, NOT at risk from closing)")
        if r.get("partial_scan"):
            lines.append("      (partial — worktree scan hit the time budget)")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=os.getcwd(), help="repo to scan (default: cwd)")
    ap.add_argument("--root", help="scan every immediate child git repo under this dir")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--ignored", action="store_true",
                    help="also scan for GITIGNORED-BUT-PRESENT files — the blind spot git status "
                         "cannot see. Off by default: it can walk tens of GB, so it must never sit "
                         "on the SessionStart critical path. Use at session close.")
    a = ap.parse_args()

    if a.root:
        root = pathlib.Path(a.root).expanduser()
        reports = [scan_repo(str(p), with_ignored=a.ignored) for p in sorted(root.iterdir())
                   if p.is_dir() and not p.is_symlink() and (p / ".git").exists()]
    else:
        reports = [scan_repo(a.repo, with_ignored=a.ignored)]

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
