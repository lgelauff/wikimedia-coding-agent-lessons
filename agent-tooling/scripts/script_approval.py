#!/usr/bin/env python3
"""Approve a script by its CONTENT, then run only the exact bytes that were approved.

Per-command approval ("may I run `python3 x.py`?") tells the human nothing about what
x.py does, and a path-based allow rule lets an edited x.py run unseen. This binds an
approval to the script's SHA-256 instead:

  approve  the agent shows the script, then runs `approve`. That command is deliberately
           NOT allowlisted, so the human gets a prompt — the prompt IS the approval.
           The hash is recorded in the ledger.
  run      allowlisted. Recomputes the hash; refuses unless it matches the ledger, so
           any edit forces a fresh approval.

Ledger: <main checkout>/.claude/script-approvals.json (override with --ledger) — the MAIN
checkout even when run from a worktree, because a worktree is removed with its ignored files.
Keys are paths relative to the project root, so every worktree shares one ledger, and the
content hash still decides. Deny the agent's
file tools on it (`Edit(**/.claude/script-approvals.json)`) — on a machine where the agent
runs as the human that is friction, not a boundary; where the ledger can be root-owned
(hague), it is a real one. Stable scripts graduate to a root-owned read-only folder and
leave the ledger altogether.

Usage:
  script_approval.py approve <script> [--note TEXT]
  script_approval.py run <script> [-- args...]
  script_approval.py list
  script_approval.py revoke <script>
Exit codes: 0 ok · 2 refused (unapproved, changed, outside the project) · 1 usage error.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REFUSED = 2


def find_root(start: Path) -> Path:
    """Nearest ancestor holding .git — the project the ledger belongs to."""
    for p in [start, *start.parents]:
        if (p / ".git").exists():
            return p
    raise SystemExit("script_approval: not inside a git project")


def main_checkout(root: Path) -> Path:
    """The main checkout behind a worktree (or root itself). The ledger lives there, because a
    worktree is deleted together with its ignored files — notes and approvals included."""
    try:
        common = subprocess.run(["git", "-C", str(root), "rev-parse", "--git-common-dir"],
                                capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return root
    common_path = (root / common).resolve() if not os.path.isabs(common) else Path(common)
    return common_path.parent if common_path.name == ".git" else root


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve_script(script: str, root: Path) -> tuple[Path, str]:
    """Real path (symlinks resolved) and its project-relative key; refuse anything outside."""
    real = Path(script).resolve(strict=True)
    try:
        key = real.relative_to(root.resolve()).as_posix()
    except ValueError:
        raise PermissionError(f"{real} is outside the project {root}") from None
    if not real.is_file():
        raise PermissionError(f"{real} is not a regular file")
    return real, key


def load_ledger(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def save_ledger(path: Path, ledger: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def check(script: str, root: Path, ledger_path: Path) -> tuple[Path, str]:
    """Return (real path, key) if the script's current bytes are approved, else raise."""
    real, key = resolve_script(script, root)
    entry = load_ledger(ledger_path).get(key)
    if entry is None:
        raise PermissionError(f"{key} is not approved — show it to the human and run `approve`")
    if entry["sha256"] != sha256(real):
        raise PermissionError(
            f"{key} changed since it was approved on {entry['approved_at']} — "
            "show the new version and run `approve` again")
    return real, key


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--ledger", help="ledger path (default <project>/.claude/script-approvals.json)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("approve"); a.add_argument("script"); a.add_argument("--note", default="")
    r = sub.add_parser("run"); r.add_argument("script"); r.add_argument("args", nargs=argparse.REMAINDER)
    sub.add_parser("list")
    v = sub.add_parser("revoke"); v.add_argument("script")
    ns = ap.parse_args(argv)

    root = find_root(Path.cwd())
    ledger_path = (Path(ns.ledger) if ns.ledger
                   else main_checkout(root) / ".claude" / "script-approvals.json")

    try:
        if ns.cmd == "approve":
            real, key = resolve_script(ns.script, root)
            ledger = load_ledger(ledger_path)
            ledger[key] = {
                "sha256": sha256(real),
                "bytes": real.stat().st_size,
                "approved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "note": ns.note,
            }
            save_ledger(ledger_path, ledger)
            print(f"approved {key} sha256={ledger[key]['sha256'][:16]}… ({ledger[key]['bytes']} bytes)")
            return 0
        if ns.cmd == "run":
            real, key = check(ns.script, root, ledger_path)
            args = ns.args[1:] if ns.args[:1] == ["--"] else ns.args
            interp = [sys.executable] if real.suffix == ".py" else []
            return subprocess.call([*interp, str(real), *args])
        if ns.cmd == "list":
            for key, e in sorted(load_ledger(ledger_path).items()):
                print(f"{key}\t{e['sha256'][:16]}…\t{e['approved_at']}\t{e.get('note', '')}")
            return 0
        if ns.cmd == "revoke":
            _, key = resolve_script(ns.script, root)
            ledger = load_ledger(ledger_path)
            if ledger.pop(key, None) is None:
                print(f"{key} was not approved")
            save_ledger(ledger_path, ledger)
            return 0
    except (PermissionError, FileNotFoundError) as e:
        print(f"script_approval: REFUSED — {e}", file=sys.stderr)
        return REFUSED
    return 1


if __name__ == "__main__":
    sys.exit(main())
