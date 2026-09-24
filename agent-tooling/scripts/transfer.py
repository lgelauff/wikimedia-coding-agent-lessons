#!/usr/bin/env python3
"""Session-to-session data transfer through the agent outbox. A member of the deliver.py family.

Design:   ~/agent/notes/wikimedia-coding-agent-lessons/transfer-design-2026-09-24.md
Playbook: agent-tooling/playbooks/session-transfer.md

One subcommand per party:

    request    (sender)       write the manifest: bytes + sha256 per file, class, from/to, dest
    check ID   (coordinator)  run the mechanical checks and print the numbers; never decides
    deliver    (mediator)     ~/agent/outbox/transfer-<id>/ -> ~/agent/inbox/transfers/<id>/
    receive ID (receiver)     verify the hashes, copy into dest (a repo's gitignored data/)
    push                      STUB: the cross-machine route is not built

`deliver` is the boundary, so like deliver.py this script is meant to be installed
**root-owned and not writable by the agent**:

    sudo install -m 0755 -o root -g wheel transfer.py /usr/local/bin/transfer.py

The deliver.py restrictions, all kept:

1. **No path arguments to deliver.** It scans the outbox for `transfer-*` folders and
   nothing else, so there is nothing to inject.
2. **No symlinks.** lstat and O_NOFOLLOW everywhere; a symlinked folder or file is refused,
   never followed.
3. **No overwrites.** An existing inbox folder, destination file or request id is refused.
   Final names are created with link(2), which fails rather than replaces.
4. **Dotfiles are skipped.** They are staging residue, not deliverables.

And the transfer ones:

5. **No approved decision, no delivery.** `~/agent/transfer/decisions/<id>.json` must say
   `approved` and carry the sha256 of the manifest it approved, so an edit to the manifest
   after approval is refused.
6. **Hashes must match.** Each file is hashed *while* it is copied, and the copy only gets its
   final name if the hash matches. The bytes that arrive are the bytes that were checked; a
   file swapped between a check and a move cannot slip through.
7. **raw-pii is refused at every step**, whatever the decision file says.

Boundary vs convention: on the Mac every session runs as the same user, so a decision file
is a convention an agent could forge. The boundaries are that this script is root-owned,
agents have no ssh, and ~/Data_pii is denied to every agent.

Exit codes (every subcommand): 0 ok or nothing to do · 1 at least one refusal, a failed
check, or a partial result · 2 could not run (bad environment, bad arguments).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import errno
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

DATA_CLASSES = ("public", "internal", "participant", "raw-pii")
SOURCE_AFTER = ("keep", "delete")
HARNESSES = ("claude-code", "opencode", "other")
PREFIX = "transfer-"
# Provisional (design: "Thresholds are placeholders"). The coordinator's limits.json wins.
DEFAULT_LIMITS = {"disk_max_used_pct": 80.0, "max_request_bytes": 5_000_000_000}
ID_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9][a-z0-9-]{0,63}$")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
CHUNK = 1 << 20
CROSS_MACHINE_REFUSAL = "cross-machine route not built: needs Lodewijk's design review"
# Only the Mac's same-machine route is built. hague's (ubuntu <-> agent via /srv/exchange) is not.
BUILT_SAME_MACHINE = ("mac",)


class EnvError(Exception):
    """The script cannot run at all (exit 2)."""


class Refused(Exception):
    """One item is refused; the reason is the message (exit 1)."""


# --- paths: evaluated per call so HOME can be overridden (tests never touch the real hub) ---

def hub() -> Path:
    return Path.home() / "agent"


def requests_dir() -> Path:
    return hub() / "transfer" / "requests"


def decisions_dir() -> Path:
    return hub() / "transfer" / "decisions"


def done_dir() -> Path:
    return hub() / "transfer" / "done"


def limits_path() -> Path:
    return hub() / "transfer" / "limits.json"


def outbox() -> Path:
    return hub() / "outbox"


def inbox_transfers() -> Path:
    return hub() / "inbox" / "transfers"


def data_pii() -> Path:
    return Path.home() / "Data_pii"


# --- small helpers ---

def _is_link(p: Path) -> bool:
    try:
        return stat.S_ISLNK(os.lstat(p).st_mode)
    except FileNotFoundError:
        return False


def _gb(n: float) -> str:
    return f"{n / 1e9:,.2f} GB"


def this_machine() -> str:
    p = hub() / "machine.json"
    try:
        name = json.loads(p.read_text(encoding="utf-8")).get("machine")
    except (OSError, ValueError, AttributeError) as e:
        raise EnvError(f"cannot tell which machine this is: {p} unreadable ({e})")
    if not isinstance(name, str) or not name:
        raise EnvError(f"cannot tell which machine this is: no 'machine' in {p}")
    return name


def valid_id(tid: str) -> str:
    if not ID_RE.match(tid):
        raise EnvError(f"not a transfer id: {tid!r} (expected YYYY-MM-DD-<slug>)")
    return tid


def ensure_real_dir(path: Path, mode: int = 0o700) -> None:
    """Create `path` (and missing parents below ~/agent) refusing any symlinked component."""
    base = hub()
    try:
        rel = path.relative_to(base)
    except ValueError:
        raise EnvError(f"{path} is not under {base}")
    cur = base
    for part in ("",) + rel.parts:
        cur = cur / part if part else cur
        try:
            st = os.lstat(cur)
        except FileNotFoundError:
            try:
                os.mkdir(cur, mode)
            except OSError as e:
                raise EnvError(f"cannot create {cur} ({e.strerror})")
            continue
        if stat.S_ISLNK(st.st_mode):
            raise EnvError(f"{cur} is a symlink (refused)")
        if not stat.S_ISDIR(st.st_mode):
            raise EnvError(f"{cur} exists and is not a directory")


def _open_regular(path: Path) -> int:
    """Open for reading without following a symlink; refuse anything but a regular file."""
    try:
        fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as e:
        if e.errno == errno.ELOOP or _is_link(path):
            raise Refused(f"{path.name}: is a symlink (symlinks are refused)")
        raise Refused(f"{path.name}: cannot open ({e.strerror})")
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise Refused(f"{path.name}: not a regular file")
    return fd


def read_regular(path: Path) -> bytes:
    with os.fdopen(_open_regular(path), "rb") as f:
        return f.read()


def hash_file(path: Path) -> tuple:
    h = hashlib.sha256()
    n = 0
    with os.fdopen(_open_regular(path), "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
            n += len(chunk)
    return n, h.hexdigest()


def copy_verified(src: Path, dst: Path, want_bytes: int, want_sha: str) -> None:
    """Copy src to dst, hashing in transit; dst only appears if size and sha256 match.

    The temporary file is created with O_EXCL and the final name with link(2), so an
    existing dst is never replaced.
    """
    fd_in = _open_regular(src)
    mode = os.fstat(fd_in).st_mode & 0o666
    tmp = dst.with_name(f".{dst.name}.partial")
    try:
        fd_out = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    except OSError as e:
        os.close(fd_in)
        raise Refused(f"{dst.name}: cannot create staging file in {dst.parent} ({e.strerror})")
    try:
        h = hashlib.sha256()
        n = 0
        with os.fdopen(fd_in, "rb") as fi, os.fdopen(fd_out, "wb") as fo:
            for chunk in iter(lambda: fi.read(CHUNK), b""):
                h.update(chunk)
                n += len(chunk)
                fo.write(chunk)
            fo.flush()
            os.fsync(fo.fileno())
        got = h.hexdigest()
        if n != want_bytes or got != want_sha:
            raise Refused(f"{src.name}: hash mismatch (manifest {want_bytes} B sha256 "
                          f"{want_sha[:12]}..., found {n} B sha256 {got[:12]}...)")
        try:
            os.link(str(tmp), str(dst))
        except FileExistsError:
            raise Refused(f"{dst.name}: already exists in {dst.parent} (refusing to overwrite)")
        except OSError as e:
            raise Refused(f"{dst.name}: cannot place file ({e.strerror})")
    finally:
        try:
            os.unlink(str(tmp))
        except OSError:
            pass


def _write_new_json(path: Path, obj: dict) -> None:
    data = (json.dumps(obj, indent=2, sort_keys=True) + "\n").encode("utf-8")
    try:
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    except FileExistsError:
        raise Refused(f"{path} already exists (refusing to overwrite)")
    with os.fdopen(fd, "wb") as f:
        f.write(data)


# --- manifest and decision ---

def validate_manifest(m, tid: str) -> None:
    def bad(msg):
        raise Refused(f"manifest {tid}: {msg}")

    if not isinstance(m, dict):
        bad("not a JSON object")
    if m.get("id") != tid:
        bad(f"id is {m.get('id')!r}, file name says {tid!r}")
    for side in ("from", "to"):
        s = m.get(side)
        if not isinstance(s, dict) or not all(isinstance(s.get(k), str)
                                              for k in ("session", "machine")):
            bad(f"'{side}' needs string 'session' and 'machine'")
    if not isinstance(m["to"].get("harness"), str):
        bad("'to' needs a string 'harness'")
    if m.get("data_class") not in DATA_CLASSES:
        bad(f"data_class {m.get('data_class')!r} not one of {DATA_CLASSES}")
    if m.get("source_after") not in SOURCE_AFTER:
        bad(f"source_after {m.get('source_after')!r} not one of {SOURCE_AFTER}")
    if not isinstance(m.get("dest"), str) or not isinstance(m.get("why"), str):
        bad("'dest' and 'why' must be strings")
    files = m.get("files")
    if not isinstance(files, list) or not files:
        bad("'files' must be a non-empty list")
    names = set()
    for f in files:
        if not isinstance(f, dict):
            bad("each file must be an object")
        n = f.get("name")
        if (not isinstance(n, str) or not n or n.startswith(".") or "/" in n
                or n in names):
            bad(f"file name {n!r} is empty, a dotfile, has a '/', or is a duplicate")
        names.add(n)
        b = f.get("bytes")
        if not isinstance(b, int) or isinstance(b, bool) or b < 0:
            bad(f"{n}: bytes must be a non-negative integer")
        if not isinstance(f.get("sha256"), str) or not SHA_RE.match(f["sha256"]):
            bad(f"{n}: sha256 must be 64 lowercase hex characters")
        if not isinstance(f.get("path"), str):
            bad(f"{n}: path must be a string")


def load_manifest(tid: str) -> tuple:
    p = requests_dir() / f"{tid}.json"
    if not os.path.lexists(p):
        raise Refused(f"no request manifest at {p}")
    raw = read_regular(p)
    try:
        m = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise Refused(f"manifest {tid}: not valid JSON ({e})")
    validate_manifest(m, tid)
    return m, raw


def require_approved(tid: str, manifest_raw: bytes) -> dict:
    p = decisions_dir() / f"{tid}.json"
    if not os.path.lexists(p):
        raise Refused(f"no decision file at {p} (not approved)")
    try:
        d = json.loads(read_regular(p).decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise Refused(f"decision {tid}: not valid JSON ({e})")
    if not isinstance(d, dict) or d.get("id") != tid:
        raise Refused(f"decision {tid}: id does not match")
    if d.get("decision") != "approved":
        raise Refused(f"decision is {d.get('decision')!r}, not 'approved'")
    if d.get("manifest_sha256") != hashlib.sha256(manifest_raw).hexdigest():
        raise Refused("manifest changed since it was approved (manifest_sha256 mismatch)")
    if not isinstance(d.get("approved_by"), str) or not d["approved_by"].strip():
        raise Refused("decision names no approver ('approved_by')")
    return d


def refuse_raw_pii(m: dict) -> None:
    if m["data_class"] == "raw-pii":
        raise Refused("data_class raw-pii is never transferred (raw PII stays in ~/Data_pii)")


# --- destination rule: inside a git repo's gitignored data/ ---

def _git_env() -> dict:
    # An inherited GIT_DIR / GIT_WORK_TREE would point git at another repository.
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def check_dest(dest_str: str, names) -> tuple:
    """Return (repo, dest). Refuse unless every file would land git-ignored under <repo>/data/."""
    if not os.path.isabs(dest_str):
        raise Refused(f"dest {dest_str!r} is not an absolute path")
    if ".." in Path(dest_str).parts:
        raise Refused(f"dest {dest_str!r} contains '..'")
    dest = Path(os.path.normpath(dest_str))
    pii = data_pii()
    if dest == pii or pii in dest.parents:
        raise Refused(f"dest {dest} is inside {pii}")
    repo = next((a for a in [dest, *dest.parents] if os.path.lexists(a / ".git")), None)
    if repo is None:
        raise Refused(f"dest {dest} is not inside a git repository")
    rel = dest.relative_to(repo)
    if not rel.parts or rel.parts[0] != "data":
        raise Refused(f"dest {dest} is outside {repo}/data/")
    cur = repo
    for part in rel.parts:
        cur = cur / part
        try:
            st = os.lstat(cur)
        except FileNotFoundError:
            break
        if stat.S_ISLNK(st.st_mode):
            raise Refused(f"{cur} is a symlink (refused: it could lead outside data/)")
        if not stat.S_ISDIR(st.st_mode):
            raise Refused(f"{cur} exists and is not a directory")
    if not (repo / "data").is_dir():
        raise Refused(f"{repo}/data/ does not exist (the receiver creates it, gitignored)")
    rels = [str(rel / n) for n in names]
    try:
        r = subprocess.run(["git", "-C", str(repo), "check-ignore", "--stdin", "-z"],
                           input="".join(p + "\0" for p in rels).encode("utf-8"),
                           capture_output=True, env=_git_env())
    except OSError as e:
        raise EnvError(f"cannot run git ({e.strerror})")
    if r.returncode not in (0, 1):
        raise EnvError(f"git check-ignore failed in {repo}: "
                       f"{r.stderr.decode('utf-8', 'replace').strip()}")
    ignored = {p for p in r.stdout.decode("utf-8", "replace").split("\0") if p}
    not_ignored = [p for p in rels if p not in ignored]
    if not_ignored:
        raise Refused(f"not gitignored in {repo}: {', '.join(not_ignored)} "
                      f"(dest must be inside the repo's gitignored data/)")
    return repo, dest


# --- request (sender) ---

def cmd_request(a) -> int:
    if not SLUG_RE.match(a.slug):
        raise EnvError(f"slug {a.slug!r} must match {SLUG_RE.pattern}")
    if a.supersedes:
        valid_id(a.supersedes)
    tid = f"{_dt.date.today().isoformat()}-{a.slug}"
    if a.data_class == "raw-pii":
        raise Refused("data_class raw-pii is never transferred (raw PII stays in ~/Data_pii)")
    dest = os.path.expanduser(a.dest)
    if not os.path.isabs(dest) or ".." in Path(dest).parts:
        raise Refused(f"dest {a.dest!r} must be an absolute path without '..'")
    from_machine = a.from_machine or this_machine()

    files, names = [], set()
    pii = data_pii()
    for f in a.files:
        p = Path(os.path.abspath(os.path.expanduser(f)))
        if p == pii or pii in p.parents:
            raise Refused(f"{p} is inside {pii}; raw PII is never transferred")
        if p.name.startswith("."):
            raise Refused(f"{p.name}: dotfiles are not transferred (the mediator skips them)")
        if p.name in names:
            raise Refused(f"{p.name}: two files share this name; the transfer folder is flat")
        names.add(p.name)
        n, sha = hash_file(p)  # refuses symlinks and non-regular files
        files.append({"name": p.name, "path": str(p), "bytes": n, "sha256": sha})

    m = {
        "id": tid,
        "created": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "from": {"session": a.from_session, "machine": from_machine},
        "to": {"session": a.to_session, "machine": a.to_machine, "harness": a.to_harness},
        "files": files,
        "total_bytes": sum(f["bytes"] for f in files),
        "data_class": a.data_class,
        "dest": dest,
        "why": a.why,
        "source_after": a.source_after,
    }
    if a.supersedes:
        m["supersedes"] = a.supersedes
    validate_manifest(m, tid)
    ensure_real_dir(requests_dir())
    out = requests_dir() / f"{tid}.json"
    _write_new_json(out, m)
    print(f"request written: {out}")
    print(f"  id {tid}: {len(files)} file(s), {m['total_bytes']:,} bytes, class {a.data_class}")
    print(f"  next: SendMessage the coordinator this path; stage nothing until it is approved")
    return 0


# --- check (coordinator) ---

def load_limits() -> tuple:
    """Return (limits, note). note is non-empty when any provisional default is in use."""
    p = limits_path()
    if not os.path.lexists(p):
        return dict(DEFAULT_LIMITS), (f"PROVISIONAL DEFAULTS (80% disk, 5 GB): {p} not found; "
                                      f"these values have not been agreed with Lodewijk")
    try:
        raw = json.loads(read_regular(p).decode("utf-8"))
    except (Refused, UnicodeDecodeError, ValueError) as e:
        raise EnvError(f"{p} unreadable ({e})")
    if not isinstance(raw, dict):
        raise EnvError(f"{p} is not a JSON object")
    lim, missing = {}, []
    for k, v in DEFAULT_LIMITS.items():
        if k in raw:
            if not isinstance(raw[k], (int, float)) or isinstance(raw[k], bool) or raw[k] < 0:
                raise EnvError(f"{p}: {k} must be a non-negative number")
            lim[k] = raw[k]
        else:
            lim[k] = v
            missing.append(k)
    note = (f"PROVISIONAL DEFAULTS for {', '.join(missing)}: not set in {p}"
            if missing else "")
    return lim, note


def _nearest_existing(p: Path) -> Path:
    while not os.path.lexists(p) and p != p.parent:
        p = p.parent
    return p


def run_checks(m: dict, here: str, lim: dict) -> list:
    """Return [(status, check, detail)], status in PASS / FAIL / UNMEASURED."""
    res = []
    fm, to = m["from"], m["to"]
    total = sum(f["bytes"] for f in m["files"])
    names = [f["name"] for f in m["files"]]

    # 1. data class vs destination
    dc = m["data_class"]
    if dc == "raw-pii":
        res.append(("FAIL", "data_class", "raw-pii is always refused; it stays in ~/Data_pii"))
    elif dc == "participant" and to["harness"] != "claude-code":
        res.append(("FAIL", "data_class",
                    f"participant data to {to['machine']}/{to['session']} running "
                    f"{to['harness']!r}; allowed only to a claude-code receiver "
                    f"(would pass: a claude-code receiving session)"))
    else:
        res.append(("PASS", "data_class",
                    f"{dc} to {to['machine']}/{to['session']} ({to['harness']})"))

    # 2. receiver named
    if to["session"].strip() and to["machine"].strip():
        res.append(("PASS", "receiver", f"named: {to['machine']}/{to['session']}"))
    else:
        res.append(("FAIL", "receiver", "no receiving session or machine named in 'to'"))

    # 3. size cap
    cap = lim["max_request_bytes"]
    if total <= cap:
        res.append(("PASS", "size", f"{total:,} bytes ({_gb(total)}) <= cap {cap:,.0f}"))
    else:
        res.append(("FAIL", "size", f"{total:,} bytes ({_gb(total)}) > cap {cap:,.0f} "
                                    f"({_gb(cap)}); split it, or make it an admin move"))

    # 4. sources still match the manifest (only measurable on the sender's machine)
    if fm["machine"] == here:
        bad = []
        for f in m["files"]:
            try:
                n, sha = hash_file(Path(f["path"]))
            except Refused as e:
                bad.append(str(e))
                continue
            if n != f["bytes"] or sha != f["sha256"]:
                bad.append(f"{f['name']}: {n} B sha256 {sha[:12]}... != manifest")
        if bad:
            res.append(("FAIL", "sources", "; ".join(bad)))
        else:
            res.append(("PASS", "sources", f"{len(m['files'])} file(s) hash as in the manifest"))
    else:
        res.append(("UNMEASURED", "sources", f"sources are on {fm['machine']}, this is {here}"))

    # 5-7. destination rule, disk, duplicates (only measurable on the receiver's machine)
    if to["machine"] != here:
        why = f"dest is on {to['machine']}, this is {here}; the {to['machine']} side must measure"
        for c in ("dest", "disk", "duplicates"):
            res.append(("UNMEASURED", c, why))
        return res

    dest = None
    try:
        repo, dest = check_dest(m["dest"], names)
        res.append(("PASS", "dest", f"{dest} is gitignored under {repo}/data/"))
    except Refused as e:
        res.append(("FAIL", "dest", str(e)))

    probe = _nearest_existing(Path(os.path.normpath(m["dest"])) if os.path.isabs(m["dest"])
                              else Path.home())
    du = shutil.disk_usage(str(probe))
    used_after = du.total - du.free + total
    pct = 100.0 * used_after / du.total if du.total else 100.0
    line = (f"{pct:.1f}% used after transfer ({_gb(used_after)} of {_gb(du.total)}, "
            f"measured at {probe}); threshold {lim['disk_max_used_pct']}%")
    if pct <= lim["disk_max_used_pct"]:
        res.append(("PASS", "disk", line))
    else:
        res.append(("FAIL", "disk", line + "; free space or pick another destination"))

    if dest is None:
        res.append(("UNMEASURED", "duplicates", "dest refused, so not scanned"))
        return res
    collisions = [n for n in names if os.path.lexists(dest / n)]
    want = {f["sha256"]: f["name"] for f in m["files"]}
    sizes = {f["bytes"] for f in m["files"]}
    dups, scanned, hashed = [], 0, 0
    if dest.is_dir() and not _is_link(dest):
        for root, _dirs, fnames in os.walk(dest, followlinks=False):
            for fn in fnames:
                p = Path(root) / fn
                try:
                    st = os.lstat(p)
                except OSError:
                    continue
                if not stat.S_ISREG(st.st_mode):
                    continue
                scanned += 1
                if st.st_size not in sizes:
                    continue
                hashed += 1
                try:
                    _, sha = hash_file(p)
                except Refused:
                    continue
                if sha in want:
                    dups.append(f"{want[sha]} == {p.relative_to(dest)}")
    detail = f"scanned {scanned} file(s) under {dest}, hashed {hashed} of matching size"
    if dups or collisions:
        parts = []
        if dups:
            parts.append("same sha256 already there: " + "; ".join(dups))
        if collisions:
            parts.append("name already taken: " + ", ".join(collisions))
        res.append(("FAIL", "duplicates", f"{'; '.join(parts)} ({detail})"))
    else:
        res.append(("PASS", "duplicates", f"none ({detail})"))
    return res


def cmd_check(a) -> int:
    tid = valid_id(a.id)
    here = this_machine()
    lim, note = load_limits()
    try:
        m, raw = load_manifest(tid)
    except Refused as e:
        raise EnvError(str(e))
    res = run_checks(m, here, lim)
    failed = [c for s, c, _ in res if s == "FAIL"]
    unmeasured = [c for s, c, _ in res if s == "UNMEASURED"]
    msha = hashlib.sha256(raw).hexdigest()
    if failed:
        verdict = (f"RETURN TO SENDER: {len(failed)} check(s) failed ({', '.join(failed)}). "
                   f"Message only the sender, with every failed check and its numbers.")
    elif unmeasured:
        verdict = (f"NOT READY: {', '.join(unmeasured)} not measured here. "
                   f"Do not approve until they are.")
    else:
        verdict = "ALL MECHANICAL CHECKS PASS. The manual checks below are still open."
    manual = [("contents", "run the secrets scan and charset-hygiene on text files; "
                           "transfer.py does not"),
              ("receiver", "confirm the receiving session exists and expects these files")]

    if a.json:
        print(json.dumps({"id": tid, "here": here, "limits": lim, "limits_note": note,
                          "manifest_sha256": msha,
                          "checks": [{"status": s, "check": c, "detail": d} for s, c, d in res],
                          "manual": [{"check": c, "detail": d} for c, d in manual],
                          "verdict": verdict}, indent=2))
    else:
        total = sum(f["bytes"] for f in m["files"])
        print(f"transfer check {tid} (on {here})")
        print(f"  {m['from']['machine']}/{m['from']['session']} -> "
              f"{m['to']['machine']}/{m['to']['session']} ({m['to']['harness']}): "
              f"{len(m['files'])} file(s), {total:,} bytes, class {m['data_class']}")
        print(f"  why: {m['why']}")
        print(f"  limits: disk <= {lim['disk_max_used_pct']}% used after transfer, "
              f"request <= {lim['max_request_bytes']:,.0f} bytes")
        if note:
            print(f"  limits: {note}")
        for s, c, d in res:
            print(f"{s:<10} {c:<11} {d}")
        for c, d in manual:
            print(f"{'MANUAL':<10} {c:<11} {d}")
        print(f"manifest_sha256: {msha}")
        print(f"verdict: {verdict}")
        print(f"note: check never writes a decision; the coordinator writes "
              f"{decisions_dir() / (tid + '.json')}")
    return 1 if (failed or unmeasured) else 0


# --- deliver (mediator) ---

def route_cross_machine(m: dict) -> None:
    """STUB. The Mac <-> hague route (ssh/rsync) is deliberately NOT BUILT.

    It needs Lodewijk's design review first: it is the one step that crosses machines, it
    must not be allowlisted, and his permission prompt is the approval.
    """
    raise Refused(CROSS_MACHINE_REFUSAL)


def _listing(folder: Path, m: dict) -> dict:
    """Map manifest name -> path in folder; refuse extra, missing, symlinked or odd entries."""
    want = {f["name"] for f in m["files"]}
    present = {}
    for child in folder.iterdir():
        if child.name.startswith("."):
            continue  # dotfiles are staging residue, not deliverables
        st = os.lstat(child)
        if stat.S_ISLNK(st.st_mode):
            raise Refused(f"{child.name}: is a symlink (symlinks are refused)")
        if not stat.S_ISREG(st.st_mode):
            raise Refused(f"{child.name}: not a regular file")
        present[child.name] = child
    extra = sorted(set(present) - want)
    missing = sorted(want - set(present))
    if extra or missing:
        raise Refused(f"folder does not match the manifest (extra: {extra or 'none'}; "
                      f"missing: {missing or 'none'})")
    return present


def deliver_one(entry: Path, here: str, inbox: Path) -> list:
    """Deliver one outbox/transfer-<id>/ folder. Return warnings; raise Refused to refuse."""
    st = os.lstat(entry)
    if stat.S_ISLNK(st.st_mode):
        raise Refused("is a symlink (symlinks are refused)")
    if not stat.S_ISDIR(st.st_mode):
        raise Refused("not a directory")
    tid = entry.name[len(PREFIX):]
    if not ID_RE.match(tid):
        raise Refused(f"{tid!r} is not a transfer id")
    m, raw = load_manifest(tid)
    refuse_raw_pii(m)
    require_approved(tid, raw)
    if m["from"]["machine"] != m["to"]["machine"]:
        route_cross_machine(m)
    if m["to"]["machine"] != here:
        raise Refused(f"route is {m['to']['machine']} -> {m['to']['machine']}, "
                      f"but this machine is {here}")
    if here not in BUILT_SAME_MACHINE:
        raise Refused(f"same-machine route on {here} not built (the design routes it through "
                      f"/srv/exchange): needs Lodewijk's design review")
    present = _listing(entry, m)

    target = inbox / tid
    if os.path.lexists(target):
        raise Refused(f"{target} already exists (refusing to overwrite)")
    try:
        os.mkdir(target, 0o700)
    except OSError as e:
        raise Refused(f"cannot create {target} ({e.strerror})")
    created = []
    try:
        for f in sorted(m["files"], key=lambda f: f["name"]):
            dst = target / f["name"]
            copy_verified(present[f["name"]], dst, f["bytes"], f["sha256"])
            created.append(dst)
    except (Refused, OSError) as e:
        for c in created:
            try:
                os.unlink(c)
            except OSError:
                pass
        try:
            os.rmdir(target)
        except OSError:
            pass
        raise e if isinstance(e, Refused) else Refused(f"copy failed ({e.strerror})")

    # Everything verified in the inbox: now empty the outbox folder.
    warnings = []
    for p in present.values():
        try:
            os.unlink(p)
        except OSError as e:
            warnings.append(f"delivered, but could not remove {p} from the outbox ({e.strerror})")
    try:
        os.rmdir(entry)
    except OSError:
        warnings.append(f"delivered, but {entry} is not empty (dotfiles left?); remove by hand")
    return warnings


def cmd_deliver(_a) -> int:
    ob = outbox()
    if not ob.is_dir():
        sys.stderr.write(f"transfer deliver: no outbox at {ob}\n")
        return 0  # nothing to do is not an error
    here = this_machine()
    inbox = inbox_transfers()
    ensure_real_dir(inbox)

    delivered, failed = [], []
    for entry in sorted(ob.iterdir()):
        name = entry.name
        if name.startswith(".") or not name.startswith(PREFIX):
            continue  # dotfiles are residue; plain files belong to deliver.py
        try:
            warnings = deliver_one(entry, here, inbox)
        except Refused as e:
            failed.append(f"{name}: {e}")
            continue
        except OSError as e:
            failed.append(f"{name}: {e.strerror or e}")
            continue
        delivered.append(name)
        failed.extend(f"{name}: {w}" for w in warnings)

    for n in delivered:
        print(f"delivered: {n} -> {inbox / n[len(PREFIX):]}")
    for f in failed:
        sys.stderr.write(f"skipped:   {f}\n")
    if failed:
        sys.stderr.write(f"transfer deliver: {len(delivered)} delivered, "
                         f"{len(failed)} refused or incomplete\n")
        return 1
    print(f"transfer deliver: {len(delivered)} transfer(s) delivered to {inbox}")
    return 0


# --- receive (receiver) ---

def cmd_receive(a) -> int:
    tid = valid_id(a.id)
    here = this_machine()
    m, raw = load_manifest(tid)
    refuse_raw_pii(m)
    require_approved(tid, raw)
    if m["to"]["machine"] != here:
        raise Refused(f"this transfer is for {m['to']['machine']}, this machine is {here}")
    src = inbox_transfers() / tid
    try:
        st = os.lstat(src)
    except FileNotFoundError:
        raise Refused(f"nothing delivered at {src} yet")
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise Refused(f"{src} is not a real directory (symlinks are refused)")
    present = _listing(src, m)
    names = sorted(present)
    _repo, dest = check_dest(m["dest"], names)
    marker = done_dir() / f"{tid}.json"
    if os.path.lexists(marker):
        raise Refused(f"already received ({marker} exists)")
    taken = [n for n in names if os.path.lexists(dest / n)]
    if taken:
        raise Refused(f"already in {dest}: {', '.join(taken)} (refusing to overwrite)")

    made_dirs = []
    cur = Path(dest.anchor)
    for part in dest.parts[1:]:
        cur = cur / part
        if not os.path.lexists(cur):
            os.mkdir(cur, 0o755)
            made_dirs.append(cur)
    check_dest(m["dest"], names)  # re-check: nothing along the path became a symlink

    created = []
    try:
        for f in sorted(m["files"], key=lambda f: f["name"]):
            dst = dest / f["name"]
            copy_verified(present[f["name"]], dst, f["bytes"], f["sha256"])
            created.append(dst)
    except (Refused, OSError) as e:
        for c in created:
            try:
                os.unlink(c)
            except OSError:
                pass
        for d in reversed(made_dirs):
            try:
                os.rmdir(d)
            except OSError:
                pass
        raise e if isinstance(e, Refused) else Refused(f"copy failed ({e.strerror})")

    ensure_real_dir(done_dir())
    _write_new_json(marker, {"id": tid, "dest": str(dest), "files": names,
                             "received": _dt.datetime.now().astimezone()
                             .isoformat(timespec="seconds")})
    print(f"received: {len(names)} file(s) into {dest}, hashes verified")
    print(f"  marked done: {marker}")
    if m["source_after"] == "delete":
        print("  sender: source_after is 'delete'; the sender may now delete its source files")
    print("  coordinator: append one line to ~/agent/transfer/log.tsv")
    return 0


# --- push: the cross-machine route ---

def cmd_push(_a) -> int:
    """STUB. See route_cross_machine: the cross-machine route is NOT BUILT."""
    sys.stderr.write(f"transfer push: {CROSS_MACHINE_REFUSAL}\n")
    return 2


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="transfer.py", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("request", help="sender: write a transfer manifest")
    r.add_argument("--slug", required=True, help="short name; the id becomes <today>-<slug>")
    r.add_argument("--from-session", required=True)
    r.add_argument("--from-machine", help="default: 'machine' in ~/agent/machine.json")
    r.add_argument("--to-session", required=True)
    r.add_argument("--to-machine", required=True)
    r.add_argument("--to-harness", required=True, choices=HARNESSES)
    r.add_argument("--data-class", required=True, choices=DATA_CLASSES)
    r.add_argument("--dest", required=True, help="receiver-side path inside a repo's data/")
    r.add_argument("--why", required=True, help="one line")
    r.add_argument("--source-after", required=True, choices=SOURCE_AFTER)
    r.add_argument("--supersedes", help="id of the returned request this one replaces")
    r.add_argument("files", nargs="+")
    r.set_defaults(func=cmd_request)

    c = sub.add_parser("check", help="coordinator: run the mechanical checks")
    c.add_argument("id")
    c.add_argument("--json", action="store_true")
    c.set_defaults(func=cmd_check)

    d = sub.add_parser("deliver", help="mediator: outbox/transfer-*/ -> inbox/transfers/ "
                                       "(takes no arguments)")
    d.set_defaults(func=cmd_deliver)

    v = sub.add_parser("receive", help="receiver: verify and copy into dest")
    v.add_argument("id")
    v.set_defaults(func=cmd_receive)

    p = sub.add_parser("push", help="cross-machine route: NOT BUILT")
    p.set_defaults(func=cmd_push)
    return ap


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    try:
        return a.func(a)
    except EnvError as e:
        sys.stderr.write(f"transfer {a.cmd}: {e}\n")
        return 2
    except Refused as e:
        sys.stderr.write(f"transfer {a.cmd}: refused: {e}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
