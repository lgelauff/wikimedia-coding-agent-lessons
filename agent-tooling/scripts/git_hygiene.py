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


# ---------------------------------------------------------------------------------------------
# READ-ONLY ENFORCEMENT
# ---------------------------------------------------------------------------------------------
# This tool must never be able to change a repo. It is run at session close, on repos holding
# unsaved work, precisely when a destructive mistake would be least recoverable — so "we only
# happen to call read-only commands" is not good enough. The allowlist makes the property
# ENFORCED rather than incidental: adding a mutating call is a loud failure, not a silent
# regression. Subcommands that are read-only only in some forms (`stash`, `worktree`) must name
# the safe verb explicitly.
_READ_ONLY_GIT = {
    "status": None, "log": None, "rev-parse": None, "ls-files": None,
    "stash": "list",        # `git stash` alone MUTATES — only `stash list` is safe
    "worktree": "list",     # `git worktree add/remove/prune` MUTATE — only `list` is safe
}


class UnsafeGitCommand(RuntimeError):
    """Raised when a non-read-only git command is attempted. A bug, never a runtime condition."""


def _assert_read_only(args: tuple) -> None:
    if not args:
        raise UnsafeGitCommand("empty git command")
    sub = args[0]
    if sub not in _READ_ONLY_GIT:
        raise UnsafeGitCommand(
            f"'git {sub}' is not on the read-only allowlist. This tool must not modify repos. "
            f"If a new read-only subcommand is genuinely needed, add it to _READ_ONLY_GIT "
            f"deliberately — and add a test.")
    required = _READ_ONLY_GIT[sub]
    if required is not None and (len(args) < 2 or args[1] != required):
        raise UnsafeGitCommand(
            f"'git {sub}' is only read-only as 'git {sub} {required}'; got: git {' '.join(args)}")


