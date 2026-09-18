#!/usr/bin/env python3
"""Move files from the agent's outbox to the user's Downloads folder.

A one-way mediator between two zones:

    ~/agent/outbox/     the agent may write here (inside its permitted zone)
    ~/Downloads/        only this script writes here (outside it)

The agent cannot reach ~/Downloads. It can only place files in the outbox and ask for this
script to run. The script is the boundary, not a permission rule — which is why it should be
installed **root-owned and not writable by the agent**:

    sudo install -m 0755 deliver.py /usr/local/bin/deliver.py
    sudo chown root:wheel /usr/local/bin/deliver.py

With mode 755 and root ownership the agent can execute it but not modify it. If it were
agent-writable it would be a convention rather than a control, and the whole point is lost.

Three deliberate restrictions, each closing a real hole:

1. **No arguments.** A filename argument would make `../../.ssh/id_rsa` valid input. It moves
   everything in the outbox and nothing else, so there is nothing to inject.
2. **No symlinks.** A symlink in the outbox pointing at a file the agent cannot read would
   otherwise be followed, and the *target* moved out. Only regular files are moved.
3. **No overwrites.** A name collision with an existing file in Downloads fails rather than
   clobbering it. Silent data loss in someone's Downloads folder is not an acceptable
   failure mode for a convenience script.

Exit codes: 0 nothing to do or all moved · 1 at least one file could not be moved ·
2 could not run (bad environment).
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

OUTBOX = Path.home() / "agent" / "outbox"
DOWNLOADS = Path.home() / "Downloads"


def main() -> int:
    if not OUTBOX.is_dir():
        sys.stderr.write(f"deliver: no outbox at {OUTBOX}\n")
        return 0  # nothing to do is not an error
    if not DOWNLOADS.is_dir():
        sys.stderr.write(f"deliver: no Downloads at {DOWNLOADS}\n")
        return 2

    moved: list[str] = []
    failed: list[str] = []

    # Sorted for deterministic, reviewable output.
    for entry in sorted(OUTBOX.iterdir()):
        name = entry.name
        if name.startswith("."):
            continue  # dotfiles are staging residue, not deliverables

        # lstat, not stat: a symlink must be refused, not followed. Following one would
        # move the target — a file the agent may not be able to read itself.
        try:
            st = entry.lstat()
        except OSError as e:
            failed.append(f"{name}: cannot stat ({e.strerror})")
            continue
        if not os.path.isfile(entry) or os.path.islink(entry):
            failed.append(f"{name}: not a regular file (symlinks are refused)")
            continue

        dest = DOWNLOADS / name
        if dest.exists() or dest.is_symlink():
            failed.append(f"{name}: already exists in Downloads (refusing to overwrite)")
            continue

        try:
            shutil.move(str(entry), str(dest))
            moved.append(name)
        except OSError as e:
            failed.append(f"{name}: move failed ({e.strerror})")

    for n in moved:
        print(f"delivered: {n}")
    for f in failed:
        sys.stderr.write(f"skipped:   {f}\n")

    # Clean up empty staging directories the agent may have made, but only if empty.
    try:
        for d in sorted(OUTBOX.iterdir(), reverse=True):
            if d.is_dir():
                try:
                    d.rmdir()
                except OSError:
                    pass  # not empty, or not ours — leave it
    except OSError:
        pass

    if failed:
        sys.stderr.write(f"deliver: {len(moved)} moved, {len(failed)} skipped\n")
        return 1
    print(f"deliver: {len(moved)} file(s) moved to {DOWNLOADS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
