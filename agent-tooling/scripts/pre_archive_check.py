#!/usr/bin/env python3
"""pre_archive_check.py — may this worktree's session be archived? PASS / FAIL / could not check.

Run by a session before it says "Ready to archive", and again, independently, by the coordinator
before it archives. Archiving can take a worktree with it, and with it everything git does not
hold: uncommitted edits, commits on no remote, gitignored paper outputs, the cwd of a running job.
Each of those has been lost or nearly lost once; each check below exists for one of them.

  pre_archive_check.py --path <worktree>                      # the session's own check
  pre_archive_check.py --path <worktree> --whole-tree         # the coordinator's check
      [--handed-over <sha>]... [--manifest <SHA256SUMS>]... [--output-glob <glob>]...
      [--state <STATE.md>] [--warn-mb 100] [--json]

Exit 0 = PASS, 1 = FAIL, 2 = could not check. Any FAIL wins over "could not check"; "could not
check" wins over PASS. Nothing passes by default: a check that cannot run is an exit 2, never a ✓.

Checks
  1 uncommitted    `git status --porcelain`: any modified, staged or untracked file.
  2 unpushed       `git rev-list HEAD --not --remotes`: commits on no remote, unless every one is
                   named with --handed-over (full sha or a prefix of at least 7 characters).
  3 outputs        gitignored files under a paper-output path (default globs below, or
                   --output-glob) must each have their sha256 in a --manifest (`sha256sum -c`
                   format), and the manifest's copy must exist and re-hash to the same value.
                   Matching is by content: a copy saved under another name still counts.
                   "Regenerable" is not a reason to skip; there is no flag for it.
     ignored-size  ignored data over --warn-mb is listed as WARN (does not fail). Dependency
                   caches are left out of that list; `cache/` and `tmp/` are not outputs but stay
                   in it, because run results have been parked in `tmp/` before.
  4 open-files     `lsof +D <path>` (20 s timeout): any process with a file or its cwd inside the
                   path. This process and its ancestors (the session running the check) are
                   excluded and named in the reason.
  5 whole-tree     (--whole-tree only) stashes made on this branch (WARN: the stash stack is
                   shared and outlives the worktree, so it is not lost, but it is unsaved work),
                   and other worktrees on the same branch or commit (info).
  6 state          (--state only) the file must have been modified today (local date).

The default mode also checks the whole tree. There is no record of which session made which edit,
so a per-session mode could only narrow by guessing, and narrowing is the unsafe direction.
--whole-tree adds check 5.

Output globs are matched against the path inside the repo, component by component; `**` matches
any number of directories, and a glob without a leading `/` may start at any depth (as in
.gitignore), so `paper*` also catches `private/paper2/...`. A file whose path has a dependency or
cache directory in it (see CACHE_DIRS) is never an output.

Read-only: every git call goes through an allowlist of read-only subcommands, with the repo's own
command-running config (fsmonitor, hooks, pager, ...) overridden; see git_hygiene.py for why.
"""
import argparse
import datetime as _dt
import fnmatch
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from git_hygiene import _HARDENING  # noqa: E402  (sibling module, not stdlib)

DEFAULT_OUTPUT_GLOBS = ("results/", "analysis/**/out*", "data/processed/", "paper*/")
# Dependency/tool caches: never outputs, and not listed by size (they are noise).
DEP_CACHE_DIRS = ("uv-cache", ".venv", "venv*", "node_modules", "__pycache__")
# Not outputs either, but still listed by size: results have been parked in tmp/ before.
SCRATCH_DIRS = ("cache", "tmp")
CACHE_DIRS = DEP_CACHE_DIRS + SCRATCH_DIRS
LSOF_TIMEOUT = 20.0
GIT_TIMEOUT = 30.0
MIN_SHA_PREFIX = 7

PASS, FAIL, WARN, INFO, ERROR = "pass", "fail", "warn", "info", "error"
MARK = {PASS: "✓", FAIL: "✗", WARN: "!", INFO: "·", ERROR: "✗"}


class CheckError(RuntimeError):
    """A check could not run. Reported as exit 2, never as a pass."""