def _git(repo: str, *args: str, timeout: float = 5.0, errors: list | None = None) -> str:
    """Run a git command. Returns stdout, or "" on ANY failure.

    ⚠ A failure and a genuinely empty result BOTH return "". That ambiguity was a real
    false-all-clear bug: every caller parses "" as zero-of-everything, so a timed-out or errored
    scan read exactly like a clean one. `errors` is the fix — pass a list and any failure is
    appended to it, so the caller can report "could not verify" instead of "nothing found".
    INABILITY TO VERIFY IS NOT VERIFIED-CLEAN. Callers that skip `errors` keep the old lenient
    behaviour, so this stays backward compatible for pure-parser tests.
    """
    _assert_read_only(args)   # hard stop before anything reaches the shell
    # --no-optional-locks: never take index.lock (read-only safety on a busy repo).
    # timeout: this can run on the SessionStart critical path — a hung cred helper, NFS worktree
    # or stale lock must not block the session.
    try:
        r = subprocess.run(["git", "--no-optional-locks", "-C", repo, *args],
                           capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        if errors is not None:
            errors.append({"repo": repo, "args": list(args), "why": f"timeout after {timeout}s"})
        return ""
    except OSError as e:
        if errors is not None:
            errors.append({"repo": repo, "args": list(args), "why": f"OSError: {e}"})
        return ""
    if r.returncode != 0:
        if errors is not None:
            errors.append({"repo": repo, "args": list(args),
                           "why": f"exit {r.returncode}: {(r.stderr or '').strip()[:120]}"})
        return ""
    return r.stdout


# ---------------------------------------------------------------------------------------------
# KNOWN-CONDITIONS REGISTRY  —  flag everything this tool does not claim to understand
# ---------------------------------------------------------------------------------------------
# Design inversion (owner, 2026-08-09). Detecting known-bad cases one at a time means every
# situation nobody anticipated reads as "nothing there" — which is the tool's whole failure mode
# in one sentence. Every open review finding (submodules, symlinked repos, bare repos, mid-rebase
# state) was an instance of it.
#
# So: enumerate what we DO handle, and surface anything else as UNKNOWN. A new git feature, an
# exotic repo layout or an unrecognised status code then produces a visible "I don't know what
# this is" instead of silence. Unknown is not an error and not dirt — it is a third state meaning
# "a human should look, because I cannot vouch for this repo".
#
# Adding a condition here is a deliberate act: you are asserting the scan handles it correctly.

# Porcelain XY codes this tool's classifier understands. Anything else -> UNKNOWN.
_KNOWN_PORCELAIN = frozenset({
    "??",              # untracked
    " M", "M ", "MM", "AM", " D", "D ", "MD", "AD",   # ordinary add/modify/delete
    "A ", "AA", "R ", "RM", "C ", " R", " C", "T ", " T", "MT", "TM",
    "UU", "AU", "UA", "DU", "UD", "DD",               # unmerged / conflicted
    "!!",              # ignored (only appears with --ignored)
})

# In-progress operations. Present => the repo is mid-operation and walking away is riskier than a
# plain edit. We detect and NAME them; we do not pretend to assess their safety.
_INPROGRESS_MARKERS = (
    ("MERGE_HEAD", "merge in progress"),
    ("rebase-merge", "rebase in progress"),
    ("rebase-apply", "rebase/am in progress"),
    ("CHERRY_PICK_HEAD", "cherry-pick in progress"),
    ("REVERT_HEAD", "revert in progress"),
    ("BISECT_LOG", "bisect in progress"),
)


def _repo_conditions(repo: str, errors: list, unknowns: list) -> list[str]:
    """Probe for states we either handle explicitly or must declare we cannot assess."""
    notes = []
    gitdir_raw = _git(repo, "rev-parse", "--git-dir", errors=errors).strip()
    gitdir = pathlib.Path(repo, gitdir_raw) if gitdir_raw and not os.path.isabs(gitdir_raw) else pathlib.Path(gitdir_raw or "")

    for marker, label in _INPROGRESS_MARKERS:
        try:
            if gitdir and (gitdir / marker).exists():
                notes.append(label)
        except OSError:
            pass

    if _git(repo, "rev-parse", "--is-bare-repository", errors=errors).strip() == "true":
        unknowns.append({"repo": repo, "what": "bare repository",
                         "why": "no working tree — this tool's dirty/ignored checks do not apply; "
                                "unpushed refs are NOT assessed here"})

    if _git(repo, "rev-parse", "--abbrev-ref", "HEAD", errors=errors).strip() == "HEAD":
        notes.append("detached HEAD")

    # Submodules: a KNOWN blind spot. git ls-files does not cross the boundary, so ignored content
    # inside a submodule is invisible. Declare it rather than quietly missing it.
    mods = [l for l in _git(repo, "ls-files", "--stage", errors=errors).splitlines()
            if l.startswith("160000")]
    if mods:
        unknowns.append({"repo": repo, "what": f"{len(mods)} submodule(s)",
                         "why": "ignored content INSIDE a submodule is not scanned — `git ls-files` "
                                "does not cross the boundary. Check them separately."})
    return notes


def _classify_porcelain(text: str, unknowns: list | None = None, repo: str = "") -> tuple[int, int]:
    """(tracked_changes, untracked). Unrecognised XY codes are reported, never silently bucketed."""
    tracked = untracked = 0
    seen_unknown = set()
    for ln in text.splitlines():
        if not ln.strip():
            continue
        code = ln[:2]
        if code == "??":
            untracked += 1
        else:
            tracked += 1
        if unknowns is not None and code not in _KNOWN_PORCELAIN and code not in seen_unknown:
            seen_unknown.add(code)
            unknowns.append({"repo": repo, "what": f"unrecognised status code {code!r}",
                             "why": "counted as a tracked change, but this tool has no rule for it "
                                    "— verify by hand"})
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
# Whole path COMPONENTS (see _is_noise) whose contents are effectively always regenerable.
# Deliberately short: a false alarm costs a glance, a false all-clear costs the work.
_IGNORE_NOISE = frozenset({"__pycache__", ".pytest_cache", ".ruff_cache", "node_modules",
                           ".mypy_cache", ".ipynb_checkpoints", ".DS_Store", ".venv", "venv",
                           ".tox", ".gradle", "env", ".eggs", ".next", ".parcel-cache"})


def _is_noise(rel: str) -> bool:
    """True only if a whole PATH COMPONENT is a known-regenerable dir.

    ⚠ Was `any(tok in rel ...)` — unanchored substring matching, which silently dropped real
    content whose name merely CONTAINED a token: `analysis/.toxicity_scores/` matched ".tox",
    and a frozen `reproducibility.venv-snapshot/` (which this project's own provenance rule tells
    you to create) matched ".venv". Both are exactly the irreplaceable kind of path this tool
    exists to surface, so the filter was hiding its own quarry.
    """
    parts = [c for c in rel.replace(os.sep, "/").split("/") if c]
    return any(c in _IGNORE_NOISE for c in parts)


def _ignored_present(path: str, deadline: float | None = None,
                     errors: list | None = None) -> tuple[list[dict], bool]:
    """Gitignored paths that EXIST on disk, largest first.

    THE blind spot: `git status` is structurally silent about ignored files, so a worktree can
    report perfectly clean while holding the only copy of something. Real incidents this exists
    for: 1,120 MB of derived analysis fields deleted with a "clean" worktree; a bug-detector and
    its scan output living only in a worktree's ignored scratch dir.

    Opt-in only (--ignored): walking ignored trees can mean tens of GB, which must never sit on
    the SessionStart critical path.
    """
    raw = _git(path, "ls-files", "--others", "--ignored", "--exclude-standard", "--directory",
               timeout=30.0, errors=errors)
    rows, truncated = [], False
    for rel in filter(None, (ln.strip() for ln in raw.splitlines())):
        if _is_noise(rel):
            continue
        if deadline is not None and time.monotonic() > deadline:
            # ⚠ Signal it. Returning a short list silently is how a partial scan reads as a
            # complete one — the exact false-all-clear this tool exists to prevent.
            truncated = True
            break
        full = pathlib.Path(path) / rel
        try:
            if full.is_dir():
                total = nfiles = 0
                def _walk_err(e, _p=rel):
                    if errors is not None:
                        errors.append({"repo": path, "args": ["walk", _p], "why": f"{e}"})
                for dirpath, dirnames, filenames in os.walk(full, onerror=_walk_err):
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
    return sorted(rows, key=lambda r: -r["bytes"]), truncated


def _human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024.0
    return f"{n:.1f}TB"


def scan_repo(repo: str, deadline: float | None = None, with_ignored: bool = False) -> dict:
    errors: list = []
    unknowns: list = []
    repo = str(pathlib.Path(repo).resolve())
    inside = _git(repo, "rev-parse", "--is-inside-work-tree", errors=errors).strip()
    if inside != "true":
        _repo_conditions(repo, errors, unknowns)   # still probe: a bare repo lands here
        return {"repo": repo, "is_repo": False, "errors": errors,
                "scan_complete": not errors, "unknowns": unknowns, "conditions": []}
    tracked, untracked = _classify_porcelain(_git(repo, "status", "--porcelain", errors=errors), unknowns, repo)
    conditions = _repo_conditions(repo, errors, unknowns)
    stashes = _count_lines(_git(repo, "stash", "list", errors=errors))
    unpushed, no_upstream = _unpushed(repo)
    dirty_worktrees, partial = [], False
    for wt in _parse_worktrees(_git(repo, "worktree", "list", "--porcelain", errors=errors)):
        if deadline is not None and time.monotonic() > deadline:
            partial = True
            break
        wt_tracked, wt_untracked = _classify_porcelain(_git(wt, "status", "--porcelain", errors=errors), unknowns, wt)
        wt_ignored, wt_trunc = _ignored_present(wt, deadline, errors) if with_ignored else ([], False)
        partial = partial or wt_trunc
        if wt_tracked or wt_untracked or wt_ignored:
            dirty_worktrees.append({"path": wt, "uncommitted": wt_tracked,
                                    "untracked": wt_untracked, "ignored": wt_ignored})
    ign_main, main_trunc = _ignored_present(repo, deadline, errors) if with_ignored else ([], False)
    partial = partial or main_trunc
    return {
        "repo": repo, "is_repo": True,
        "branch": _git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip(),
        "uncommitted": tracked, "untracked": untracked,
        "stashes": stashes, "unpushed": unpushed, "no_upstream": no_upstream,
        "dirty_worktrees": dirty_worktrees, "partial_scan": partial,
        # Main-checkout ignored content is reported but NEVER counts as at-risk: it is the normal
        # build/data store and a session ending cannot hurt it. Only a WORKTREE's ignored content
        # is at-risk, because collapsing a worktree is routine cleanup that takes it along.
        "ignored_main": ign_main,
        # A scan that could not complete MUST NOT read as a clean one.
        "errors": errors, "scan_complete": not errors and not partial,
        # Third state: not an error, not dirt — "a human should look, because I cannot
        # vouch for this". Anything the tool does not claim to understand lands here.
        "unknowns": unknowns, "conditions": conditions,
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


def has_unknowns(r: dict) -> bool:
    """Encountered something it has no rule for — cannot vouch for this repo."""
    return bool(r.get("unknowns"))


def scan_failed(r: dict) -> bool:
    """Scan could not be completed -> its 'clean' means nothing."""
    return not r.get("scan_complete", True)


def format_report(reports: list[dict]) -> str:
    dirty = [r for r in reports if is_dirty(r)]
    broken = [r for r in reports if scan_failed(r) and r not in dirty]
    unsure = [r for r in reports if has_unknowns(r) and r not in dirty and r not in broken]
    if not dirty and not broken and not unsure:
        return ""
    lines = []
    # Report unverifiable repos FIRST and separately. "I could not check" must never be
    # displayed as, or mistaken for, "I checked and it was fine".
    for r in broken + unsure + dirty:
        for u in (r.get("unknowns") or []):
            lines.append(f"❓ UNKNOWN — {pathlib.Path(u['repo']).name}: {u['what']}")
            lines.append(f"      {u['why']}")
        for c in (r.get("conditions") or []):
            lines.append(f"❗ {pathlib.Path(r['repo']).name}: {c} — higher risk to walk away from "
                         f"than a plain edit")
        if scan_failed(r):
            name = pathlib.Path(r["repo"]).name
            errs = r.get("errors") or []
            lines.append(f"⛔ SCAN INCOMPLETE — {name}: {len(errs)} git operation(s) failed. "
                         f"This repo's result is UNVERIFIED, not clean.")
            for e in errs[:3]:
                lines.append(f"      {' '.join(e['args'])[:48]} -> {e['why'][:70]}")
            if len(errs) > 3:
                lines.append(f"      ... and {len(errs) - 3} more (--json for all)")
    if not dirty:
        return "\n".join(lines)
    lines.append("⚠️  UNSAVED / AT-RISK GIT WORK")
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


def _deadline(budget: float | None) -> float | None:
    return None if budget is None else time.monotonic() + budget


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=os.getcwd(), help="repo to scan (default: cwd)")
    ap.add_argument("--root", help="scan every immediate child git repo under this dir")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--budget", type=float, default=None, metavar="SEC",
                    help="wall-clock budget for the scan. Without it there is NO time limit and "
                         "the partial-scan guard never fires — it was previously unreachable from "
                         "the CLI entirely. Set it for unattended/hook use; omit at session close "
                         "when you want completeness over speed.")
    ap.add_argument("--ignored", action="store_true",
                    help="also scan for GITIGNORED-BUT-PRESENT files — the blind spot git status "
                         "cannot see. Off by default: it can walk tens of GB, so it must never sit "
                         "on the SessionStart critical path. Use at session close.")
    a = ap.parse_args()

    if a.root:
        root = pathlib.Path(a.root).expanduser()
        reports = []
        for child in sorted(root.iterdir()):
            if not child.is_dir() or not (child / ".git").exists():
                continue
            if child.is_symlink():
                # Was silently skipped — a whole repo absent from the sweep with no trace.
                reports.append({"repo": str(child), "is_repo": False, "errors": [],
                                "scan_complete": True, "conditions": [],
                                "unknowns": [{"repo": str(child), "what": "symlinked repo — NOT SCANNED",
                                              "why": "skipped to avoid double-counting/loops; scan it "
                                                     "directly with --repo if it holds real work"}]})
                continue
            reports.append(scan_repo(str(child), deadline=_deadline(a.budget), with_ignored=a.ignored))
    else:
        reports = [scan_repo(a.repo, deadline=_deadline(a.budget), with_ignored=a.ignored)]

    if a.json:
        print(json.dumps(reports, indent=2))
        if any(scan_failed(r) or has_unknowns(r) for r in reports):
            return 2
        return 1 if any(is_dirty(r) for r in reports) else 0

    report = format_report(reports)
    if report:
        print(report)
        # 2 outranks 1: an unverifiable scan is a worse state than a known-dirty one, because
        # you cannot act on what you could not see.
        return 2 if any(scan_failed(r) or has_unknowns(r) for r in reports) else 1
    print("✓ git clean (nothing uncommitted/stashed/unpushed; scan completed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
