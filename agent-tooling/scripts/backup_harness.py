#!/usr/bin/env python3
"""backup_harness.py — one local, restorable archive of the harness state.

Why this exists: the harness's state is not all in git. `.claude/` working notes are
gitignored (nothing in them is recoverable), the commits are local (nothing is pushed),
and `~/agent/machine.json` is deliberately never committed. A disk accident or a bad
`rm` loses all three, and the handoff has called backups the largest outstanding risk
for several sessions.

This is a **local** archive: it protects against accidental deletion, not against disk
failure or theft. A real off-machine backup (push the repo, mirror `~/agent`) is a human
decision and is not done here. Backups of the other machine's research data are separate
and out of scope.

  python3 backup_harness.py                     # write to ~/agent/backups/
  python3 backup_harness.py --dest /somewhere
  python3 backup_harness.py --dry-run           # list what would be included

Excludes, deliberately: `.claude/refs/` (~663 MB of cloned third-party repos, disposable),
`outbox/` (delivered outputs may carry research data), Python caches, and `.stage/`.
Exit codes: 0 wrote (or dry-ran), 1 nothing to back up, 2 could not complete.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
import tarfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_DEFAULT = HERE.parents[1]
AGENT_HOME_DEFAULT = Path.home() / "agent"
DEST_DEFAULT = AGENT_HOME_DEFAULT / "backups"

# Path components (relative to the archive root) that never belong in a backup.
# `backups` is excluded so an archive does not swallow its own destination and every
# previous archive (unbounded self-inclusion).
EXCLUDE_PARTS = {".claude/refs", ".stage", "outbox", "backups", "__pycache__", ".pytest_cache"}
EXCLUDE_SUFFIXES = {".pyc", ".pyo"}


def _excluded(rel: str) -> bool:
    rel = rel.replace(os.sep, "/")
    for part in EXCLUDE_PARTS:
        if rel == part or rel.startswith(part + "/") or f"/{part}/" in f"/{rel}/":
            return True
    return any(rel.endswith(s) for s in EXCLUDE_SUFFIXES)


def collect(repo: Path, agent_home: Path) -> list[tuple[Path, str]]:
    """(source path, archive name) pairs to back up. Pure enough to test."""
    items: list[tuple[Path, str]] = []
    if repo.is_dir():
        items.append((repo, "repo"))
    if agent_home.is_dir():
        items.append((agent_home, "agent"))
    return items


def _filter(arcname: str):
    """tarfile filter: drop excluded paths, keep directories."""
    def f(ti: tarfile.TarInfo):
        rel = ti.name.split("/", 1)[1] if "/" in ti.name else ti.name
        if _excluded(rel):
            return None
        return ti
    return f


def build_archive(items: list[tuple[Path, str]], out: Path) -> None:
    with tarfile.open(out, "w:gz") as tar:
        for src, arcname in items:
            tar.add(src, arcname=arcname, filter=_filter(arcname))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=str(REPO_DEFAULT))
    ap.add_argument("--agent-home", default=str(AGENT_HOME_DEFAULT))
    ap.add_argument("--dest", default=str(DEST_DEFAULT))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    repo, agent_home, dest = Path(a.repo).resolve(), Path(a.agent_home), Path(a.dest)
    items = collect(repo, agent_home)
    if not items:
        print("nothing to back up: neither the repo nor the agent home exists")
        return 1

    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = dest / f"harness-backup-{stamp}.tar.gz"
    if a.dry_run:
        print(f"DRY RUN — would write {out}")
        for src, arcname in items:
            print(f"  {arcname}/  <- {src}  (excluding {sorted(EXCLUDE_PARTS)})")
        return 0

    try:
        dest.mkdir(parents=True, exist_ok=True, mode=0o700)
        build_archive(items, out)
    except OSError as e:
        print(f"COULD NOT COMPLETE: {e}")
        return 2
    # The archive carries machine.json and gitignored working notes; keep it private.
    os.chmod(out, 0o600)
    digest = sha256(out)
    sha_path = out.with_suffix(out.suffix + ".sha256")
    sha_path.write_text(f"{digest}  {out.name}\n", encoding="utf-8")
    os.chmod(sha_path, 0o600)
    print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB)")
    print(f"sha256 {digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