# ---------------------------------------------------------------------------------------------
# read-only git
# ---------------------------------------------------------------------------------------------
_READ_ONLY_GIT = {
    "status": None, "rev-list": None, "rev-parse": None, "ls-files": None,
    "stash": "list", "worktree": "list",
}


class UnsafeGitCommand(RuntimeError):
    """A non-read-only git command was attempted. A bug, never a runtime condition."""


def _assert_read_only(args):
    if not args or args[0] not in _READ_ONLY_GIT:
        raise UnsafeGitCommand(f"'git {' '.join(args)}' is not on the read-only allowlist")
    verb = _READ_ONLY_GIT[args[0]]
    if verb is not None and (len(args) < 2 or args[1] != verb):
        raise UnsafeGitCommand(f"'git {args[0]}' is only read-only as 'git {args[0]} {verb}'")


def git(repo, *args):
    """Run a read-only git command; return stdout. Any failure raises CheckError."""
    _assert_read_only(args)
    try:
        r = subprocess.run(["git", *_HARDENING, "-C", repo, *args],
                           capture_output=True, text=True, timeout=GIT_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise CheckError(f"git {args[0]} timed out after {GIT_TIMEOUT:.0f} s")
    except OSError as e:
        raise CheckError(f"git could not run: {e}")
    if r.returncode != 0:
        raise CheckError(f"git {' '.join(args)}: exit {r.returncode}: {r.stderr.strip()[:200]}")
    return r.stdout


def _z(text):
    return [p for p in text.split("\0") if p]


# ---------------------------------------------------------------------------------------------
# path classification
# ---------------------------------------------------------------------------------------------
def _glob_parts_match(pats, parts, inside):
    """Component-wise glob match of a pattern prefix: True if `pats` matches a leading run of
    `parts`. With `inside`, something must remain after the match (the glob names a directory
    and the path lies inside it); without, the glob may also name the file itself."""
    if not pats:
        return bool(parts) or not inside
    if pats[0] == "**":
        return any(_glob_parts_match(pats[1:], parts[i:], inside) for i in range(len(parts) + 1))
    return bool(parts) and fnmatch.fnmatchcase(parts[0], pats[0]) and \
        _glob_parts_match(pats[1:], parts[1:], inside)


def matches_output(relpath, globs):
    parts = pathlib.PurePosixPath(relpath).parts
    for g in globs:
        anchored = g.startswith("/")
        pats = [p for p in g.strip("/").split("/") if p]
        if not anchored:
            pats = ["**"] + pats
        # 'x/' names a directory: the path must lie inside it. 'x' may also be the file.
        if _glob_parts_match(pats, parts, inside=g.endswith("/")):
            return True
    return False


def cache_kind(relpath):
    """'dep' for a dependency cache, 'scratch' for cache/ or tmp/, None otherwise."""
    dirs = pathlib.PurePosixPath(relpath.rstrip("/")).parts
    dirs = dirs if relpath.endswith("/") else dirs[:-1]
    if any(fnmatch.fnmatchcase(d, p) for d in dirs for p in DEP_CACHE_DIRS):
        return "dep"
    if any(d in SCRATCH_DIRS for d in dirs):
        return "scratch"
    return None


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def parse_manifest(path):
    """`sha256sum` output: '<64 hex> <space|*><path>'. Returns {sha: [abs paths of copies]}.
    A malformed line is an error: a manifest we half-understand is not evidence."""
    base = os.path.dirname(os.path.abspath(path))
    out = {}
    try:
        lines = pathlib.Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as e:
        raise CheckError(f"manifest {path} unreadable: {e}")
    for n, line in enumerate(lines, 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        sha, sep, rest = line[:64], line[64:65], line[65:]
        if len(sha) != 64 or sep != " " or not rest or \
                any(c not in "0123456789abcdefABCDEF" for c in sha):
            raise CheckError(f"manifest {path}:{n} is not sha256sum format")
        name = rest[1:] if rest[0] in " *" else rest
        out.setdefault(sha.lower(), []).append(os.path.join(base, name))
    return out


def _du(path):
    """Bytes under path, not following symlinks."""
    try:
        st = os.lstat(path)
    except OSError:
        return 0
    if not os.path.isdir(path) or os.path.islink(path):
        return st.st_size
    total = 0
    for root, dirs, files in os.walk(path, followlinks=False):
        for f in files:
            try:
                total += os.lstat(os.path.join(root, f)).st_size
            except OSError:
                pass
    return total


# ---------------------------------------------------------------------------------------------
# checks: each returns a list of result dicts {check, status, reason, items}
# ---------------------------------------------------------------------------------------------
def _r(check, status, reason, items=None):
    return {"check": check, "status": status, "reason": reason, "items": items or []}


def check_uncommitted(top):
    lines = _z(git(top, "status", "--porcelain", "-z", "--untracked-files=all"))
    files = []
    skip = False
    for entry in lines:
        if skip:              # the source path of a rename/copy is its own -z field
            skip = False
            continue
        files.append(entry[3:])
        skip = entry[0] in "RC"
    if files:
        return [_r("uncommitted", FAIL, f"{len(files)} uncommitted or untracked file(s)", files)]
    return [_r("uncommitted", PASS, "no uncommitted or untracked files")]


def check_unpushed(top, handed_over):
    shas = git(top, "rev-list", "HEAD", "--not", "--remotes").split()
    for h in handed_over:
        if len(h) < MIN_SHA_PREFIX:
            raise CheckError(f"--handed-over {h!r}: give at least {MIN_SHA_PREFIX} hex characters")
    open_ = [s for s in shas if not any(s.startswith(h.lower()) for h in handed_over)]
    if open_:
        return [_r("unpushed", FAIL,
                   f"{len(open_)} commit(s) on no remote and not --handed-over", open_)]
    if shas:
        return [_r("unpushed", PASS, f"{len(shas)} commit(s) on no remote, all handed over")]
    return [_r("unpushed", PASS, "every commit is on a remote")]


def check_outputs(top, globs, manifests, warn_mb):
    ignored = _z(git(top, "ls-files", "--others", "--ignored", "--exclude-standard", "-z"))
    outputs = [p for p in ignored if cache_kind(p) is None and matches_output(p, globs)]
    output_set = set(outputs)
    other = [p for p in ignored if cache_kind(p) is None and p not in output_set]
    results = []

    index = {}
    for m in manifests:
        for sha, copies in parse_manifest(m).items():
            index.setdefault(sha, []).extend(copies)
    verified = {}   # copy path -> sha, so each durable copy is hashed once

    def saved(sha):
        for copy in index.get(sha, ()):
            if copy not in verified:
                try:
                    verified[copy] = sha256_file(copy)
                except OSError:
                    verified[copy] = None
            if verified[copy] == sha:
                return True
        return False

    missing, stale_copy = [], []
    for p in outputs:
        full = os.path.join(top, p)
        if os.path.islink(full):
            missing.append(f"{p} (symlink: save its target, then list the target)")
            continue
        try:
            sha = sha256_file(full)
        except OSError as e:
            raise CheckError(f"cannot hash {p}: {e}")
        if saved(sha):
            continue
        (stale_copy if sha in index else missing).append(p)
    if stale_copy:
        results.append(_r("outputs", FAIL, f"{len(stale_copy)} paper output(s) listed in a "
                          "manifest whose durable copy is missing or no longer matches", stale_copy))
    if missing:
        how = "no --manifest given" if not manifests else "sha256 not in any manifest"
        results.append(_r("outputs", FAIL,
                          f"{len(missing)} gitignored paper output(s) not saved ({how})", missing))
    if not results:
        results.append(_r("outputs", PASS,
                          f"{len(outputs)} gitignored paper output(s), all in a verified manifest"
                          if outputs else "no gitignored paper outputs"))

    # Size listing works on git's collapsed view (one line per ignored directory).
    entries = _z(git(top, "status", "--porcelain", "-z", "--ignored=traditional",
                     "--untracked-files=normal"))
    big, dep_bytes = [], 0
    for e in entries:
        if not e.startswith("!! "):
            continue
        rel = e[3:]
        size = _du(os.path.join(top, rel))
        if cache_kind(rel) == "dep" or any(
                fnmatch.fnmatchcase(pathlib.PurePosixPath(rel).name, p) for p in DEP_CACHE_DIRS):
            dep_bytes += size
            continue
        if size > warn_mb * 1024 * 1024:
            big.append(f"{rel} ({size / 1024 / 1024:.0f} MB)")
    if big:
        results.append(_r("ignored-size", WARN,
                          f"{len(big)} ignored entr(y/ies) over {warn_mb} MB: decide before archiving",
                          big))
    results.append(_r("ignored-other", INFO,
                      f"{len(other)} other ignored file(s) (not outputs, not caches); "
                      f"dependency caches {dep_bytes / 1024 / 1024:.0f} MB, not counted"))
    return results


def _ancestors():
    """This process and its ancestors: the session running the check holds its cwd here."""
    pids, pid = {os.getpid()}, os.getppid()
    for _ in range(64):
        if pid <= 1 or pid in pids:
            break
        pids.add(pid)
        try:
            out = subprocess.run(["ps", "-o", "ppid=", "-p", str(pid)], capture_output=True,
                                 text=True, timeout=5).stdout.strip()
            pid = int(out)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            break
    return pids


def _alive(pid):
    try:
        os.kill(pid, 0)          # signal 0: existence check only, sends nothing
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def parse_lsof(text):
    """`lsof -F pcn` output -> {pid: command}."""
    procs, pid = {}, None
    for line in text.splitlines():
        if line.startswith("p"):
            pid = int(line[1:])
            procs.setdefault(pid, "?")
        elif line.startswith("c") and pid is not None:
            procs[pid] = line[1:]
    return procs


def check_open_files(top, lsof="lsof"):
    exe = shutil.which(lsof)
    if not exe:
        raise CheckError("lsof not found: cannot tell whether a process holds files here")
    proc = subprocess.Popen([exe, "-w", "-n", "-P", "-F", "pc", "+D", top],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        out, err = proc.communicate(timeout=LSOF_TIMEOUT)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        raise CheckError(f"lsof +D timed out after {LSOF_TIMEOUT:.0f} s")
    # macOS lsof +D exits 1 whether or not it found anything, so the exit code cannot tell
    # "nothing open" from a failure. With -w (warnings off), anything on stderr is an error.
    if proc.returncode not in (0, 1) or err.strip():
        raise CheckError(f"lsof failed: exit {proc.returncode}: {err.strip()[:200]}")
    procs = parse_lsof(out)
    mine = _ancestors() | {proc.pid}
    excluded = sorted(p for p in procs if p in mine)
    # Short-lived helpers (lsof's own fork, a shell the session spawns for a hook) show up and
    # are gone by now; a job left running is still there.
    others = {p: c for p, c in procs.items() if p not in mine and _alive(p)}
    gone = len(procs) - len(excluded) - len(others)
    note = f" (excluded this check's own process chain: {excluded})" if excluded else ""
    note += f" ({gone} short-lived process(es) exited during the check)" if gone else ""
    if others:
        return [_r("open-files", FAIL, f"{len(others)} process(es) hold files here{note}",
                   [f"pid {p} {c}" for p, c in sorted(others.items())])]
    return [_r("open-files", PASS, f"no process holds files here{note}")]


def check_whole_tree(top):
    results = []
    branch = git(top, "rev-parse", "--abbrev-ref", "HEAD").strip()
    head = git(top, "rev-parse", "HEAD").strip()
    stashes = []
    for line in git(top, "stash", "list", "--format=%H %gs").splitlines():
        sha, _, subject = line.partition(" ")
        # 'WIP on <branch>: ...' (git stash) or 'On <branch>: ...' (git stash push -m)
        for pre in ("WIP on ", "On "):
            if subject.startswith(pre) and subject[len(pre):].split(":", 1)[0] == branch:
                stashes.append(f"{sha[:12]} {subject}")
    if branch == "HEAD":
        results.append(_r("stashes", INFO, "detached HEAD: stashes cannot be tied to a branch"))
    elif stashes:
        results.append(_r("stashes", WARN, f"{len(stashes)} stash(es) made on {branch}", stashes))
    else:
        results.append(_r("stashes", PASS, f"no stashes made on {branch}"))

    real = os.path.realpath(top)
    shared, wt = [], {}
    for line in git(top, "worktree", "list", "--porcelain").splitlines() + [""]:
        if not line:
            if wt and os.path.realpath(wt.get("worktree", "")) != real:
                if branch != "HEAD" and wt.get("branch") == f"refs/heads/{branch}":
                    shared.append(f"{wt['worktree']} (same branch)")
                elif wt.get("HEAD") == head:
                    shared.append(f"{wt['worktree']} (same commit)")
            wt = {}
            continue
        k, _, v = line.partition(" ")
        wt[k] = v
    results.append(_r("shared-branch", INFO,
                      f"{len(shared)} other worktree(s) on this branch or commit" if shared
                      else "no other worktree on this branch or commit", shared))
    return results


def check_state(path, today=None):
    today = today or _dt.date.today()
    try:
        mtime = _dt.date.fromtimestamp(os.stat(path).st_mtime)
    except OSError as e:
        return [_r("state", FAIL, f"{path}: {e.strerror}")]
    if mtime != today:
        return [_r("state", FAIL, f"{path} last modified {mtime}, not today ({today})")]
    return [_r("state", PASS, f"{path} modified today")]


# ---------------------------------------------------------------------------------------------
def run(args):
    path = os.path.abspath(args.path)
    if not os.path.isdir(path):
        return [_r("repo", ERROR, f"{path} is not a directory")], None
    try:
        if git(path, "rev-parse", "--is-inside-work-tree").strip() != "true":
            raise CheckError("not inside a work tree")
        top = os.path.realpath(git(path, "rev-parse", "--show-toplevel").strip())
    except CheckError as e:
        return [_r("repo", ERROR, f"{path} is not a git work tree: {e}")], None

    steps = [
        ("uncommitted", lambda: check_uncommitted(top)),
        ("unpushed", lambda: check_unpushed(top, args.handed_over)),
        ("outputs", lambda: check_outputs(top, args.output_glob or DEFAULT_OUTPUT_GLOBS,
                                          args.manifest, args.warn_mb)),
        ("open-files", lambda: check_open_files(top)),
    ]
    if args.whole_tree:
        steps.append(("whole-tree", lambda: check_whole_tree(top)))
    if args.state:
        steps.append(("state", lambda: check_state(args.state)))
    results = []
    for name, fn in steps:
        try:
            results.extend(fn())
        except CheckError as e:
            results.append(_r(name, ERROR, f"could not check: {e}"))
    return results, top


def verdict(results):
    statuses = {r["status"] for r in results}
    if FAIL in statuses:
        return "FAIL", 1
    if ERROR in statuses or not results:
        return "FAIL", 2
    return "PASS", 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--path", required=True, help="worktree or folder to check")
    ap.add_argument("--whole-tree", action="store_true",
                    help="coordinator mode: also stashes and worktrees sharing the branch")
    ap.add_argument("--handed-over", action="append", default=[], metavar="SHA",
                    help="an unpushed commit that has been handed over (repeatable)")
    ap.add_argument("--manifest", action="append", default=[], metavar="SHA256SUMS",
                    help="durable-store manifest in sha256sum format (repeatable)")
    ap.add_argument("--output-glob", action="append", default=[], metavar="GLOB",
                    help=f"paper-output path glob (repeatable; replaces {DEFAULT_OUTPUT_GLOBS})")
    ap.add_argument("--state", help="STATE file that must have been modified today")
    ap.add_argument("--warn-mb", type=float, default=100.0)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    results, top = run(args)
    word, code = verdict(results)
    stamp = _dt.datetime.now().astimezone().isoformat(timespec="seconds")
    if args.json:
        print(json.dumps({"path": os.path.abspath(args.path), "toplevel": top,
                          "whole_tree": args.whole_tree, "results": results,
                          "verdict": word, "exit": code, "time": stamp}, indent=2))
    else:
        for r in results:
            print(f"{MARK[r['status']]} {r['check']}: {r['reason']}")
            for item in r["items"][:50]:
                print(f"    {item}")
            if len(r["items"]) > 50:
                print(f"    … and {len(r['items']) - 50} more")
        if code == 2:
            print("could not complete every check: not a PASS")
        print(f"pre-archive check: {word} ({stamp})")
    return code


if __name__ == "__main__":
    sys.exit(main())
